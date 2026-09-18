import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import agents.sql_analyst as sql_module

from models.schema import AgentSchema


def _catalog():
    return {
        "catalog_version": 1,
        "schemas": [
            {
                "name": (
                    "dbt_test_silver"
                ),
                "layer": "silver",
                "relations": [
                    {
                        "name": (
                            "stg_orders"
                        ),
                        "type": "view",
                        "columns": [
                            {
                                "name": (
                                    "order_id"
                                ),
                                "data_type": (
                                    "bigint"
                                ),
                            },
                            {
                                "name": (
                                    "amount"
                                ),
                                "data_type": (
                                    "double precision"
                                ),
                            },
                        ],
                    },
                ],
            },
            {
                "name": (
                    "dbt_test_gold"
                ),
                "layer": "gold",
                "relations": [
                    {
                        "name": (
                            "mart_sales"
                        ),
                        "type": "table",
                        "columns": [
                            {
                                "name": (
                                    "customer_id"
                                ),
                                "data_type": (
                                    "bigint"
                                ),
                            },
                            {
                                "name": (
                                    "revenue"
                                ),
                                "data_type": (
                                    "double precision"
                                ),
                            },
                        ],
                    },
                ],
            },
        ],
    }


def test_sql_prompt_uses_governed_catalog(
    monkeypatch,
):
    catalog = _catalog()

    database = MagicMock()

    database.analytics_catalog\
        .return_value = (
            catalog
        )

    database.serialize_analytics_catalog\
        .side_effect = (
            lambda value: json.dumps(
                value,
                indent=2,
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(
        sql_module,
        "get_database",
        lambda: database,
    )

    monkeypatch.setattr(
        sql_module,
        "get_runtime_settings",
        lambda: SimpleNamespace(
            dbt_target_schema=(
                "dbt_test"
            )
        ),
    )

    state = AgentSchema(
        curated_ques=(
            "Show total sales."
        )
    )

    result = (
        sql_module
        .build_sql_prompt(
            state
        )
    )

    database.analytics_catalog\
        .assert_called_once_with(
            target_schema=(
                "dbt_test"
            )
        )

    database.schema_details\
        .assert_not_called()

    assert (
        result[
            "analytics_catalog"
        ]
        == catalog
    )

    assert (
        "dbt_test_silver"
        in result[
            "prompt_query"
        ]
    )

    assert (
        "dbt_test_gold"
        in result[
            "prompt_query"
        ]
    )

    assert (
        "mart_sales"
        in result[
            "prompt_query"
        ]
    )

    assert (
        "Sample Data:"
        not in result[
            "prompt_query"
        ]
    )



def test_sql_safety_uses_catalog_snapshot_from_state(
    monkeypatch,
):
    catalog = _catalog()

    captured = {}

    def fake_validate(
        sql,
        *,
        analytics_catalog=None,
    ):
        captured[
            "sql"
        ] = sql

        captured[
            "analytics_catalog"
        ] = analytics_catalog

        return SimpleNamespace(
            is_safe=True,
            reason="safe",
        )

    monkeypatch.setattr(
        sql_module
        .SQLSafetyValidator,
        "validate",
        fake_validate,
    )

    state = AgentSchema(
        generated_sql_query=(
            "SELECT customer_id, revenue "
            "FROM "
            "dbt_test_gold.mart_sales "
            "LIMIT 10"
        ),
        analytics_catalog=(
            catalog
        ),
    )

    result = (
        sql_module
        .check_sql_safety(
            state
        )
    )

    assert (
        result["is_safe"]
        == "YES"
    )

    assert (
        captured[
            "analytics_catalog"
        ]
        is state.analytics_catalog
    )

    assert (
        captured[
            "analytics_catalog"
        ]
        == catalog
    )

    assert (
        captured[
            "sql"
        ]
        == state.generated_sql_query
    )


def test_sql_agent_rejects_relation_outside_snapshot():
    state = AgentSchema(
        generated_sql_query=(
            "SELECT * "
            "FROM public.users"
        ),
        analytics_catalog=(
            _catalog()
        ),
    )

    result = (
        sql_module
        .check_sql_safety(
            state
        )
    )

    assert (
        result["is_safe"]
        == "NO"
    )

    assert (
        "unauthorized schema"
        in result["comments"]
    )


def test_sql_agent_rejects_unqualified_physical_relation():
    state = AgentSchema(
        generated_sql_query=(
            "SELECT * "
            "FROM mart_sales"
        ),
        analytics_catalog=(
            _catalog()
        ),
    )

    result = (
        sql_module
        .check_sql_safety(
            state
        )
    )

    assert (
        result["is_safe"]
        == "NO"
    )

    assert (
        "schema-qualified"
        in result["comments"]
    )