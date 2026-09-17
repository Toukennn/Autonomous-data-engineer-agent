import json
import math
import re
from dataclasses import dataclass
from typing import Literal

import sqlglot
from sqlglot import exp

from models.schema import (
    CastColumnsOperation,
    DBTTransformPlan,
    FillMissingOperation,
    FilterRowsOperation,
    GroupByAggregateOperation,
    RenameColumnsOperation,
    SelectColumnsOperation,
    StringTransformOperation,
)
from utils.data_layers import (
    validate_dataset_name,
)
from utils.exceptions import (
    DatasetError,
)


@dataclass(
    frozen=True
)
class DBTCompiledTransform:
    sql: str
    output_columns: tuple[str, ...]


class DBTSQLCompiler:
    """
    Deterministically compile a DBTTransformPlan
    into PostgreSQL SQL.

    No arbitrary SQL input is accepted.
    """

    MODEL_NAME_PATTERN = re.compile(
        r"^[a-z0-9_]+$"
    )

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

    @classmethod
    def _validate_column(
        cls,
        column: str,
    ) -> None:
        if (
            not isinstance(column, str)
            or not column
        ):
            raise DatasetError(
                "dbt column names must be "
                "non-empty strings."
            )

        if "\x00" in column:
            raise DatasetError(
                "dbt column names cannot "
                "contain null bytes."
            )

        if (
            len(
                column.encode("utf-8")
            )
            > cls.POSTGRES_IDENTIFIER_MAX_BYTES
        ):
            raise DatasetError(
                "dbt column name exceeds PostgreSQL's "
                "63-byte identifier limit."
            )

    @classmethod
    def _validate_columns(
        cls,
        columns: list[str],
    ) -> None:
        if not columns:
            raise DatasetError(
                "dbt transformation requires "
                "at least one column."
            )

        if len(columns) != len(set(columns)):
            raise DatasetError(
                "dbt transformation contains "
                "duplicate column names."
            )

        for column in columns:
            cls._validate_column(column)

    @staticmethod
    def _quote_identifier(
        identifier: str,
    ) -> str:
        return (
            '"'
            + identifier.replace(
                '"',
                '""',
            )
            + '"'
        )

    @staticmethod
    def _literal(
        value,
    ) -> str:
        if value is None:
            return "null"

        if isinstance(value, bool):
            return (
                "true"
                if value
                else "false"
            )

        if isinstance(value, int):
            return str(value)

        if isinstance(value, float):
            if not math.isfinite(value):
                raise DatasetError(
                    "Non-finite numeric SQL "
                    "literals are not allowed."
                )

            return repr(value)

        if isinstance(value, str):
            return (
                "'"
                + value.replace(
                    "'",
                    "''",
                )
                + "'"
            )

        raise DatasetError(
            "Unsupported SQL literal type."
        )

    @classmethod
    def _require_columns(
        cls,
        available: list[str],
        required: list[str],
    ) -> None:
        missing = [
            column
            for column in required
            if column not in available
        ]

        if missing:
            raise DatasetError(
                "dbt transformation references "
                f"missing columns: {missing}"
            )

    @classmethod
    def _filter_sql(
        cls,
        operation: FilterRowsOperation,
    ) -> str:
        column = cls._quote_identifier(
            operation.column
        )

        operator = operation.operator
        value = operation.value

        if operator == "is_null":
            return f"{column} is null"

        if operator == "not_null":
            return f"{column} is not null"

        if operator == "eq":
            if value is None:
                return f"{column} is null"

            return (
                f"{column} = "
                f"{cls._literal(value)}"
            )

        if operator == "ne":
            if value is None:
                return f"{column} is not null"

            return (
                f"{column} <> "
                f"{cls._literal(value)}"
            )

        comparisons = {
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
        }

        if operator in comparisons:
            if value is None:
                raise DatasetError(
                    "Comparison filter cannot "
                    "use a null value."
                )

            return (
                f"{column} "
                f"{comparisons[operator]} "
                f"{cls._literal(value)}"
            )

        if operator in {
            "in",
            "not_in",
        }:
            if not isinstance(
                value,
                list,
            ):
                raise DatasetError(
                    f"{operator} requires "
                    "a list value."
                )

            if not value:
                return (
                    "false"
                    if operator == "in"
                    else "true"
                )

            values = ", ".join(
                cls._literal(item)
                for item in value
            )

            keyword = (
                "in"
                if operator == "in"
                else "not in"
            )

            return (
                f"{column} "
                f"{keyword} ({values})"
            )

        if operator == "contains":
            if not isinstance(
                value,
                str,
            ):
                raise DatasetError(
                    "contains requires "
                    "a string value."
                )

            literal = cls._literal(
                value
            )

            if operation.case_sensitive:
                return (
                    "strpos("
                    f"{column}, "
                    f"{literal}"
                    ") > 0"
                )

            return (
                "strpos("
                f"lower({column}), "
                f"lower({literal})"
                ") > 0"
            )

        raise DatasetError(
            "Unsupported dbt filter operator."
        )

    @staticmethod
    def _cast_type(
        target_type: str,
    ) -> str:
        mapping = {
            "string": "text",
            "integer": "bigint",
            "float": "double precision",
            "boolean": "boolean",
            "datetime": "timestamptz",
            "category": "text",
        }

        try:
            return mapping[target_type]

        except KeyError as exc:
            raise DatasetError(
                "Unsupported dbt cast type."
            ) from exc


    def compile(
        self,
        *,
        plan: DBTTransformPlan,
        input_columns: list[str],
        relation_kind: Literal[
            "bronze_source",
            "silver_ref",
        ],
        relation_name: str,
        allow_aggregation: bool,
    ) -> DBTCompiledTransform:

        self._validate_columns(
            input_columns
        )

        if relation_kind == "bronze_source":

            safe_dataset = (
                validate_dataset_name(
                    relation_name
                )
            )

            relation_sql = (
                "{{ source("
                '"bronze", '
                f"{json.dumps(safe_dataset)}"
                ") }}"
            )

        elif relation_kind == "silver_ref":

            if not (
                self.MODEL_NAME_PATTERN
                .fullmatch(
                    relation_name
                )
            ):
                raise DatasetError(
                    "Invalid Silver dbt model "
                    "reference."
                )

            relation_sql = (
                "{{ ref("
                f"{json.dumps(relation_name)}"
                ") }}"
            )

        else:
            raise DatasetError(
                "Unsupported dbt relation kind."
            )

        current_columns = list(
            input_columns
        )

        ctes: list[
            tuple[str, str]
        ] = []

        base_columns = ",\n".join(
            "        "
            + self._quote_identifier(
                column
            )
            for column
            in current_columns
        )

        ctes.append(
            (
                "step_0",
                (
                    "select\n"
                    f"{base_columns}\n"
                    "from __DBT_RELATION__"
                ),
            )
        )

        previous_step = "step_0"

        for index, operation in enumerate(
            plan.operations,
            start=1,
        ):
            step_name = (
                f"step_{index}"
            )

            # SELECT
            if isinstance(
                operation,
                SelectColumnsOperation,
            ):
                self._require_columns(
                    current_columns,
                    operation.columns,
                )

                self._validate_columns(
                    operation.columns
                )

                current_columns = list(
                    operation.columns
                )

                projection = ",\n".join(
                    "    "
                    + self._quote_identifier(
                        column
                    )
                    for column
                    in current_columns
                )

                body = (
                    "select\n"
                    f"{projection}\n"
                    f"from {previous_step}"
                )

            # FILTER
            elif isinstance(
                operation,
                FilterRowsOperation,
            ):
                self._require_columns(
                    current_columns,
                    [
                        operation.column
                    ],
                )

                projection = ",\n".join(
                    "    "
                    + self._quote_identifier(
                        column
                    )
                    for column
                    in current_columns
                )

                predicate = (
                    self._filter_sql(
                        operation
                    )
                )

                body = (
                    "select\n"
                    f"{projection}\n"
                    f"from {previous_step}\n"
                    f"where {predicate}"
                )

            # RENAME
            elif isinstance(
                operation,
                RenameColumnsOperation,
            ):
                self._require_columns(
                    current_columns,
                    list(
                        operation.mapping
                    ),
                )

                renamed = [
                    operation.mapping.get(
                        column,
                        column,
                    )
                    for column
                    in current_columns
                ]

                self._validate_columns(
                    renamed
                )

                expressions = []

                for old, new in zip(
                    current_columns,
                    renamed,
                    strict=True,
                ):
                    old_sql = (
                        self._quote_identifier(
                            old
                        )
                    )

                    if old == new:
                        expressions.append(
                            f"    {old_sql}"
                        )

                    else:
                        expressions.append(
                            "    "
                            f"{old_sql} as "
                            f"{self._quote_identifier(new)}"
                        )

                current_columns = renamed

                body = (
                    "select\n"
                    + ",\n".join(
                        expressions
                    )
                    + "\n"
                    + f"from {previous_step}"
                )

            # FILL MISSING
            elif isinstance(
                operation,
                FillMissingOperation,
            ):
                self._require_columns(
                    current_columns,
                    list(
                        operation.values
                    ),
                )

                expressions = []

                for column in current_columns:

                    column_sql = (
                        self._quote_identifier(
                            column
                        )
                    )

                    if (
                        column
                        in operation.values
                    ):
                        expressions.append(
                            "    coalesce("
                            f"{column_sql}, "
                            f"{self._literal(operation.values[column])}"
                            ") as "
                            f"{column_sql}"
                        )

                    else:
                        expressions.append(
                            f"    {column_sql}"
                        )

                body = (
                    "select\n"
                    + ",\n".join(
                        expressions
                    )
                    + "\n"
                    + f"from {previous_step}"
                )

            # CAST
            elif isinstance(
                operation,
                CastColumnsOperation,
            ):
                self._require_columns(
                    current_columns,
                    list(
                        operation.dtypes
                    ),
                )

                expressions = []

                for column in current_columns:
                    column_sql = (
                        self._quote_identifier(
                            column
                        )
                    )

                    if (
                        column
                        in operation.dtypes
                    ):
                        target = (
                            self._cast_type(
                                operation
                                .dtypes[
                                    column
                                ]
                            )
                        )

                        expressions.append(
                            "    cast("
                            f"{column_sql} "
                            f"as {target}"
                            ") as "
                            f"{column_sql}"
                        )

                    else:
                        expressions.append(
                            f"    {column_sql}"
                        )

                body = (
                    "select\n"
                    + ",\n".join(
                        expressions
                    )
                    + "\n"
                    + f"from {previous_step}"
                )

            # STRING TRANSFORM
            elif isinstance(
                operation,
                StringTransformOperation,
            ):
                self._require_columns(
                    current_columns,
                    operation.columns,
                )

                function = {
                    "strip": "trim",
                    "lower": "lower",
                    "upper": "upper",
                }[
                    operation.action
                ]

                expressions = []

                for column in current_columns:
                    column_sql = (
                        self._quote_identifier(
                            column
                        )
                    )

                    if (
                        column
                        in operation.columns
                    ):
                        expressions.append(
                            "    "
                            f"{function}("
                            f"{column_sql}"
                            ") as "
                            f"{column_sql}"
                        )

                    else:
                        expressions.append(
                            f"    {column_sql}"
                        )

                body = (
                    "select\n"
                    + ",\n".join(
                        expressions
                    )
                    + "\n"
                    + f"from {previous_step}"
                )

            # AGGREGATION
            elif isinstance(
                operation,
                GroupByAggregateOperation,
            ):
                if not allow_aggregation:
                    raise DatasetError(
                        "Aggregation is not allowed "
                        "in Silver dbt models."
                    )

                required = list(
                    operation.group_by
                ) + [
                    aggregation.column
                    for aggregation
                    in operation.aggregations
                ]

                self._require_columns(
                    current_columns,
                    required,
                )

                aliases = [
                    aggregation.alias
                    for aggregation
                    in operation.aggregations
                ]

                output_columns = (
                    list(
                        operation.group_by
                    )
                    + aliases
                )

                self._validate_columns(
                    output_columns
                )

                expressions = [
                    "    "
                    + self._quote_identifier(
                        column
                    )
                    for column
                    in operation.group_by
                ]

                functions = {
                    "sum": "sum",
                    "mean": "avg",
                    "min": "min",
                    "max": "max",
                    "count": "count",
                }

                for aggregation in (
                    operation.aggregations
                ):
                    column_sql = (
                        self._quote_identifier(
                            aggregation.column
                        )
                    )

                    alias_sql = (
                        self._quote_identifier(
                            aggregation.alias
                        )
                    )

                    if (
                        aggregation.function
                        in functions
                    ):
                        expression = (
                            f"{functions[aggregation.function]}"
                            f"({column_sql})"
                        )

                    elif (
                        aggregation.function
                        == "nunique"
                    ):
                        expression = (
                            "count(distinct "
                            f"{column_sql})"
                        )

                    elif (
                        aggregation.function
                        == "median"
                    ):
                        expression = (
                            "percentile_cont(0.5) "
                            "within group "
                            f"(order by {column_sql})"
                        )

                    else:
                        raise DatasetError(
                            "Unsupported dbt "
                            "aggregation."
                        )

                    expressions.append(
                        "    "
                        f"{expression} as "
                        f"{alias_sql}"
                    )

                body = (
                    "select\n"
                    + ",\n".join(
                        expressions
                    )
                    + "\n"
                    + f"from {previous_step}"
                )

                if operation.group_by:
                    body += (
                        "\ngroup by "
                        + ", ".join(
                            self._quote_identifier(
                                column
                            )
                            for column
                            in operation.group_by
                        )
                    )

                current_columns = (
                    output_columns
                )

            else:
                raise DatasetError(
                    "Unsupported operation in "
                    "dbt transformation plan."
                )

            ctes.append(
                (
                    step_name,
                    body,
                )
            )

            previous_step = step_name

        final_columns = ",\n".join(
            "    "
            + self._quote_identifier(
                column
            )
            for column
            in current_columns
        )

        cte_sql = ",\n".join(
            (
                f"{name} as (\n"
                f"{body}\n"
                ")"
            )
            for name, body
            in ctes
        )

        validation_sql = (
            "with\n"
            f"{cte_sql}\n"
            "select\n"
            f"{final_columns}\n"
            f"from {previous_step}\n"
        )

        try:
            parsed = (
                sqlglot.parse_one(
                    validation_sql,
                    read="postgres",
                )
            )

        except Exception as exc:
            raise DatasetError(
                "Generated dbt SQL failed "
                "deterministic SQL validation."
            ) from exc

        if not isinstance(
            parsed,
            exp.Select,
        ):
            raise DatasetError(
                "Generated dbt transformation "
                "must be a SELECT query."
            )

        final_sql = (
            validation_sql.replace(
                "__DBT_RELATION__",
                relation_sql,
            )
        )

        return DBTCompiledTransform(
            sql=final_sql,
            output_columns=tuple(
                current_columns
            ),
        )