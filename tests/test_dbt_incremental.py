import pytest

from models.schema import (
    CastColumnsOperation,
    DBTTransformPlan,
    FilterRowsOperation,
    GroupByAggregateOperation,
    AggregationSpec,
    RenameColumnsOperation,
    SelectColumnsOperation,
    StringTransformOperation,
)

from utils.dbt_incremental import (
    derive_incremental_key,
)

from utils.exceptions import (
    DatasetError,
)


def test_identity_plan_preserves_business_key():
    result = derive_incremental_key(
        plan=DBTTransformPlan(),
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is True

    assert (
        result.key_columns
        == (
            "order_id",
        )
    )


def test_projection_preserves_key_when_retained():
    plan = DBTTransformPlan(
        operations=[
            SelectColumnsOperation(
                type="select_columns",
                columns=[
                    "order_id",
                    "amount",
                ],
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
            "description",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is True

    assert (
        result.key_columns
        == (
            "order_id",
        )
    )


def test_projection_removing_key_disables_incremental():
    plan = DBTTransformPlan(
        operations=[
            SelectColumnsOperation(
                type="select_columns",
                columns=[
                    "amount"
                ],
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is False

    assert result.key_columns == ()


def test_key_rename_is_propagated():
    plan = DBTTransformPlan(
        operations=[
            RenameColumnsOperation(
                type="rename_columns",
                mapping={
                    "order_id": (
                        "warehouse_order_id"
                    )
                },
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is True

    assert (
        result.key_columns
        == (
            "warehouse_order_id",
        )
    )


def test_composite_key_is_preserved():
    result = derive_incremental_key(
        plan=DBTTransformPlan(),
        input_columns=[
            "order_id",
            "line_id",
            "amount",
        ],
        input_key_columns=[
            "order_id",
            "line_id",
        ],
    )

    assert result.eligible is True

    assert (
        result.key_columns
        == (
            "order_id",
            "line_id",
        )
    )


def test_filter_disables_incremental():
    plan = DBTTransformPlan(
        operations=[
            FilterRowsOperation(
                type="filter_rows",
                column="amount",
                operator="gte",
                value=100,
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is False


def test_aggregation_disables_incremental():
    plan = DBTTransformPlan(
        operations=[
            GroupByAggregateOperation(
                type="groupby_aggregate",
                group_by=[
                    "customer_id"
                ],
                aggregations=[
                    AggregationSpec(
                        column="amount",
                        function="sum",
                        alias="total_amount",
                    )
                ],
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "customer_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is False


def test_key_cast_disables_incremental():
    plan = DBTTransformPlan(
        operations=[
            CastColumnsOperation(
                type="cast_columns",
                dtypes={
                    "order_id": "string",
                },
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is False


def test_non_key_cast_is_safe():
    plan = DBTTransformPlan(
        operations=[
            CastColumnsOperation(
                type="cast_columns",
                dtypes={
                    "amount": "float",
                },
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is True


def test_key_string_transform_disables_incremental():
    plan = DBTTransformPlan(
        operations=[
            StringTransformOperation(
                type="string_transform",
                columns=[
                    "order_id"
                ],
                action="lower",
            )
        ]
    )

    result = derive_incremental_key(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[
            "order_id"
        ],
    )

    assert result.eligible is False


def test_no_business_key_disables_incremental():
    result = derive_incremental_key(
        plan=DBTTransformPlan(),
        input_columns=[
            "order_id",
            "amount",
        ],
        input_key_columns=[],
    )

    assert result.eligible is False

    assert result.key_columns == ()


def test_missing_business_key_column_is_rejected():
    with pytest.raises(
        DatasetError,
        match=(
            "not present"
        ),
    ):
        derive_incremental_key(
            plan=DBTTransformPlan(),
            input_columns=[
                "amount"
            ],
            input_key_columns=[
                "order_id"
            ],
        )