import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from utils.data_layers import (
    validate_dataset_name,
)
from utils.exceptions import (
    DatasetError,
)


@dataclass(
    frozen=True
)
class DBTSilverModelResult:
    source_dataset: str
    model_name: str
    model_file: Path


class DBTSilverModelManager:
    """
    Deterministically create bootstrap Silver
    dbt models from registered Bronze sources.

    No arbitrary SQL is accepted here.

    The first Silver model is an explicit projection
    of the Bronze columns. Transformation SQL will be
    introduced later through the validated dbt planner.
    """

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

    def __init__(
        self,
        *,
        dbt_project_dir: Path,
    ):
        self.dbt_project_dir = (
            dbt_project_dir.resolve()
        )

        self.staging_directory = (
            self.dbt_project_dir
            / "models"
            / "staging"
            / "generated"
        ).resolve()

        try:
            self.staging_directory.relative_to(
                self.dbt_project_dir
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt staging directory escaped "
                "the configured dbt project."
            ) from exc

    # ============================================================
    # MODEL NAME
    # ============================================================

    @staticmethod
    def _dataset_hash(
        dataset_name: str,
    ) -> str:
        return (
            hashlib.sha256(
                dataset_name.encode(
                    "utf-8"
                )
            )
            .hexdigest()[:8]
        )

    def model_name_for_dataset(
        self,
        dataset_name: str,
    ) -> str:
        """
        Generate a collision-resistant dbt model name.

        Examples:

            orders
                -> stg_orders

            order-items
                -> stg_order_items_<hash>

            order.items
                -> stg_order_items_<different hash>
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        normalized = re.sub(
            r"[^a-z0-9_]",
            "_",
            safe_dataset_name,
        )

        normalized = re.sub(
            r"_+",
            "_",
            normalized,
        ).strip("_")

        if not normalized:
            raise DatasetError(
                "Dataset name cannot produce "
                "a valid dbt model name."
            )

        prefix = "stg_"

        candidate = (
            prefix
            + normalized
        )

        requires_hash = (
            normalized
            != safe_dataset_name
            or len(
                candidate.encode(
                    "utf-8"
                )
            )
            > self.POSTGRES_IDENTIFIER_MAX_BYTES
        )

        if not requires_hash:
            return candidate

        digest = (
            self._dataset_hash(
                safe_dataset_name
            )
        )

        available_stem_length = (
            self.POSTGRES_IDENTIFIER_MAX_BYTES
            - len(prefix)
            - 1
            - len(digest)
        )

        stem = (
            normalized[
                :available_stem_length
            ]
            .rstrip("_")
        )

        return (
            f"{prefix}"
            f"{stem}_"
            f"{digest}"
        )

    # ============================================================
    # SQL IDENTIFIERS
    # ============================================================

    @classmethod
    def _validate_columns(
        cls,
        columns: list[str],
    ) -> None:
        if not columns:
            raise DatasetError(
                "Cannot create a Silver dbt model "
                "without columns."
            )

        if (
            len(
                set(
                    columns
                )
            )
            != len(columns)
        ):
            raise DatasetError(
                "Silver dbt model contains "
                "duplicate column names."
            )

        for column in columns:
            if (
                not isinstance(
                    column,
                    str,
                )
                or not column
            ):
                raise DatasetError(
                    "Silver dbt model column names "
                    "must be non-empty strings."
                )

            if "\x00" in column:
                raise DatasetError(
                    "Silver dbt model column names "
                    "cannot contain null bytes."
                )

            if (
                len(
                    column.encode(
                        "utf-8"
                    )
                )
                > cls.POSTGRES_IDENTIFIER_MAX_BYTES
            ):
                raise DatasetError(
                    "Silver dbt model column name "
                    "exceeds PostgreSQL's "
                    "63-byte identifier limit."
                )

    @staticmethod
    def _quote_identifier(
        identifier: str,
    ) -> str:
        escaped = (
            identifier.replace(
                '"',
                '""',
            )
        )

        return (
            f'"{escaped}"'
        )

    # ============================================================
    # MODEL GENERATION
    # ============================================================


    def model_file_for_dataset(
        self,
        dataset_name: str,
    ) -> Path:
        """
        Resolve the deterministic generated Silver
        model file for one logical dataset.
        """

        model_name = (
            self.model_name_for_dataset(
                dataset_name
            )
        )

        return (
            self.staging_directory
            / f"{model_name}.sql"
        )

    def create_source_projection(
        self,
        *,
        source_dataset: str,
        columns: list[str],
    ) -> DBTSilverModelResult:
        """
        Create the first deterministic Silver model.

        This is intentionally only an explicit projection:

            Bronze source
                ↓
            Silver staging view

        Arbitrary transformation SQL is not accepted yet.
        """

        safe_dataset_name = (
            validate_dataset_name(
                source_dataset
            )
        )

        self._validate_columns(
            columns
        )

        model_name = (
            self.model_name_for_dataset(
                safe_dataset_name
            )
        )

        model_file = (
            self.model_file_for_dataset(
                safe_dataset_name
            )
        )

        rendered_columns = (
            ",\n".join(
                "    "
                + self._quote_identifier(
                    column
                )
                for column in columns
            )
        )

        bronze_source = json.dumps(
            "bronze"
        )

        dataset_literal = json.dumps(
            safe_dataset_name,
            ensure_ascii=False,
        )

        sql_payload = (
            "select\n"
            f"{rendered_columns}\n"
            "from "
            "{{ source("
            f"{bronze_source}, "
            f"{dataset_literal}"
            ") }}\n"
        )

        temp_file = (
            model_file.with_name(
                f".{model_file.name}.tmp"
            )
        )

        try:
            self.staging_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_file.write_text(
                sql_payload,
                encoding="utf-8",
            )

            temp_file.replace(
                model_file
            )

        except OSError as exc:
            try:
                if temp_file.exists():
                    temp_file.unlink()

            except OSError:
                pass

            raise DatasetError(
                "Failed to persist Silver "
                "dbt model."
            ) from exc

        return DBTSilverModelResult(
            source_dataset=(
                safe_dataset_name
            ),
            model_name=model_name,
            model_file=model_file,
        )


@dataclass(
    frozen=True
)
class DBTGoldModelResult:
    source_dataset: str
    source_model_name: str
    model_name: str
    model_file: Path


class DBTGoldModelManager:
    """
    Deterministically create bootstrap Gold dbt marts
    from generated Silver models.

    Gold models may reference Silver models only through
    dbt ref().

    Arbitrary SQL is intentionally not accepted.
    """

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

    DBT_MODEL_NAME_PATTERN = re.compile(
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

        self.marts_directory = (
            self.dbt_project_dir
            / "models"
            / "marts"
            / "generated"
        ).resolve()

        try:
            self.marts_directory.relative_to(
                self.dbt_project_dir
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt marts directory escaped "
                "the configured dbt project."
            ) from exc

    @staticmethod
    def _dataset_hash(
        dataset_name: str,
    ) -> str:
        return (
            hashlib.sha256(
                dataset_name.encode(
                    "utf-8"
                )
            )
            .hexdigest()[:8]
        )

    def model_name_for_dataset(
        self,
        dataset_name: str,
    ) -> str:
        """
        Produce a collision-resistant Gold dbt model name.
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        normalized = re.sub(
            r"[^a-z0-9_]",
            "_",
            safe_dataset_name,
        )

        normalized = re.sub(
            r"_+",
            "_",
            normalized,
        ).strip("_")

        if not normalized:
            raise DatasetError(
                "Dataset name cannot produce "
                "a valid Gold dbt model name."
            )

        prefix = "mart_"

        candidate = (
            prefix
            + normalized
        )

        requires_hash = (
            normalized
            != safe_dataset_name
            or len(
                candidate.encode(
                    "utf-8"
                )
            )
            > self.POSTGRES_IDENTIFIER_MAX_BYTES
        )

        if not requires_hash:
            return candidate

        digest = (
            self._dataset_hash(
                safe_dataset_name
            )
        )

        available_stem_length = (
            self.POSTGRES_IDENTIFIER_MAX_BYTES
            - len(prefix)
            - 1
            - len(digest)
        )

        stem = (
            normalized[
                :available_stem_length
            ]
            .rstrip("_")
        )

        return (
            f"{prefix}"
            f"{stem}_"
            f"{digest}"
        )

    @classmethod
    def _validate_model_name(
        cls,
        model_name: str,
    ) -> None:
        """
        Only deterministic dbt model identifiers may
        be passed into ref().
        """

        if (
            not isinstance(
                model_name,
                str,
            )
            or not model_name
        ):
            raise DatasetError(
                "Silver dbt model name must "
                "be a non-empty string."
            )

        if (
            not cls
            .DBT_MODEL_NAME_PATTERN
            .fullmatch(
                model_name
            )
        ):
            raise DatasetError(
                "Invalid Silver dbt model name."
            )

        if (
            len(
                model_name.encode(
                    "utf-8"
                )
            )
            > cls.POSTGRES_IDENTIFIER_MAX_BYTES
        ):
            raise DatasetError(
                "Silver dbt model name exceeds "
                "PostgreSQL's 63-byte identifier limit."
            )

    def create_silver_projection(
        self,
        *,
        source_dataset: str,
        source_model_name: str,
        columns: list[str],
    ) -> DBTGoldModelResult:
        """
        Create a deterministic bootstrap Gold mart.

        The generated model may reference only one
        validated Silver dbt model through ref().
        """

        safe_dataset_name = (
            validate_dataset_name(
                source_dataset
            )
        )

        self._validate_model_name(
            source_model_name
        )

        DBTSilverModelManager\
            ._validate_columns(
                columns
            )

        model_name = (
            self.model_name_for_dataset(
                safe_dataset_name
            )
        )

        model_file = (
            self.model_file_for_dataset (
                safe_dataset_name
            )
        )

        rendered_columns = (
            ",\n".join(
                "    "
                + DBTSilverModelManager
                ._quote_identifier(
                    column
                )
                for column in columns
            )
        )

        silver_model_literal = (
            json.dumps(
                source_model_name
            )
        )

        sql_payload = (
            "select\n"
            f"{rendered_columns}\n"
            "from "
            "{{ ref("
            f"{silver_model_literal}"
            ") }}\n"
        )

        temp_file = (
            model_file.with_name(
                f".{model_file.name}.tmp"
            )
        )

        try:
            self.marts_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_file.write_text(
                sql_payload,
                encoding="utf-8",
            )

            temp_file.replace(
                model_file
            )

        except OSError as exc:
            try:
                if temp_file.exists():
                    temp_file.unlink()

            except OSError:
                pass

            raise DatasetError(
                "Failed to persist Gold "
                "dbt model."
            ) from exc

        return DBTGoldModelResult(
            source_dataset=(
                safe_dataset_name
            ),
            source_model_name=(
                source_model_name
            ),
            model_name=model_name,
            model_file=model_file,
        )

    def model_file_for_dataset( 
        self, 
        dataset_name: str, 
    ) -> Path:
        model_name = (
            self.model_name_for_dataset(
                dataset_name
            )
        )

        return (
            self.marts_directory
            / f"{model_name}.sql"
        )


    def model_file_for_dataset(
        self,
        dataset_name: str,
    ) -> Path:
        """
        Resolve the deterministic generated Gold
        model file for one logical dataset.
        """

        model_name = (
            self.model_name_for_dataset(
                dataset_name
            )
        )

        return (
            self.marts_directory
            / f"{model_name}.sql"
        )