import pandas as pd

from models.data_quality import (
    AcceptedValuesRule,
    DataQualityContract,
    DataQualityResult,
    NotNullRule,
    QualityCheckResult,
    RangeRule,
    RowCountRule,
    UniqueRule,
)
from utils.exceptions import (
    DatasetError,
)


def _require_columns(
    dataframe: pd.DataFrame,
    columns: list[str],
) -> None:
    """
    Reject a quality contract referencing
    columns that do not exist.
    """

    missing = [
        column
        for column in columns
        if column
        not in dataframe.columns
    ]

    if missing:
        raise DatasetError(
            "Data-quality contract references "
            "missing columns: "
            f"{missing}"
        )


def evaluate_data_quality(
    *,
    dataframe: pd.DataFrame,
    contract: DataQualityContract,
) -> DataQualityResult:
    """
    Evaluate a DataFrame against a typed,
    deterministic quality contract.

    The function does not mutate data.
    """

    checks: list[
        QualityCheckResult
    ] = []

    for rule in contract.rules:

        # ========================================================
        # NOT NULL
        # ========================================================

        if isinstance(
            rule,
            NotNullRule,
        ):
            _require_columns(
                dataframe,
                [rule.column],
            )

            violations = int(
                dataframe[
                    rule.column
                ]
                .isna()
                .sum()
            )

            checks.append(
                QualityCheckResult(
                    rule_type=(
                        rule.type
                    ),
                    passed=(
                        violations == 0
                    ),
                    violation_count=(
                        violations
                    ),
                    description=(
                        "Column "
                        f"'{rule.column}' "
                        "must not contain "
                        "null values."
                    ),
                )
            )

            continue

        # ========================================================
        # UNIQUE
        # ========================================================

        if isinstance(
            rule,
            UniqueRule,
        ):
            _require_columns(
                dataframe,
                rule.columns,
            )

            violations = int(
                dataframe
                .duplicated(
                    subset=(
                        rule.columns
                    ),
                    keep="first",
                )
                .sum()
            )

            checks.append(
                QualityCheckResult(
                    rule_type=(
                        rule.type
                    ),
                    passed=(
                        violations == 0
                    ),
                    violation_count=(
                        violations
                    ),
                    description=(
                        "Columns "
                        f"{rule.columns} "
                        "must uniquely identify "
                        "rows."
                    ),
                )
            )

            continue

        # ========================================================
        # ACCEPTED VALUES
        # ========================================================

        if isinstance(
            rule,
            AcceptedValuesRule,
        ):
            _require_columns(
                dataframe,
                [rule.column],
            )

            series = dataframe[
                rule.column
            ]

            non_null = (
                series.notna()
            )

            invalid = (
                non_null
                & ~series.isin(
                    rule.values
                )
            )

            violations = int(
                invalid.sum()
            )

            checks.append(
                QualityCheckResult(
                    rule_type=(
                        rule.type
                    ),
                    passed=(
                        violations == 0
                    ),
                    violation_count=(
                        violations
                    ),
                    description=(
                        "Column "
                        f"'{rule.column}' "
                        "contains only accepted "
                        "values."
                    ),
                )
            )

            continue

        # ========================================================
        # RANGE
        # ========================================================

        if isinstance(
            rule,
            RangeRule,
        ):
            _require_columns(
                dataframe,
                [rule.column],
            )

            series = dataframe[
                rule.column
            ]

            invalid = pd.Series(
                False,
                index=dataframe.index,
            )

            non_null = (
                series.notna()
            )

            if (
                rule.min_value
                is not None
            ):
                if rule.inclusive_min:
                    invalid |= (
                        non_null
                        & (
                            series
                            < rule.min_value
                        )
                    )
                else:
                    invalid |= (
                        non_null
                        & (
                            series
                            <= rule.min_value
                        )
                    )

            if (
                rule.max_value
                is not None
            ):
                if rule.inclusive_max:
                    invalid |= (
                        non_null
                        & (
                            series
                            > rule.max_value
                        )
                    )
                else:
                    invalid |= (
                        non_null
                        & (
                            series
                            >= rule.max_value
                        )
                    )

            violations = int(
                invalid.sum()
            )

            checks.append(
                QualityCheckResult(
                    rule_type=(
                        rule.type
                    ),
                    passed=(
                        violations == 0
                    ),
                    violation_count=(
                        violations
                    ),
                    description=(
                        "Column "
                        f"'{rule.column}' "
                        "must remain inside "
                        "the configured range."
                    ),
                )
            )

            continue

        # ========================================================
        # ROW COUNT
        # ========================================================

        if isinstance(
            rule,
            RowCountRule,
        ):
            row_count = len(
                dataframe
            )

            violations = 0

            if (
                row_count
                < rule.min_rows
            ):
                violations = (
                    rule.min_rows
                    - row_count
                )

            elif (
                rule.max_rows
                is not None
                and row_count
                > rule.max_rows
            ):
                violations = (
                    row_count
                    - rule.max_rows
                )

            checks.append(
                QualityCheckResult(
                    rule_type=(
                        rule.type
                    ),
                    passed=(
                        violations == 0
                    ),
                    violation_count=(
                        violations
                    ),
                    description=(
                        "Dataset row count must "
                        "satisfy configured "
                        "limits."
                    ),
                )
            )

            continue

        raise DatasetError(
            "Unsupported data-quality rule: "
            f"{type(rule).__name__}"
        )

    failed_checks = sum(
        not check.passed
        for check in checks
    )

    return DataQualityResult(
        passed=(
            failed_checks == 0
        ),
        total_checks=len(
            checks
        ),
        failed_checks=(
            failed_checks
        ),
        checks=checks,
    )