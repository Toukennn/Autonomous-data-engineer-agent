from dataclasses import (
    dataclass,
)

from models.schema import (
    CastColumnsOperation,
    DBTTransformPlan,
    FillMissingOperation,
    FilterRowsOperation,
    GroupByAggregateOperation,
    RenameColumnsOperation,
    SelectColumnsOperation,
    StringTransformOperation,
)

from utils.exceptions import (
    DatasetError,
)


@dataclass(
    frozen=True
)
class DBTIncrementalDecision:
    """
    Deterministic decision describing whether
    a transformation preserves a safe business
    key for downstream incremental materialization.
    """

    eligible: bool

    key_columns: tuple[
        str,
        ...
    ]

    reason: str


def derive_incremental_key(
    *,
    plan: DBTTransformPlan,
    input_columns: list[str],
    input_key_columns: list[str],
) -> DBTIncrementalDecision:
    """
    Determine whether a dbt transformation plan
    preserves one stable output row per business key.

    The LLM does not participate in this decision.

    Safe operations:

    - projection, if every key column survives
    - rename, including deterministic key rename
    - non-key fill_missing
    - non-key cast
    - non-key string transformation

    Unsafe operations:

    - filtering
    - aggregation
    - dropping a key through projection
    - mutating a key value

    Returning eligible=False means callers should
    fall back to normal full-table materialization.
    """

    current_columns = list(
        input_columns
    )

    if (
        len(
            current_columns
        )
        != len(
            set(
                current_columns
            )
        )
    ):
        raise DatasetError(
            "Incremental-key analysis received "
            "duplicate input columns."
        )

    key_columns = list(
        input_key_columns
    )

    if not key_columns:
        return DBTIncrementalDecision(
            eligible=False,
            key_columns=(),
            reason=(
                "No persisted business key "
                "is available."
            ),
        )

    if (
        len(
            key_columns
        )
        != len(
            set(
                key_columns
            )
        )
    ):
        raise DatasetError(
            "Incremental-key analysis received "
            "duplicate key columns."
        )

    missing_keys = [
        column
        for column
        in key_columns
        if column
        not in current_columns
    ]

    if missing_keys:
        raise DatasetError(
            "Business-key columns are not present "
            "in the dbt model input columns."
        )

    for operation in plan.operations:

        # ========================================================
        # PROJECTION
        # ========================================================

        if isinstance(
            operation,
            SelectColumnsOperation,
        ):
            missing_after_projection = [
                column
                for column
                in key_columns
                if column
                not in operation.columns
            ]

            if missing_after_projection:
                return DBTIncrementalDecision(
                    eligible=False,
                    key_columns=(),
                    reason=(
                        "Projection removes at least "
                        "one business-key column."
                    ),
                )

            current_columns = list(
                operation.columns
            )

        # ========================================================
        # RENAME
        # ========================================================

        elif isinstance(
            operation,
            RenameColumnsOperation,
        ):
            renamed_columns = [
                operation.mapping.get(
                    column,
                    column,
                )
                for column
                in current_columns
            ]

            renamed_keys = [
                operation.mapping.get(
                    column,
                    column,
                )
                for column
                in key_columns
            ]

            if (
                len(
                    renamed_columns
                )
                != len(
                    set(
                        renamed_columns
                    )
                )
            ):
                raise DatasetError(
                    "dbt rename operation produces "
                    "duplicate output columns."
                )

            if (
                len(
                    renamed_keys
                )
                != len(
                    set(
                        renamed_keys
                    )
                )
            ):
                return DBTIncrementalDecision(
                    eligible=False,
                    key_columns=(),
                    reason=(
                        "Business-key rename produces "
                        "duplicate key columns."
                    ),
                )

            current_columns = (
                renamed_columns
            )

            key_columns = (
                renamed_keys
            )

        # ========================================================
        # FILTERING
        # ========================================================

        elif isinstance(
            operation,
            FilterRowsOperation,
        ):
            return DBTIncrementalDecision(
                eligible=False,
                key_columns=(),
                reason=(
                    "Filtering can remove an existing "
                    "business key from incremental output."
                ),
            )

        # ========================================================
        # AGGREGATION
        # ========================================================

        elif isinstance(
            operation,
            GroupByAggregateOperation,
        ):
            return DBTIncrementalDecision(
                eligible=False,
                key_columns=(),
                reason=(
                    "Aggregation changes the dataset "
                    "row grain."
                ),
            )

        # ========================================================
        # FILL MISSING
        # ========================================================

        elif isinstance(
            operation,
            FillMissingOperation,
        ):
            if any(
                column
                in operation.values
                for column
                in key_columns
            ):
                return DBTIncrementalDecision(
                    eligible=False,
                    key_columns=(),
                    reason=(
                        "fill_missing modifies a "
                        "business-key column."
                    ),
                )

        # ========================================================
        # CAST
        # ========================================================

        elif isinstance(
            operation,
            CastColumnsOperation,
        ):
            if any(
                column
                in operation.dtypes
                for column
                in key_columns
            ):
                return DBTIncrementalDecision(
                    eligible=False,
                    key_columns=(),
                    reason=(
                        "Casting a business-key column "
                        "can change row identity."
                    ),
                )

        # ========================================================
        # STRING TRANSFORMATION
        # ========================================================

        elif isinstance(
            operation,
            StringTransformOperation,
        ):
            if any(
                column
                in operation.columns
                for column
                in key_columns
            ):
                return DBTIncrementalDecision(
                    eligible=False,
                    key_columns=(),
                    reason=(
                        "String transformation modifies "
                        "a business-key column."
                    ),
                )

        else:
            raise DatasetError(
                "Unsupported operation during "
                "incremental-key analysis."
            )

    if any(
        column
        not in current_columns
        for column
        in key_columns
    ):
        return DBTIncrementalDecision(
            eligible=False,
            key_columns=(),
            reason=(
                "Business key is not present in "
                "the final output columns."
            ),
        )

    return DBTIncrementalDecision(
        eligible=True,
        key_columns=tuple(
            key_columns
        ),
        reason=(
            "Transformation preserves one stable "
            "output row per business key."
        ),
    )