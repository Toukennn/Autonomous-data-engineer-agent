from dataclasses import dataclass
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import (
    Scope,
    build_scope,
)

@dataclass(
    frozen=True
)
class SQLValidationResult:
    """
    Result returned by the deterministic
    SQL safety validator.
    """

    is_safe: bool
    reason: str


class SQLSafetyValidator:
    """
    Deterministically validate SQL before
    it reaches PostgreSQL.

    Base safety rules:

    - exactly one SQL statement
    - read-only query expressions only
    - no DML / DDL
    - no transaction/control commands
    - valid PostgreSQL syntax

    Governed analytics mode additionally
    requires every physical relation to:

    - be schema-qualified
    - belong to an approved analytics schema
    - exist in the deterministic analytics catalog

    CTE references are allowed without schema
    qualification because they are temporary
    query-local relations rather than physical
    PostgreSQL relations.

    This validator is a deterministic security
    boundary and does not rely on an LLM.
    """

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

    IDENTIFIER_PATTERN = re.compile(
        r"^[A-Za-z_][A-Za-z0-9_]*$"
    )

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

    FORBIDDEN_ANALYTICS_SCHEMAS = {
        "bronze",
        "public",
        "information_schema",
        "pg_catalog",
    }

    # ========================================================
    # IDENTIFIER VALIDATION
    # ========================================================

    @classmethod
    def _validate_catalog_identifier(
        cls,
        value,
        *,
        field: str,
    ) -> str:
        if (
            not isinstance(
                value,
                str,
            )
            or not value
        ):
            raise ValueError(
                "Analytics catalog contains "
                f"an invalid {field}."
            )

        if not (
            cls
            .IDENTIFIER_PATTERN
            .fullmatch(
                value
            )
        ):
            raise ValueError(
                "Analytics catalog contains "
                f"an unsafe {field}."
            )

        if (
            len(
                value.encode(
                    "utf-8"
                )
            )
            > cls
            .POSTGRES_IDENTIFIER_MAX_BYTES
        ):
            raise ValueError(
                "Analytics catalog contains "
                f"an overlong {field}."
            )

        return value

    # ========================================================
    # CATALOG → ALLOWLIST
    # ========================================================

    @classmethod
    def _catalog_allowlist(
        cls,
        analytics_catalog: dict,
    ) -> tuple[
        set[str],
        set[
            tuple[
                str,
                str,
            ]
        ],
    ]:
        """
        Convert the deterministic analytics catalog
        into safe schema/relation allowlists.

        The catalog itself is revalidated rather than
        trusted blindly.
        """

        if not isinstance(
            analytics_catalog,
            dict,
        ):
            raise ValueError(
                "Analytics catalog must "
                "be a dictionary."
            )

        if (
            analytics_catalog.get(
                "catalog_version"
            )
            != 1
        ):
            raise ValueError(
                "Unsupported analytics "
                "catalog version."
            )

        schemas = (
            analytics_catalog.get(
                "schemas"
            )
        )

        if not isinstance(
            schemas,
            list,
        ):
            raise ValueError(
                "Analytics catalog contains "
                "an invalid schemas list."
            )

        allowed_schemas: set[
            str
        ] = set()

        allowed_relations: set[
            tuple[
                str,
                str,
            ]
        ] = set()

        for schema in schemas:

            if not isinstance(
                schema,
                dict,
            ):
                raise ValueError(
                    "Analytics catalog contains "
                    "an invalid schema entry."
                )

            schema_name = (
                cls
                ._validate_catalog_identifier(
                    schema.get(
                        "name"
                    ),
                    field="schema name",
                )
            )

            layer = (
                schema.get(
                    "layer"
                )
            )

            if layer not in {
                "silver",
                "gold",
            }:
                raise ValueError(
                    "Analytics catalog contains "
                    "an unsupported layer."
                )

            lowered_schema = (
                schema_name.lower()
            )

            if (
                lowered_schema
                in cls
                .FORBIDDEN_ANALYTICS_SCHEMAS
                or lowered_schema.startswith(
                    "pg_"
                )
            ):
                raise ValueError(
                    "Analytics catalog contains "
                    "a forbidden schema."
                )

            if (
                schema_name
                in allowed_schemas
            ):
                raise ValueError(
                    "Analytics catalog contains "
                    "duplicate schemas."
                )

            allowed_schemas.add(
                schema_name
            )

            relations = (
                schema.get(
                    "relations"
                )
            )

            if not isinstance(
                relations,
                list,
            ):
                raise ValueError(
                    "Analytics catalog contains "
                    "an invalid relations list."
                )

            for relation in relations:

                if not isinstance(
                    relation,
                    dict,
                ):
                    raise ValueError(
                        "Analytics catalog contains "
                        "an invalid relation entry."
                    )

                relation_name = (
                    cls
                    ._validate_catalog_identifier(
                        relation.get(
                            "name"
                        ),
                        field=(
                            "relation name"
                        ),
                    )
                )

                relation_type = (
                    relation.get(
                        "type"
                    )
                )

                if relation_type not in {
                    "table",
                    "view",
                }:
                    raise ValueError(
                        "Analytics catalog contains "
                        "an unsupported relation type."
                    )

                relation_key = (
                    schema_name,
                    relation_name,
                )

                if (
                    relation_key
                    in allowed_relations
                ):
                    raise ValueError(
                        "Analytics catalog contains "
                        "duplicate relations."
                    )

                allowed_relations.add(
                    relation_key
                )

        return (
            allowed_schemas,
            allowed_relations,
        )

    # ========================================================
    # GOVERNED RELATION VALIDATION
    # ========================================================

    @classmethod
    def _validate_governed_relations(
        cls,
        statement: exp.Query,
        *,
        analytics_catalog: dict,
    ) -> SQLValidationResult | None:
        """
        Validate physical PostgreSQL relations
        against the governed analytics catalog.

        SQLGlot scopes are used so CTEs and
        subqueries cannot be confused with
        physical database relations.
        """

        try:
            (
                allowed_schemas,
                allowed_relations,
            ) = cls._catalog_allowlist(
                analytics_catalog
            )

        except ValueError as exc:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "Analytics catalog validation "
                    f"failed: {exc}"
                ),
            )

        # ========================================================
        # BUILD SQL SCOPE GRAPH
        # ========================================================

        try:
            root_scope = (
                build_scope(
                    statement
                )
            )

        except Exception:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "SQL relation scopes could "
                    "not be analyzed safely."
                ),
            )

        if root_scope is None:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "SQL relation scopes could "
                    "not be resolved."
                ),
            )

        governed_relation_count = 0

        # ========================================================
        # PHYSICAL SOURCES
        # ========================================================
        #
        # Scope.selected_sources resolves the semantic
        # meaning of FROM / JOIN sources.
        #
        # Physical relation:
        #     exp.Table
        #
        # CTE / subquery:
        #     Scope
        #
        # This avoids treating every exp.Table node
        # as a real PostgreSQL relation.
        # ========================================================

        try:

            scopes = (
                root_scope.traverse()
            )

            for scope in scopes:

                for (
                    _alias,
                    (
                        _node,
                        source,
                    ),
                ) in (
                    scope
                    .selected_sources
                    .items()
                ):

                    # --------------------------------------------
                    # CTE / SUBQUERY
                    # --------------------------------------------

                    if isinstance(
                        source,
                        Scope,
                    ):
                        continue

                    # --------------------------------------------
                    # UNKNOWN SOURCE TYPE
                    # --------------------------------------------

                    if not isinstance(
                        source,
                        exp.Table,
                    ):
                        return SQLValidationResult(
                            is_safe=False,
                            reason=(
                                "Query contains an "
                                "unsupported analytical "
                                "source type."
                            ),
                        )

                    relation_name = (
                        source.name
                    )

                    schema_name = (
                        source.db
                    )

                    catalog_name = (
                        source.catalog
                    )

                    # --------------------------------------------
                    # INVALID RELATION
                    # --------------------------------------------

                    if not relation_name:

                        return SQLValidationResult(
                            is_safe=False,
                            reason=(
                                "Query contains an "
                                "invalid relation "
                                "reference."
                            ),
                        )

                    # --------------------------------------------
                    # CROSS-DATABASE REFERENCE
                    # --------------------------------------------

                    if catalog_name:

                        return SQLValidationResult(
                            is_safe=False,
                            reason=(
                                "Cross-database relation "
                                "references are not "
                                "allowed."
                            ),
                        )

                    # --------------------------------------------
                    # REQUIRE SCHEMA QUALIFICATION
                    # --------------------------------------------

                    if not schema_name:

                        return SQLValidationResult(
                            is_safe=False,
                            reason=(
                                "Physical analytics "
                                "relations must be "
                                "schema-qualified: "
                                f"{relation_name}"
                            ),
                        )

                    # --------------------------------------------
                    # SCHEMA ALLOWLIST
                    # --------------------------------------------

                    if (
                        schema_name
                        not in allowed_schemas
                    ):

                        return SQLValidationResult(
                            is_safe=False,
                            reason=(
                                "Query references an "
                                "unauthorized schema: "
                                f"{schema_name}"
                            ),
                        )

                    # --------------------------------------------
                    # RELATION ALLOWLIST
                    # --------------------------------------------

                    relation_key = (
                        schema_name,
                        relation_name,
                    )

                    if (
                        relation_key
                        not in allowed_relations
                    ):

                        return SQLValidationResult(
                            is_safe=False,
                            reason=(
                                "Query references a "
                                "relation that is not "
                                "present in the governed "
                                "analytics catalog: "
                                f"{schema_name}."
                                f"{relation_name}"
                            ),
                        )

                    governed_relation_count += 1

        except Exception:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "SQL relation scopes could "
                    "not be validated safely."
                ),
            )

        # ========================================================
        # REQUIRE WAREHOUSE ACCESS
        # ========================================================

        if governed_relation_count == 0:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "Governed analytics queries "
                    "must reference at least one "
                    "approved Silver or Gold "
                    "relation."
                ),
            )

        return None

    # ========================================================
    # MAIN VALIDATOR
    # ========================================================

    @classmethod
    def validate(
        cls,
        sql: str,
        *,
        analytics_catalog: dict | None = None,
    ) -> SQLValidationResult:
        """
        Validate one PostgreSQL query.

        When analytics_catalog is omitted, this preserves
        the existing generic read-only SQL validation.

        When analytics_catalog is provided, governed
        relation validation is additionally enforced.
        """

        if not sql or not sql.strip():

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "SQL query is empty."
                ),
            )

        try:
            statements = (
                sqlglot.parse(
                    sql,
                    read="postgres",
                )
            )

        except ParseError as exc:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "SQL could not be parsed "
                    "as valid PostgreSQL: "
                    f"{exc}"
                ),
            )

        # ----------------------------------------------------
        # EXACTLY ONE STATEMENT
        # ----------------------------------------------------

        if len(statements) != 1:

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "Only one SQL statement "
                    "is allowed."
                ),
            )

        statement = (
            statements[0]
        )

        # ----------------------------------------------------
        # QUERY EXPRESSIONS ONLY
        # ----------------------------------------------------

        if not isinstance(
            statement,
            exp.Query,
        ):

            return SQLValidationResult(
                is_safe=False,
                reason=(
                    "Only read-only query "
                    "expressions are allowed."
                ),
            )

        # ----------------------------------------------------
        # FULL AST WRITE CHECK
        # ----------------------------------------------------

        for node in statement.walk():

            if isinstance(
                node,
                cls.FORBIDDEN_EXPRESSIONS,
            ):

                return SQLValidationResult(
                    is_safe=False,
                    reason=(
                        "Query contains forbidden "
                        "SQL operation: "
                        f"{type(node).__name__}"
                    ),
                )

        # ----------------------------------------------------
        # GOVERNED ANALYTICS
        # ----------------------------------------------------

        if (
            analytics_catalog
            is not None
        ):

            relation_result = (
                cls
                ._validate_governed_relations(
                    statement,
                    analytics_catalog=(
                        analytics_catalog
                    ),
                )
            )

            if (
                relation_result
                is not None
            ):
                return relation_result

            return SQLValidationResult(
                is_safe=True,
                reason=(
                    "Query is a single parsed "
                    "read-only PostgreSQL statement "
                    "and references only governed "
                    "analytics relations."
                ),
            )

        return SQLValidationResult(
            is_safe=True,
            reason=(
                "Query is a single parsed "
                "read-only PostgreSQL statement."
            ),
        )