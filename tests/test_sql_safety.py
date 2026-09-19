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



def _analytics_catalog():
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
                    }
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
                    }
                ],
            },
        ],
    }


@pytest.mark.parametrize(
    "query",
    [
        """
        SELECT *
        FROM dbt_test_gold.mart_sales
        """,
        """
        SELECT
            customer_id,
            revenue
        FROM dbt_test_gold.mart_sales
        WHERE revenue > 100
        """,
        """
        SELECT
            s.customer_id,
            o.amount
        FROM dbt_test_gold.mart_sales AS s
        JOIN dbt_test_silver.stg_orders AS o
          ON o.order_id = s.customer_id
        """,
        """
        WITH high_value AS (
            SELECT *
            FROM dbt_test_gold.mart_sales
            WHERE revenue > 100
        )
        SELECT *
        FROM high_value
        """,
        """
        WITH orders AS (
            SELECT *
            FROM dbt_test_silver.stg_orders
        ),
        sales AS (
            SELECT *
            FROM dbt_test_gold.mart_sales
        )
        SELECT *
        FROM orders
        JOIN sales
          ON orders.order_id
             = sales.customer_id
        """,
    ],
)
def test_governed_analytics_queries_are_accepted(
    query,
):
    result = (
        SQLSafetyValidator
        .validate(
            query,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is True
    )


@pytest.mark.parametrize(
    (
        "query",
        "reason",
    ),
    [
        (
            """
            SELECT *
            FROM mart_sales
            """,
            (
                "schema-qualified"
            ),
        ),
        (
            """
            SELECT *
            FROM bronze.orders
            """,
            (
                "unauthorized schema"
            ),
        ),
        (
            """
            SELECT *
            FROM public.users
            """,
            (
                "unauthorized schema"
            ),
        ),
        (
            """
            SELECT *
            FROM information_schema.tables
            """,
            (
                "unauthorized schema"
            ),
        ),
        (
            """
            SELECT *
            FROM pg_catalog.pg_class
            """,
            (
                "unauthorized schema"
            ),
        ),
        (
            """
            SELECT *
            FROM dbt_test_gold.unknown_model
            """,
            (
                "not present in the "
                "governed analytics catalog"
            ),
        ),
        (
            """
            SELECT *
            FROM another_database.
                 dbt_test_gold.
                 mart_sales
            """,
            (
                "Cross-database"
            ),
        ),
    ],
)
def test_governed_analytics_rejects_unauthorized_relations(
    query,
    reason,
):
    result = (
        SQLSafetyValidator
        .validate(
            query,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is False
    )

    assert (
        reason
        in result.reason
    )


def test_governed_analytics_requires_real_relation():
    result = (
        SQLSafetyValidator
        .validate(
            "SELECT 1",
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is False
    )

    assert (
        "at least one approved"
        in result.reason
    )


def test_cte_name_does_not_need_schema_qualification():
    result = (
        SQLSafetyValidator
        .validate(
            """
            WITH sales AS (
                SELECT *
                FROM dbt_test_gold.mart_sales
            )
            SELECT *
            FROM sales
            """,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is True
    )


def test_cte_only_query_without_governed_relation_is_rejected():
    result = (
        SQLSafetyValidator
        .validate(
            """
            WITH values_only AS (
                SELECT 1 AS value
            )
            SELECT *
            FROM values_only
            """,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is False
    )

    assert (
        "at least one approved"
        in result.reason
    )


def test_governed_analytics_still_rejects_writes():
    result = (
        SQLSafetyValidator
        .validate(
            """
            DELETE
            FROM dbt_test_gold.mart_sales
            """,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is False
    )


def test_governed_analytics_rejects_invalid_catalog():
    catalog = (
        _analytics_catalog()
    )

    catalog[
        "schemas"
    ][0]["name"] = (
        "public"
    )

    result = (
        SQLSafetyValidator
        .validate(
            """
            SELECT *
            FROM public.stg_orders
            """,
            analytics_catalog=(
                catalog
            ),
        )
    )

    assert (
        result.is_safe
        is False
    )

    assert (
        "forbidden schema"
        in result.reason
    )


def test_nested_cte_name_cannot_hide_outer_physical_table():
    """
    A CTE named 'users' exists only inside
    the nested EXISTS query.

    The outer unqualified 'users' relation
    must still be treated as a physical table
    and rejected.
    """

    query = """
    SELECT *
    FROM users
    WHERE EXISTS (
        WITH users AS (
            SELECT *
            FROM dbt_test_gold.mart_sales
        )
        SELECT 1
        FROM users
    )
    """

    result = (
        SQLSafetyValidator
        .validate(
            query,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is False
    )

    assert (
        "schema-qualified"
        in result.reason
    )


def test_nested_cte_with_governed_relations_is_allowed():
    query = """
    SELECT *
    FROM dbt_test_gold.mart_sales AS sales
    WHERE EXISTS (
        WITH orders AS (
            SELECT *
            FROM dbt_test_silver.stg_orders
        )
        SELECT 1
        FROM orders
        WHERE orders.order_id
              = sales.customer_id
    )
    """

    result = (
        SQLSafetyValidator
        .validate(
            query,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert (
        result.is_safe
        is True
    )


def test_governed_validation_reports_relations():
    result = (
        SQLSafetyValidator
        .validate(
            """
            SELECT *
            FROM dbt_test_gold.mart_sales
            JOIN dbt_test_silver.stg_orders
              ON stg_orders.order_id
                 = mart_sales.customer_id
            """,
            analytics_catalog=(
                _analytics_catalog()
            ),
        )
    )

    assert result.is_safe is True

    assert (
        result.referenced_relations
        == (
            "dbt_test_gold.mart_sales",
            "dbt_test_silver.stg_orders",
        )
    )