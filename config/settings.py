from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
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

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def data_root(self) -> Path:
        return (
            PROJECT_ROOT / "data"
        ).resolve()


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