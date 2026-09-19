import json
from dataclasses import dataclass

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

from utils.data_layers import (
    validate_dataset_name,
)

import hashlib

from models.warehouse_keys import (
    BusinessKeyContract,
)

from utils.business_keys import (
    validate_business_key,
)

from utils.exceptions import (
    BusinessKeyError,
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

    Bronze tables are refreshed in place so
    downstream dbt relations can safely depend
    on their PostgreSQL identity.
    """

    BRONZE_SCHEMA = "bronze"

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

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
    # POSTGRES IDENTIFIER VALIDATION
    # ============================================================

    @classmethod
    def _validate_postgres_identifier(
        cls,
        identifier: str,
        *,
        kind: str,
    ) -> None:
        """
        Reject identifiers PostgreSQL would truncate.
        """

        if (
            len(
                identifier.encode(
                    "utf-8"
                )
            )
            > cls.POSTGRES_IDENTIFIER_MAX_BYTES
        ):
            raise DatasetError(
                f"{kind} exceeds PostgreSQL's "
                "63-byte identifier limit."
            )

    # ============================================================
    # DATAFRAME VALIDATION
    # ============================================================

    @classmethod
    def _validate_dataframe(
        cls,
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

        if (
            len(
                dataframe.columns
            )
            == 0
        ):
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

            cls._validate_postgres_identifier(
                column,
                kind=(
                    "Warehouse column name"
                ),
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
            return (
                "DOUBLE PRECISION"
            )

        if (
            pd.api.types
            .is_datetime64_any_dtype(
                dtype
            )
        ):
            return "TIMESTAMPTZ"

        return "TEXT"

    @staticmethod
    def _normalize_postgres_type(
        data_type: str,
    ) -> str:
        """
        Convert information_schema type names into
        the canonical PostgreSQL types used by this
        warehouse writer.
        """

        mapping = {
            "boolean": (
                "BOOLEAN"
            ),
            "bigint": (
                "BIGINT"
            ),
            "double precision": (
                "DOUBLE PRECISION"
            ),
            "timestamp with time zone": (
                "TIMESTAMPTZ"
            ),
            "text": (
                "TEXT"
            ),
        }

        normalized = (
            mapping.get(
                data_type.lower()
            )
        )

        if normalized is None:
            raise DatasetError(
                "Unsupported existing PostgreSQL "
                f"column type: {data_type}"
            )

        return normalized

    # ============================================================
    # EXISTING WAREHOUSE SCHEMA
    # ============================================================

    def _get_existing_columns(
        self,
        *,
        cursor,
        dataset_name: str,
    ) -> dict[str, str]:
        """
        Read the current PostgreSQL Bronze schema.

        Returns:

            {
                "column_name": "POSTGRES_TYPE",
                ...
            }

        An empty mapping means the table does not
        currently exist.
        """

        cursor.execute(
            """
            SELECT
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (
                self.BRONZE_SCHEMA,
                dataset_name,
            ),
        )

        rows = (
            cursor.fetchall()
        )

        return {
            column_name: (
                self._normalize_postgres_type(
                    data_type
                )
            )
            for (
                column_name,
                data_type,
            ) in rows
        }

    def _synchronize_table_schema(
        self,
        *,
        cursor,
        dataset_name: str,
        dataframe: pd.DataFrame,
    ) -> None:
        """
        Synchronize the Bronze PostgreSQL table with
        the incoming additive schema.

        Important:

        Existing tables are NEVER dropped here.

        This preserves dependencies such as:

            bronze.orders
                ↓
            stg_orders
                ↓
            mart_orders

        Supported transitions:

        - first table creation
        - identical schema
        - additive columns

        Rejected transitions:

        - removed columns
        - incompatible PostgreSQL type changes
        """

        existing_columns = (
            self._get_existing_columns(
                cursor=cursor,
                dataset_name=(
                    dataset_name
                ),
            )
        )

        incoming_columns = {
            column: (
                self._postgres_type(
                    dataframe[
                        column
                    ]
                )
            )
            for column
            in dataframe.columns
        }

        # ========================================================
        # FIRST LOAD
        # ========================================================

        if not existing_columns:

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
                            postgres_type
                        ),
                    )
                    for (
                        column,
                        postgres_type,
                    )
                    in incoming_columns.items()
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
                        dataset_name
                    ),
                    column_definitions,
                )
            )

            return

        # ========================================================
        # REMOVED COLUMNS
        # ========================================================

        removed_columns = [
            column
            for column
            in existing_columns
            if column
            not in incoming_columns
        ]

        if removed_columns:
            raise DatasetError(
                "Warehouse Bronze schema would "
                "remove existing columns: "
                f"{removed_columns}"
            )

        # ========================================================
        # EXISTING COLUMN TYPE COMPATIBILITY
        # ========================================================

        for (
            column,
            incoming_type,
        ) in incoming_columns.items():

            if (
                column
                not in existing_columns
            ):
                continue

            existing_type = (
                existing_columns[
                    column
                ]
            )

            if (
                existing_type
                != incoming_type
            ):
                raise DatasetError(
                    "Warehouse Bronze schema "
                    "type change is not supported "
                    f"for column '{column}': "
                    f"{existing_type} -> "
                    f"{incoming_type}"
                )

        # ========================================================
        # ADDITIVE COLUMNS
        # ========================================================

        added_columns = [
            column
            for column
            in incoming_columns
            if column
            not in existing_columns
        ]

        for column in (
            added_columns
        ):

            cursor.execute(
                sql.SQL(
                    "ALTER TABLE {}.{} "
                    "ADD COLUMN {} {}"
                ).format(
                    sql.Identifier(
                        self.BRONZE_SCHEMA
                    ),
                    sql.Identifier(
                        dataset_name
                    ),
                    sql.Identifier(
                        column
                    ),
                    sql.SQL(
                        incoming_columns[
                            column
                        ]
                    ),
                )
            )

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

        if (
            isinstance(
                missing,
                bool,
            )
            and missing
        ):
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
                return (
                    value.item()
                )

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
                    for value
                    in values
                )
            )

        return rows

    # ============================================================
    # BRONZE TABLE REFRESH
    # ============================================================

    def replace_bronze_table(
        self,
        *,
        dataset_name: str,
        dataframe: pd.DataFrame,
    ) -> WarehouseLoadResult:
        """
        Atomically refresh one Bronze warehouse table.

        Target relation:

            bronze.<logical_dataset_name>

        The relation is refreshed IN PLACE.

        Existing Bronze tables are not dropped because
        downstream dbt views may depend on them.

        Workflow:

        First load:

            CREATE TABLE
                ↓
            INSERT

        Existing table:

            inspect schema
                ↓
            additive ALTER TABLE if required
                ↓
            TRUNCATE
                ↓
            INSERT

        All changes occur inside one PostgreSQL
        transaction.

        A failure rolls back the entire refresh.
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        self._validate_postgres_identifier(
            safe_dataset_name,
            kind=(
                "Warehouse table name"
            ),
        )

        self._validate_dataframe(
            dataframe
        )

        columns = list(
            dataframe.columns
        )

        column_identifiers = (
            sql.SQL(
                ", "
            ).join(
                sql.Identifier(
                    column
                )
                for column
                in columns
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

            with (
                connection.cursor()
                as cursor
            ):

                # ====================================================
                # APPLICATION-CONTROLLED BRONZE SCHEMA
                # ====================================================

                cursor.execute(
                    sql.SQL(
                        "CREATE SCHEMA IF NOT EXISTS {}"
                    ).format(
                        sql.Identifier(
                            self.BRONZE_SCHEMA
                        )
                    )
                )

                # ====================================================
                # SYNCHRONIZE TABLE SCHEMA
                # ====================================================
                #
                # Never DROP the Bronze table.
                #
                # dbt relations may depend on its PostgreSQL
                # relation identity.
                # ====================================================

                self._synchronize_table_schema(
                    cursor=cursor,
                    dataset_name=(
                        safe_dataset_name
                    ),
                    dataframe=dataframe,
                )

                # ====================================================
                # REFRESH DATA IN PLACE
                # ====================================================

                cursor.execute(
                    sql.SQL(
                        "TRUNCATE TABLE {}.{}"
                    ).format(
                        sql.Identifier(
                            self.BRONZE_SCHEMA
                        ),
                        sql.Identifier(
                            safe_dataset_name
                        ),
                    )
                )

                # ====================================================
                # BULK INSERT
                # ====================================================

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

        except DatasetError:
            # Schema compatibility failures must
            # also roll back any preceding ALTER
            # operations in this transaction.
            connection.rollback()

            raise

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


    @staticmethod
    def _business_key_index_name(
        *,
        dataset_name: str,
        key_columns: tuple[str, ...],
    ) -> str:
        """
        Generate an application-controlled,
        PostgreSQL-safe unique-index name.

        Raw dataset/column names are not embedded
        into the physical index name.
        """

        canonical = json.dumps(
            {
                "dataset": dataset_name,
                "key_columns": list(
                    key_columns
                ),
            },
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

        digest = hashlib.sha256(
            canonical.encode(
                "utf-8"
            )
        ).hexdigest()[:24]

        return (
            f"bk_{digest}_uq"
        )



    def _validate_existing_business_keys(
        self,
        *,
        cursor,
        dataset_name: str,
        key_columns: tuple[str, ...],
    ) -> None:
        """
        Validate existing PostgreSQL rows before
        enforcing a business-key unique index.

        Only aggregate counts are read.
        """

        null_predicate = (
            sql.SQL(
                " OR "
            ).join(
                sql.SQL(
                    "{} IS NULL"
                ).format(
                    sql.Identifier(
                        column
                    )
                )
                for column
                in key_columns
            )
        )

        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*) "
                "FROM {}.{} "
                "WHERE {}"
            ).format(
                sql.Identifier(
                    self.BRONZE_SCHEMA
                ),
                sql.Identifier(
                    dataset_name
                ),
                null_predicate,
            )
        )

        null_result = (
            cursor.fetchone()
        )

        null_key_row_count = (
            int(
                null_result[0]
            )
            if (
                null_result
                and null_result[0]
            )
            else 0
        )

        if null_key_row_count:

            raise BusinessKeyError(
                "Existing warehouse table contains "
                "null business-key values.",
                details={
                    "key_columns": list(
                        key_columns
                    ),
                    "null_key_row_count": (
                        null_key_row_count
                    ),
                },
            )

        key_identifiers = (
            sql.SQL(
                ", "
            ).join(
                sql.Identifier(
                    column
                )
                for column
                in key_columns
            )
        )

        cursor.execute(
            sql.SQL(
                "SELECT COALESCE("
                "SUM(duplicate_count), 0"
                ") "
                "FROM ("
                "SELECT COUNT(*) AS duplicate_count "
                "FROM {}.{} "
                "GROUP BY {} "
                "HAVING COUNT(*) > 1"
                ") AS duplicate_groups"
            ).format(
                sql.Identifier(
                    self.BRONZE_SCHEMA
                ),
                sql.Identifier(
                    dataset_name
                ),
                key_identifiers,
            )
        )

        duplicate_result = (
            cursor.fetchone()
        )

        duplicate_key_row_count = (
            int(
                duplicate_result[0]
            )
            if (
                duplicate_result
                and duplicate_result[0]
            )
            else 0
        )

        if duplicate_key_row_count:

            raise BusinessKeyError(
                "Existing warehouse table contains "
                "duplicate business-key values.",
                details={
                    "key_columns": list(
                        key_columns
                    ),
                    "duplicate_key_row_count": (
                        duplicate_key_row_count
                    ),
                },
            )


    def _ensure_business_key_index(
        self,
        *,
        cursor,
        dataset_name: str,
        key_columns: tuple[str, ...],
    ) -> None:
        """
        Ensure PostgreSQL can deterministically
        enforce ON CONFLICT for this business key.
        """

        index_name = (
            self._business_key_index_name(
                dataset_name=(
                    dataset_name
                ),
                key_columns=(
                    key_columns
                ),
            )
        )

        self._validate_postgres_identifier(
            index_name,
            kind=(
                "Business-key index name"
            ),
        )

        key_identifiers = (
            sql.SQL(
                ", "
            ).join(
                sql.Identifier(
                    column
                )
                for column
                in key_columns
            )
        )

        cursor.execute(
            sql.SQL(
                "CREATE UNIQUE INDEX "
                "IF NOT EXISTS {} "
                "ON {}.{} ({})"
            ).format(
                sql.Identifier(
                    index_name
                ),
                sql.Identifier(
                    self.BRONZE_SCHEMA
                ),
                sql.Identifier(
                    dataset_name
                ),
                key_identifiers,
            )
        )


    def merge_bronze_table(
        self,
        *,
        dataset_name: str,
        dataframe: pd.DataFrame,
        business_key: BusinessKeyContract,
    ) -> WarehouseLoadResult:
        """
        Deterministically merge a Bronze dataset
        into PostgreSQL using its persisted
        business-key contract.

        Existing rows:
            updated only when non-key values changed

        New rows:
            inserted

        Missing incoming rows:
            preserved

        The table is never dropped or truncated.
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        self._validate_postgres_identifier(
            safe_dataset_name,
            kind=(
                "Warehouse table name"
            ),
        )

        self._validate_dataframe(
            dataframe
        )

        # Defense in depth. The caller is expected
        # to validate as well, but the warehouse
        # boundary must enforce the contract itself.
        validate_business_key(
            dataframe=dataframe,
            contract=business_key,
        )

        key_columns = tuple(
            business_key.columns
        )

        columns = list(
            dataframe.columns
        )

        non_key_columns = [
            column
            for column
            in columns
            if column
            not in key_columns
        ]

        column_identifiers = (
            sql.SQL(
                ", "
            ).join(
                sql.Identifier(
                    column
                )
                for column
                in columns
            )
        )

        key_identifiers = (
            sql.SQL(
                ", "
            ).join(
                sql.Identifier(
                    column
                )
                for column
                in key_columns
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
            connection.autocommit = False

            with (
                connection.cursor()
                as cursor
            ):

                cursor.execute(
                    sql.SQL(
                        "CREATE SCHEMA "
                        "IF NOT EXISTS {}"
                    ).format(
                        sql.Identifier(
                            self.BRONZE_SCHEMA
                        )
                    )
                )

                # Preserve the existing additive-only
                # physical schema policy.
                self._synchronize_table_schema(
                    cursor=cursor,
                    dataset_name=(
                        safe_dataset_name
                    ),
                    dataframe=dataframe,
                )

                # Existing historical rows must already
                # satisfy the new row-identity contract.
                self._validate_existing_business_keys(
                    cursor=cursor,
                    dataset_name=(
                        safe_dataset_name
                    ),
                    key_columns=(
                        key_columns
                    ),
                )

                self._ensure_business_key_index(
                    cursor=cursor,
                    dataset_name=(
                        safe_dataset_name
                    ),
                    key_columns=(
                        key_columns
                    ),
                )

                if rows:

                    if non_key_columns:

                        assignments = (
                            sql.SQL(
                                ", "
                            ).join(
                                sql.SQL(
                                    "{} = EXCLUDED.{}"
                                ).format(
                                    sql.Identifier(
                                        column
                                    ),
                                    sql.Identifier(
                                        column
                                    ),
                                )
                                for column
                                in non_key_columns
                            )
                        )

                        changed_predicate = (
                            sql.SQL(
                                " OR "
                            ).join(
                                sql.SQL(
                                    "target.{} "
                                    "IS DISTINCT FROM "
                                    "EXCLUDED.{}"
                                ).format(
                                    sql.Identifier(
                                        column
                                    ),
                                    sql.Identifier(
                                        column
                                    ),
                                )
                                for column
                                in non_key_columns
                            )
                        )

                        merge_query = (
                            sql.SQL(
                                "INSERT INTO {}.{} "
                                "AS target ({}) "
                                "VALUES %s "
                                "ON CONFLICT ({}) "
                                "DO UPDATE SET {} "
                                "WHERE {}"
                            ).format(
                                sql.Identifier(
                                    self.BRONZE_SCHEMA
                                ),
                                sql.Identifier(
                                    safe_dataset_name
                                ),
                                column_identifiers,
                                key_identifiers,
                                assignments,
                                changed_predicate,
                            )
                        )

                    else:

                        # A dataset consisting only of its
                        # business-key columns has nothing
                        # to update on conflict.
                        merge_query = (
                            sql.SQL(
                                "INSERT INTO {}.{} "
                                "AS target ({}) "
                                "VALUES %s "
                                "ON CONFLICT ({}) "
                                "DO NOTHING"
                            ).format(
                                sql.Identifier(
                                    self.BRONZE_SCHEMA
                                ),
                                sql.Identifier(
                                    safe_dataset_name
                                ),
                                column_identifiers,
                                key_identifiers,
                            )
                        )

                    execute_values(
                        cursor,
                        merge_query,
                        rows,
                        page_size=1000,
                    )

            connection.commit()

        except DatasetError:

            connection.rollback()

            raise

        except psycopg2.Error as exc:

            connection.rollback()

            raise WarehouseLoadError(
                "Failed to merge Bronze dataset "
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