from typing import (
    Annotated,
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)


QualityValue = (
    str
    | int
    | float
    | bool
)


class NotNullRule(BaseModel):
    type: Literal["not_null"]

    column: str


class UniqueRule(BaseModel):
    type: Literal["unique"]

    columns: list[str] = Field(
        min_length=1
    )


class AcceptedValuesRule(BaseModel):
    type: Literal[
        "accepted_values"
    ]

    column: str

    values: list[
        QualityValue
    ] = Field(
        min_length=1
    )


class RangeRule(BaseModel):
    type: Literal["range"]

    column: str

    min_value: (
        int | float | None
    ) = None

    max_value: (
        int | float | None
    ) = None

    inclusive_min: bool = True
    inclusive_max: bool = True

    @model_validator(
        mode="after"
    )
    def validate_bounds(
        self,
    ):
        if (
            self.min_value is None
            and self.max_value is None
        ):
            raise ValueError(
                "Range rule requires at least "
                "one bound."
            )

        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value
            > self.max_value
        ):
            raise ValueError(
                "Range rule minimum cannot "
                "exceed maximum."
            )

        return self


class RowCountRule(BaseModel):
    type: Literal["row_count"]

    min_rows: int = Field(
        default=0,
        ge=0,
    )

    max_rows: (
        int | None
    ) = Field(
        default=None,
        ge=0,
    )

    @model_validator(
        mode="after"
    )
    def validate_row_limits(
        self,
    ):
        if (
            self.max_rows is not None
            and self.min_rows
            > self.max_rows
        ):
            raise ValueError(
                "Minimum rows cannot exceed "
                "maximum rows."
            )

        return self


QualityRule = Annotated[
    (
        NotNullRule
        | UniqueRule
        | AcceptedValuesRule
        | RangeRule
        | RowCountRule
    ),
    Field(
        discriminator="type"
    ),
]


class DataQualityContract(
    BaseModel
):
    """
    Declarative data-quality expectations.

    Validation is performed by deterministic
    application code.
    """

    contract_version: int = Field(
        default=1,
        ge=1,
    )

    name: str

    rules: list[
        QualityRule
    ] = Field(
        default_factory=list
    )


class QualityCheckResult(
    BaseModel
):
    rule_type: str

    passed: bool

    violation_count: int = Field(
        ge=0
    )

    description: str


class DataQualityResult(
    BaseModel
):
    passed: bool

    total_checks: int = Field(
        ge=0
    )

    failed_checks: int = Field(
        ge=0
    )

    checks: list[
        QualityCheckResult
    ] = Field(
        default_factory=list
    )