import psycopg2
import json 
import re
from psycopg2 import sql
from dataclasses import dataclass

from config.settings import (
    get_database_settings,
    get_runtime_settings,
)

from utils.exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
)

@dataclass(
    frozen=True
)
class ReadOnlyQueryResult:
    """
    Structured result from deterministic
    read-only PostgreSQL execution.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple, ...]
    row_count: int
    truncated: bool

    def as_dict(
        self,
    ) -> dict:
        return {
            "columns": list(
                self.columns
            ),
            "rows": list(
                self.rows
            ),
            "row_count": (
                self.row_count
            ),
            "truncated": (
                self.truncated
            ),
        }

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
    # GOVERNED ANALYTICS CATALOG
    # ========================================================

    ANALYTICS_SCHEMA_PATTERN = re.compile(
        r"^[A-Za-z_][A-Za-z0-9_]*$"
    )

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

    @classmethod
    def analytics_schema_names(
        cls,
        target_schema: str,
    ) -> tuple[str, str]:
        """
        Resolve the PostgreSQL schemas exposed
        to analytical query generation.

        Bronze and public are deliberately excluded.
        """

        if (
            not isinstance(
                target_schema,
                str,
            )
            or not cls
            .ANALYTICS_SCHEMA_PATTERN
            .fullmatch(
                target_schema
            )
        ):
            raise DatabaseQueryError(
                "Invalid dbt target schema "
                "for analytics catalog."
            )

        silver_schema = (
            f"{target_schema}_silver"
        )

        gold_schema = (
            f"{target_schema}_gold"
        )

        for schema_name in (
            silver_schema,
            gold_schema,
        ):
            if (
                len(
                    schema_name.encode(
                        "utf-8"
                    )
                )
                > cls
                .POSTGRES_IDENTIFIER_MAX_BYTES
            ):
                raise DatabaseQueryError(
                    "Analytics schema exceeds "
                    "PostgreSQL's 63-byte "
                    "identifier limit."
                )

        return (
            silver_schema,
            gold_schema,
        )

    def analytics_catalog(
        self,
        *,
        target_schema: str,
    ) -> dict:
        """
        Return the application-controlled catalog
        of dbt Silver and Gold relations.

        Only metadata is returned.
        Raw/sample rows are never included.
        """

        (
            silver_schema,
            gold_schema,
        ) = self.analytics_schema_names(
            target_schema
        )

        allowed_schemas = (
            silver_schema,
            gold_schema,
        )

        layer_by_schema = {
            silver_schema: "silver",
            gold_schema: "gold",
        }

        connection = (
            self._connect()
        )

        try:
            connection.set_session(
                readonly=True,
                autocommit=False,
            )

            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        tables.table_schema,
                        tables.table_name,
                        tables.table_type,
                        columns.column_name,
                        columns.data_type,
                        columns.ordinal_position
                    FROM information_schema.tables
                    AS tables
                    JOIN information_schema.columns
                    AS columns
                      ON (
                          columns.table_schema
                          = tables.table_schema
                          AND columns.table_name
                          = tables.table_name
                      )
                    WHERE tables.table_schema
                          = ANY(%s)
                      AND tables.table_type
                          IN (
                              'BASE TABLE',
                              'VIEW'
                          )
                    ORDER BY
                        tables.table_schema,
                        tables.table_name,
                        columns.ordinal_position;
                    """,
                    (
                        list(
                            allowed_schemas
                        ),
                    ),
                )

                rows = (
                    cursor.fetchall()
                )

            connection.rollback()

        except psycopg2.Error as exc:

            connection.rollback()

            raise DatabaseQueryError(
                "Failed to retrieve governed "
                "analytics catalog."
            ) from exc

        finally:
            connection.close()

        relations_by_schema: dict[
            str,
            dict[str, dict],
        ] = {
            silver_schema: {},
            gold_schema: {},
        }

        for (
            schema_name,
            relation_name,
            relation_type,
            column_name,
            data_type,
            _ordinal_position,
        ) in rows:

            if (
                schema_name
                not in layer_by_schema
            ):
                raise DatabaseQueryError(
                    "Analytics catalog returned "
                    "an unauthorized schema."
                )

            if (
                relation_type
                == "BASE TABLE"
            ):
                normalized_type = (
                    "table"
                )

            elif (
                relation_type
                == "VIEW"
            ):
                normalized_type = (
                    "view"
                )

            else:
                raise DatabaseQueryError(
                    "Analytics catalog returned "
                    "an unsupported relation type."
                )

            schema_relations = (
                relations_by_schema[
                    schema_name
                ]
            )

            relation = (
                schema_relations
                .setdefault(
                    relation_name,
                    {
                        "name": (
                            relation_name
                        ),
                        "type": (
                            normalized_type
                        ),
                        "columns": [],
                    },
                )
            )

            if (
                relation["type"]
                != normalized_type
            ):
                raise DatabaseQueryError(
                    "Analytics catalog contains "
                    "inconsistent relation metadata."
                )

            relation[
                "columns"
            ].append(
                {
                    "name": (
                        column_name
                    ),
                    "data_type": (
                        data_type
                    ),
                }
            )

        schemas = []

        for schema_name in (
            silver_schema,
            gold_schema,
        ):

            relations = (
                relations_by_schema[
                    schema_name
                ]
            )

            schemas.append(
                {
                    "name": (
                        schema_name
                    ),
                    "layer": (
                        layer_by_schema[
                            schema_name
                        ]
                    ),
                    "relations": [
                        relations[name]
                        for name
                        in sorted(
                            relations
                        )
                    ],
                }
            )

        return {
            "catalog_version": 1,
            "schemas": schemas,
        }

    def analytics_catalog_context(
        self,
        *,
        target_schema: str,
    ) -> str:
        """
        Load and serialize the governed analytics
        catalog.
        """

        catalog = (
            self.analytics_catalog(
                target_schema=(
                    target_schema
                )
            )
        )

        return (
            self.serialize_analytics_catalog(
                catalog
            )
        )

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

    @staticmethod
    def serialize_analytics_catalog(
        catalog: dict,
    ) -> str:
        """
        Serialize an already-loaded analytics
        catalog for LLM context.

        This does not perform another database
        query.
        """

        return json.dumps(
            catalog,
            indent=2,
            ensure_ascii=False,
        )

    def execute_read_only_result(
        self,
        query: str,
        statement_timeout_ms: int | None = None,
        max_rows: int | None = None,
    ) -> ReadOnlyQueryResult:

        runtime = (
            get_runtime_settings()
        )

        statement_timeout_ms = (
            statement_timeout_ms
            if statement_timeout_ms
            is not None
            else (
                runtime
                .sql_statement_timeout_ms
            )
        )

        max_rows = (
            max_rows
            if max_rows is not None
            else runtime.sql_max_rows
        )

        connection = (
            self._connect()
        )

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

                cursor.execute(
                    query
                )

                if (
                    cursor.description
                    is None
                ):
                    raise RuntimeError(
                        "Read-only SQL query did "
                        "not produce a result set."
                    )

                rows = cursor.fetchmany(
                    max_rows + 1
                )

                truncated = (
                    len(rows)
                    > max_rows
                )

                rows = (
                    rows[
                        :max_rows
                    ]
                )

                columns = tuple(
                    description.name
                    for description
                    in cursor.description
                )

                result = (
                    ReadOnlyQueryResult(
                        columns=columns,
                        rows=tuple(
                            rows
                        ),
                        row_count=len(
                            rows
                        ),
                        truncated=(
                            truncated
                        ),
                    )
                )

                connection.rollback()

                return result

        except psycopg2.Error as exc:

            connection.rollback()

            raise DatabaseQueryError(
                "SQL execution failed."
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