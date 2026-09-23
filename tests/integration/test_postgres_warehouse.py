import os
import shutil
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from config.settings import get_database_settings
from utils.data_layers import DataLayer
from utils.database import DatabaseUtil
from utils.dbt_execution import DBTExecutor


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION") != "1",
    reason="requires RUN_DATABASE_INTEGRATION=1 and a real PostgreSQL database",
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_SCHEMA = "dbt_test"


@pytest.fixture(scope="module")
def database_config() -> dict:
    return get_database_settings().psycopg_config()


@pytest.fixture(scope="module")
def warehouse(database_config, tmp_path_factory):
    project_dir = tmp_path_factory.mktemp("dbt-integration")
    shutil.copy2(
        PROJECT_ROOT / "dbt" / "dbt_project.yml",
        project_dir / "dbt_project.yml",
    )
    shutil.copy2(
        PROJECT_ROOT / "dbt" / "profiles.yml",
        project_dir / "profiles.yml",
    )

    staging = project_dir / "models" / "staging" / "generated"
    marts = project_dir / "models" / "marts" / "generated"
    staging.mkdir(parents=True)
    marts.mkdir(parents=True)

    (staging / "stg_ci_orders.sql").write_text(
        """
SELECT
    order_id::bigint AS order_id,
    region::text AS region,
    amount::bigint AS amount
FROM bronze.ci_orders
""".strip(),
        encoding="utf-8",
    )
    (marts / "mart_ci_orders.sql").write_text(
        """
SELECT
    region,
    COUNT(*)::bigint AS order_count,
    SUM(amount)::bigint AS total_amount
FROM {{ ref("stg_ci_orders") }}
GROUP BY region
""".strip(),
        encoding="utf-8",
    )

    managed_schemas = (
        "bronze",
        f"{TARGET_SCHEMA}_silver",
        f"{TARGET_SCHEMA}_gold",
    )
    connection = psycopg2.connect(**database_config)
    connection.autocommit = True

    try:
        with connection.cursor() as cursor:
            for schema_name in reversed(managed_schemas):
                cursor.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema_name)
                    )
                )

            cursor.execute("CREATE SCHEMA bronze")
            cursor.execute(
                """
                CREATE TABLE bronze.ci_orders (
                    order_id bigint PRIMARY KEY,
                    region text NOT NULL,
                    amount bigint NOT NULL
                )
                """
            )
            cursor.executemany(
                """
                INSERT INTO bronze.ci_orders (
                    order_id,
                    region,
                    amount
                )
                VALUES (%s, %s, %s)
                """,
                (
                    (1, "north", 10),
                    (2, "south", 20),
                    (3, "north", 15),
                ),
            )

        executor = DBTExecutor(
            dbt_project_dir=project_dir,
            db_config=database_config,
            target_schema=TARGET_SCHEMA,
            threads=1,
        )
        build_result = executor.build_model(
            layer=DataLayer.GOLD,
            dataset_name="ci_orders",
            model_name="mart_ci_orders",
        )

        yield {
            "database": DatabaseUtil(database_config),
            "build_result": build_result,
        }

    finally:
        try:
            with connection.cursor() as cursor:
                for schema_name in reversed(managed_schemas):
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(schema_name)
                        )
                    )
        finally:
            connection.close()


def test_database_settings_connect_to_postgres(database_config):
    connection = psycopg2.connect(**database_config)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
    finally:
        connection.close()


def test_dbt_build_is_visible_in_governed_catalog(warehouse):
    build_result = warehouse["build_result"]
    catalog = warehouse["database"].analytics_catalog(
        target_schema=TARGET_SCHEMA
    )

    assert build_result.selector == "+mart_ci_orders"
    assert build_result.artifact.target_status == "success"

    relations = {
        (
            schema["layer"],
            schema["name"],
            relation["name"],
        )
        for schema in catalog["schemas"]
        for relation in schema["relations"]
    }

    assert (
        "silver",
        "dbt_test_silver",
        "stg_ci_orders",
    ) in relations
    assert (
        "gold",
        "dbt_test_gold",
        "mart_ci_orders",
    ) in relations
    assert all(schema["name"] != "bronze" for schema in catalog["schemas"])


def test_database_util_queries_bounded_gold_results(warehouse):
    database = warehouse["database"]
    query = """
        SELECT region, order_count, total_amount
        FROM dbt_test_gold.mart_ci_orders
        ORDER BY region
    """

    result = database.execute_read_only_result(query, max_rows=10)

    assert result.columns == (
        "region",
        "order_count",
        "total_amount",
    )
    assert result.rows == (
        ("north", 2, 25),
        ("south", 1, 20),
    )
    assert result.row_count == 2
    assert result.truncated is False

    bounded = database.execute_read_only_result(query, max_rows=1)

    assert bounded.row_count == 1
    assert bounded.truncated is True
