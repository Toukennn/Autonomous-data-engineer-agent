import pytest

from utils.sql_safety import SQLSafetyValidator


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM users",
        "SELECT id, name FROM users LIMIT 10",
        """
        SELECT user_id, COUNT(*)
        FROM rides
        GROUP BY user_id
        """,
        """
        SELECT u.id, COUNT(r.id)
        FROM users AS u
        LEFT JOIN rides AS r
            ON r.user_id = u.id
        GROUP BY u.id
        """,
        """
        WITH active_users AS (
            SELECT *
            FROM users
            WHERE id > 10
        )
        SELECT *
        FROM active_users
        """,
        """
        SELECT id FROM users
        UNION
        SELECT user_id FROM rides
        """,
    ],
)
def test_safe_queries_are_accepted(query):
    result = SQLSafetyValidator.validate(
        query
    )

    assert result.is_safe is True


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM users",
        "UPDATE users SET name = 'x'",
        "INSERT INTO users(id) VALUES (1)",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN x INT",
        "TRUNCATE TABLE users",
        "CREATE TABLE dangerous(id INT)",
    ],
)
def test_write_queries_are_rejected(query):
    result = SQLSafetyValidator.validate(
        query
    )

    assert result.is_safe is False


def test_multiple_statements_are_rejected():
    result = SQLSafetyValidator.validate(
        """
        SELECT * FROM users;
        DELETE FROM users;
        """
    )

    assert result.is_safe is False

    assert (
        "one SQL statement"
        in result.reason
    )


def test_empty_query_is_rejected():
    result = SQLSafetyValidator.validate(
        ""
    )

    assert result.is_safe is False


def test_whitespace_query_is_rejected():
    result = SQLSafetyValidator.validate(
        "      "
    )

    assert result.is_safe is False


def test_invalid_sql_is_rejected():
    result = SQLSafetyValidator.validate(
        "SELECT FROM WHERE"
    )

    assert result.is_safe is False


def test_write_operation_hidden_inside_cte_is_rejected():
    query = """
    WITH deleted_users AS (
        DELETE FROM users
        RETURNING *
    )
    SELECT *
    FROM deleted_users
    """

    result = SQLSafetyValidator.validate(
        query
    )

    assert result.is_safe is False