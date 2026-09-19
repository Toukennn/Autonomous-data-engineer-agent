import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import agents.sql_analyst as sql_module

from models.schema import AgentSchema

from utils.database import (
    ReadOnlyQueryResult,
)

from utils.execution_observability import (
    ExecutionRunStore,
)


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
            referenced_relations=(
                "dbt_test_gold.mart_sales",
            ),
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



def test_sql_success_observability_is_safe(
    tmp_path,
    monkeypatch,
):
    store = ExecutionRunStore(
        tmp_path / "data"
    )

    monkeypatch.setattr(
        sql_module,
        "execution_store",
        store,
    )

    initialize_result = (
        sql_module
        .initialize_run_node(
            AgentSchema()
        )
    )

    run_id = (
        initialize_result[
            "run_id"
        ]
    )

    generated_sql = (
        "SELECT customer_id, revenue "
        "FROM "
        "dbt_test_gold.mart_sales "
        "LIMIT 10"
    )

    safety_state = AgentSchema(
        run_id=run_id,
        generated_sql_query=(
            generated_sql
        ),
        analytics_catalog=(
            _catalog()
        ),
    )

    safety_result = (
        sql_module
        .check_sql_safety(
            safety_state
        )
    )

    assert (
        safety_result["is_safe"]
        == "YES"
    )

    fake_database = MagicMock()

    fake_database\
        .execute_read_only_result\
        .return_value = (
            ReadOnlyQueryResult(
                columns=(
                    "customer_id",
                    "revenue",
                ),
                rows=(
                    (
                        123,
                        "VERY_SECRET_ROW_VALUE",
                    ),
                ),
                row_count=1,
                truncated=False,
            )
        )

    monkeypatch.setattr(
        sql_module,
        "get_database",
        lambda: fake_database,
    )

    execution_state = AgentSchema(
        run_id=run_id,
        generated_sql_query=(
            generated_sql
        ),
        analytics_catalog=(
            _catalog()
        ),
        is_safe="YES",
        referenced_relations=(
            safety_result[
                "referenced_relations"
            ]
        ),
        user_question=(
            "VERY_SECRET_USER_QUESTION"
        ),
        prompt_query=(
            "VERY_SECRET_PROMPT"
        ),
    )

    execution_result = (
        sql_module.execute_sql(
            execution_state
        )
    )

    assert (
        execution_result[
            "sql_execution_failed"
        ]
        is False
    )

    completion_state = (
        execution_state.model_copy(
            update=(
                execution_result
            )
        )
    )

    sql_module.complete_run_node(
        completion_state
    )

    run = store.get_run(
        run_id
    )

    assert (
        run["agent"]
        == "sql_analyst"
    )

    assert (
        run["status"]
        == "completed"
    )

    assert (
        run["max_tool_calls"]
        is None
    )

    assert (
        len(
            run["events"]
        )
        == 2
    )

    safety_event = (
        run["events"][0]
    )

    execution_event = (
        run["events"][1]
    )

    assert (
        safety_event[
            "event_type"
        ]
        == "sql_safety"
    )

    assert (
        safety_event["status"]
        == "success"
    )

    assert (
        safety_event[
            "metadata"
        ][
            "referenced_relations"
        ]
        == [
            "dbt_test_gold.mart_sales"
        ]
    )

    assert (
        execution_event[
            "event_type"
        ]
        == "sql_execution"
    )

    assert (
        execution_event["status"]
        == "success"
    )

    assert (
        execution_event[
            "metadata"
        ][
            "row_count"
        ]
        == 1
    )

    assert (
        execution_event[
            "metadata"
        ][
            "column_count"
        ]
        == 2
    )

    assert (
        execution_event[
            "metadata"
        ][
            "truncated"
        ]
        is False
    )

    serialized_run = (
        json.dumps(
            run
        )
    )

    assert (
        generated_sql
        not in serialized_run
    )

    assert (
        "VERY_SECRET_ROW_VALUE"
        not in serialized_run
    )

    assert (
        "VERY_SECRET_USER_QUESTION"
        not in serialized_run
    )

    assert (
        "VERY_SECRET_PROMPT"
        not in serialized_run
    )



def test_sql_rejection_observability_is_safe(
    tmp_path,
    monkeypatch,
):
    store = ExecutionRunStore(
        tmp_path / "data"
    )

    monkeypatch.setattr(
        sql_module,
        "execution_store",
        store,
    )

    initialize_result = (
        sql_module
        .initialize_run_node(
            AgentSchema()
        )
    )

    run_id = (
        initialize_result[
            "run_id"
        ]
    )

    unsafe_sql = (
        "SELECT * "
        "FROM public.secret_users"
    )

    state = AgentSchema(
        run_id=run_id,
        generated_sql_query=(
            unsafe_sql
        ),
        analytics_catalog=(
            _catalog()
        ),
        user_question=(
            "PRIVATE USER QUESTION"
        ),
    )

    safety_result = (
        sql_module
        .check_sql_safety(
            state
        )
    )

    assert (
        safety_result["is_safe"]
        == "NO"
    )

    cancel_state = (
        state.model_copy(
            update=(
                safety_result
            )
        )
    )

    sql_module.cancel_sql(
        cancel_state
    )

    run = store.get_run(
        run_id
    )

    assert (
        run["status"]
        == "completed"
    )

    assert (
        len(
            run["events"]
        )
        == 1
    )

    event = (
        run["events"][0]
    )

    assert (
        event[
            "event_type"
        ]
        == "sql_safety"
    )

    assert (
        event["status"]
        == "rejected"
    )

    serialized_run = (
        json.dumps(
            run
        )
    )

    assert (
        unsafe_sql
        not in serialized_run
    )

    assert (
        "PRIVATE USER QUESTION"
        not in serialized_run
    )



def test_sql_failure_observability_excludes_error_message(
    tmp_path,
    monkeypatch,
):
    store = ExecutionRunStore(
        tmp_path / "data"
    )

    monkeypatch.setattr(
        sql_module,
        "execution_store",
        store,
    )

    initialize_result = (
        sql_module
        .initialize_run_node(
            AgentSchema()
        )
    )

    run_id = (
        initialize_result[
            "run_id"
        ]
    )

    fake_database = MagicMock()

    fake_database\
        .execute_read_only_result\
        .side_effect = RuntimeError(
            "VERY_SECRET_DATABASE_ERROR"
        )

    monkeypatch.setattr(
        sql_module,
        "get_database",
        lambda: fake_database,
    )

    state = AgentSchema(
        run_id=run_id,
        generated_sql_query=(
            "SELECT customer_id "
            "FROM "
            "dbt_test_gold.mart_sales"
        ),
        referenced_relations=[
            "dbt_test_gold.mart_sales"
        ],
    )

    result = (
        sql_module.execute_sql(
            state
        )
    )

    assert (
        result[
            "sql_execution_failed"
        ]
        is True
    )

    completion_state = (
        state.model_copy(
            update=result
        )
    )

    sql_module.complete_run_node(
        completion_state
    )

    run = store.get_run(
        run_id
    )

    assert (
        run["status"]
        == "failed"
    )

    event = (
        run["events"][0]
    )

    assert (
        event["status"]
        == "failed"
    )

    assert (
        event[
            "metadata"
        ][
            "error_type"
        ]
        == "RuntimeError"
    )

    serialized_run = (
        json.dumps(
            run
        )
    )

    assert (
        "VERY_SECRET_DATABASE_ERROR"
        not in serialized_run
    )