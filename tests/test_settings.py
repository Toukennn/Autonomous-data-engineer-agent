import pytest

from pydantic import (
    ValidationError,
)

from config.settings import (
    PROJECT_ROOT,
    DatabaseSettings,
    RuntimeSettings,
)

def test_runtime_default_values():
    settings = RuntimeSettings(
        _env_file=None
    )

    assert (
        settings.sql_statement_timeout_ms
        == 10_000
    )

    assert (
        settings.sql_max_rows
        == 1_000
    )

    assert (
        settings.http_timeout_seconds
        == 30
    )

    assert (
        settings.api_max_response_bytes
        == 20_000_000
    )


def test_database_settings_from_environment(
    monkeypatch,
):
    monkeypatch.setenv(
        "DB_HOST",
        "localhost",
    )

    monkeypatch.setenv(
        "DB_PORT",
        "5432",
    )

    monkeypatch.setenv(
        "DB_USER",
        "test_user",
    )

    monkeypatch.setenv(
        "DB_PASSWORD",
        "test_password",
    )

    monkeypatch.setenv(
        "DB_NAME",
        "test_database",
    )

    settings = DatabaseSettings(
        _env_file=None
    )

    assert settings.host == "localhost"

    assert settings.port == 5432

    assert settings.user == "test_user"

    assert (
        settings.database
        == "test_database"
    )

    assert (
        settings.password
        .get_secret_value()
        == "test_password"
    )


def test_psycopg_config_mapping(
    monkeypatch,
):
    monkeypatch.setenv(
        "DB_HOST",
        "db.example.com",
    )

    monkeypatch.setenv(
        "DB_PORT",
        "5433",
    )

    monkeypatch.setenv(
        "DB_USER",
        "reader",
    )

    monkeypatch.setenv(
        "DB_PASSWORD",
        "secret",
    )

    monkeypatch.setenv(
        "DB_NAME",
        "analytics",
    )

    settings = DatabaseSettings(
        _env_file=None
    )

    config = (
        settings.psycopg_config()
    )

    assert config == {
        "host": "db.example.com",
        "user": "reader",
        "password": "secret",
        "dbname": "analytics",
        "port": 5433,
    }


def test_runtime_default_data_root():
    settings = RuntimeSettings(
        _env_file=None
    )

    assert (
        settings.data_root
        == (
            PROJECT_ROOT
            / "data"
        ).resolve()
    )


def test_runtime_data_root_from_environment(
    monkeypatch,
    tmp_path,
):
    data_root = (
        tmp_path
        / "persistent-data"
    ).resolve()

    monkeypatch.setenv(
        "DATA_ROOT",
        str(
            data_root
        ),
    )

    settings = RuntimeSettings(
        _env_file=None
    )

    assert (
        settings.data_root
        == data_root
    )


def test_runtime_rejects_relative_data_root(
    monkeypatch,
):
    monkeypatch.setenv(
        "DATA_ROOT",
        "relative/data",
    )

    with pytest.raises(
        ValidationError,
        match="DATA_ROOT",
    ):
        RuntimeSettings(
            _env_file=None
        )