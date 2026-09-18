import psycopg2
from psycopg2 import sql

from config.settings import (
    get_database_settings,
    get_runtime_settings,
)


def print_relation(
    cursor,
    *,
    schema_name: str,
    relation_name: str,
    relation_type: str,
    limit: int = 10,
) -> None:
    count_query = sql.SQL(
        "SELECT COUNT(*) FROM {}.{}"
    ).format(
        sql.Identifier(
            schema_name
        ),
        sql.Identifier(
            relation_name
        ),
    )

    cursor.execute(
        count_query
    )

    row_count = (
        cursor.fetchone()[0]
    )

    sample_query = sql.SQL(
        "SELECT * FROM {}.{} LIMIT %s"
    ).format(
        sql.Identifier(
            schema_name
        ),
        sql.Identifier(
            relation_name
        ),
    )

    cursor.execute(
        sample_query,
        (
            limit,
        ),
    )

    rows = (
        cursor.fetchall()
    )

    columns = [
        description.name
        for description
        in cursor.description
    ]

    print(
        "\n"
        + "=" * 80
    )

    print(
        f"{schema_name}.{relation_name}"
    )

    print(
        f"Type: {relation_type}"
    )

    print(
        f"Rows: {row_count}"
    )

    print(
        f"Columns: {columns}"
    )

    print(
        "-" * 80
    )

    if not rows:
        print(
            "<empty relation>"
        )

        return

    for row in rows:
        print(
            dict(
                zip(
                    columns,
                    row,
                    strict=True,
                )
            )
        )


def main() -> None:
    database_settings = (
        get_database_settings()
    )

    runtime_settings = (
        get_runtime_settings()
    )

    target_schema = (
        runtime_settings
        .dbt_target_schema
    )

    schemas = [
        "bronze",
        f"{target_schema}_silver",
        f"{target_schema}_gold",
    ]

    connection = (
        psycopg2.connect(
            **database_settings
            .psycopg_config()
        )
    )

    try:
        with connection.cursor() as cursor:

            for schema_name in schemas:

                print(
                    "\n\n"
                    f"### SCHEMA: {schema_name}"
                )

                cursor.execute(
                    """
                    SELECT
                        table_name,
                        table_type
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    ORDER BY table_name
                    """,
                    (
                        schema_name,
                    ),
                )

                relations = (
                    cursor.fetchall()
                )

                if not relations:
                    print(
                        "No relations found."
                    )

                    continue

                for (
                    relation_name,
                    relation_type,
                ) in relations:

                    print_relation(
                        cursor,
                        schema_name=(
                            schema_name
                        ),
                        relation_name=(
                            relation_name
                        ),
                        relation_type=(
                            relation_type
                        ),
                    )

    finally:
        connection.close()


if __name__ == "__main__":
    main()