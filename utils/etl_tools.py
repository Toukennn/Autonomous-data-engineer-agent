import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from utils.api_client import APIClient

from config.settings import get_runtime_settings
from models.schema import (
    CastColumnsOperation,
    DropColumnsOperation,
    DropDuplicatesOperation,
    FillMissingOperation,
    FilterRowsOperation,
    GroupByAggregateOperation,
    RenameColumnsOperation,
    SelectColumnsOperation,
    SortValuesOperation,
    StringTransformOperation,
    TransformPlan,
)
from utils.exceptions import (
    DataQualityError,
    DatasetError,
    SchemaEvolutionError,
    UnsupportedFormatError,
)

from utils.incremental_state import IncrementalStateStore

from utils.schema_evolution import (
    compare_schemas,
    dataframe_schema,
    schema_fingerprint,
    schema_transition_fingerprint,
)

from utils.data_layers import (
    DataLayer,
    resolve_layer_dataset_directory,
    validate_dataset_name,
)

from utils.lineage import LineageStore

from utils.data_quality import (
    evaluate_data_quality,
)

from utils.data_quality_contracts import (
    DataQualityContractStore,
    quality_contract_fingerprint,
)

from models.data_quality import (
    DataQualityContract,
)

class ETLTools:
    """
    Deterministic ETL operations used by the ETL agent.

    The LLM decides WHAT transformation should happen by generating
    a validated TransformPlan.

    This class controls HOW the transformation happens using a
    restricted set of deterministic Pandas operations.

    Arbitrary Python execution is intentionally not supported.
    """

    SCHEMA_EVOLUTION_POLICY = (
        "additive_only"
    )

    SUPPORTED_FORMATS = {
        "csv",
        "json",
        "parquet",
    }

    def __init__(self):
        """
        Load runtime configuration and initialize API ingestion.
        """

        settings = get_runtime_settings()

        self.project_root = settings.project_root
        self.data_root = settings.data_root

        self.api_client = APIClient()

        self.lineage_store = (
            LineageStore(
                self.data_root
            )
        )

        self.quality_contract_store = (
            DataQualityContractStore(
                self.data_root
            )
        )

    # ============================================================
    # PATH SAFETY
    # ============================================================

    def _resolve_data_path(
        self,
        path: str,
        must_exist: bool = False,
    ) -> Path:
        """
        Resolve a path while ensuring it remains inside
        the project's data directory.

        This prevents the ETL agent from accessing arbitrary
        files elsewhere on the machine.
        """

        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = (
                self.project_root
                / candidate
            )

        candidate = candidate.resolve()

        try:
            candidate.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "ETL file operations are restricted "
                "to the project's data directory."
            ) from exc

        if must_exist and not candidate.exists():
            raise DatasetError(
                f"Dataset does not exist: {candidate}"
            )

        return candidate


    def configure_quality_contract(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
        contract: DataQualityContract,
    ) -> str:
        """
        Persist a new quality contract for a Silver or Gold
        logical dataset.

        Existing different contracts cannot be overwritten
        through the agent-facing workflow.

        Repeating the exact same contract is idempotent.
        """

        if layer not in {
            DataLayer.SILVER,
            DataLayer.GOLD,
        }:
            raise DatasetError(
                "Agent-configured quality contracts "
                "are supported only for Silver "
                "and Gold datasets."
            )

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        if not contract.name.strip():
            raise DatasetError(
                "Data-quality contract name "
                "must not be empty."
            )

        if not contract.rules:
            raise DatasetError(
                "An agent-configured data-quality "
                "contract must contain at least "
                "one explicit quality rule."
            )

        requested_fingerprint = (
            quality_contract_fingerprint(
                contract
            )
        )

        existing_contract = (
            self.quality_contract_store
            .load(
                layer=layer,
                dataset_name=(
                    safe_dataset_name
                ),
            )
        )

        if existing_contract is not None:

            existing_fingerprint = (
                quality_contract_fingerprint(
                    existing_contract
                )
            )

            if (
                existing_fingerprint
                == requested_fingerprint
            ):
                return (
                    "Data-quality contract is already "
                    "configured with the same content.\n"
                    f"Dataset: {safe_dataset_name}\n"
                    f"Layer: {layer.value}\n"
                    f"Contract: {contract.name}\n"
                    f"Contract version: "
                    f"{contract.contract_version}\n"
                    f"Rules: {len(contract.rules)}\n"
                    f"Fingerprint: "
                    f"{existing_fingerprint}"
                )

            raise DatasetError(
                "A different data-quality contract "
                f"already exists for {layer.value} "
                f"dataset '{safe_dataset_name}'. "
                "The ETL agent is not allowed to "
                "overwrite or weaken an existing "
                "quality contract."
            )

        fingerprint = (
            self.quality_contract_store
            .save(
                layer=layer,
                dataset_name=(
                    safe_dataset_name
                ),
                contract=contract,
            )
        )

        return (
            "Data-quality contract configured "
            "successfully.\n"
            f"Dataset: {safe_dataset_name}\n"
            f"Layer: {layer.value}\n"
            f"Contract: {contract.name}\n"
            f"Contract version: "
            f"{contract.contract_version}\n"
            f"Rules: {len(contract.rules)}\n"
            f"Fingerprint: {fingerprint}"
        )
        

    def _evaluate_quality_gate(
        self,
        *,
        dataframe: pd.DataFrame,
        layer: DataLayer,
        dataset_name: str,
        rejection_file: Path,
    ) -> tuple[
        dict | None,
        str | None,
    ]:
        """
        Evaluate a candidate dataset against its
        persisted quality contract.

        No contract:
            allow the candidate.

        Passing contract:
            return quality metadata.

        Failing contract:
            persist rejection information and raise
            DataQualityError before dataset mutation.
        """

        contract = (
            self.quality_contract_store
            .load(
                layer=layer,
                dataset_name=dataset_name,
            )
        )

        if contract is None:
            return (
                None,
                None,
            )

        fingerprint = (
            quality_contract_fingerprint(
                contract
            )
        )

        result = (
            evaluate_data_quality(
                dataframe=dataframe,
                contract=contract,
            )
        )

        result_payload = (
            result.model_dump(
                mode="json"
            )
        )

        if result.passed:
            return (
                result_payload,
                fingerprint,
            )

        details: dict[
            str,
            object,
        ] = {
            "layer": layer.value,
            "dataset": dataset_name,
            "contract_name": (
                contract.name
            ),
            "contract_version": (
                contract.contract_version
            ),
            "contract_fingerprint": (
                fingerprint
            ),
            "quality_result": (
                result_payload
            ),
        }

        self._persist_quality_rejection(
            layer=layer,
            dataset_name=dataset_name,
            contract_name=(
                contract.name
            ),
            contract_version=(
                contract.contract_version
            ),
            contract_fingerprint=(
                fingerprint
            ),
            quality_result=(
                result_payload
            ),
            rejection_file=(
                rejection_file
            ),
        )

        failed_checks = [
            check
            for check in result.checks
            if not check.passed
        ]

        check_summaries = [
            (
                f"{check.rule_type}: "
                f"{check.violation_count} "
                "violation(s)"
            )
            for check in failed_checks[
                :5
            ]
        ]

        failure_summary = "; ".join(
            check_summaries
        )

        remaining_failures = (
            len(failed_checks)
            - len(check_summaries)
        )

        if remaining_failures > 0:
            failure_summary += (
                f"; +{remaining_failures} "
                "additional failed check(s)"
            )

        raise DataQualityError(
            (
                "Candidate "
                f"{layer.value} dataset "
                f"'{dataset_name}' failed "
                f"data-quality contract "
                f"'{contract.name}'. "
                f"{len(failed_checks)} of "
                f"{result.total_checks} checks failed. "
                f"{failure_summary}. "
                f"Rejection report: "
                f"{rejection_file}"
            ),
            details=details,
        )


    def _persist_quality_rejection(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
        contract_name: str,
        contract_version: int,
        contract_fingerprint: str,
        quality_result: dict,
        rejection_file: Path,
    ) -> None:
        """
        Persist a failed quality-gate evaluation.

        The report contains aggregate quality
        results only. Raw dataset rows are not
        persisted.
        """

        if rejection_file.exists():

            try:
                with rejection_file.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    report = json.load(
                        file
                    )

            except (
                OSError,
                json.JSONDecodeError,
            ) as exc:
                raise DatasetError(
                    "Failed to load data-quality "
                    "rejection report."
                ) from exc

            if not isinstance(
                report,
                dict,
            ):
                raise DatasetError(
                    "Data-quality rejection report "
                    "must be a JSON object."
                )

            events = report.get(
                "events"
            )

            if not isinstance(
                events,
                list,
            ):
                raise DatasetError(
                    "Data-quality rejection report "
                    "contains an invalid events list."
                )

        else:

            report = {
                "report_version": 1,
                "layer": layer.value,
                "dataset": dataset_name,
                "events": [],
            }

            events = report[
                "events"
            ]

        event = {
            "rejected_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "contract_name": (
                contract_name
            ),
            "contract_version": (
                contract_version
            ),
            "contract_fingerprint": (
                contract_fingerprint
            ),
            "quality_result": (
                quality_result
            ),
        }

        events.append(
            event
        )

        report["events"] = events

        self._save_json_atomic(
            payload=report,
            file_path=rejection_file,
        )



    def _resolve_layer_dataset_file(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
        file_stem: str,
    ) -> Path:
        """
        Resolve exactly one physical dataset file inside a
        deterministic medallion layer.

        The dataset name is a logical identifier, not a path.
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        dataset_directory = (
            resolve_layer_dataset_directory(
                data_root=self.data_root,
                layer=layer,
                dataset_name=(
                    safe_dataset_name
                ),
            )
        )

        candidates = [
            (
                dataset_directory
                / f"{file_stem}.{file_format}"
            )
            for file_format
            in sorted(
                self.SUPPORTED_FORMATS
            )
            if (
                dataset_directory
                / f"{file_stem}.{file_format}"
            ).exists()
        ]

        if not candidates:
            raise DatasetError(
                f"{layer.value.title()} dataset "
                f"does not exist: "
                f"{safe_dataset_name}"
            )

        if len(candidates) > 1:
            raise DatasetError(
                f"Multiple physical files exist for "
                f"{layer.value} dataset "
                f"'{safe_dataset_name}'. "
                "The dataset format is ambiguous."
            )

        return candidates[0]

    # ============================================================
    # FORMAT VALIDATION
    # ============================================================

    def _validate_format(
        self,
        file_format: str,
    ) -> str:
        """
        Validate and normalize a dataset format.
        """

        normalized = (
            file_format
            .lower()
            .strip()
            .lstrip(".")
        )

        if normalized not in self.SUPPORTED_FORMATS:
            raise UnsupportedFormatError(
                f"Unsupported format: {file_format}. "
                f"Supported formats: "
                f"{sorted(self.SUPPORTED_FORMATS)}"
            )

        return normalized

    # ============================================================
    # DATAFRAME LOADING
    # ============================================================

    def _load_dataframe(
        self,
        file_path: str,
    ) -> pd.DataFrame:
        """
        Load a supported dataset from the project's data directory.
        """

        path = self._resolve_data_path(
            file_path,
            must_exist=True,
        )

        extension = (
            path.suffix
            .lower()
        )

        try:

            if extension == ".csv":
                return pd.read_csv(
                    path
                )

            if extension == ".json":

                try:
                    return pd.read_json(
                        path,
                        lines=True,
                    )

                except ValueError:
                    return pd.read_json(
                        path
                    )

            if extension == ".parquet":
                return pd.read_parquet(
                    path
                )

        except Exception as exc:
            raise DatasetError(
                f"Failed to load dataset: {path.name}"
            ) from exc

        raise UnsupportedFormatError(
            f"Unsupported input format: {extension}"
        )

    # ============================================================
    # DATAFRAME SAVING
    # ============================================================

    def _save_dataframe(
        self,
        dataframe: pd.DataFrame,
        file_path: Path,
        file_format: str,
    ) -> None:
        """
        Save a DataFrame using a supported output format.
        """

        file_format = self._validate_format(
            file_format
        )

        try:
            file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if file_format == "csv":

                dataframe.to_csv(
                    file_path,
                    index=False,
                )

                return

            if file_format == "json":

                dataframe.to_json(
                    file_path,
                    orient="records",
                    lines=True,
                )

                return

            if file_format == "parquet":

                dataframe.to_parquet(
                    file_path,
                    index=False,
                )

                return

        except Exception as exc:
            raise DatasetError(
                f"Failed to save dataset to: {file_path}"
            ) from exc


    def _save_dataframe_atomic(
        self,
        dataframe: pd.DataFrame,
        file_path: Path,
        file_format: str,
    ) -> None:
        """
        Atomically replace a dataset.

        The new dataset is written completely to a temporary file
        before it replaces the existing dataset.
        """

        file_format = self._validate_format(
            file_format
        )

        temp_file = file_path.with_name(
            f".{file_path.stem}.tmp{file_path.suffix}"
        )

        try:
            self._save_dataframe(
                dataframe=dataframe,
                file_path=temp_file,
                file_format=file_format,
            )

            temp_file.replace(
                file_path
            )

        except DatasetError:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass

            raise

        except OSError as exc:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass

            raise DatasetError(
                f"Failed to atomically save dataset: {file_path}"
            ) from exc


    @staticmethod
    def _save_json_atomic(
        payload: dict,
        file_path: Path,
    ) -> None:
        """
        Atomically save a JSON metadata file.
        """

        temp_file = file_path.with_name(
            f".{file_path.name}.tmp"
        )

        try:
            file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with temp_file.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    payload,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )

            temp_file.replace(
                file_path
            )

        except (
            OSError,
            TypeError,
            ValueError,
        ) as exc:

            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass

            raise DatasetError(
                "Failed to atomically save extraction metadata."
            ) from exc

    def _persist_schema_history(
        self,
        dataframe: pd.DataFrame,
        schema_history_file: Path,
        source_url: str,
        output_file: Path,
    ) -> tuple[str, int]:
        """
        Persist schema versions for an extracted dataset.

        A new history entry is written only when the logical schema
        fingerprint changes.

        Returns:
            (current_fingerprint, current_schema_version)
        """

        current_schema = dataframe_schema(
            dataframe
        )

        current_fingerprint = (
            schema_fingerprint(
                current_schema
            )
        )

        # ============================================================
        # LOAD EXISTING HISTORY
        # ============================================================

        if schema_history_file.exists():

            try:
                with schema_history_file.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    history = json.load(
                        file
                    )

            except (
                OSError,
                json.JSONDecodeError,
            ) as exc:
                raise DatasetError(
                    "Failed to load schema history."
                ) from exc

            if not isinstance(
                history,
                dict,
            ):
                raise DatasetError(
                    "Schema history must be a JSON object."
                )

            entries = history.get(
                "entries"
            )

            if not isinstance(
                entries,
                list,
            ):
                raise DatasetError(
                    "Schema history contains an invalid entries list."
                )

        else:

            history = {
                "history_version": 1,
                "dataset": str(
                    output_file
                ),
                "entries": [],
            }

            entries = history[
                "entries"
            ]

        # ============================================================
        # DO NOT DUPLICATE UNCHANGED SCHEMAS
        # ============================================================

        if entries:

            latest_entry = (
                entries[-1]
            )

            if not isinstance(
                latest_entry,
                dict,
            ):
                raise DatasetError(
                    "Schema history contains an invalid entry."
                )

            latest_fingerprint = (
                latest_entry.get(
                    "fingerprint"
                )
            )

            latest_version = (
                latest_entry.get(
                    "schema_version"
                )
            )

            if not isinstance(
                latest_version,
                int,
            ):
                raise DatasetError(
                    "Schema history contains an invalid schema version."
                )

            if (
                latest_fingerprint
                == current_fingerprint
            ):
                return (
                    current_fingerprint,
                    latest_version,
                )

            schema_version = (
                latest_version + 1
            )

        else:

            schema_version = 1

        # ============================================================
        # CREATE NEW SCHEMA VERSION
        # ============================================================

        entry = {
            "schema_version": (
                schema_version
            ),
            "fingerprint": (
                current_fingerprint
            ),
            "schema": (
                current_schema
            ),
            "recorded_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "source_url": (
                source_url
            ),
        }

        entries.append(
            entry
        )

        history[
            "latest_fingerprint"
        ] = current_fingerprint

        history[
            "entries"
        ] = entries

        # ============================================================
        # ATOMIC SAVE
        # ============================================================

        self._save_json_atomic(
            payload=history,
            file_path=schema_history_file,
        )

        return (
            current_fingerprint,
            schema_version,
        )


    def _persist_schema_rejection(
        self,
        *,
        details: dict[str, object],
        rejection_file: Path,
        source_url: str,
        output_file: Path,
        previous_watermark: (
            str
            | int
            | float
            | None
        ),
    ) -> str:
        """
        Persist a rejected schema transition.

        Identical rejected transitions are not duplicated.

        Returns:
            Stable rejection identifier.
        """

        existing_schema = details.get(
            "existing_schema"
        )

        incoming_schema = details.get(
            "incoming_schema"
        )

        if not isinstance(
            existing_schema,
            dict,
        ):
            raise DatasetError(
                "Schema rejection is missing "
                "the existing schema."
            )

        if not isinstance(
            incoming_schema,
            dict,
        ):
            raise DatasetError(
                "Schema rejection is missing "
                "the incoming schema."
            )

        rejection_id = (
            schema_transition_fingerprint(
                existing_schema,
                incoming_schema,
            )
        )

        # ============================================================
        # LOAD EXISTING REJECTIONS
        # ============================================================

        if rejection_file.exists():

            try:
                with rejection_file.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    report = json.load(
                        file
                    )

            except (
                OSError,
                json.JSONDecodeError,
            ) as exc:
                raise DatasetError(
                    "Failed to load schema rejection report."
                ) from exc

            if not isinstance(
                report,
                dict,
            ):
                raise DatasetError(
                    "Schema rejection report must "
                    "be a JSON object."
                )

            events = report.get(
                "events"
            )

            if not isinstance(
                events,
                list,
            ):
                raise DatasetError(
                    "Schema rejection report contains "
                    "an invalid events list."
                )

        else:

            report = {
                "report_version": 1,
                "dataset": str(
                    output_file
                ),
                "schema_evolution_policy": (
                    self.SCHEMA_EVOLUTION_POLICY
                ),
                "events": [],
            }

            events = report[
                "events"
            ]

        # ============================================================
        # IDEMPOTENT REJECTION REPORTING
        # ============================================================

        for event in events:

            if (
                isinstance(
                    event,
                    dict,
                )
                and event.get(
                    "rejection_id"
                )
                == rejection_id
            ):
                return rejection_id

        # ============================================================
        # NEW REJECTION EVENT
        # ============================================================

        event = {
            "rejection_id": (
                rejection_id
            ),
            "detected_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "decision": "rejected",
            "reason": (
                "breaking_schema_change"
            ),
            "schema_evolution_policy": (
                self.SCHEMA_EVOLUTION_POLICY
            ),
            "source_url": (
                source_url
            ),
            "previous_watermark": (
                previous_watermark
            ),
            "existing_schema_fingerprint": (
                schema_fingerprint(
                    existing_schema
                )
            ),
            "incoming_schema_fingerprint": (
                schema_fingerprint(
                    incoming_schema
                )
            ),
            "added_columns": details.get(
                "added_columns",
                [],
            ),
            "removed_columns": details.get(
                "removed_columns",
                [],
            ),
            "type_changes": details.get(
                "type_changes",
                {},
            ),
            "existing_schema": (
                existing_schema
            ),
            "incoming_schema": (
                incoming_schema
            ),
        }

        events.append(
            event
        )

        report["events"] = events

        self._save_json_atomic(
            payload=report,
            file_path=rejection_file,
        )

        return rejection_id
        

    def _merge_incremental_dataframe(
        self,
        existing_file: Path,
        new_dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Merge newly extracted records with an existing dataset.

        Safe additive schema evolution is supported:

        - newly added columns are accepted
        - historical rows receive null values for new columns

        Breaking changes are rejected:

        - removed columns
        - logical type changes

        Exact duplicate rows are removed so retrying an extraction
        after a checkpoint-write failure remains idempotent.
        """

        if not existing_file.exists():
            return new_dataframe.copy()

        existing_dataframe = (
            self._load_dataframe(
                str(existing_file)
            )
        )

        # An empty API batch does not provide enough information to
        # infer a schema change.
        if new_dataframe.empty:
            return existing_dataframe

        schema_diff = compare_schemas(
            existing_dataframe=existing_dataframe,
            incoming_dataframe=new_dataframe,
        )

        # ============================================================
        # BREAKING SCHEMA CHANGES
        # ============================================================

        if schema_diff.is_breaking:

            message_details = []

            if schema_diff.added_columns:
                message_details.append(
                    "Added columns: "
                    f"{list(schema_diff.added_columns)}."
                )

            if schema_diff.removed_columns:
                message_details.append(
                    "Removed columns: "
                    f"{list(schema_diff.removed_columns)}."
                )

            if schema_diff.type_changes:
                message_details.append(
                    "Type changes: "
                    f"{schema_diff.type_changes}."
                )

            structured_type_changes = {
                column: {
                    "from": old_type,
                    "to": new_type,
                }
                for (
                    column,
                    (
                        old_type,
                        new_type,
                    ),
                )
                in schema_diff.type_changes.items()
            }

            raise SchemaEvolutionError(
                (
                    "Breaking incremental API schema "
                    "change detected. "
                    + " ".join(
                        message_details
                    )
                ),
                details={
                    "existing_schema": (
                        schema_diff.existing_schema
                    ),
                    "incoming_schema": (
                        schema_diff.incoming_schema
                    ),
                    "added_columns": list(
                        schema_diff.added_columns
                    ),
                    "removed_columns": list(
                        schema_diff.removed_columns
                    ),
                    "type_changes": (
                        structured_type_changes
                    ),
                },
            )

        # ============================================================
        # SAFE ADDITIVE EVOLUTION
        # ============================================================

        if schema_diff.is_additive_only:

            final_columns = [
                *existing_dataframe.columns,
                *schema_diff.added_columns,
            ]

            # reindex automatically fills the newly introduced columns
            # in historical rows with null values.
            existing_dataframe = (
                existing_dataframe.reindex(
                    columns=final_columns
                )
            )

            new_dataframe = (
                new_dataframe.reindex(
                    columns=final_columns
                )
            )

        else:
            # No schema change.
            # Preserve the durable dataset's column ordering.
            new_dataframe = new_dataframe[
                existing_dataframe.columns
            ]

        # ============================================================
        # MERGE
        # ============================================================

        combined = pd.concat(
            [
                existing_dataframe,
                new_dataframe,
            ],
            ignore_index=True,
        )

        # ============================================================
        # IDEMPOTENT RETRY PROTECTION
        # ============================================================

        combined = (
            combined
            .drop_duplicates(
                keep="last"
            )
            .reset_index(
                drop=True
            )
        )

        return combined
            

    # ============================================================
    # API EXTRACTION
    # ============================================================

    def extract_load(
        self,
        url: str,
        dataset_name: str = "extract",
        format: str = "csv",
        paginate: bool = True,
        records_path: str | None = "results",
        next_path: str | None = "next",
        use_auth: bool = False,
        state_key: str | None = None,
        watermark_param: str | None = None,
        watermark_field: str | None = None,
    ) -> str:
        """
        Extract API records and persist them safely.

        Incremental ingestion is enabled when incremental configuration
        is supplied.

        The checkpoint is advanced only after:

        1. API extraction succeeds.
        2. Schema changes are observed and previous versions are historicized
        3. Dataset persistence succeeds.
        4. Extraction metadata persistence succeeds.
        """

        # ============================================================
        # OUTPUT VALIDATION
        # ============================================================

        file_format = self._validate_format(
            format
        )

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        output_directory = (
            resolve_layer_dataset_directory(
                data_root=self.data_root,
                layer=DataLayer.BRONZE,
                dataset_name=(
                    safe_dataset_name
                ),
            )
        )

        output_file = (
            output_directory
            / f"extracted_data.{file_format}"
        )

        metadata_file = (
            output_directory
            / "extraction_metadata.json"
        )

        schema_history_file = (
            output_directory
            / "schema_history.json"
        )

        schema_rejection_file = (
            output_directory
            / "schema_change_rejections.json"
        )

        # ============================================================
        # INCREMENTAL CONFIGURATION
        # ============================================================

        incremental_enabled = any(
            value is not None
            for value in (
                state_key,
                watermark_param,
                watermark_field,
            )
        )

        state_store = None
        state = None
        previous_watermark = None

        if incremental_enabled:

            if (
                state_key is None
                or not state_key.strip()
            ):
                raise DatasetError(
                    "Incremental ingestion requires a state key."
                )

            if (
                watermark_param is None
                or not watermark_param.strip()
            ):
                raise DatasetError(
                    "Incremental ingestion requires "
                    "a watermark parameter."
                )

            if (
                watermark_field is None
                or not watermark_field.strip()
            ):
                raise DatasetError(
                    "Incremental ingestion requires "
                    "a watermark field."
                )

            state_store = IncrementalStateStore(
                data_root=self.data_root
            )

            state = state_store.load(
                state_key
            )

            if state is not None:

                if "cursor_value" not in state:
                    raise DatasetError(
                        "Incremental checkpoint does not contain "
                        "a cursor value."
                    )

                previous_watermark = (
                    state["cursor_value"]
                )

                if (
                    previous_watermark is not None
                    and (
                        isinstance(
                            previous_watermark,
                            bool,
                        )
                        or not isinstance(
                            previous_watermark,
                            (
                                str,
                                int,
                                float,
                            ),
                        )
                    )
                ):
                    raise DatasetError(
                        "Incremental checkpoint contains "
                        "an unsupported cursor value."
                    )

                # ----------------------------------------------------
                # Prevent accidental checkpoint reuse
                # ----------------------------------------------------

                state_metadata = (
                    state.get(
                        "metadata",
                        {}
                    )
                )

                expected_metadata = {
                    "source_url": url,
                    "watermark_param": (
                        watermark_param
                    ),
                    "watermark_field": (
                        watermark_field
                    ),
                    "dataset_name": (
                        safe_dataset_name
                    ),
                    "data_layer": (
                        DataLayer.BRONZE.value
                    ),
                    "output_file": str(
                        output_file
                    ),
                }

                if isinstance(
                    state_metadata,
                    dict,
                ):
                    for (
                        key,
                        expected_value,
                    ) in expected_metadata.items():

                        stored_value = (
                            state_metadata.get(
                                key
                            )
                        )

                        if (
                            stored_value is not None
                            and stored_value
                            != expected_value
                        ):
                            raise DatasetError(
                                "Incremental state key is already "
                                "associated with a different "
                                f"{key}."
                            )


        # ===========================================================
        # Prevent historical data loss
        # ===========================================================
         
        if (
            state is not None
            and not output_file.exists()
        ):
            raise DatasetError(
                "Incremental checkpoint exists but "
                "the associated Bronze dataset is missing. "
                "Refusing to continue because using the "
                "stored checkpoint could skip historical data."
            )


        # ============================================================
        # API EXTRACTION
        # ============================================================

        result = self.api_client.extract_records(
            url=url,
            paginate=paginate,
            records_path=records_path,
            next_path=next_path,
            use_auth=use_auth,
            watermark_param=(
                watermark_param
                if incremental_enabled
                else None
            ),
            watermark_field=(
                watermark_field
                if incremental_enabled
                else None
            ),
            watermark_value=(
                previous_watermark
                if incremental_enabled
                else None
            ),
        )

        # ============================================================
        # TABULAR CONVERSION
        # ============================================================

        try:
            new_dataframe = pd.json_normalize(
                result.records
            )

        except Exception as exc:
            raise DatasetError(
                "Failed to convert extracted API records "
                "into a tabular dataset."
            ) from exc

        # ============================================================
        # INCREMENTAL MERGE
        # ============================================================
        if incremental_enabled:

            try:
                dataframe = (
                    self._merge_incremental_dataframe(
                        existing_file=output_file,
                        new_dataframe=new_dataframe,
                    )
                )

            except SchemaEvolutionError as exc:

                rejection_id = (
                    self._persist_schema_rejection(
                        details=exc.details,
                        rejection_file=(
                            schema_rejection_file
                        ),
                        source_url=url,
                        output_file=output_file,
                        previous_watermark=(
                            previous_watermark
                        ),
                    )
                )

                raise SchemaEvolutionError(
                    (
                        f"{exc} "
                        "The durable dataset and checkpoint "
                        "were not modified. "
                        f"Rejection report: "
                        f"{schema_rejection_file}. "
                        f"Rejection id: "
                        f"{rejection_id}."
                    ),
                    details=exc.details,
                ) from exc


        else:
            dataframe = new_dataframe

        # ============================================================
        # DURABLE DATASET SAVE
        # ============================================================

        self._save_dataframe_atomic(
            dataframe=dataframe,
            file_path=output_file,
            file_format=file_format,
        )

        # ============================================================
        # SCHEMA HISTORY
        # ============================================================

        (
            current_schema_fingerprint,
            current_schema_version,
        ) = self._persist_schema_history(
            dataframe=dataframe,
            schema_history_file=(
                schema_history_file
            ),
            source_url=url,
            output_file=output_file,
        )

        # ============================================================
        # EXTRACTION METADATA
        # ============================================================

        extraction_metadata = dict(
            result.metadata
        )

        extraction_metadata.update(
            {
                "state_key": (
                    state_key
                    if incremental_enabled
                    else None
                ),
                "rows_in_batch": len(
                    new_dataframe
                ),
                "rows_in_dataset": len(
                    dataframe
                ),
                "schema_version": (
                    current_schema_version
                ),
                "schema_fingerprint": (
                    current_schema_fingerprint
                ),
                "schema_history_file": str(
                    schema_history_file
                ),
                "schema_evolution_policy": (
                    self.SCHEMA_EVOLUTION_POLICY
                ),
                "dataset_name": (
                    safe_dataset_name
                ),
                "data_layer": (
                    DataLayer.BRONZE.value
                ),
                "ingestion_mode": (
                    "incremental"
                    if incremental_enabled
                    else "full"
                ),
            }
        )

        self._save_json_atomic(
            payload=extraction_metadata,
            file_path=metadata_file,
        )

        # ============================================================
        # LINEAGE
        # ============================================================

        lineage_event_id = (
            self.lineage_store
            .record_extraction(
                source_url=url,
                target_dataset=(
                    safe_dataset_name
                ),
                target_schema_fingerprint=(
                    current_schema_fingerprint
                ),
                output_format=(
                    file_format
                ),
            )
        )

        # ============================================================
        # CHECKPOINT COMMIT
        # ============================================================
        #
        # This MUST remain after all durable writes above: 
        # dataset, schema history, and extraction metadata
        # ============================================================

        checkpoint_file = None

        if incremental_enabled:

            next_watermark = (
                result.metadata.get(
                    "next_watermark"
                )
            )

            # If no watermark has ever been observed, there is nothing
            # useful to checkpoint yet.
            if next_watermark is not None:

                checkpoint_file = (
                    state_store.save(
                        state_key,
                        cursor_value=next_watermark,
                        metadata={
                            "source_url": url,
                            "watermark_param": (
                                watermark_param
                            ),
                            "watermark_field": (
                                watermark_field
                            ),
                            "output_file": str(
                                output_file
                            ),
                            "dataset_name": (
                                safe_dataset_name
                            ),
                            "data_layer": (
                                DataLayer.BRONZE.value
                            ),
                            "schema_version": (
                                current_schema_version
                            ),
                            "schema_fingerprint": (
                                current_schema_fingerprint
                            ),
                            "schema_evolution_policy": (
                                self.SCHEMA_EVOLUTION_POLICY
                            ),
                        },
                    )
                )

        # ============================================================
        # RESULT
        # ============================================================

        summary = (
            "Data successfully extracted.\n"
            f"Rows in this extraction: "
            f"{len(new_dataframe)}\n"
            f"Rows in dataset: "
            f"{len(dataframe)}\n"
            f"Pages fetched: "
            f"{result.metadata['pages_fetched']}\n"
            f"Bytes downloaded: "
            f"{result.metadata['bytes_downloaded']}\n"
            f"Dataset: {output_file}\n"
            f"Metadata: {metadata_file}\n"
            f"Schema version: "
            f"{current_schema_version}\n"
            f"Schema fingerprint: "
            f"{current_schema_fingerprint}\n"
            f"Schema history: "
            f"{schema_history_file}"
            f"\nDataset name: "
            f"{safe_dataset_name}"
            f"\nData layer: "
            f"{DataLayer.BRONZE.value}"
            f"\nLineage event: {lineage_event_id}"
        )

        if incremental_enabled:
            summary += (
                "\nIncremental ingestion: enabled"
                f"\nPrevious watermark: "
                f"{previous_watermark}"
                f"\nNext watermark: "
                f"{result.metadata.get('next_watermark')}"
            )

            if checkpoint_file is not None:
                summary += (
                    f"\nCheckpoint: "
                    f"{checkpoint_file}"
                )

        return summary
    # ============================================================
    # DATASET CONTEXT
    # ============================================================

    def get_dataset_context(
        self,
        file_path: str,
    ) -> str:
        """
        Return metadata and a small sample for the ETL planner.

        The complete dataset is not sent to the LLM.
        """

        dataframe = (
            self._load_dataframe(
                file_path
            )
        )

        try:
            sample_json = (
                dataframe
                .head(5)
                .to_json(
                    orient="records",
                    date_format="iso",
                )
            )

            context = {
                "row_count": len(
                    dataframe
                ),
                "columns": list(
                    dataframe.columns
                ),
                "dtypes": {
                    column: str(dtype)
                    for column, dtype
                    in dataframe.dtypes.items()
                },
                "null_counts": {
                    column: int(count)
                    for column, count
                    in dataframe
                    .isnull()
                    .sum()
                    .items()
                },
                "sample_rows": (
                    json.loads(
                        sample_json
                    )
                ),
            }

            return json.dumps(
                context,
                indent=2,
                default=str,
            )

        except Exception as exc:
            raise DatasetError(
                "Failed to generate dataset context."
            ) from exc

    # ============================================================
    # COLUMN VALIDATION
    # ============================================================

    @staticmethod
    def _validate_columns(
        dataframe: pd.DataFrame,
        columns: list[str],
    ) -> None:
        """
        Ensure all requested columns exist.
        """

        missing = [
            column
            for column in columns
            if column not in dataframe.columns
        ]

        if missing:
            raise DatasetError(
                "Transformation references missing "
                f"columns: {missing}"
            )

    # ============================================================
    # FILTERING
    # ============================================================

    def _apply_filter(
        self,
        dataframe: pd.DataFrame,
        operation: FilterRowsOperation,
    ) -> pd.DataFrame:
        """
        Apply a validated row filter.
        """

        self._validate_columns(
            dataframe,
            [operation.column],
        )

        series = dataframe[
            operation.column
        ]

        operator = (
            operation.operator
        )

        value = (
            operation.value
        )

        try:

            if operator == "is_null":

                mask = series.isna()

            elif operator == "not_null":

                mask = series.notna()

            elif operator == "contains":

                if not isinstance(
                    value,
                    str,
                ):
                    raise DatasetError(
                        "'contains' requires "
                        "a string value."
                    )

                mask = (
                    series
                    .astype("string")
                    .str.contains(
                        value,
                        case=(
                            operation
                            .case_sensitive
                        ),
                        regex=False,
                        na=False,
                    )
                )

            elif operator in {
                "in",
                "not_in",
            }:

                if not isinstance(
                    value,
                    list,
                ):
                    raise DatasetError(
                        f"'{operator}' requires "
                        "a list value."
                    )

                mask = series.isin(
                    value
                )

                if operator == "not_in":
                    mask = ~mask

            elif operator == "eq":

                mask = (
                    series == value
                )

            elif operator == "ne":

                mask = (
                    series != value
                )

            elif operator == "gt":

                mask = (
                    series > value
                )

            elif operator == "gte":

                mask = (
                    series >= value
                )

            elif operator == "lt":

                mask = (
                    series < value
                )

            elif operator == "lte":

                mask = (
                    series <= value
                )

            else:
                raise DatasetError(
                    "Unsupported filter operator: "
                    f"{operator}"
                )

        except DatasetError:
            raise

        except Exception as exc:
            raise DatasetError(
                "Failed to apply filter on column "
                f"'{operation.column}'."
            ) from exc

        return dataframe.loc[
            mask
        ].copy()

    # ============================================================
    # TYPE CASTING
    # ============================================================

    def _cast_columns(
        self,
        dataframe: pd.DataFrame,
        operation: CastColumnsOperation,
    ) -> pd.DataFrame:
        """
        Safely cast selected columns.
        """

        self._validate_columns(
            dataframe,
            list(
                operation.dtypes.keys()
            ),
        )

        result = dataframe.copy()

        try:

            for column, target_type in (
                operation.dtypes.items()
            ):

                if target_type == "string":

                    result[column] = (
                        result[column]
                        .astype("string")
                    )

                elif target_type == "integer":

                    result[column] = (
                        pd.to_numeric(
                            result[column],
                            errors="raise",
                        )
                        .astype("Int64")
                    )

                elif target_type == "float":

                    result[column] = (
                        pd.to_numeric(
                            result[column],
                            errors="raise",
                        )
                        .astype(float)
                    )

                elif target_type == "datetime":

                    result[column] = (
                        pd.to_datetime(
                            result[column],
                            errors="raise",
                        )
                    )

                elif target_type == "category":

                    result[column] = (
                        result[column]
                        .astype("category")
                    )

                elif target_type == "boolean":

                    if (
                        pd.api.types
                        .is_bool_dtype(
                            result[column]
                        )
                    ):

                        result[column] = (
                            result[column]
                            .astype("boolean")
                        )

                    else:

                        normalized = (
                            result[column]
                            .astype("string")
                            .str.strip()
                            .str.lower()
                        )

                        mapping = {
                            "true": True,
                            "1": True,
                            "yes": True,
                            "false": False,
                            "0": False,
                            "no": False,
                        }

                        non_null_values = (
                            normalized
                            .dropna()
                        )

                        unknown = (
                            non_null_values[
                                ~non_null_values
                                .isin(mapping)
                            ]
                            .unique()
                        )

                        if len(
                            unknown
                        ) > 0:
                            raise DatasetError(
                                "Cannot safely convert "
                                f"'{column}' to boolean. "
                                "Unknown values: "
                                f"{list(unknown)}"
                            )

                        result[column] = (
                            normalized
                            .map(mapping)
                            .astype("boolean")
                        )

        except DatasetError:
            raise

        except Exception as exc:
            raise DatasetError(
                "Failed to cast one or more columns."
            ) from exc

        return result

    # ============================================================
    # APPLY ONE OPERATION
    # ============================================================

    def _apply_operation(
        self,
        dataframe: pd.DataFrame,
        operation,
    ) -> pd.DataFrame:
        """
        Apply one allowed transformation operation.
        """

        # --------------------------------------------------------
        # SELECT COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            SelectColumnsOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            return dataframe.loc[
                :,
                operation.columns,
            ].copy()

        # --------------------------------------------------------
        # DROP COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            DropColumnsOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            return dataframe.drop(
                columns=operation.columns
            )

        # --------------------------------------------------------
        # RENAME COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            RenameColumnsOperation,
        ):

            self._validate_columns(
                dataframe,
                list(
                    operation.mapping.keys()
                ),
            )

            return dataframe.rename(
                columns=operation.mapping
            )

        # --------------------------------------------------------
        # FILTER ROWS
        # --------------------------------------------------------

        if isinstance(
            operation,
            FilterRowsOperation,
        ):

            return self._apply_filter(
                dataframe,
                operation,
            )

        # --------------------------------------------------------
        # DROP DUPLICATES
        # --------------------------------------------------------

        if isinstance(
            operation,
            DropDuplicatesOperation,
        ):

            if operation.subset:

                self._validate_columns(
                    dataframe,
                    operation.subset,
                )

            return (
                dataframe
                .drop_duplicates(
                    subset=operation.subset,
                    keep=operation.keep,
                )
                .copy()
            )

        # --------------------------------------------------------
        # SORT VALUES
        # --------------------------------------------------------

        if isinstance(
            operation,
            SortValuesOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            return (
                dataframe
                .sort_values(
                    by=operation.columns,
                    ascending=(
                        operation.ascending
                    ),
                    kind="stable",
                )
                .copy()
            )

        # --------------------------------------------------------
        # FILL MISSING
        # --------------------------------------------------------

        if isinstance(
            operation,
            FillMissingOperation,
        ):

            self._validate_columns(
                dataframe,
                list(
                    operation.values.keys()
                ),
            )

            try:
                return dataframe.fillna(
                    value=operation.values
                )

            except Exception as exc:
                raise DatasetError(
                    "Failed to fill missing values."
                ) from exc

        # --------------------------------------------------------
        # CAST COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            CastColumnsOperation,
        ):

            return self._cast_columns(
                dataframe,
                operation,
            )

        # --------------------------------------------------------
        # STRING TRANSFORMS
        # --------------------------------------------------------

        if isinstance(
            operation,
            StringTransformOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            result = dataframe.copy()

            try:

                for column in (
                    operation.columns
                ):

                    values = (
                        result[column]
                        .astype("string")
                    )

                    if (
                        operation.action
                        == "strip"
                    ):

                        values = (
                            values
                            .str.strip()
                        )

                    elif (
                        operation.action
                        == "lower"
                    ):

                        values = (
                            values
                            .str.lower()
                        )

                    elif (
                        operation.action
                        == "upper"
                    ):

                        values = (
                            values
                            .str.upper()
                        )

                    result[column] = values

            except Exception as exc:
                raise DatasetError(
                    "Failed to apply string "
                    "transformation."
                ) from exc

            return result

        # --------------------------------------------------------
        # GROUP BY / AGGREGATE
        # --------------------------------------------------------

        if isinstance(
            operation,
            GroupByAggregateOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.group_by,
            )

            aggregation_columns = [
                item.column
                for item
                in operation.aggregations
            ]

            self._validate_columns(
                dataframe,
                aggregation_columns,
            )

            named_aggregations = {}

            for item in (
                operation.aggregations
            ):

                if (
                    item.alias
                    in named_aggregations
                ):
                    raise DatasetError(
                        "Duplicate aggregation alias: "
                        f"{item.alias}"
                    )

                named_aggregations[
                    item.alias
                ] = pd.NamedAgg(
                    column=item.column,
                    aggfunc=item.function,
                )

            try:
                return (
                    dataframe
                    .groupby(
                        operation.group_by,
                        dropna=False,
                    )
                    .agg(
                        **named_aggregations
                    )
                    .reset_index()
                )

            except Exception as exc:
                raise DatasetError(
                    "Failed to perform grouped "
                    "aggregation."
                ) from exc

        raise DatasetError(
            "Unsupported transformation operation: "
            f"{type(operation).__name__}"
        )

    # ============================================================
    # APPLY TRANSFORMATION PLAN
    # ============================================================

    def apply_transform_plan(
        self,
        dataframe: pd.DataFrame,
        plan: TransformPlan,
    ) -> pd.DataFrame:
        """
        Apply a validated sequence of deterministic transformations.
        """

        result = dataframe.copy()

        for index, operation in enumerate(
            plan.operations,
            start=1,
        ):

            try:
                result = (
                    self._apply_operation(
                        result,
                        operation,
                    )
                )

            except DatasetError as exc:
                raise DatasetError(
                    "Transformation failed at "
                    f"operation {index} "
                    f"({operation.type}): {exc}"
                ) from exc

        return result

    # ============================================================
    # TRANSFORM + LOAD
    # ============================================================

    def transform_load(
        self,
        input_file_path: str,
        output_folder: str,
        output_format: str,
        plan: TransformPlan,
    ) -> str:
        """
        Load a dataset, execute a validated transformation plan,
        and save the transformed result.
        """

        file_format = (
            self._validate_format(
                output_format
            )
        )

        dataframe = (
            self._load_dataframe(
                input_file_path
            )
        )

        original_rows = len(
            dataframe
        )

        original_columns = len(
            dataframe.columns
        )

        transformed = (
            self.apply_transform_plan(
                dataframe,
                plan,
            )
        )

        output_directory = (
            self._resolve_data_path(
                output_folder
            )
        )

        output_file = (
            output_directory
            / (
                "transformed_data."
                f"{file_format}"
            )
        )

        self._save_dataframe(
            dataframe=transformed,
            file_path=output_file,
            file_format=file_format,
        )

        return (
            "Transformation completed successfully.\n"
            f"Input rows: {original_rows}\n"
            f"Input columns: {original_columns}\n"
            f"Output rows: {len(transformed)}\n"
            f"Output columns: "
            f"{list(transformed.columns)}\n"
            f"Output file: {output_file}\n"
            f"Plan summary: {plan.summary}"
        )


    def transform_bronze_to_silver(
        self,
        source_dataset_name: str,
        plan: TransformPlan,
        target_dataset_name: str | None = None,
        output_format: str = "csv",
    ) -> str:
        """
        Transform a Bronze dataset into a deterministic Silver dataset.

        Bronze is treated as the immutable source.

        The transformation plan may intentionally change the schema,
        because Silver represents cleaned and standardized data.

        If a Silver quality contract exists for the target dataset,
        the transformed candidate must pass it before durable
        persistence occurs.
        """

        source_name = (
            validate_dataset_name(
                source_dataset_name
            )
        )

        target_name = (
            validate_dataset_name(
                target_dataset_name
                if target_dataset_name
                is not None
                else source_name
            )
        )

        file_format = (
            self._validate_format(
                output_format
            )
        )

        # ============================================================
        # RESOLVE BRONZE SOURCE
        # ============================================================

        source_file = (
            self._resolve_layer_dataset_file(
                layer=DataLayer.BRONZE,
                dataset_name=source_name,
                file_stem="extracted_data",
            )
        )

        source_dataframe = (
            self._load_dataframe(
                str(source_file)
            )
        )

        original_rows = len(
            source_dataframe
        )

        original_columns = list(
            source_dataframe.columns
        )

        source_schema = (
            dataframe_schema(
                source_dataframe
            )
        )

        source_schema_fingerprint = (
            schema_fingerprint(
                source_schema
            )
        )

        # ============================================================
        # APPLY DETERMINISTIC TRANSFORMATION
        # ============================================================

        transformed = (
            self.apply_transform_plan(
                source_dataframe,
                plan,
            )
        )

        # ============================================================
        # CANDIDATE OUTPUT SCHEMA
        # ============================================================

        output_schema = (
            dataframe_schema(
                transformed
            )
        )

        output_schema_fingerprint = (
            schema_fingerprint(
                output_schema
            )
        )

        # ============================================================
        # SILVER DESTINATION
        # ============================================================

        output_directory = (
            resolve_layer_dataset_directory(
                data_root=self.data_root,
                layer=DataLayer.SILVER,
                dataset_name=target_name,
            )
        )

        output_file = (
            output_directory
            / (
                "transformed_data."
                f"{file_format}"
            )
        )

        metadata_file = (
            output_directory
            / "transformation_metadata.json"
        )

        quality_rejection_file = (
            output_directory
            / "quality_rejections.json"
        )

        # ============================================================
        # SILVER QUALITY GATE
        # ============================================================
        #
        # IMPORTANT:
        #
        # This MUST happen before the durable Silver save.
        #
        # If the candidate fails its contract:
        #
        # - DataQualityError is raised
        # - rejection metadata is persisted
        # - the existing Silver dataset is NOT replaced
        # - metadata is NOT replaced
        # - successful lineage is NOT written
        # ============================================================

        (
            quality_result,
            quality_contract_fingerprint_value,
        ) = self._evaluate_quality_gate(
            dataframe=transformed,
            layer=DataLayer.SILVER,
            dataset_name=target_name,
            rejection_file=(
                quality_rejection_file
            ),
        )

        # ============================================================
        # DURABLE SILVER SAVE
        # ============================================================

        self._save_dataframe_atomic(
            dataframe=transformed,
            file_path=output_file,
            file_format=file_format,
        )

        # ============================================================
        # TRANSFORMATION METADATA
        # ============================================================

        metadata = {
            "metadata_version": 1,
            "transformed_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "source_dataset": (
                source_name
            ),
            "source_layer": (
                DataLayer.BRONZE.value
            ),
            "source_file": str(
                source_file
            ),
            "source_schema": (
                source_schema
            ),
            "source_schema_fingerprint": (
                source_schema_fingerprint
            ),
            "target_dataset": (
                target_name
            ),
            "target_layer": (
                DataLayer.SILVER.value
            ),
            "output_file": str(
                output_file
            ),
            "output_format": (
                file_format
            ),
            "input_rows": (
                original_rows
            ),
            "output_rows": len(
                transformed
            ),
            "input_columns": (
                original_columns
            ),
            "output_columns": list(
                transformed.columns
            ),
            "output_schema": (
                output_schema
            ),
            "output_schema_fingerprint": (
                output_schema_fingerprint
            ),

            # ========================================================
            # QUALITY METADATA
            # ========================================================

            "quality_gate": {
                "contract_configured": (
                    quality_result
                    is not None
                ),
                "contract_fingerprint": (
                    quality_contract_fingerprint_value
                ),
                "result": (
                    quality_result
                ),
            },

            "transformation_plan": (
                plan.model_dump(
                    mode="json"
                )
            ),
        }

        self._save_json_atomic(
            payload=metadata,
            file_path=metadata_file,
        )

        # ============================================================
        # LINEAGE
        # ============================================================

        plan_payload = (
            plan.model_dump(
                mode="json"
            )
        )

        lineage_event_id = (
            self.lineage_store
            .record_transition(
                operation="transform",
                source_layer=(
                    DataLayer.BRONZE
                ),
                source_dataset=(
                    source_name
                ),
                source_schema_fingerprint=(
                    source_schema_fingerprint
                ),
                target_layer=(
                    DataLayer.SILVER
                ),
                target_dataset=(
                    target_name
                ),
                target_schema_fingerprint=(
                    output_schema_fingerprint
                ),
                plan_payload=(
                    plan_payload
                ),
                output_format=(
                    file_format
                ),
                quality_contract_fingerprint=(
                    quality_contract_fingerprint_value
                ),
                quality_result=(
                    quality_result
                ),
            )
        )

        # ============================================================
        # RESULT
        # ============================================================

        quality_status = (
            "passed"
            if quality_result is not None
            else "not configured"
        )

        return (
            "Bronze-to-Silver transformation "
            "completed successfully.\n"
            f"Source dataset: {source_name}\n"
            f"Source layer: "
            f"{DataLayer.BRONZE.value}\n"
            f"Target dataset: {target_name}\n"
            f"Target layer: "
            f"{DataLayer.SILVER.value}\n"
            f"Input rows: {original_rows}\n"
            f"Output rows: "
            f"{len(transformed)}\n"
            f"Output columns: "
            f"{list(transformed.columns)}\n"
            f"Output schema fingerprint: "
            f"{output_schema_fingerprint}\n"
            f"Quality contract: "
            f"{quality_status}\n"
            f"Output file: {output_file}\n"
            f"Metadata: {metadata_file}\n"
            f"Plan summary: {plan.summary}"
            f"\nLineage event: {lineage_event_id}"
        )

    def transform_silver_to_gold(
        self,
        source_dataset_name: str,
        plan: TransformPlan,
        target_dataset_name: str | None = None,
        output_format: str = "csv",
    ) -> str:
        """
        Transform a Silver dataset into a deterministic Gold dataset.

        Gold datasets are curated, analytics-ready outputs derived
        exclusively from Silver datasets.

        The validated TransformPlan may intentionally filter,
        aggregate, select, rename, or otherwise reshape the data.

        If a Gold quality contract exists for the target dataset,
        the curated candidate must pass it before durable
        persistence occurs.
        """

        source_name = (
            validate_dataset_name(
                source_dataset_name
            )
        )

        target_name = (
            validate_dataset_name(
                target_dataset_name
                if target_dataset_name
                is not None
                else source_name
            )
        )

        file_format = (
            self._validate_format(
                output_format
            )
        )

        # ============================================================
        # RESOLVE SILVER SOURCE
        # ============================================================

        source_file = (
            self._resolve_layer_dataset_file(
                layer=DataLayer.SILVER,
                dataset_name=source_name,
                file_stem="transformed_data",
            )
        )

        source_dataframe = (
            self._load_dataframe(
                str(source_file)
            )
        )

        original_rows = len(
            source_dataframe
        )

        original_columns = list(
            source_dataframe.columns
        )

        source_schema = (
            dataframe_schema(
                source_dataframe
            )
        )

        source_schema_fingerprint = (
            schema_fingerprint(
                source_schema
            )
        )

        # ============================================================
        # APPLY DETERMINISTIC CURATION
        # ============================================================

        curated = (
            self.apply_transform_plan(
                source_dataframe,
                plan,
            )
        )

        # ============================================================
        # CANDIDATE OUTPUT SCHEMA
        # ============================================================

        output_schema = (
            dataframe_schema(
                curated
            )
        )

        output_schema_fingerprint = (
            schema_fingerprint(
                output_schema
            )
        )

        # ============================================================
        # GOLD DESTINATION
        # ============================================================

        output_directory = (
            resolve_layer_dataset_directory(
                data_root=self.data_root,
                layer=DataLayer.GOLD,
                dataset_name=target_name,
            )
        )

        output_file = (
            output_directory
            / (
                "curated_data."
                f"{file_format}"
            )
        )

        metadata_file = (
            output_directory
            / "curation_metadata.json"
        )

        quality_rejection_file = (
            output_directory
            / "quality_rejections.json"
        )

        # ============================================================
        # GOLD QUALITY GATE
        # ============================================================
        #
        # The candidate Gold dataset must pass its configured
        # quality contract before the existing durable Gold
        # dataset may be replaced.
        # ============================================================

        (
            quality_result,
            quality_contract_fingerprint_value,
        ) = self._evaluate_quality_gate(
            dataframe=curated,
            layer=DataLayer.GOLD,
            dataset_name=target_name,
            rejection_file=(
                quality_rejection_file
            ),
        )

        # ============================================================
        # DURABLE GOLD SAVE
        # ============================================================

        self._save_dataframe_atomic(
            dataframe=curated,
            file_path=output_file,
            file_format=file_format,
        )

        # ============================================================
        # GOLD METADATA
        # ============================================================

        metadata = {
            "metadata_version": 1,
            "curated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "source_dataset": (
                source_name
            ),
            "source_layer": (
                DataLayer.SILVER.value
            ),
            "source_file": str(
                source_file
            ),
            "source_schema": (
                source_schema
            ),
            "source_schema_fingerprint": (
                source_schema_fingerprint
            ),
            "target_dataset": (
                target_name
            ),
            "target_layer": (
                DataLayer.GOLD.value
            ),
            "output_file": str(
                output_file
            ),
            "output_format": (
                file_format
            ),
            "input_rows": (
                original_rows
            ),
            "output_rows": len(
                curated
            ),
            "input_columns": (
                original_columns
            ),
            "output_columns": list(
                curated.columns
            ),
            "output_schema": (
                output_schema
            ),
            "output_schema_fingerprint": (
                output_schema_fingerprint
            ),

            # ========================================================
            # QUALITY METADATA
            # ========================================================

            "quality_gate": {
                "contract_configured": (
                    quality_result
                    is not None
                ),
                "contract_fingerprint": (
                    quality_contract_fingerprint_value
                ),
                "result": (
                    quality_result
                ),
            },

            "curation_plan": (
                plan.model_dump(
                    mode="json"
                )
            ),
        }

        self._save_json_atomic(
            payload=metadata,
            file_path=metadata_file,
        )

        # ============================================================
        # LINEAGE
        # ============================================================

        plan_payload = (
            plan.model_dump(
                mode="json"
            )
        )

        lineage_event_id = (
            self.lineage_store
            .record_transition(
                operation="curate",
                source_layer=(
                    DataLayer.SILVER
                ),
                source_dataset=(
                    source_name
                ),
                source_schema_fingerprint=(
                    source_schema_fingerprint
                ),
                target_layer=(
                    DataLayer.GOLD
                ),
                target_dataset=(
                    target_name
                ),
                target_schema_fingerprint=(
                    output_schema_fingerprint
                ),
                plan_payload=(
                    plan_payload
                ),
                output_format=(
                    file_format
                ),
                quality_contract_fingerprint=(
                    quality_contract_fingerprint_value
                ),
                quality_result=(
                    quality_result
                ),
            )
        )

        # ============================================================
        # RESULT
        # ============================================================

        quality_status = (
            "passed"
            if quality_result is not None
            else "not configured"
        )

        return (
            "Silver-to-Gold curation "
            "completed successfully.\n"
            f"Source dataset: {source_name}\n"
            f"Source layer: "
            f"{DataLayer.SILVER.value}\n"
            f"Target dataset: {target_name}\n"
            f"Target layer: "
            f"{DataLayer.GOLD.value}\n"
            f"Input rows: {original_rows}\n"
            f"Output rows: "
            f"{len(curated)}\n"
            f"Output columns: "
            f"{list(curated.columns)}\n"
            f"Output schema fingerprint: "
            f"{output_schema_fingerprint}\n"
            f"Quality contract: "
            f"{quality_status}\n"
            f"Output file: {output_file}\n"
            f"Metadata: {metadata_file}\n"
            f"Plan summary: {plan.summary}"
            f"\nLineage event: {lineage_event_id}"
        )


# using this function the physical path remains completely application-controlled. 
    def get_layer_dataset_context(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
    ) -> str:
        """
        Return planner-safe context for a deterministic
        medallion-layer dataset.
        """

        if layer == DataLayer.BRONZE:
            file_stem = "extracted_data"

        elif layer == DataLayer.SILVER:
            file_stem = "transformed_data"

        elif layer == DataLayer.GOLD:
            file_stem = "curated_data"

        else:
            raise DatasetError(
                f"Unsupported data layer: {layer}"
            )

        dataset_file = (
            self._resolve_layer_dataset_file(
                layer=layer,
                dataset_name=dataset_name,
                file_stem=file_stem,
            )
        )

        return self.get_dataset_context(
            str(dataset_file)
        )