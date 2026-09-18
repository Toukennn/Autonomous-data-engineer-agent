import pandas as pd
import psycopg2
import pytest
from unittest.mock import (
    MagicMock,
)

from utils.exceptions import (
    DatasetError,
    WarehouseLoadError,
)

from utils.warehouse import (
    PostgresWarehouseLoader,
)


def _loader():
    return PostgresWarehouseLoader(
        {
            "host": "localhost",
            "user": "test",
            "password": "test",
            "dbname": "test",
            "port": 5432,
        }
    )


def test_bronze_table_load_commits(
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

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        lambda **kwargs: connection,
    )

    inserted = {}

    def fake_execute_values(
        cursor_arg,
        query,
        rows,
        page_size,
    ):
        inserted["cursor"] = (
            cursor_arg
        )
        inserted["query"] = query
        inserted["rows"] = rows
        inserted["page_size"] = (
            page_size
        )

    monkeypatch.setattr(
        "utils.warehouse.execute_values",
        fake_execute_values,
    )

    dataframe = pd.DataFrame(
        {
            "id": [1, 2],
            "name": [
                "alice",
                "bob",
            ],
        }
    )

    result = (
        _loader()
        .replace_bronze_table(
            dataset_name="customers",
            dataframe=dataframe,
        )
    )

    assert (
        result.schema
        == "bronze"
    )

    assert (
        result.table
        == "customers"
    )

    assert (
        result.row_count
        == 2
    )

    assert (
        result.column_count
        == 2
    )

    assert (
        result.columns
        == (
            "id",
            "name",
        )
    )

    assert (
        cursor.execute.call_count
        >= 3
    )

    executed_queries = [
        repr(
            call.args[0]
        ).upper()
        for call
        in cursor.execute.call_args_list
    ]

    assert not any(
        "DROP TABLE"
        in query
        for query
        in executed_queries
    )

    assert any(
        "CREATE TABLE"
        in query
        for query
        in executed_queries
    )

    assert any(
        "TRUNCATE TABLE"
        in query
        for query
        in executed_queries
    )

    assert inserted["rows"] == [
        (
            1,
            "alice",
        ),
        (
            2,
            "bob",
        ),
    ]

    assert (
        inserted["page_size"]
        == 1000
    )

    connection.commit\
        .assert_called_once()

    connection.rollback\
        .assert_not_called()

    connection.close\
        .assert_called_once()


def test_empty_bronze_dataset_creates_table(
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

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        lambda **kwargs: connection,
    )

    execute_values_mock = (
        MagicMock()
    )

    monkeypatch.setattr(
        "utils.warehouse.execute_values",
        execute_values_mock,
    )

    dataframe = pd.DataFrame(
        {
            "id": pd.Series(
                dtype="int64"
            ),
            "name": pd.Series(
                dtype="string"
            ),
        }
    )

    result = (
        _loader()
        .replace_bronze_table(
            dataset_name="customers",
            dataframe=dataframe,
        )
    )

    assert (
        result.row_count
        == 0
    )

    execute_values_mock\
        .assert_not_called()

    connection.commit\
        .assert_called_once()


def test_warehouse_load_rolls_back_on_database_failure(
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

    cursor.execute.side_effect = (
        psycopg2.Error(
            "simulated failure"
        )
    )

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        lambda **kwargs: connection,
    )

    dataframe = pd.DataFrame(
        {
            "id": [1],
        }
    )

    with pytest.raises(
        WarehouseLoadError,
        match=(
            "Failed to load Bronze dataset"
        ),
    ):
        _loader()\
            .replace_bronze_table(
                dataset_name="orders",
                dataframe=dataframe,
            )

    connection.rollback\
        .assert_called_once()

    connection.commit\
        .assert_not_called()

    connection.close\
        .assert_called_once()


def test_invalid_dataset_name_is_rejected_before_database_access(
    monkeypatch,
):
    connect_mock = MagicMock()

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        connect_mock,
    )

    dataframe = pd.DataFrame(
        {
            "id": [1],
        }
    )

    with pytest.raises(
        DatasetError,
        match="Invalid dataset name",
    ):
        _loader()\
            .replace_bronze_table(
                dataset_name=(
                    "../../orders"
                ),
                dataframe=dataframe,
            )

    connect_mock.assert_not_called()


def test_duplicate_columns_are_rejected(
    monkeypatch,
):
    connect_mock = MagicMock()

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        connect_mock,
    )

    dataframe = pd.DataFrame(
        [
            [1, 2]
        ],
        columns=[
            "id",
            "id",
        ],
    )

    with pytest.raises(
        DatasetError,
        match="duplicate column names",
    ):
        _loader()\
            .replace_bronze_table(
                dataset_name="orders",
                dataframe=dataframe,
            )

    connect_mock.assert_not_called()


def test_overlong_table_name_is_rejected(
    monkeypatch,
):
    connect_mock = MagicMock()

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        connect_mock,
    )

    dataframe = pd.DataFrame(
        {
            "id": [1],
        }
    )

    with pytest.raises(
        DatasetError,
        match="63-byte identifier limit",
    ):
        _loader().replace_bronze_table(
            dataset_name="a" * 64,
            dataframe=dataframe,
        )

    connect_mock.assert_not_called()


def test_overlong_column_name_is_rejected(
    monkeypatch,
):
    connect_mock = MagicMock()

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        connect_mock,
    )

    dataframe = pd.DataFrame(
        {
            "a" * 64: [1],
        }
    )

    with pytest.raises(
        DatasetError,
        match="63-byte identifier limit",
    ):
        _loader().replace_bronze_table(
            dataset_name="orders",
            dataframe=dataframe,
        )

    connect_mock.assert_not_called()


def test_existing_bronze_table_is_refreshed_without_drop(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor\
        .return_value\
        .__enter__\
        .return_value = cursor

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        lambda **kwargs: connection,
    )

    loader = _loader()

    monkeypatch.setattr(
        loader,
        "_get_existing_columns",
        lambda **kwargs: {
            "name": "TEXT",
            "url": "TEXT",
        },
    )

    monkeypatch.setattr(
        "utils.warehouse.execute_values",
        MagicMock(),
    )

    dataframe = pd.DataFrame(
        {
            "name": [
                "bulbasaur",
            ],
            "url": [
                "https://example.com/1",
            ],
        }
    )

    loader.replace_bronze_table(
        dataset_name="pokemon",
        dataframe=dataframe,
    )

    # The important invariant:
    # existing relation is preserved rather
    # than dropped/recreated.

    for call in (
        cursor.execute
        .call_args_list
    ):
        query = call.args[0]

        # psycopg2 Composed objects expose their
        # structure through repr().
        assert (
            "DROP TABLE"
            not in repr(query).upper()
        )

    connection.commit\
        .assert_called_once()

    connection.rollback\
        .assert_not_called()



def test_existing_bronze_table_adds_new_column(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor\
        .return_value\
        .__enter__\
        .return_value = cursor

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        lambda **kwargs: connection,
    )

    loader = _loader()

    monkeypatch.setattr(
        loader,
        "_get_existing_columns",
        lambda **kwargs: {
            "id": "BIGINT",
        },
    )

    monkeypatch.setattr(
        "utils.warehouse.execute_values",
        MagicMock(),
    )

    dataframe = pd.DataFrame(
        {
            "id": [1],
            "name": ["alice"],
        }
    )

    loader.replace_bronze_table(
        dataset_name="customers",
        dataframe=dataframe,
    )

    query_reprs = [
        repr(call.args[0]).upper()
        for call
        in cursor.execute.call_args_list
    ]

    assert any(
        "ALTER TABLE"
        in query
        and "ADD COLUMN"
        in query
        for query in query_reprs
    )



def test_existing_bronze_table_rejects_type_change(
    monkeypatch,
):
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor\
        .return_value\
        .__enter__\
        .return_value = cursor

    monkeypatch.setattr(
        "utils.warehouse.psycopg2.connect",
        lambda **kwargs: connection,
    )

    loader = _loader()

    monkeypatch.setattr(
        loader,
        "_get_existing_columns",
        lambda **kwargs: {
            "amount": "BIGINT",
        },
    )

    dataframe = pd.DataFrame(
        {
            "amount": [1.5],
        }
    )

    with pytest.raises(
        DatasetError,
        match="type change",
    ):
        loader.replace_bronze_table(
            dataset_name="orders",
            dataframe=dataframe,
        )

    connection.rollback\
        .assert_called_once()