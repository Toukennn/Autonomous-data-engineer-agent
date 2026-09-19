import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from models.schema import (
    DBTTransformPlan,
)
from utils.data_layers import (
    DataLayer,
    validate_dataset_name,
)
from utils.exceptions import (
    DatasetError,
)


@dataclass(
    frozen=True
)
class DBTModelMetadata:
    layer: DataLayer
    dataset_name: str
    source_dataset_name: str
    model_name: str
    source_model_name: str | None
    input_columns: tuple[str, ...]
    output_columns: tuple[str, ...]
    plan_fingerprint: str
    plan: DBTTransformPlan

    materialization: str

    incremental_eligible: bool

    incremental_key_columns: tuple[
        str,
        ...
    ]

    incremental_reason: str

    metadata_file: Path


class DBTModelMetadataStore:
    """
    Persist deterministic metadata for generated dbt models.

    SQL itself is not stored here.

    This records:
    - logical dataset identity
    - source relationship
    - actual input/output columns
    - validated transformation plan
    - deterministic plan fingerprint
    """

    STORE_VERSION = 1

    MODEL_NAME_PATTERN = re.compile(
        r"^[a-z0-9_]+$"
    )

    def __init__(
        self,
        *,
        dbt_project_dir: Path,
    ):
        self.dbt_project_dir = (
            dbt_project_dir.resolve()
        )

        self.metadata_root = (
            self.dbt_project_dir
            / "generated_metadata"
        ).resolve()

        try:
            self.metadata_root.relative_to(
                self.dbt_project_dir
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt model metadata directory "
                "escaped the dbt project."
            ) from exc

    @staticmethod
    def _plan_fingerprint(
        plan: DBTTransformPlan,
    ) -> str:
        canonical = json.dumps(
            plan.model_dump(
                mode="json"
            ),
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            ensure_ascii=False,
        )

        return hashlib.sha256(
            canonical.encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _validate_columns(
        columns: list[str],
    ) -> None:
        if not columns:
            raise DatasetError(
                "dbt model metadata requires "
                "at least one column."
            )

        if len(columns) != len(set(columns)):
            raise DatasetError(
                "dbt model metadata contains "
                "duplicate columns."
            )

        for column in columns:
            if (
                not isinstance(column, str)
                or not column
            ):
                raise DatasetError(
                    "dbt model metadata column names "
                    "must be non-empty strings."
                )

    @classmethod
    def _validate_model_name(
        cls,
        model_name: str,
    ) -> None:
        if not (
            isinstance(model_name, str)
            and cls.MODEL_NAME_PATTERN
            .fullmatch(model_name)
        ):
            raise DatasetError(
                "Invalid dbt model name in metadata."
            )

    def _metadata_file(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
    ) -> Path:
        if layer not in {
            DataLayer.SILVER,
            DataLayer.GOLD,
        }:
            raise DatasetError(
                "dbt model metadata supports "
                "Silver and Gold only."
            )

        safe_dataset = (
            validate_dataset_name(
                dataset_name
            )
        )

        file_path = (
            self.metadata_root
            / layer.value
            / f"{safe_dataset}.json"
        ).resolve()

        try:
            file_path.relative_to(
                self.metadata_root
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt model metadata path escaped "
                "its configured directory."
            ) from exc

        return file_path

    def save(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
        source_dataset_name: str,
        model_name: str,
        source_model_name: str | None,
        input_columns: list[str],
        output_columns: list[str],
        plan: DBTTransformPlan,
        materialization: str | None = None,
        incremental_eligible: bool = False,
        incremental_key_columns: (
            list[str]
            | None
        ) = None,
        incremental_reason: str = "",
    ) -> Path:
        safe_dataset = (
            validate_dataset_name(
                dataset_name
            )
        )

        safe_source = (
            validate_dataset_name(
                source_dataset_name
            )
        )

        self._validate_model_name(
            model_name
        )

        if source_model_name is not None:
            self._validate_model_name(
                source_model_name
            )

        self._validate_columns(
            input_columns
        )

        self._validate_columns(
            output_columns
        )

        resolved_materialization = (
            materialization
            if materialization is not None
            else (
                "view"
                if layer
                == DataLayer.SILVER
                else "table"
            )
        )

        allowed_materializations = {
            DataLayer.SILVER: {
                "view",
            },
            DataLayer.GOLD: {
                "table",
                "incremental",
            },
        }

        if (
            resolved_materialization
            not in allowed_materializations[
                layer
            ]
        ):
            raise DatasetError(
                "Invalid dbt materialization "
                "for model metadata."
            )

        resolved_incremental_keys = list(
            incremental_key_columns
            or []
        )

        if resolved_incremental_keys:

            self._validate_columns(
                resolved_incremental_keys
            )

        if (
            incremental_eligible
            and not resolved_incremental_keys
        ):
            raise DatasetError(
                "Incremental-eligible dbt metadata "
                "requires at least one key column."
            )

        if (
            not incremental_eligible
            and resolved_incremental_keys
        ):
            raise DatasetError(
                "Non-incremental dbt metadata cannot "
                "contain incremental key columns."
            )

        missing_incremental_keys = [
            column
            for column
            in resolved_incremental_keys
            if column
            not in output_columns
        ]

        if missing_incremental_keys:
            raise DatasetError(
                "Incremental key columns must exist "
                "in dbt model output columns."
            )

        if not isinstance(
            incremental_reason,
            str,
        ):
            raise DatasetError(
                "Incremental decision reason "
                "must be a string."
            )

        metadata_file = (
            self._metadata_file(
                layer=layer,
                dataset_name=safe_dataset,
            )
        )

        fingerprint = (
            self._plan_fingerprint(
                plan
            )
        )

        payload = {
            "store_version": (
                self.STORE_VERSION
            ),
            "layer": layer.value,
            "dataset": safe_dataset,
            "source_dataset": (
                safe_source
            ),
            "model_name": (
                model_name
            ),
            "source_model_name": (
                source_model_name
            ),
            "input_columns": (
                input_columns
            ),
            "output_columns": (
                output_columns
            ),
            "plan_fingerprint": (
                fingerprint
            ),
            "plan": plan.model_dump(
                mode="json"
            ),
            "materialization": (
                resolved_materialization
            ),
            "incremental": {
                "eligible": (
                    incremental_eligible
                ),
                "key_columns": (
                    resolved_incremental_keys
                ),
                "reason": (
                    incremental_reason
                ),
            },
        }

        temp_file = (
            metadata_file.with_name(
                f".{metadata_file.name}.tmp"
            )
        )

        try:
            metadata_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_file.write_text(
                json.dumps(
                    payload,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            temp_file.replace(
                metadata_file
            )

        except OSError as exc:
            try:
                if temp_file.exists():
                    temp_file.unlink()

            except OSError:
                pass

            raise DatasetError(
                "Failed to persist dbt "
                "model metadata."
            ) from exc

        return metadata_file

    def load(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
    ) -> DBTModelMetadata | None:
        safe_dataset = (
            validate_dataset_name(
                dataset_name
            )
        )

        metadata_file = (
            self._metadata_file(
                layer=layer,
                dataset_name=safe_dataset,
            )
        )

        if not metadata_file.exists():
            return None

        try:
            payload = json.loads(
                metadata_file.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise DatasetError(
                "Failed to load dbt "
                "model metadata."
            ) from exc

        if (
            payload.get(
                "store_version"
            )
            != self.STORE_VERSION
        ):
            raise DatasetError(
                "Unsupported dbt model "
                "metadata version."
            )

        if (
            payload.get("layer")
            != layer.value
        ):
            raise DatasetError(
                "dbt model metadata layer "
                "binding mismatch."
            )

        if (
            payload.get("dataset")
            != safe_dataset
        ):
            raise DatasetError(
                "dbt model metadata dataset "
                "binding mismatch."
            )

        model_name = payload.get(
            "model_name"
        )

        source_model_name = (
            payload.get(
                "source_model_name"
            )
        )

        self._validate_model_name(
            model_name
        )

        if source_model_name is not None:
            self._validate_model_name(
                source_model_name
            )

        input_columns = payload.get(
            "input_columns"
        )

        output_columns = payload.get(
            "output_columns"
        )

        if not isinstance(
            input_columns,
            list,
        ):
            raise DatasetError(
                "Invalid dbt model metadata "
                "input columns."
            )

        if not isinstance(
            output_columns,
            list,
        ):
            raise DatasetError(
                "Invalid dbt model metadata "
                "output columns."
            )

        self._validate_columns(
            input_columns
        )

        self._validate_columns(
            output_columns
        )

        try:
            plan = (
                DBTTransformPlan
                .model_validate(
                    payload.get(
                        "plan"
                    )
                )
            )

        except Exception as exc:
            raise DatasetError(
                "Persisted dbt transformation "
                "plan is invalid."
            ) from exc

        fingerprint = (
            self._plan_fingerprint(
                plan
            )
        )

        if (
            payload.get(
                "plan_fingerprint"
            )
            != fingerprint
        ):
            raise DatasetError(
                "dbt model metadata plan "
                "fingerprint mismatch."
            )

        source_dataset = (
            payload.get(
                "source_dataset"
            )
        )

        if not isinstance(
            source_dataset,
            str,
        ):
            raise DatasetError(
                "Invalid dbt source dataset "
                "metadata."
            )

        source_dataset = (
            validate_dataset_name(
                source_dataset
            )
        )

        materialization = (
            payload.get(
                "materialization"
            )
        )

        # Backward compatibility with metadata
        # generated before Phase 2J.4B.
        if materialization is None:

            materialization = (
                "view"
                if layer
                == DataLayer.SILVER
                else "table"
            )

        allowed_materializations = {
            DataLayer.SILVER: {
                "view",
            },
            DataLayer.GOLD: {
                "table",
                "incremental",
            },
        }

        if (
            materialization
            not in allowed_materializations[
                layer
            ]
        ):
            raise DatasetError(
                "Invalid persisted dbt "
                "materialization."
            )


        incremental_payload = (
            payload.get(
                "incremental"
            )
        )

        if incremental_payload is None:

            incremental_eligible = False
            incremental_key_columns = []
            incremental_reason = (
                "Metadata predates incremental "
                "key-lineage tracking."
            )

        else:

            if not isinstance(
                incremental_payload,
                dict,
            ):
                raise DatasetError(
                    "Invalid persisted dbt "
                    "incremental metadata."
                )

            incremental_eligible = (
                incremental_payload.get(
                    "eligible"
                )
            )

            incremental_key_columns = (
                incremental_payload.get(
                    "key_columns"
                )
            )

            incremental_reason = (
                incremental_payload.get(
                    "reason"
                )
            )

            if not isinstance(
                incremental_eligible,
                bool,
            ):
                raise DatasetError(
                    "Invalid persisted incremental "
                    "eligibility value."
                )

            if not isinstance(
                incremental_key_columns,
                list,
            ):
                raise DatasetError(
                    "Invalid persisted incremental "
                    "key columns."
                )

            if not isinstance(
                incremental_reason,
                str,
            ):
                raise DatasetError(
                    "Invalid persisted incremental "
                    "decision reason."
                )

            if incremental_key_columns:
                self._validate_columns(
                    incremental_key_columns
                )

            if (
                incremental_eligible
                and not incremental_key_columns
            ):
                raise DatasetError(
                    "Incremental-eligible metadata "
                    "is missing its key columns."
                )

            if (
                not incremental_eligible
                and incremental_key_columns
            ):
                raise DatasetError(
                    "Non-incremental metadata "
                    "contains incremental keys."
                )

            if any(
                column
                not in output_columns
                for column
                in incremental_key_columns
            ):
                raise DatasetError(
                    "Persisted incremental key "
                    "does not exist in model output."
                )

        return DBTModelMetadata(
            layer=layer,
            dataset_name=(
                safe_dataset
            ),
            source_dataset_name=(
                source_dataset
            ),
            model_name=model_name,
            source_model_name=(
                source_model_name
            ),
            input_columns=tuple(
                input_columns
            ),
            output_columns=tuple(
                output_columns
            ),
            plan_fingerprint=(
                fingerprint
            ),
            plan=plan,

            materialization=(
                materialization
            ),

            incremental_eligible=(
                incremental_eligible
            ),

            incremental_key_columns=tuple(
                incremental_key_columns
            ),

            incremental_reason=(
                incremental_reason
            ),

            metadata_file=(
                metadata_file
            ),
        )