import ast
from types import SimpleNamespace
from unittest.mock import MagicMock

from utils.database import DatabaseUtil


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