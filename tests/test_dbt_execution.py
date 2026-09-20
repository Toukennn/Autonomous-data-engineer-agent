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

from utils.dbt_artifacts import (
    DBTBuildArtifactSummary,
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

class FakeArtifactReader:
    """
    Deterministic artifact reader used by
    successful dbt executor unit tests.

    FakeRunner does not create real dbt
    target artifacts, so these tests inject
    the validated artifact boundary directly.
    """

    def parse_build(
        self,
        *,
        model_name: str,
    ) -> DBTBuildArtifactSummary:

        if model_name.startswith(
            "stg_"
        ):
            relation_schema = (
                "dbt_test_silver"
            )

        else:
            relation_schema = (
                "dbt_test_gold"
            )

        unique_id = (
            "model."
            "autonomous_data_engineer."
            f"{model_name}"
        )

        return (
            DBTBuildArtifactSummary(
                invocation_id=(
                    "12345678-1234-5678-"
                    "1234-567812345678"
                ),
                command="build",
                target_model_unique_id=(
                    unique_id
                ),
                target_model_name=(
                    model_name
                ),
                target_status=(
                    "success"
                ),
                target_execution_time_seconds=(
                    0.2
                ),
                relation_schema=(
                    relation_schema
                ),
                relation_name=(
                    model_name
                ),
                dependency_unique_ids=(),
                executed_model_unique_ids=(
                    (
                        unique_id,
                    )
                ),
                tests=(),
                elapsed_time_seconds=(
                    0.3
                ),
            )
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
        artifact_reader=(
            FakeArtifactReader()
        ),
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
        artifact_reader=(
            FakeArtifactReader()
        ),
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


def test_dbt_unhandled_failure_records_safe_exception_type(
    tmp_path,
):
    dbt_root = tmp_path / "dbt"
    _create_model(
        dbt_root=dbt_root,
        layer=DataLayer.SILVER,
        model_name="stg_orders",
    )

    class FakeRunner:
        def invoke(self, args):
            return SimpleNamespace(
                success=False,
                exception=RuntimeError(
                    "DB_PASSWORD=should-not-leak"
                ),
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
        exc_info.value.details["failure_kind"]
        == "unhandled_error"
    )
    assert (
        exc_info.value.details["exception_type"]
        == "RuntimeError"
    )
    assert (
        "should-not-leak"
        not in str(exc_info.value.details)
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
        artifact_reader=(
            FakeArtifactReader()
        ),
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


def test_dbt_artifact_is_attached_to_build_result(
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
                success=True,
                exception=None,
            )

    executor = DBTExecutor(
        dbt_project_dir=(
            dbt_root
        ),
        db_config=(
            _db_config()
        ),
        target_schema=(
            "dbt_test"
        ),
        threads=1,
        runner_factory=(
            FakeRunner
        ),
        artifact_reader=(
            FakeArtifactReader()
        ),
    )

    result = (
        executor.build_model(
            layer=DataLayer.SILVER,
            dataset_name="orders",
            model_name="stg_orders",
        )
    )

    assert (
        result.artifact
        .target_model_name
        == "stg_orders"
    )

    assert (
        result.artifact
        .target_status
        == "success"
    )

    assert (
        result.artifact
        .relation_schema
        == "dbt_test_silver"
    )