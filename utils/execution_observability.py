import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from utils.exceptions import DatasetError


class ExecutionRunStore:
    """
    Persistent structured execution records for ETL agent runs.

    Execution records describe runtime behavior.

    They are separate from lineage, which describes durable
    dataset relationships.
    """

    RUN_VERSION = 1

    _EVENT_STATUSES = {
        "success",
        "failed",
        "rejected",
    }

    _RUN_STATUSES = {
        "running",
        "completed",
        "failed",
    }

    _ALLOWED_AGENTS = {
        "etl_analyst",
        "sql_analyst",
    }    

    def __init__(
        self,
        data_root: Path,
    ):
        self.data_root = (
            data_root.resolve()
        )

        self.runs_directory = (
            self.data_root
            / "_runs"
        ).resolve()

        try:
            self.runs_directory.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Execution-run directory escaped "
                "the configured data directory."
            ) from exc

    @staticmethod
    def _utc_now() -> str:
        return (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

    def _resolve_run_file(
        self,
        run_id: str,
    ) -> Path:
        """
        Validate a run ID and resolve its file.
        """

        try:
            normalized_run_id = str(
                UUID(run_id)
            )

        except (
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            raise DatasetError(
                "Execution run ID must be "
                "a valid UUID."
            ) from exc

        run_file = (
            self.runs_directory
            / f"{normalized_run_id}.json"
        ).resolve()

        try:
            run_file.relative_to(
                self.runs_directory
            )

        except ValueError as exc:
            raise DatasetError(
                "Execution run path escaped "
                "the run directory."
            ) from exc

        return run_file

    def _save_atomic(
        self,
        payload: dict,
        file_path: Path,
    ) -> None:
        """
        Atomically persist one execution run.
        """

        temp_file = (
            file_path
            .with_name(
                f".{file_path.name}.tmp"
            )
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
                "Failed to persist execution run."
            ) from exc

    def _load_run(
        self,
        run_id: str,
    ) -> dict:
        run_file = (
            self._resolve_run_file(
                run_id
            )
        )

        if not run_file.exists():
            raise DatasetError(
                f"Execution run does not exist: "
                f"{run_id}"
            )

        try:
            with run_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                payload = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise DatasetError(
                "Failed to load ETL execution run."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise DatasetError(
                "Execution run must be "
                "a JSON object."
            )

        if (
            payload.get("run_version")
            != self.RUN_VERSION
        ):
            raise DatasetError(
                "Unsupported execution-run version."
            )

        events = payload.get(
            "events"
        )

        if not isinstance(
            events,
            list,
        ):
            raise DatasetError(
                "Execution run contains an "
                "invalid events list."
            )

        return payload

    def start_run(
        self,
        *,
        run_id: str,
        max_tool_calls: int | None = None,
        agent: str = "etl_analyst",
    ) -> None:
        """
        Create a new structured execution record.
        """

        if (
            agent
            not in self._ALLOWED_AGENTS
        ):
            raise DatasetError(
                "Unsupported execution-run agent."
            )

        if (
            max_tool_calls
            is not None
            and (
                isinstance(
                    max_tool_calls,
                    bool,
                )
                or not isinstance(
                    max_tool_calls,
                    int,
                )
                or max_tool_calls < 1
            )
        ):
            raise DatasetError(
                "Execution-run tool limit must "
                "be a positive integer or None."
            )

        run_file = (
            self._resolve_run_file(
                run_id
            )
        )

        if run_file.exists():
            raise DatasetError(
                "Execution run already exists: "
                f"{run_id}"
            )

        payload = {
            "run_version": (
                self.RUN_VERSION
            ),
            "run_id": run_id,
            "agent": agent,
            "status": "running",
            "started_at": (
                self._utc_now()
            ),
            "completed_at": None,
            "max_tool_calls": (
                max_tool_calls
            ),
            "failure_reason": None,
            "events": [],
        }

        self._save_atomic(
            payload,
            run_file,
        )

    def record_event(
        self,
        *,
        run_id: str,
        event_type: str,
        name: str,
        status: str,
        started_at: str,
        completed_at: str,
        duration_ms: float,
        metadata: dict | None = None,
    ) -> None:
        """
        Append one structured runtime event.
        """

        if (
            status
            not in self._EVENT_STATUSES
        ):
            raise DatasetError(
                "Invalid execution-event status."
            )

        payload = (
            self._load_run(
                run_id
            )
        )

        if (
            payload["status"]
            != "running"
        ):
            raise DatasetError(
                "Cannot append events to a "
                "completed execution run."
            )

        events = payload[
            "events"
        ]

        event = {
            "sequence": (
                len(events) + 1
            ),
            "event_type": (
                event_type
            ),
            "name": name,
            "status": status,
            "started_at": started_at,
            "completed_at": (
                completed_at
            ),
            "duration_ms": (
                round(
                    duration_ms,
                    3,
                )
            ),
            "metadata": (
                metadata
                if metadata is not None
                else {}
            ),
        }

        events.append(
            event
        )

        self._save_atomic(
            payload,
            self._resolve_run_file(
                run_id
            ),
        )

    def complete_run(
        self,
        *,
        run_id: str,
        status: str,
        failure_reason: str | None = None,
    ) -> None:
        """
        Mark a run completed or failed.
        """

        if status not in {
            "completed",
            "failed",
        }:
            raise DatasetError(
                "Final execution-run status must "
                "be completed or failed."
            )

        payload = (
            self._load_run(
                run_id
            )
        )

        if payload["status"] in {
            "completed",
            "failed",
        }:
            return

        payload["status"] = (
            status
        )

        payload["completed_at"] = (
            self._utc_now()
        )

        payload["failure_reason"] = (
            failure_reason
        )

        self._save_atomic(
            payload,
            self._resolve_run_file(
                run_id
            ),
        )

    def get_run(
        self,
        run_id: str,
    ) -> dict:
        """
        Return one execution record.
        """

        return self._load_run(
            run_id
        )