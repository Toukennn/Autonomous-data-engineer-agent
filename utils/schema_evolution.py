from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SchemaDiff:
    """
    Deterministic description of differences between two
    tabular schemas.
    """

    existing_schema: dict[str, str]
    incoming_schema: dict[str, str]

    added_columns: tuple[str, ...]
    removed_columns: tuple[str, ...]

    type_changes: dict[
        str,
        tuple[str, str],
    ]

    @property
    def has_changes(
        self,
    ) -> bool:
        return bool(
            self.added_columns
            or self.removed_columns
            or self.type_changes
        )

    @property
    def is_additive_only(
        self,
    ) -> bool:
        """
        True when the incoming schema only adds columns.

        Example:

            old:
                id, name

            new:
                id, name, email
        """

        return bool(
            self.added_columns
        ) and not (
            self.removed_columns
            or self.type_changes
        )

    @property
    def is_breaking(
        self,
    ) -> bool:
        """
        Removing columns or changing logical types is currently
        considered breaking.
        """

        return bool(
            self.removed_columns
            or self.type_changes
        )


def _logical_type(
    series: pd.Series,
) -> str:
    """
    Convert Pandas dtypes into a smaller, stable logical type system.

    We intentionally group integer and float values under "number"
    so harmless numeric widening does not appear as schema drift.
    """

    if pd.api.types.is_bool_dtype(
        series.dtype
    ):
        return "boolean"

    if pd.api.types.is_numeric_dtype(
        series.dtype
    ):
        return "number"

    if pd.api.types.is_datetime64_any_dtype(
        series.dtype
    ):
        return "datetime"

    if pd.api.types.is_string_dtype(
        series.dtype
    ):
        return "string"

    return "object"


def dataframe_schema(
    dataframe: pd.DataFrame,
) -> dict[str, str]:
    """
    Return the logical schema of a DataFrame.

    Example:

        {
            "id": "number",
            "name": "string",
            "active": "boolean"
        }
    """

    return {
        column: _logical_type(
            dataframe[column]
        )
        for column in dataframe.columns
    }


def compare_schemas(
    existing_dataframe: pd.DataFrame,
    incoming_dataframe: pd.DataFrame,
) -> SchemaDiff:
    """
    Compare the schema of an existing dataset with a newly
    extracted API batch.
    """

    existing_schema = dataframe_schema(
        existing_dataframe
    )

    incoming_schema = dataframe_schema(
        incoming_dataframe
    )

    added_columns = tuple(
        column
        for column in incoming_schema
        if column not in existing_schema
    )

    removed_columns = tuple(
        column
        for column in existing_schema
        if column not in incoming_schema
    )

    shared_columns = tuple(
        column
        for column in existing_schema
        if column in incoming_schema
    )

    type_changes = {
        column: (
            existing_schema[column],
            incoming_schema[column],
        )
        for column in shared_columns
        if (
            existing_schema[column]
            != incoming_schema[column]
        )
    }

    return SchemaDiff(
        existing_schema=existing_schema,
        incoming_schema=incoming_schema,
        added_columns=added_columns,
        removed_columns=removed_columns,
        type_changes=type_changes,
    )