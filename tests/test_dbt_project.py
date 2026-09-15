from pathlib import Path

from dbt.cli.main import (
    dbtRunner,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

DBT_PROJECT_DIR = (
    PROJECT_ROOT
    / "dbt"
)


def test_dbt_project_parses(
    monkeypatch,
):
    """
    Verify that the committed dbt project and
    PostgreSQL profile can be parsed without
    making a real database connection.
    """

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
        "test",
    )

    monkeypatch.setenv(
        "DB_PASSWORD",
        "test",
    )

    monkeypatch.setenv(
        "DB_NAME",
        "test",
    )

    monkeypatch.setenv(
        "DBT_TARGET_SCHEMA",
        "dbt_test",
    )

    monkeypatch.setenv(
        "DBT_THREADS",
        "1",
    )

    result = (
        dbtRunner()
        .invoke(
            [
                "parse",
                "--project-dir",
                str(
                    DBT_PROJECT_DIR
                ),
                "--profiles-dir",
                str(
                    DBT_PROJECT_DIR
                ),
            ]
        )
    )

    assert (
        result.success
        is True
    ), (
        "dbt project failed to parse: "
        f"{result.exception}"
    )



def test_dbt_profile_uses_environment_credentials():
    """
    Database credentials must be referenced through
    environment variables rather than committed
    directly into the repository.
    """

    profile = (
        DBT_PROJECT_DIR
        / "profiles.yml"
    ).read_text(
        encoding="utf-8"
    )

    required_variables = (
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
    )

    for variable in (
        required_variables
    ):
        assert (
            f"env_var('{variable}'"
            in profile
        )