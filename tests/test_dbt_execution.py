import os
from types import (
    SimpleNamespace,
)

import pytest

from utils.data_layers import (
    DataLayer,
)
from utils.dbt_execution import (
    DBTExecutor,
)
from utils.exceptions import (
    DBTExecutionError,
    DatasetError,
)


def _db_config():
    return {
        "host": "localhost",
        "port": 5432,
        "user": "tester",
        "password": "secret",
        "dbname": "warehouse",
    }


def _create_model(
    *,
    dbt_root,
    layer,
    model_name,
):
    if layer == DataLayer.SILVER:
        directory = (
            dbt_root
            / "models"
            / "staging"
            / "generated"
        )

    else:
        directory = (
            dbt_root
            / "models"
            / "marts"
            / "generated"
        )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        directory
        / f"{model_name}.sql"
    ).write_text(
        "select 1\n",
        encoding="utf-8",
    )


def test_silver_build_uses_exact_selector(
    tmp_path,
):
    dbt_root = (
        tmp_path
        / "dbt"
    )

    _create_model(
        dbt_root=dbt_root,
        layer=DataLayer.SILVER,
        model_name="stg_orders",
    )

    calls = []

    class FakeRunner:
        def invoke(
            self,
            args,
        ):
            calls.append(
                list(args)
            )

            assert (
                os.environ[
                    "DB_PASSWORD"
                ]
                == "secret"
            )

            return SimpleNamespace(
                success=True,
                exception=None,
            )

    executor = DBTExecutor(
        dbt_project_dir=dbt_root,
        db_config=_db_config(),
        target_schema="dbt_test",
        threads=1,
        runner_factory=FakeRunner,
    )

    result = executor.build_model(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        model_name="stg_orders",
    )

    assert (
        result.selector
        == "stg_orders"
    )

    assert (
        calls[0][0]
        == "build"
    )

    assert (
        calls[0][1:3]
        == [
            "--select",
            "stg_orders",
        ]
    )


def test_gold_build_includes_ancestors(
    tmp_path,
):
    dbt_root = (
        tmp_path
        / "dbt"
    )

    _create_model(
        dbt_root=dbt_root,
        layer=DataLayer.GOLD,
        model_name="mart_orders",
    )

    class FakeRunner:
        def invoke(
            self,
            args,
        ):
            assert (
                args[
                    args.index(
                        "--select"
                    )
                    + 1
                ]
                == "+mart_orders"
            )

            return SimpleNamespace(
                success=True,
                exception=None,
            )

    executor = DBTExecutor(
        dbt_project_dir=dbt_root,
        db_config=_db_config(),
        target_schema="dbt_test",
        threads=1,
        runner_factory=FakeRunner,
    )

    result = executor.build_model(
        layer=DataLayer.GOLD,
        dataset_name="orders",
        model_name="mart_orders",
    )

    assert (
        result.selector
        == "+mart_orders"
    )


def test_dbt_execution_rejects_unsafe_model_name(
    tmp_path,
):
    executor = DBTExecutor(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        ),
        db_config=_db_config(),
        target_schema="dbt_test",
        threads=1,
    )

    with pytest.raises(
        DatasetError,
        match="Invalid dbt model name",
    ):
        executor.build_model(
            layer=DataLayer.GOLD,
            dataset_name="orders",
            model_name=(
                "mart_orders+"
            ),
        )


def test_dbt_execution_requires_model_file(
    tmp_path,
):
    executor = DBTExecutor(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        ),
        db_config=_db_config(),
        target_schema="dbt_test",
        threads=1,
    )

    with pytest.raises(
        DatasetError,
        match=(
            "does not exist"
        ),
    ):
        executor.build_model(
            layer=DataLayer.SILVER,
            dataset_name="orders",
            model_name="stg_orders",
        )


def test_dbt_handled_failure_becomes_execution_error(
    tmp_path,
):
    dbt_root = (
        tmp_path
        / "dbt"
    )

    _create_model(
        dbt_root=dbt_root,
        layer=DataLayer.SILVER,
        model_name="stg_orders",
    )

    class FakeRunner:
        def invoke(
            self,
            args,
        ):
            return SimpleNamespace(
                success=False,
                exception=None,
            )

    executor = DBTExecutor(
        dbt_project_dir=dbt_root,
        db_config=_db_config(),
        target_schema="dbt_test",
        threads=1,
        runner_factory=FakeRunner,
    )

    with pytest.raises(
        DBTExecutionError,
    ) as exc_info:

        executor.build_model(
            layer=DataLayer.SILVER,
            dataset_name="orders",
            model_name="stg_orders",
        )

    assert (
        exc_info.value
        .details[
            "failure_kind"
        ]
        == "build_failed"
    )


def test_dbt_environment_is_restored(
    tmp_path,
    monkeypatch,
):
    dbt_root = (
        tmp_path
        / "dbt"
    )

    _create_model(
        dbt_root=dbt_root,
        layer=DataLayer.SILVER,
        model_name="stg_orders",
    )

    monkeypatch.setenv(
        "DB_PASSWORD",
        "original",
    )

    class FakeRunner:
        def invoke(
            self,
            args,
        ):
            assert (
                os.environ[
                    "DB_PASSWORD"
                ]
                == "secret"
            )

            return SimpleNamespace(
                success=True,
                exception=None,
            )

    executor = DBTExecutor(
        dbt_project_dir=dbt_root,
        db_config=_db_config(),
        target_schema="dbt_test",
        threads=1,
        runner_factory=FakeRunner,
    )

    executor.build_model(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        model_name="stg_orders",
    )

    assert (
        os.environ[
            "DB_PASSWORD"
        ]
        == "original"
    )