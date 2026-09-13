import os
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)

load_dotenv(
    PROJECT_ROOT / ".env"
)


# ============================================================
# DATABASE UTIL
# ============================================================

class DatabaseUtil:
    """
    PostgreSQL utility used by the SQL analyst.

    Query execution is performed inside read-only transactions
    with a statement timeout and result-size limit.
    """

    def __init__(
        self,
        db_config: dict,
    ):
        self.db_config = db_config


    # ========================================================
    # CONNECTION
    # ========================================================

    def _connect(self):
        """
        Create a PostgreSQL connection.
        """

        try:

            return psycopg2.connect(
                **self.db_config
            )

        except psycopg2.Error as exc:

            raise ConnectionError(
                "Could not connect to PostgreSQL. "
                "Check the database credentials."
            ) from exc


    # ========================================================
    # SCHEMA INFORMATION
    # ========================================================

    def schema_details(
        self,
        schema_name: str,
    ) -> str:
        """
        Retrieve table and column metadata for the selected schema.
        """

        context_parts = [
            f"Database Schema: {schema_name}"
        ]

        connection = self._connect()

        try:

            with connection.cursor() as cursor:

                # ------------------------------------------------
                # Tables
                # ------------------------------------------------

                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name;
                    """,
                    (schema_name,),
                )

                tables = cursor.fetchall()

                for (table_name,) in tables:

                    context_parts.append(
                        f"\nTable: {table_name}"
                    )

                    # --------------------------------------------
                    # Columns
                    # --------------------------------------------

                    cursor.execute(
                        """
                        SELECT
                            column_name,
                            data_type
                        FROM information_schema.columns
                        WHERE table_schema = %s
                          AND table_name = %s
                        ORDER BY ordinal_position;
                        """,
                        (
                            schema_name,
                            table_name,
                        ),
                    )

                    columns = (
                        cursor.fetchall()
                    )

                    for (
                        column_name,
                        data_type,
                    ) in columns:

                        context_parts.append(
                            f"  Column: "
                            f"{column_name}, "
                            f"Data Type: {data_type}"
                        )

                    # --------------------------------------------
                    # Small sample
                    # --------------------------------------------

                    sample_query = sql.SQL(
                        """
                        SELECT *
                        FROM {}.{}
                        LIMIT 5
                        """
                    ).format(
                        sql.Identifier(
                            schema_name
                        ),
                        sql.Identifier(
                            table_name
                        ),
                    )

                    cursor.execute(
                        sample_query
                    )

                    sample_rows = (
                        cursor.fetchall()
                    )

                    context_parts.append(
                        "  Sample Data:"
                    )

                    for row in sample_rows:

                        context_parts.append(
                            f"    {row}"
                        )

        except psycopg2.Error as exc:

            raise RuntimeError(
                "Failed to retrieve database "
                "schema information."
            ) from exc

        finally:

            connection.close()

        return "\n".join(
            context_parts
        )


    # ========================================================
    # SAFE QUERY EXECUTION
    # ========================================================

    def execute_read_only(
        self,
        query: str,
        statement_timeout_ms: int = 10_000,
        max_rows: int = 1_000,
    ) -> str:
        """
        Execute one query inside a PostgreSQL read-only transaction.

        Protections:

        - transaction is READ ONLY
        - statement timeout
        - maximum number of returned rows
        - automatic rollback / cleanup

        Args:
            query:
                Validated SQL query.

            statement_timeout_ms:
                Maximum database execution time.

            max_rows:
                Maximum rows returned to the application.

        Returns:
            String representation of the query result.
        """

        connection = self._connect()

        try:

            # ----------------------------------------------------
            # Database-level protection
            # ----------------------------------------------------

            connection.set_session(
                readonly=True,
                autocommit=False,
            )

            with connection.cursor() as cursor:

                # -----------------------------------------------
                # Statement timeout
                # -----------------------------------------------

                cursor.execute(
                    """
                    SELECT set_config(
                        'statement_timeout',
                        %s,
                        true
                    );
                    """,
                    (
                        f"{statement_timeout_ms}ms",
                    ),
                )

                # -----------------------------------------------
                # Execute validated query
                # -----------------------------------------------

                cursor.execute(
                    query
                )

                if cursor.description is None:

                    raise RuntimeError(
                        "Read-only SQL query did not "
                        "produce a result set."
                    )

                # Fetch one extra row so we can determine
                # whether truncation happened.
                rows = cursor.fetchmany(
                    max_rows + 1
                )

                truncated = (
                    len(rows) > max_rows
                )

                rows = rows[
                    :max_rows
                ]

                column_names = [
                    description.name
                    for description
                    in cursor.description
                ]

                result = {
                    "columns": column_names,
                    "rows": rows,
                    "row_count": len(rows),
                    "truncated": truncated,
                }

                # Read-only transaction: rollback deliberately.
                connection.rollback()

                return str(
                    result
                )

        except psycopg2.Error as exc:

            connection.rollback()

            raise RuntimeError(
                f"SQL execution failed: {exc}"
            ) from exc

        finally:

            connection.close()


# ============================================================
# CONFIG
# ============================================================

def load_database_config() -> dict:

    env_names = {
        "host": "host",
        "user": "user",
        "password": "password",
        "dbname": "database",
    }

    config = {
        key: os.getenv(env_name)
        for key, env_name
        in env_names.items()
    }

    missing = [
        env_name
        for key, env_name
        in env_names.items()
        if not config[key]
    ]

    if missing:

        raise RuntimeError(
            "Missing required database "
            "environment variables: "
            + ", ".join(missing)
        )

    try:

        config["port"] = int(
            os.getenv(
                "port",
                "5432",
            )
        )

    except ValueError as exc:

        raise RuntimeError(
            "Database port must be "
            "a valid integer."
        ) from exc

    return config


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    db = DatabaseUtil(
        load_database_config()
    )

    print(
        db.schema_details(
            "public"
        )
    )