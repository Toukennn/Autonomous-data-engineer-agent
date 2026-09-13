import psycopg2
from psycopg2 import sql

from config.settings import (
    get_database_settings,
    get_runtime_settings,
)
from utils.exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
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
            raise DatabaseConnectionError(
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

            raise DatabaseQueryError(
                "Failed to retrieve database schema information."
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
        statement_timeout_ms: int | None = None,
        max_rows: int | None = None,
    ) -> str:

        runtime = get_runtime_settings()

        statement_timeout_ms = (
            statement_timeout_ms
            if statement_timeout_ms is not None
            else runtime.sql_statement_timeout_ms
        )

        max_rows = (
            max_rows
            if max_rows is not None
            else runtime.sql_max_rows
        )

        connection = self._connect()

        try:
            connection.set_session(
                readonly=True,
                autocommit=False,
            )

            with connection.cursor() as cursor:

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

                cursor.execute(query)

                if cursor.description is None:
                    raise RuntimeError(
                        "Read-only SQL query did not produce a result set."
                    )

                rows = cursor.fetchmany(
                    max_rows + 1
                )

                truncated = (
                    len(rows) > max_rows
                )

                rows = rows[:max_rows]

                column_names = [
                    description.name
                    for description in cursor.description
                ]

                result = {
                    "columns": column_names,
                    "rows": rows,
                    "row_count": len(rows),
                    "truncated": truncated,
                }

                connection.rollback()

                return str(result)

        except psycopg2.Error as exc:

            connection.rollback()

            raise DatabaseQueryError(
                f"SQL execution failed: {exc}"
            ) from exc

        finally:

            connection.close()


# ============================================================
# CONFIG
# ============================================================


def load_database_config() -> dict:
    """
    Load validated PostgreSQL configuration.
    """

    settings = get_database_settings()

    return settings.psycopg_config()


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