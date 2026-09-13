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