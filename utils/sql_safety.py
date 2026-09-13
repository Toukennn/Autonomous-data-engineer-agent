from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


@dataclass(frozen=True)
class SQLValidationResult:
    """
    Result returned by the deterministic SQL safety validator.
    """

    is_safe: bool
    reason: str


class SQLSafetyValidator:
    """
    Deterministically validate SQL before it reaches PostgreSQL.

    Safety rules:

    - Exactly one SQL statement is allowed.
    - The statement must be a read-only query.
    - DML and DDL operations are rejected.
    - Transaction/control statements are rejected.
    - The SQL must be valid PostgreSQL syntax.

    This validator is a security boundary and does not rely on an LLM.
    """

    # Expression types that are always forbidden.
    FORBIDDEN_EXPRESSIONS = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.TruncateTable,
        exp.Merge,
        exp.Command,
    )

    @classmethod
    def validate(
        cls,
        sql: str,
    ) -> SQLValidationResult:

        if not sql or not sql.strip():

            return SQLValidationResult(
                is_safe=False,
                reason="SQL query is empty.",
            )

        try:
            statements = sqlglot.parse(
                sql,
                read="postgres",
            )

        except ParseError as exc:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "SQL could not be parsed as valid "
                    f"PostgreSQL: {exc}"
                ),
            )

        # --------------------------------------------------------
        # Exactly one SQL statement
        # --------------------------------------------------------

        if len(statements) != 1:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "Only one SQL statement is allowed."
                ),
            )

        statement = statements[0]

        # --------------------------------------------------------
        # Only SELECT / UNION / INTERSECT / EXCEPT style queries
        # --------------------------------------------------------

        if not isinstance(
            statement,
            exp.Query,
        ):

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "Only read-only query expressions "
                    "are allowed."
                ),
            )

        # --------------------------------------------------------
        # Search the entire syntax tree
        #
        # This is important because an unsafe operation could
        # potentially be hidden inside a CTE or nested structure.
        # --------------------------------------------------------

        for node in statement.walk():

            if isinstance(
                node,
                cls.FORBIDDEN_EXPRESSIONS,
            ):

                return SQLValidationResult(
                    is_safe=False,
                    reason=(
                        "Query contains forbidden SQL "
                        f"operation: {type(node).__name__}"
                    ),
                )

        return SQLValidationResult(
            is_safe=True,
            reason=(
                "Query is a single parsed "
                "read-only PostgreSQL statement."
            ),
        )