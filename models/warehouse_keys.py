from pydantic import (
    BaseModel,
    Field,
    field_validator,
)


POSTGRES_IDENTIFIER_MAX_BYTES = 63


class BusinessKeyContract(
    BaseModel
):
    """
    Declarative row-identity contract for one
    logical Bronze warehouse dataset.

    This contract defines WHICH columns identify
    one logical row.

    It does not define SQL merge behavior.
    """

    contract_version: int = Field(
        default=1,
        ge=1,
    )

    columns: list[str] = Field(
        min_length=1,
        max_length=16,
    )

    @field_validator(
        "columns"
    )
    @classmethod
    def validate_columns(
        cls,
        columns: list[str],
    ) -> list[str]:

        seen: set[str] = set()

        validated: list[
            str
        ] = []

        for column in columns:

            if not isinstance(
                column,
                str,
            ):
                raise ValueError(
                    "Business-key columns "
                    "must be strings."
                )

            if not column:
                raise ValueError(
                    "Business-key columns "
                    "cannot be empty."
                )

            if "\x00" in column:
                raise ValueError(
                    "Business-key columns "
                    "cannot contain null bytes."
                )

            if (
                len(
                    column.encode(
                        "utf-8"
                    )
                )
                > POSTGRES_IDENTIFIER_MAX_BYTES
            ):
                raise ValueError(
                    "Business-key column exceeds "
                    "PostgreSQL's 63-byte "
                    "identifier limit."
                )

            if column in seen:
                raise ValueError(
                    "Business-key columns "
                    "must be unique."
                )

            seen.add(
                column
            )

            validated.append(
                column
            )

        return validated