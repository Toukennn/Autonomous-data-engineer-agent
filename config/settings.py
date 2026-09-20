from functools import lru_cache
from pathlib import Path

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    field_validator,
)

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _BaseAppSettings(BaseSettings):
    """
    Common configuration shared by all settings groups.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class DatabaseSettings(_BaseAppSettings):
    """
    PostgreSQL configuration.

    Both the new DB_* names and the project's legacy environment
    variable names are supported during migration.
    """

    host: str = Field(
        validation_alias=AliasChoices(
            "DB_HOST",
            "host",
        )
    )

    user: str = Field(
        validation_alias=AliasChoices(
            "DB_USER",
            "user",
        )
    )

    password: SecretStr = Field(
        validation_alias=AliasChoices(
            "DB_PASSWORD",
            "password",
        )
    )

    database: str = Field(
        validation_alias=AliasChoices(
            "DB_NAME",
            "database",
        )
    )

    port: int = Field(
        default=5432,
        validation_alias=AliasChoices(
            "DB_PORT",
            "port",
        ),
        ge=1,
        le=65535,
    )

    def psycopg_config(self) -> dict:
        return {
            "host": self.host,
            "user": self.user,
            "password": self.password.get_secret_value(),
            "dbname": self.database,
            "port": self.port,
        }


class RuntimeSettings(_BaseAppSettings):
    """
    Runtime limits and safety controls.
    """

    sql_statement_timeout_ms: int = Field(
        default=10_000,
        ge=100,
        le=120_000,
    )

    sql_max_rows: int = Field(
        default=1_000,
        ge=1,
        le=10_000,
    )

    http_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=120,
    )

    api_max_response_bytes: int = Field(
        default=20_000_000,
        ge=1_000,
    )

    data_root_path: Path = Field(
        default=(
            PROJECT_ROOT
            / "data"
        ),
        validation_alias=(
            "DATA_ROOT"
        ),
    )


    @field_validator(
        "data_root_path"
    )
    @classmethod
    def validate_data_root_path(
        cls,
        value: Path,
    ) -> Path:

        path = (
            Path(
                value
            )
            .expanduser()
        )

        if not path.is_absolute():
            raise ValueError(
                "DATA_ROOT must be an "
                "absolute path."
            )

        return path.resolve()


    @property
    def project_root(
        self,
    ) -> Path:
        return PROJECT_ROOT


    @property
    def data_root(
        self,
    ) -> Path:
        return (
            self.data_root_path
        )

    api_max_total_response_bytes: int = Field(
        default=100_000_000,
        ge=1_000,
    )

    api_max_pages: int = Field(
        default=50,
        ge=1,
        le=10_000,
    )

    api_max_records: int = Field(
        default=100_000,
        ge=1,
    )

    api_retry_total: int = Field(
        default=4,
        ge=0,
        le=10,
    )

    api_retry_backoff_seconds: float = Field(
        default=0.5,
        ge=0,
        le=60,
    )

    api_user_agent: str = Field(
        default="autonomous-data-engineer-agent/0.1",
    )

    api_auth_token: SecretStr | None = Field(
        default=None,
        validation_alias="API_AUTH_TOKEN",
    )

    api_auth_header: str = Field(
        default="Authorization",
        validation_alias="API_AUTH_HEADER",
    )

    api_auth_scheme: str = Field(
        default="Bearer",
        validation_alias="API_AUTH_SCHEME",
    )

    api_max_redirects: int = Field(
        default=5,
        ge=0,
        le=20,
    )

    etl_max_tool_calls: int = Field(
        default=8,
        validation_alias="ETL_MAX_TOOL_CALLS",
        ge=1,
        le=50,
    )

    agent_request_timeout_seconds: float = Field(
        default=600.0,
        validation_alias=(
            "AGENT_REQUEST_TIMEOUT_SECONDS"
        ),
        gt=0,
        le=3600,
    )

    dbt_target_schema: str = Field(
        default="dbt_dev",
        validation_alias=(
            "DBT_TARGET_SCHEMA"
        ),
        min_length=1,
        pattern=(
            r"^[a-zA-Z_]"
            r"[a-zA-Z0-9_]*$"
        ),
    )

    dbt_threads: int = Field(
        default=4,
        validation_alias="DBT_THREADS",
        ge=1,
        le=32,
    )

class LLMSettings(_BaseAppSettings):
    """
    LLM provider and model configuration.
    """

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )

    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )

    low_model: str = Field(
        default="gpt-5.6-luna",
        validation_alias="OPENAI_LOW_MODEL",
    )

    medium_model: str = Field(
        default="gpt-5.6-terra",
        validation_alias="OPENAI_MEDIUM_MODEL",
    )

    high_model: str = Field(
        default="gpt-5.6-sol",
        validation_alias="OPENAI_HIGH_MODEL",
    )

    anthropic_model: str = Field(
        default="claude-sonnet-5",
        validation_alias="ANTHROPIC_MODEL",
    )


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()