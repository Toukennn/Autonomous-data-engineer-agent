class DataEngineerError(Exception):
    """
    Base exception for expected application failures.
    """


class ConfigurationError(DataEngineerError):
    """
    Invalid or missing application configuration.
    """


class DatabaseError(DataEngineerError):
    """
    Base database failure.
    """


class DatabaseConnectionError(DatabaseError):
    """
    PostgreSQL connection could not be established.
    """


class DatabaseQueryError(DatabaseError):
    """
    PostgreSQL query execution failed.
    """


class ETLError(DataEngineerError):
    """
    Base ETL failure.
    """


class DatasetError(ETLError):
    """
    Dataset could not be loaded, validated, or transformed.
    """


class SchemaEvolutionError(DatasetError):
    """
    A dataset was rejected because its schema transition
    violates the configured schema-evolution policy.

    details contains the deterministic schema comparison that
    caused the rejection.
    """

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object],
    ):
        super().__init__(
            message
        )

        self.details = details


class DataQualityError(
    DatasetError
):
    """
    A candidate dataset was rejected because
    it violated its configured quality contract.

    details contains the deterministic quality
    evaluation that caused the rejection.
    """

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object],
    ):
        super().__init__(
            message
        )

        self.details = details


class WarehouseLoadError(
    DatabaseError
):
    """
    A deterministic warehouse load failed.
    """


class DBTExecutionError(
    ETLError # the parent is ETLError because dbt failures are not necessarily database failures
):
    """
    A bounded dbt invocation failed.

    details contains safe execution metadata only.
    Raw database credentials, SQL, and dbt logs are
    intentionally excluded.
    """

    def __init__(
        self,
        message: str,
        *,
        details: dict[
            str,
            object,
        ],
    ):
        super().__init__(
            message
        )

        self.details = details


class ExternalAPIError(ETLError):
    """
    External API extraction failed.
    """


class UnsupportedFormatError(ETLError):
    """
    Requested dataset format is unsupported.
    """


class LLMConfigurationError(ConfigurationError):
    """
    Required LLM provider configuration is missing.
    """


class DBTArtifactError(
    ETLError
):
    """
    dbt execution artifacts are missing,
    malformed, or inconsistent.
    """