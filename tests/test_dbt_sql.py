import pytest

from models.schema import (
    DBTTransformPlan,
    FilterRowsOperation,
    GroupByAggregateOperation,
    AggregationSpec,
    RenameColumnsOperation,
)
from utils.dbt_sql import (
    DBTSQLCompiler,
)
from utils.exceptions import (
    DatasetError,
)


def test_silver_plan_compiles_to_source():
    compiler = DBTSQLCompiler()

    plan = DBTTransformPlan(
        operations=[
            FilterRowsOperation(
                type="filter_rows",
                column="amount",
                operator="gte",
                value=0,
            ),
            RenameColumnsOperation(
                type="rename_columns",
                mapping={
                    "amount": "order_amount",
                },
            ),
        ]
    )

    result = compiler.compile(
        plan=plan,
        input_columns=[
            "order_id",
            "amount",
        ],
        relation_kind=(
            "bronze_source"
        ),
        relation_name="orders",
        allow_aggregation=False,
    )

    assert (
        '{{ source("bronze", "orders") }}'
        in result.sql
    )

    assert (
        result.output_columns
        == (
            "order_id",
            "order_amount",
        )
    )


def test_gold_aggregation_compiles_to_ref():
    compiler = DBTSQLCompiler()

    plan = DBTTransformPlan(
        operations=[
            GroupByAggregateOperation(
                type="groupby_aggregate",
                group_by=[
                    "customer_id",
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

    result = compiler.compile(
        plan=plan,
        input_columns=[
            "customer_id",
            "amount",
        ],
        relation_kind="silver_ref",
        relation_name="stg_orders",
        allow_aggregation=True,
    )

    assert (
        '{{ ref("stg_orders") }}'
        in result.sql
    )

    assert (
        result.output_columns
        == (
            "customer_id",
            "total_amount",
        )
    )


def test_silver_rejects_aggregation():
    compiler = DBTSQLCompiler()

    plan = DBTTransformPlan(
        operations=[
            GroupByAggregateOperation(
                type="groupby_aggregate",
                group_by=["customer_id"],
                aggregations=[
                    AggregationSpec(
                        column="amount",
                        function="sum",
                        alias="total",
                    )
                ],
            )
        ]
    )

    with pytest.raises(
        DatasetError,
        match=(
            "Aggregation is not allowed"
        ),
    ):
        compiler.compile(
            plan=plan,
            input_columns=[
                "customer_id",
                "amount",
            ],
            relation_kind=(
                "bronze_source"
            ),
            relation_name="orders",
            allow_aggregation=False,
        )