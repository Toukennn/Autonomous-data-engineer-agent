import json
from dataclasses import dataclass

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

from utils.data_layers import (
    validate_dataset_name,
)
from utils.exceptions import (
    DatabaseConnectionError,
    DatasetError,
    WarehouseLoadError,
)


@dataclass(
    frozen=True
)
class WarehouseLoadResult:
    """
    Result of one successful deterministic
    warehouse load.
    """

    schema: str
    table: str
    row_count: int
    column_count: int
    columns: tuple[str, ...]


class PostgresWarehouseLoader:
    """
    Deterministic PostgreSQL warehouse writer.

    This component is separate from DatabaseUtil,
    which is intentionally read-only and used by
    the SQL Analyst.

    Physical warehouse placement is controlled by
    the application, never by an LLM.
    """

    BRONZE_SCHEMA = "bronze"

    def __init__(
        self,
        db_config: dict,
    ):
        self.db_config = db_config

    # ============================================================
    # CONNECTION
    # ============================================================

    def _connect(
        self,
    ):
        try:
            return psycopg2.connect(
                **self.db_config
            )

        except psycopg2.Error as exc:
            raise DatabaseConnectionError(
                "Could not connect to PostgreSQL "
                "for warehouse loading."
            ) from exc

    # ============================================================
    # DATAFRAME VALIDATION
    # ============================================================

    @staticmethod
    def _validate_dataframe(
        dataframe: pd.DataFrame,
    ) -> None:
        """
        Validate properties required for a safe
        relational table.
        """

        if not isinstance(
            dataframe,
            pd.DataFrame,
        ):
            raise DatasetError(
                "Warehouse input must be "
                "a Pandas DataFrame."
            )

        if len(
            dataframe.columns
        ) == 0:
            raise DatasetError(
                "Cannot create a warehouse table "
                "from a dataset with no columns."
            )

        if (
            dataframe.columns
            .duplicated()
            .any()
        ):
            raise DatasetError(
                "Warehouse dataset contains "
                "duplicate column names."
            )

        for column in (
            dataframe.columns
        ):
            if not isinstance(
                column,
                str,
            ):
                raise DatasetError(
                    "Warehouse column names "
                    "must be strings."
                )

            if not column:
                raise DatasetError(
                    "Warehouse column names "
                    "cannot be empty."
                )

            if "\x00" in column:
                raise DatasetError(
                    "Warehouse column names "
                    "cannot contain null bytes."
                )

    # ============================================================
    # POSTGRES TYPE MAPPING
    # ============================================================

    @staticmethod
    def _postgres_type(
        series: pd.Series,
    ) -> str:
        """
        Deterministically map Pandas dtypes to
        conservative PostgreSQL types.

        Bronze intentionally favors stable,
        general-purpose representations.
        """

        dtype = series.dtype

        if (
            pd.api.types
            .is_bool_dtype(
                dtype
            )
        ):
            return "BOOLEAN"

        if (
            pd.api.types
            .is_integer_dtype(
                dtype
            )
        ):
            return "BIGINT"

        if (
            pd.api.types
            .is_float_dtype(
                dtype
            )
        ):
            return "DOUBLE PRECISION"

        if (
            pd.api.types
            .is_datetime64_any_dtype(
                dtype
            )
        ):
            return "TIMESTAMPTZ"

        return "TEXT"

    # ============================================================
    # VALUE NORMALIZATION
    # ============================================================

    @staticmethod
    def _normalize_value(
        value,
    ):
        """
        Convert Pandas / NumPy values into values
        Psycopg can safely bind.

        Nested list/dict objects are serialized to
        stable JSON text in Bronze.
        """

        if value is None:
            return None

        if isinstance(
            value,
            (
                dict,
                list,
            ),
        ):
            return json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )

        try:
            missing = pd.isna(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            missing = False

        if isinstance(
            missing,
            bool,
        ) and missing:
            return None

        if isinstance(
            value,
            pd.Timestamp,
        ):
            return (
                value.to_pydatetime()
            )

        # NumPy scalar → native Python scalar.
        if hasattr(
            value,
            "item",
        ):
            try:
                return value.item()

            except (
                ValueError,
                AttributeError,
            ):
                pass

        return value

    def _prepare_rows(
        self,
        dataframe: pd.DataFrame,
    ) -> list[tuple]:
        """
        Convert the DataFrame into parameterized
        PostgreSQL row values.
        """

        rows: list[
            tuple
        ] = []

        for values in (
            dataframe.itertuples(
                index=False,
                name=None,
            )
        ):
            rows.append(
                tuple(
                    self._normalize_value(
                        value
                    )
                    for value in values
                )
            )

        return rows

    # ============================================================
    # BRONZE TABLE REPLACEMENT
    # ============================================================

    def replace_bronze_table(
        self,
        *,
        dataset_name: str,
        dataframe: pd.DataFrame,
    ) -> WarehouseLoadResult:
        """
        Atomically replace one Bronze warehouse table.

        Target relation:

            bronze.<logical_dataset_name>

        The schema is application-controlled.

        The operation executes inside one PostgreSQL
        transaction so a failure rolls back the table
        replacement.
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        self._validate_dataframe(
            dataframe
        )

        columns = list(
            dataframe.columns
        )

        column_definitions = (
            sql.SQL(
                ", "
            ).join(
                sql.SQL(
                    "{} {}"
                ).format(
                    sql.Identifier(
                        column
                    ),
                    sql.SQL(
                        self._postgres_type(
                            dataframe[
                                column
                            ]
                        )
                    ),
                )
                for column in columns
            )
        )

        column_identifiers = (
            sql.SQL(
                ", "
            ).join(
                sql.Identifier(
                    column
                )
                for column in columns
            )
        )

        rows = (
            self._prepare_rows(
                dataframe
            )
        )

        connection = (
            self._connect()
        )

        try:
            connection.autocommit = (
                False
            )

            with connection.cursor() as cursor:

                # ================================================
                # APPLICATION-CONTROLLED BRONZE SCHEMA
                # ================================================

                cursor.execute(
                    sql.SQL(
                        "CREATE SCHEMA IF NOT EXISTS {}"
                    ).format(
                        sql.Identifier(
                            self.BRONZE_SCHEMA
                        )
                    )
                )

                # ================================================
                # REPLACE TABLE
                # ================================================

                cursor.execute(
                    sql.SQL(
                        "DROP TABLE IF EXISTS {}.{}"
                    ).format(
                        sql.Identifier(
                            self.BRONZE_SCHEMA
                        ),
                        sql.Identifier(
                            safe_dataset_name
                        ),
                    )
                )

                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE {}.{} ({})"
                    ).format(
                        sql.Identifier(
                            self.BRONZE_SCHEMA
                        ),
                        sql.Identifier(
                            safe_dataset_name
                        ),
                        column_definitions,
                    )
                )

                # ================================================
                # BULK INSERT
                # ================================================

                if rows:

                    insert_query = (
                        sql.SQL(
                            "INSERT INTO {}.{} ({}) "
                            "VALUES %s"
                        ).format(
                            sql.Identifier(
                                self.BRONZE_SCHEMA
                            ),
                            sql.Identifier(
                                safe_dataset_name
                            ),
                            column_identifiers,
                        )
                    )

                    execute_values(
                        cursor,
                        insert_query,
                        rows,
                        page_size=1000,
                    )

            connection.commit()

        except psycopg2.Error as exc:

            connection.rollback()

            raise WarehouseLoadError(
                "Failed to load Bronze dataset "
                f"'{safe_dataset_name}' into "
                "PostgreSQL."
            ) from exc

        finally:
            connection.close()

        return WarehouseLoadResult(
            schema=(
                self.BRONZE_SCHEMA
            ),
            table=(
                safe_dataset_name
            ),
            row_count=len(
                dataframe
            ),
            column_count=len(
                columns
            ),
            columns=tuple(
                columns
            ),
        )