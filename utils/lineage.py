import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from utils.data_layers import DataLayer
from utils.exceptions import DatasetError

from utils.dbt_artifacts import (
    DBTBuildArtifactSummary,
)


def payload_fingerprint(
    payload: object,
) -> str:
    """
    Create a stable SHA-256 fingerprint for a JSON-serializable
    payload.

    Used primarily to identify transformation plans without
    duplicating the complete plan inside the lineage log.
    """

    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetError(
            "Failed to fingerprint lineage payload."
        ) from exc

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


class LineageStore:
    """
    Persistent append-only lineage store.

    Lineage is application-controlled and must never be
    written directly by an LLM.
    """

    LINEAGE_VERSION = 1
    _ALLOWED_OPERATIONS = {
        "extract",
        "transform",
        "curate",
        "warehouse_sync",
        "dbt_build",
    }

    def __init__(
        self,
        data_root: Path,
    ):
        self.data_root = (
            data_root.resolve()
        )

        self.lineage_directory = (
            self.data_root
            / "_lineage"
        ).resolve()

        try:
            self.lineage_directory.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Lineage directory escaped the "
                "configured data directory."
            ) from exc

        self.lineage_file = (
            self.lineage_directory
            / "lineage.json"
        )

    def _load_document(
        self,
    ) -> dict:
        """
        Load and validate the lineage document.
        """

        if not self.lineage_file.exists():
            return {
                "lineage_version": (
                    self.LINEAGE_VERSION
                ),
                "events": [],
            }

        try:
            with self.lineage_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                document = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise DatasetError(
                "Failed to load lineage history."
            ) from exc

        if not isinstance(
            document,
            dict,
        ):
            raise DatasetError(
                "Lineage history must be a JSON object."
            )

        version = document.get(
            "lineage_version"
        )

        if (
            version
            != self.LINEAGE_VERSION
        ):
            raise DatasetError(
                "Unsupported lineage history version."
            )

        events = document.get(
            "events"
        )

        if not isinstance(
            events,
            list,
        ):
            raise DatasetError(
                "Lineage history contains an "
                "invalid events list."
            )

        return document

    def _save_document_atomic(
        self,
        document: dict,
    ) -> None:
        """
        Atomically replace the lineage document.
        """

        temp_file = (
            self.lineage_file
            .with_name(
                ".lineage.json.tmp"
            )
        )

        try:
            self.lineage_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            with temp_file.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    document,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )

            temp_file.replace(
                self.lineage_file
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
                "Failed to atomically persist lineage."
            ) from exc

    def _append_event(
        self,
        *,
        operation: str,
        source: dict,
        target: dict,
        metadata: dict | None = None,
    ) -> str:
        """
        Append one successful pipeline event.
        """

        if (
            operation
            not in self._ALLOWED_OPERATIONS
        ):
            raise DatasetError(
                "Unsupported lineage operation: "
                f"{operation}"
            )

        document = (
            self._load_document()
        )

        event_id = str(
            uuid4()
        )

        event = {
            "event_id": event_id,
            "recorded_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "operation": operation,
            "source": source,
            "target": target,
            "metadata": (
                metadata
                if metadata is not None
                else {}
            ),
        }

        document[
            "events"
        ].append(
            event
        )

        self._save_document_atomic(
            document
        )

        return event_id

    def record_extraction(
        self,
        *,
        source_url: str,
        target_dataset: str,
        target_schema_fingerprint: str,
        output_format: str,
    ) -> str:
        """
        Record External API -> Bronze lineage.
        """

        return self._append_event(
            operation="extract",
            source={
                "type": "api",
                "url": source_url,
            },
            target={
                "type": "dataset",
                "layer": (
                    DataLayer.BRONZE.value
                ),
                "dataset": (
                    target_dataset
                ),
                "schema_fingerprint": (
                    target_schema_fingerprint
                ),
            },
            metadata={
                "output_format": (
                    output_format
                ),
            },
        )


    def record_warehouse_sync(
        self,
        *,
        source_dataset: str,
        source_schema_fingerprint: str,
        warehouse_schema: str,
        warehouse_table: str,
        row_count: int,
        column_count: int,
        load_mode: str,
        business_key_configured: bool,
        business_key_column_count: int,
        business_key_fingerprint: (
            str | None
        ),
        source_dataset_fingerprint: str,
        checkpoint_bound: bool,
    ) -> str:
        """
        Record successful materialization of a durable
        Bronze dataset into the PostgreSQL warehouse.

        This is not a Medallion transformation.
        The logical data remains Bronze; only its
        physical execution/storage backend changes.
        """

        if warehouse_schema != (
            DataLayer.BRONZE.value
        ):
            raise DatasetError(
                "Bronze warehouse synchronization "
                "must target the Bronze schema."
            )

        if (
            not isinstance(
                row_count,
                int,
            )
            or isinstance(
                row_count,
                bool,
            )
            or row_count < 0
        ):
            raise DatasetError(
                "Warehouse lineage row count "
                "must be a non-negative integer."
            )

        if (
            not isinstance(
                column_count,
                int,
            )
            or isinstance(
                column_count,
                bool,
            )
            or column_count < 1
        ):
            raise DatasetError(
                "Warehouse lineage column count "
                "must be a positive integer."
            )

        if load_mode not in {
            "refresh_in_place",
            "merge_upsert",
        }:
            raise DatasetError(
                "Unsupported warehouse lineage "
                "load mode."
            )

        if not isinstance(
            business_key_configured,
            bool,
        ):
            raise DatasetError(
                "Warehouse lineage business-key "
                "configuration flag must be boolean."
            )

        if (
            not isinstance(
                business_key_column_count,
                int,
            )
            or isinstance(
                business_key_column_count,
                bool,
            )
            or business_key_column_count < 0
        ):
            raise DatasetError(
                "Warehouse lineage business-key "
                "column count must be a "
                "non-negative integer."
            )

        if not isinstance(
            checkpoint_bound,
            bool,
        ):
            raise DatasetError(
                "Warehouse lineage checkpoint-bound "
                "flag must be boolean."
            )

        if (
            not isinstance(
                source_dataset_fingerprint,
                str,
            )
            or not source_dataset_fingerprint
        ):
            raise DatasetError(
                "Warehouse lineage requires a "
                "source dataset fingerprint."
            )

        if load_mode == "merge_upsert":

            if not business_key_configured:
                raise DatasetError(
                    "merge_upsert lineage requires "
                    "a configured business key."
                )

            if business_key_column_count < 1:
                raise DatasetError(
                    "merge_upsert lineage requires "
                    "at least one business-key column."
                )

            if (
                not isinstance(
                    business_key_fingerprint,
                    str,
                )
                or not business_key_fingerprint
            ):
                raise DatasetError(
                    "merge_upsert lineage requires "
                    "a business-key fingerprint."
                )

        else:

            if business_key_configured:
                raise DatasetError(
                    "refresh_in_place lineage cannot "
                    "claim a configured business key."
                )

            if business_key_column_count != 0:
                raise DatasetError(
                    "refresh_in_place lineage cannot "
                    "contain business-key columns."
                )

            if business_key_fingerprint is not None:
                raise DatasetError(
                    "refresh_in_place lineage cannot "
                    "contain a business-key fingerprint."
                )


        return self._append_event(
            operation=(
                "warehouse_sync"
            ),
            source={
                "type": "dataset",
                "layer": (
                    DataLayer.BRONZE.value
                ),
                "dataset": (
                    source_dataset
                ),
                "schema_fingerprint": (
                    source_schema_fingerprint
                ),
            },
            target={
                "type": (
                    "warehouse_table"
                ),
                "schema": (
                    warehouse_schema
                ),
                "table": (
                    warehouse_table
                ),
            },
            metadata={
                "load_mode": (
                    load_mode
                ),
                "row_count": (
                    row_count
                ),
                "column_count": (
                    column_count
                ),
                "source_dataset_fingerprint": (
                    source_dataset_fingerprint
                ),
                "checkpoint_bound": (
                    checkpoint_bound
                ),
                "business_key": {
                    "configured": (
                        business_key_configured
                    ),
                    "column_count": (
                        business_key_column_count
                    ),
                    "contract_fingerprint": (
                        business_key_fingerprint
                    ),
                },
            },
        )
    

    def record_transition(
        self,
        *,
        operation: str,
        source_layer: DataLayer,
        source_dataset: str,
        source_schema_fingerprint: str,
        target_layer: DataLayer,
        target_dataset: str,
        target_schema_fingerprint: str,
        plan_payload: dict,
        output_format: str,
        quality_contract_fingerprint: (
            str | None
        ) = None,
        quality_result: (
            dict | None
        ) = None,
    ) -> str:
        """
        Record a successful deterministic
        dataset-to-dataset transition.

        When a quality contract governs the
        promotion, lineage records a compact
        summary proving which contract authorized
        the durable output.
        """

        if operation not in {
            "transform",
            "curate",
        }:
            raise DatasetError(
                "Dataset lineage transition must "
                "be transform or curate."
            )

        plan_hash = (
            payload_fingerprint(
                plan_payload
            )
        )

        # ============================================================
        # QUALITY LINEAGE
        # ============================================================

        contract_configured = (
            quality_contract_fingerprint
            is not None
        )

        if (
            contract_configured
            != (
                quality_result
                is not None
            )
        ):
            raise DatasetError(
                "Lineage quality metadata is "
                "incomplete. Contract fingerprint "
                "and quality result must either "
                "both be present or both be absent."
            )

        if quality_result is not None:

            passed = (
                quality_result.get(
                    "passed"
                )
            )

            total_checks = (
                quality_result.get(
                    "total_checks"
                )
            )

            failed_checks = (
                quality_result.get(
                    "failed_checks"
                )
            )

            if passed is not True:
                raise DatasetError(
                    "Successful lineage cannot be "
                    "written for a failed "
                    "data-quality gate."
                )

            if (
                not isinstance(
                    total_checks,
                    int,
                )
                or isinstance(
                    total_checks,
                    bool,
                )
                or total_checks < 0
            ):
                raise DatasetError(
                    "Invalid quality total-check "
                    "count for lineage."
                )

            if (
                not isinstance(
                    failed_checks,
                    int,
                )
                or isinstance(
                    failed_checks,
                    bool,
                )
                or failed_checks < 0
            ):
                raise DatasetError(
                    "Invalid quality failed-check "
                    "count for lineage."
                )

            quality_metadata = {
                "contract_configured": True,
                "contract_fingerprint": (
                    quality_contract_fingerprint
                ),
                "passed": True,
                "total_checks": (
                    total_checks
                ),
                "failed_checks": (
                    failed_checks
                ),
            }

        else:

            quality_metadata = {
                "contract_configured": False,
                "contract_fingerprint": None,
                "passed": None,
                "total_checks": None,
                "failed_checks": None,
            }

        return self._append_event(
            operation=operation,
            source={
                "type": "dataset",
                "layer": (
                    source_layer.value
                ),
                "dataset": (
                    source_dataset
                ),
                "schema_fingerprint": (
                    source_schema_fingerprint
                ),
            },
            target={
                "type": "dataset",
                "layer": (
                    target_layer.value
                ),
                "dataset": (
                    target_dataset
                ),
                "schema_fingerprint": (
                    target_schema_fingerprint
                ),
            },
            metadata={
                "plan_fingerprint": (
                    plan_hash
                ),
                "output_format": (
                    output_format
                ),
                "quality_gate": (
                    quality_metadata
                ),
            },
        )


    def get_events(
        self,
    ) -> list[dict]:
        """
        Return persisted lineage events.
        """

        document = (
            self._load_document()
        )

        return list(
            document["events"]
        )

    def record_dbt_build(
        self,
        *,
        source_layer: DataLayer,
        source_dataset: str,
        target_layer: DataLayer,
        target_dataset: str,
        model_name: str,
        plan_fingerprint: str,
        quality_contract_fingerprint: (
            str | None
        ),
        materialization: str,
        incremental_eligible: bool,
        incremental_key_column_count: int,
        artifact: DBTBuildArtifactSummary,
    ) -> str:
        """
        Record one successful, artifact-verified
        dbt model build.

        No compiled SQL, raw dbt messages,
        credentials, or adapter responses are
        persisted.
        """

        if target_layer not in {
            DataLayer.SILVER,
            DataLayer.GOLD,
        }:
            raise DatasetError(
                "dbt lineage supports "
                "Silver and Gold only."
            )

        expected_source_layer = (
            DataLayer.BRONZE
            if (
                target_layer
                == DataLayer.SILVER
            )
            else DataLayer.SILVER
        )

        if (
            source_layer
            != expected_source_layer
        ):
            raise DatasetError(
                "Invalid dbt lineage "
                "source layer."
            )

        if (
            artifact.target_status
            != "success"
        ):
            raise DatasetError(
                "Successful dbt lineage cannot "
                "be written for a failed model."
            )

        if (
            artifact.target_model_name
            != model_name
        ):
            raise DatasetError(
                "dbt lineage model identity "
                "does not match the artifact."
            )

        if (
            artifact.relation_name
            != model_name
        ):
            raise DatasetError(
                "dbt lineage relation identity "
                "does not match the model."
            )


        allowed_materializations = (
            {
                "view",
            }
            if target_layer
            == DataLayer.SILVER
            else {
                "table",
                "incremental",
            }
        )

        if (
            materialization
            not in allowed_materializations
        ):
            raise DatasetError(
                "Invalid dbt lineage materialization."
            )

        if not isinstance(
            incremental_eligible,
            bool,
        ):
            raise DatasetError(
                "dbt lineage incremental eligibility "
                "must be boolean."
            )

        if (
            not isinstance(
                incremental_key_column_count,
                int,
            )
            or isinstance(
                incremental_key_column_count,
                bool,
            )
            or incremental_key_column_count < 0
        ):
            raise DatasetError(
                "dbt lineage incremental key-column "
                "count must be non-negative."
            )

        if (
            incremental_eligible
            and incremental_key_column_count < 1
        ):
            raise DatasetError(
                "Incremental-eligible dbt lineage "
                "requires at least one key column."
            )

        if (
            not incremental_eligible
            and incremental_key_column_count != 0
        ):
            raise DatasetError(
                "Non-incremental dbt lineage cannot "
                "contain incremental key columns."
            )

        if (
            target_layer == DataLayer.GOLD
            and materialization == "incremental"
            and not incremental_eligible
        ):
            raise DatasetError(
                "Incremental Gold materialization "
                "requires incremental eligibility."
            )

        if (
            target_layer == DataLayer.GOLD
            and materialization == "table"
            and incremental_eligible
        ):
            raise DatasetError(
                "Incremental-eligible Gold lineage "
                "must use incremental materialization."
            )

        tests = [
            {
                "unique_id": (
                    test.unique_id
                ),
                "name": (
                    test.name
                ),
                "status": (
                    test.status
                ),
                "execution_time_seconds": (
                    test
                    .execution_time_seconds
                ),
                "failures": (
                    test.failures
                ),
                "directly_tests_target": (
                    test
                    .directly_tests_target
                ),
            }
            for test
            in artifact.tests
        ]

        return self._append_event(
            operation="dbt_build",
            source={
                "type": "dataset",
                "layer": (
                    source_layer.value
                ),
                "dataset": (
                    source_dataset
                ),
            },
            target={
                "type": "dbt_model",
                "layer": (
                    target_layer.value
                ),
                "dataset": (
                    target_dataset
                ),
                "model": (
                    model_name
                ),
                "unique_id": (
                    artifact
                    .target_model_unique_id
                ),
                "relation": {
                    "schema": (
                        artifact
                        .relation_schema
                    ),
                    "name": (
                        artifact
                        .relation_name
                    ),
                },
            },
            metadata={
                "invocation_id": (
                    artifact
                    .invocation_id
                ),
                "plan_fingerprint": (
                    plan_fingerprint
                ),
                "quality_contract_fingerprint": (
                    quality_contract_fingerprint
                ),
                "dependencies": list(
                    artifact
                    .dependency_unique_ids
                ),
                "executed_models": list(
                    artifact
                    .executed_model_unique_ids
                ),
                "execution": {
                    "target_status": (
                        artifact
                        .target_status
                    ),
                    "target_execution_time_seconds": (
                        artifact
                        .target_execution_time_seconds
                    ),
                    "total_elapsed_time_seconds": (
                        artifact
                        .elapsed_time_seconds
                    ),
                },
                "tests": tests,
                "materialization": (
                    materialization
                ),
                "incremental": {
                    "eligible": (
                        incremental_eligible
                    ),
                    "key_column_count": (
                        incremental_key_column_count
                    ),
                },
            },
        )