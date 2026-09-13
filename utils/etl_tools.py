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
    DatasetError,
    UnsupportedFormatError,
)

from utils.incremental_state import IncrementalStateStore

from utils.schema_evolution import (
    compare_schemas,
    dataframe_schema,
    schema_fingerprint,
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

            details = []

            if schema_diff.added_columns:
                details.append(
                    "Added columns: "
                    f"{list(schema_diff.added_columns)}."
                )

            if schema_diff.removed_columns:
                details.append(
                    "Removed columns: "
                    f"{list(schema_diff.removed_columns)}."
                )

            if schema_diff.type_changes:
                details.append(
                    "Type changes: "
                    f"{schema_diff.type_changes}."
                )

            raise DatasetError(
                "Breaking incremental API schema change detected. "
                + " ".join(details)
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
        output_folder: str,
        format: str,
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
        2. Dataset persistence succeeds.
        3. Extraction metadata persistence succeeds.
        """

        # ============================================================
        # OUTPUT VALIDATION
        # ============================================================

        file_format = self._validate_format(
            format
        )

        output_directory = (
            self._resolve_data_path(
                output_folder
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

            dataframe = (
                self._merge_incremental_dataframe(
                    existing_file=output_file,
                    new_dataframe=new_dataframe,
                )
            )

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
            }
        )

        self._save_json_atomic(
            payload=extraction_metadata,
            file_path=metadata_file,
        )

        # ============================================================
        # CHECKPOINT COMMIT
        # ============================================================
        #
        # This MUST remain after both durable writes above.
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