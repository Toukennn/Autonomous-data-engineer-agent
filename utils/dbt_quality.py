import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from models.data_quality import (
    AcceptedValuesRule,
    DataQualityContract,
    NotNullRule,
    RangeRule,
    RowCountRule,
    UniqueRule,
)
from utils.data_layers import (
    DataLayer,
    validate_dataset_name,
)
from utils.data_quality_contracts import (
    quality_contract_fingerprint,
)
from utils.exceptions import (
    DatasetError,
)


@dataclass(
    frozen=True
)
class DBTQualitySyncResult:
    layer: DataLayer
    dataset_name: str
    model_name: str
    contract_configured: bool
    contract_fingerprint: str | None
    rule_count: int
    properties_file: Path | None


class DBTQualityTestManager:
    """
    Deterministically translate persisted application
    DataQualityContracts into dbt data tests.

    The quality contract remains the source of truth.
    dbt receives only application-generated test
    definitions.

    Arbitrary SQL is not accepted.
    """

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

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

    # ============================================================
    # PATHS
    # ============================================================

    def _model_directory(
        self,
        layer: DataLayer,
    ) -> Path:

        if layer == DataLayer.SILVER:
            directory = (
                self.dbt_project_dir
                / "models"
                / "staging"
                / "generated"
            )

        elif layer == DataLayer.GOLD:
            directory = (
                self.dbt_project_dir
                / "models"
                / "marts"
                / "generated"
            )

        else:
            raise DatasetError(
                "dbt quality tests may govern "
                "Silver or Gold models only."
            )

        directory = directory.resolve()

        try:
            directory.relative_to(
                self.dbt_project_dir
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt quality-test directory escaped "
                "the configured dbt project."
            ) from exc

        return directory

    # ============================================================
    # MODEL VALIDATION
    # ============================================================

    @classmethod
    def _validate_model_name(
        cls,
        model_name: str,
    ) -> None:

        if (
            not isinstance(
                model_name,
                str,
            )
            or not model_name
        ):
            raise DatasetError(
                "dbt model name must be "
                "a non-empty string."
            )

        if not (
            cls.MODEL_NAME_PATTERN
            .fullmatch(
                model_name
            )
        ):
            raise DatasetError(
                "Invalid dbt model name for "
                "quality governance."
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
                "dbt model name exceeds PostgreSQL's "
                "63-byte identifier limit."
            )

    @staticmethod
    def _validate_columns(
        columns: list[str],
    ) -> None:

        if not isinstance(
            columns,
            list,
        ):
            raise DatasetError(
                "dbt quality columns must "
                "be a list."
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
                "dbt quality columns contain "
                "duplicates."
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
                    "dbt quality column names must "
                    "be non-empty strings."
                )

    # ============================================================
    # CONTRACT VALIDATION
    # ============================================================

    @staticmethod
    def _required_columns(
        contract: DataQualityContract,
    ) -> set[str]:

        required: set[str] = set()

        for rule in contract.rules:

            if isinstance(
                rule,
                NotNullRule,
            ):
                required.add(
                    rule.column
                )

            elif isinstance(
                rule,
                UniqueRule,
            ):
                required.update(
                    rule.columns
                )

            elif isinstance(
                rule,
                AcceptedValuesRule,
            ):
                required.add(
                    rule.column
                )

            elif isinstance(
                rule,
                RangeRule,
            ):
                required.add(
                    rule.column
                )

            elif isinstance(
                rule,
                RowCountRule,
            ):
                continue

            else:
                raise DatasetError(
                    "Unsupported data-quality rule "
                    "for dbt translation."
                )

        return required

    def _validate_contract_columns(
        self,
        *,
        contract: DataQualityContract,
        columns: list[str],
    ) -> None:

        required = (
            self._required_columns(
                contract
            )
        )

        available = set(
            columns
        )

        missing = sorted(
            required
            - available
        )

        if missing:
            raise DatasetError(
                "dbt quality contract references "
                "missing model columns: "
                f"{missing}"
            )

    # ============================================================
    # TEST IDENTITY
    # ============================================================

    @staticmethod
    def _test_name(
        *,
        layer: DataLayer,
        model_name: str,
        rule_index: int,
        rule,
    ) -> str:

        canonical_rule = (
            json.dumps(
                rule.model_dump(
                    mode="json"
                ),
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
                ensure_ascii=False,
            )
        )

        digest = (
            hashlib.sha256(
                (
                    f"{layer.value}:"
                    f"{model_name}:"
                    f"{rule_index}:"
                    f"{canonical_rule}"
                ).encode(
                    "utf-8"
                )
            )
            .hexdigest()[:10]
        )

        return (
            f"qc_{layer.value}_"
            f"{rule_index:03d}_"
            f"{rule.type}_"
            f"{digest}"
        )

    # ============================================================
    # ACCEPTED VALUE SERIALIZATION
    # ============================================================

    @staticmethod
    def _json_values(
        values: list,
    ) -> list[str]:

        rendered: list[str] = []

        try:
            for value in values:
                rendered.append(
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        separators=(
                            ",",
                            ":",
                        ),
                        allow_nan=False,
                    )
                )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise DatasetError(
                "Accepted values cannot be "
                "represented safely for dbt."
            ) from exc

        return rendered

    # ============================================================
    # DBT PAYLOAD
    # ============================================================

    def _render_contract_payload(
        self,
        *,
        layer: DataLayer,
        model_name: str,
        contract: DataQualityContract,
    ) -> dict:

        model_tests: list = []

        column_tests: dict[
            str,
            list,
        ] = {}

        for index, rule in enumerate(
            contract.rules,
            start=1,
        ):
            test_name = (
                self._test_name(
                    layer=layer,
                    model_name=model_name,
                    rule_index=index,
                    rule=rule,
                )
            )

            # ====================================================
            # NOT NULL
            # ====================================================

            if isinstance(
                rule,
                NotNullRule,
            ):
                column_tests.setdefault(
                    rule.column,
                    [],
                ).append(
                    {
                        "not_null": {
                            "name": test_name,
                        }
                    }
                )

                continue

            # ====================================================
            # UNIQUE COMBINATION
            # ====================================================

            if isinstance(
                rule,
                UniqueRule,
            ):
                model_tests.append(
                    {
                        "quality_unique_combination": {
                            "name": test_name,
                            "arguments": {
                                "columns": (
                                    rule.columns
                                ),
                            },
                        }
                    }
                )

                continue

            # ====================================================
            # ACCEPTED VALUES
            # ====================================================

            if isinstance(
                rule,
                AcceptedValuesRule,
            ):
                column_tests.setdefault(
                    rule.column,
                    [],
                ).append(
                    {
                        "quality_accepted_values": {
                            "name": test_name,
                            "arguments": {
                                "values_json": (
                                    self._json_values(
                                        rule.values
                                    )
                                ),
                            },
                        }
                    }
                )

                continue

            # ====================================================
            # RANGE
            # ====================================================

            if isinstance(
                rule,
                RangeRule,
            ):
                arguments = {
                    "inclusive_min": (
                        rule.inclusive_min
                    ),
                    "inclusive_max": (
                        rule.inclusive_max
                    ),
                }

                if (
                    rule.min_value
                    is not None
                ):
                    arguments[
                        "min_value"
                    ] = (
                        rule.min_value
                    )

                if (
                    rule.max_value
                    is not None
                ):
                    arguments[
                        "max_value"
                    ] = (
                        rule.max_value
                    )

                column_tests.setdefault(
                    rule.column,
                    [],
                ).append(
                    {
                        "quality_range": {
                            "name": test_name,
                            "arguments": (
                                arguments
                            ),
                        }
                    }
                )

                continue

            # ====================================================
            # ROW COUNT
            # ====================================================

            if isinstance(
                rule,
                RowCountRule,
            ):
                arguments = {
                    "min_rows": (
                        rule.min_rows
                    ),
                }

                if (
                    rule.max_rows
                    is not None
                ):
                    arguments[
                        "max_rows"
                    ] = (
                        rule.max_rows
                    )

                model_tests.append(
                    {
                        "quality_row_count": {
                            "name": test_name,
                            "arguments": (
                                arguments
                            ),
                        }
                    }
                )

                continue

            raise DatasetError(
                "Unsupported data-quality rule "
                "for dbt translation."
            )

        model_definition = {
            "name": model_name,
        }

        if model_tests:
            model_definition[
                "data_tests"
            ] = model_tests

        if column_tests:
            model_definition[
                "columns"
            ] = [
                {
                    "name": column,
                    "data_tests": (
                        column_tests[
                            column
                        ]
                    ),
                }
                for column in sorted(
                    column_tests
                )
            ]

        return {
            "version": 2,
            "models": [
                model_definition,
            ],
        }

    # ============================================================
    # PERSISTENCE
    # ============================================================

    @staticmethod
    def _save_atomic(
        *,
        payload: dict,
        file_path: Path,
    ) -> None:

        temp_file = (
            file_path.with_name(
                f".{file_path.name}.tmp"
            )
        )

        try:
            file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_file.write_text(
                (
                    json.dumps(
                        payload,
                        indent=2,
                        ensure_ascii=False,
                    )
                    + "\n"
                ),
                encoding="utf-8",
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
                "Failed to persist dbt "
                "quality-test definition."
            ) from exc

    # ============================================================
    # PUBLIC SYNCHRONIZATION
    # ============================================================

    def sync_model_contract(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
        model_name: str,
        columns: list[str],
        contract: (
            DataQualityContract
            | None
        ),
    ) -> DBTQualitySyncResult:

        if layer not in {
            DataLayer.SILVER,
            DataLayer.GOLD,
        }:
            raise DatasetError(
                "dbt quality governance supports "
                "Silver and Gold only."
            )

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        self._validate_model_name(
            model_name
        )

        self._validate_columns(
            columns
        )

        directory = (
            self._model_directory(
                layer
            )
        )

        properties_file = (
            directory
            / (
                f"{model_name}"
                "__quality.yml"
            )
        )

        # ========================================================
        # NO CONTRACT
        # ========================================================

        if contract is None:

            try:
                if properties_file.exists():
                    properties_file.unlink()

            except OSError as exc:
                raise DatasetError(
                    "Failed to clear stale dbt "
                    "quality-test definition."
                ) from exc

            return DBTQualitySyncResult(
                layer=layer,
                dataset_name=(
                    safe_dataset_name
                ),
                model_name=model_name,
                contract_configured=False,
                contract_fingerprint=None,
                rule_count=0,
                properties_file=None,
            )

        # ========================================================
        # VALIDATED CONTRACT
        # ========================================================

        self._validate_contract_columns(
            contract=contract,
            columns=columns,
        )

        fingerprint = (
            quality_contract_fingerprint(
                contract
            )
        )

        # Empty contracts should not leave stale tests.
        if not contract.rules:

            try:
                if properties_file.exists():
                    properties_file.unlink()

            except OSError as exc:
                raise DatasetError(
                    "Failed to clear stale dbt "
                    "quality-test definition."
                ) from exc

            return DBTQualitySyncResult(
                layer=layer,
                dataset_name=(
                    safe_dataset_name
                ),
                model_name=model_name,
                contract_configured=True,
                contract_fingerprint=(
                    fingerprint
                ),
                rule_count=0,
                properties_file=None,
            )

        payload = (
            self._render_contract_payload(
                layer=layer,
                model_name=model_name,
                contract=contract,
            )
        )

        self._save_atomic(
            payload=payload,
            file_path=properties_file,
        )

        return DBTQualitySyncResult(
            layer=layer,
            dataset_name=(
                safe_dataset_name
            ),
            model_name=model_name,
            contract_configured=True,
            contract_fingerprint=(
                fingerprint
            ),
            rule_count=len(
                contract.rules
            ),
            properties_file=(
                properties_file
            ),
        )