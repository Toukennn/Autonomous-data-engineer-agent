import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.exceptions import DatasetError


class IncrementalStateStore:
    """
    Persistent deterministic state storage for incremental ingestion.

    State files are stored inside:

        data/_state/

    The LLM never reads or writes checkpoint files directly.
    """

    STATE_KEY_PATTERN = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )

    def __init__(
        self,
        data_root: Path,
    ):
        self.data_root = (
            data_root
            .resolve()
        )

        self.state_root = (
            self.data_root
            / "_state"
        ).resolve()

        try:
            self.state_root.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Incremental state directory must remain "
                "inside the data directory."
            ) from exc

    # ============================================================
    # STATE KEY VALIDATION
    # ============================================================

    def _validate_state_key(
        self,
        state_key: str,
    ) -> str:
        """
        Validate the identifier used for a checkpoint.

        Only simple names are accepted so callers cannot create
        arbitrary paths.
        """

        normalized = (
            state_key
            .strip()
        )

        if not normalized:
            raise DatasetError(
                "Incremental state key cannot be empty."
            )

        if not self.STATE_KEY_PATTERN.fullmatch(
            normalized
        ):
            raise DatasetError(
                "Incremental state key may contain only "
                "letters, numbers, '.', '_' and '-'."
            )

        return normalized

    # ============================================================
    # STATE PATH
    # ============================================================

    def _state_path(
        self,
        state_key: str,
    ) -> Path:
        """
        Return the checkpoint file path for a state key.
        """

        state_key = (
            self._validate_state_key(
                state_key
            )
        )

        path = (
            self.state_root
            / f"{state_key}.json"
        ).resolve()

        try:
            path.relative_to(
                self.state_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Incremental state path escaped "
                "the state directory."
            ) from exc

        return path

    # ============================================================
    # LOAD
    # ============================================================

    def load(
        self,
        state_key: str,
    ) -> dict[str, Any] | None:
        """
        Load a saved incremental checkpoint.

        Returns None when no checkpoint exists yet.
        """

        path = self._state_path(
            state_key
        )

        if not path.exists():
            return None

        try:
            with path.open(
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
                "Failed to load incremental "
                f"state: {state_key}"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise DatasetError(
                "Incremental state file must "
                "contain a JSON object."
            )

        return payload

    # ============================================================
    # SAVE
    # ============================================================

    def save(
        self,
        state_key: str,
        *,
        cursor_value: Any,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """
        Persist an incremental ingestion checkpoint.

        The write is performed through a temporary file and then
        atomically replaced so a partially written checkpoint is
        not left behind if the process fails.
        """

        path = self._state_path(
            state_key
        )

        temp_path = path.with_suffix(
            ".json.tmp"
        )

        payload = {
            "version": 1,
            "state_key": state_key,
            "cursor_value": cursor_value,
            "updated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "metadata": (
                metadata or {}
            ),
        }

        try:
            self.state_root.mkdir(
                parents=True,
                exist_ok=True,
            )

            with temp_path.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    payload,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )

            temp_path.replace(
                path
            )

        except (
            OSError,
            TypeError,
            ValueError,
        ) as exc:

            try:
                if temp_path.exists():
                    temp_path.unlink()

            except OSError:
                pass

            raise DatasetError(
                "Failed to save incremental "
                f"state: {state_key}"
            ) from exc

        return path