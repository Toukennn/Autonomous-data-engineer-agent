import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from utils.data_layers import DataLayer
from utils.exceptions import DatasetError


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
    ) -> str:
        """
        Record a deterministic dataset-to-dataset transition.
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