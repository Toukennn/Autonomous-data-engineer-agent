import ast
from types import SimpleNamespace
from unittest.mock import MagicMock

from utils.database import DatabaseUtil

import pytest

from utils.exceptions import (
    DatabaseQueryError,
)


def test_execute_read_only_uses_readonly_transaction(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor.return_value.__enter__.return_value = (
        cursor
    )

    cursor.description = [
        SimpleNamespace(
            name="id"
        )
    ]

    cursor.fetchmany.return_value = [
        (1,),
        (2,),
    ]

    monkeypatch.setattr(
        "utils.database.psycopg2.connect",
        lambda **kwargs: connection,
    )

    database = DatabaseUtil(
        {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "dbname": "test",
            "port": 5432,
        }
    )

    raw_result = (
        database.execute_read_only(
            "SELECT id FROM users",
            statement_timeout_ms=500,
            max_rows=1,
        )
    )

    result = ast.literal_eval(
        raw_result
    )

    connection.set_session.assert_called_once_with(
        readonly=True,
        autocommit=False,
    )

    assert (
        cursor.execute
        .call_args_list[1]
        .args[0]
        == "SELECT id FROM users"
    )

    cursor.fetchmany.assert_called_once_with(
        2
    )

    assert result["rows"] == [
        (1,)
    ]

    assert (
        result["truncated"]
        is True
    )

    connection.rollback.assert_called()

    connection.close.assert_called_once()


def test_analytics_catalog_discovers_dbt_silver_and_gold(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor\
        .return_value\
        .__enter__\
        .return_value = (
            cursor
        )

    cursor.fetchall.return_value = [
        (
            "dbt_test_gold",
            "mart_sales",
            "BASE TABLE",
            "customer_id",
            "bigint",
            1,
        ),
        (
            "dbt_test_gold",
            "mart_sales",
            "BASE TABLE",
            "revenue",
            "double precision",
            2,
        ),
        (
            "dbt_test_silver",
            "stg_orders",
            "VIEW",
            "order_id",
            "bigint",
            1,
        ),
        (
            "dbt_test_silver",
            "stg_orders",
            "VIEW",
            "amount",
            "double precision",
            2,
        ),
    ]

    monkeypatch.setattr(
        "utils.database.psycopg2.connect",
        lambda **kwargs: connection,
    )

    database = DatabaseUtil(
        {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "dbname": "test",
            "port": 5432,
        }
    )

    catalog = (
        database.analytics_catalog(
            target_schema=(
                "dbt_test"
            )
        )
    )

    assert (
        catalog[
            "catalog_version"
        ]
        == 1
    )

    schemas = {
        schema["name"]: schema
        for schema
        in catalog["schemas"]
    }

    assert set(
        schemas
    ) == {
        "dbt_test_silver",
        "dbt_test_gold",
    }

    silver = (
        schemas[
            "dbt_test_silver"
        ]
    )

    gold = (
        schemas[
            "dbt_test_gold"
        ]
    )

    assert (
        silver["layer"]
        == "silver"
    )

    assert (
        silver[
            "relations"
        ][0]["name"]
        == "stg_orders"
    )

    assert (
        silver[
            "relations"
        ][0]["type"]
        == "view"
    )

    assert (
        gold[
            "relations"
        ][0]["name"]
        == "mart_sales"
    )

    assert (
        gold[
            "relations"
        ][0]["type"]
        == "table"
    )

    connection.set_session\
        .assert_called_once_with(
            readonly=True,
            autocommit=False,
        )

    connection.rollback\
        .assert_called_once()

    connection.close\
        .assert_called_once()


def test_analytics_catalog_does_not_query_sample_rows(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor\
        .return_value\
        .__enter__\
        .return_value = (
            cursor
        )

    cursor.fetchall.return_value = []

    monkeypatch.setattr(
        "utils.database.psycopg2.connect",
        lambda **kwargs: connection,
    )

    database = DatabaseUtil(
        {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "dbname": "test",
            "port": 5432,
        }
    )

    database.analytics_catalog(
        target_schema=(
            "dbt_test"
        )
    )

    assert (
        cursor.execute.call_count
        == 1
    )

    query = (
        cursor.execute
        .call_args
        .args[0]
    )

    assert (
        "information_schema.tables"
        in query
    )

    assert (
        "LIMIT 5"
        not in query
    )

    assert (
        "SELECT *"
        not in query
    )


def test_analytics_catalog_excludes_bronze_and_public(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor\
        .return_value\
        .__enter__\
        .return_value = (
            cursor
        )

    cursor.fetchall.return_value = []

    monkeypatch.setattr(
        "utils.database.psycopg2.connect",
        lambda **kwargs: connection,
    )

    database = DatabaseUtil(
        {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "dbname": "test",
            "port": 5432,
        }
    )

    database.analytics_catalog(
        target_schema=(
            "dbt_test"
        )
    )

    parameters = (
        cursor.execute
        .call_args
        .args[1]
    )

    schemas = (
        parameters[0]
    )

    assert schemas == [
        "dbt_test_silver",
        "dbt_test_gold",
    ]

    assert (
        "bronze"
        not in schemas
    )

    assert (
        "public"
        not in schemas
    )


def test_analytics_schema_rejects_invalid_name():
    with pytest.raises(
        DatabaseQueryError,
        match=(
            "Invalid dbt target schema"
        ),
    ):
        DatabaseUtil\
            .analytics_schema_names(
                "dbt-test;DROP"
            )