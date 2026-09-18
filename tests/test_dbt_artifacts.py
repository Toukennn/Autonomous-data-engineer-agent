import json

import pytest

from utils.dbt_artifacts import (
    DBTArtifactReader,
)
from utils.exceptions import (
    DBTArtifactError,
)


INVOCATION_ID = (
    "12345678-1234-5678-1234-567812345678"
)


def _write_artifacts(
    tmp_path,
    *,
    command="build",
    schema="dbt_dev_silver",
):
    dbt_root = (
        tmp_path
        / "dbt"
    )

    target = (
        dbt_root
        / "target"
    )

    target.mkdir(
        parents=True
    )

    model_unique_id = (
        "model.autonomous_data_engineer.stg_orders"
    )

    test_unique_id = (
        "test.autonomous_data_engineer."
        "qc_silver_not_null_orders"
    )

    manifest = {
        "metadata": {},
        "nodes": {
            model_unique_id: {
                "unique_id": (
                    model_unique_id
                ),
                "resource_type": (
                    "model"
                ),
                "name": (
                    "stg_orders"
                ),
                "alias": (
                    "stg_orders"
                ),
                "schema": (
                    schema
                ),
                "depends_on": {
                    "nodes": [
                        (
                            "source."
                            "autonomous_data_engineer."
                            "bronze.orders"
                        )
                    ]
                },
            },
            test_unique_id: {
                "unique_id": (
                    test_unique_id
                ),
                "resource_type": (
                    "test"
                ),
                "name": (
                    "qc_silver_not_null_orders"
                ),
                "depends_on": {
                    "nodes": [
                        model_unique_id
                    ]
                },
            },
        },
    }

    run_results = {
        "metadata": {
            "invocation_id": (
                INVOCATION_ID
            )
        },
        "args": {
            "which": command,
        },
        "elapsed_time": 0.5,
        "results": [
            {
                "unique_id": (
                    model_unique_id
                ),
                "status": "success",
                "execution_time": 0.3,

                # Intentionally present.
                # The artifact reader must ignore it.
                "compiled_code": (
                    "select secret_sql"
                ),
            },
            {
                "unique_id": (
                    test_unique_id
                ),
                "status": "pass",
                "execution_time": 0.1,
                "failures": 0,
                "compiled_code": (
                    "select more_secret_sql"
                ),
            },
        ],
    }

    (
        target
        / "manifest.json"
    ).write_text(
        json.dumps(
            manifest
        ),
        encoding="utf-8",
    )

    (
        target
        / "run_results.json"
    ).write_text(
        json.dumps(
            run_results
        ),
        encoding="utf-8",
    )

    return dbt_root


def test_dbt_build_artifacts_are_parsed_safely(
    tmp_path,
):
    dbt_root = (
        _write_artifacts(
            tmp_path
        )
    )

    result = (
        DBTArtifactReader(
            dbt_project_dir=(
                dbt_root
            )
        )
        .parse_build(
            model_name=(
                "stg_orders"
            )
        )
    )

    assert (
        result.invocation_id
        == INVOCATION_ID
    )

    assert (
        result.command
        == "build"
    )

    assert (
        result.target_status
        == "success"
    )

    assert (
        result.relation_schema
        == "dbt_dev_silver"
    )

    assert (
        result.relation_name
        == "stg_orders"
    )

    assert len(
        result.tests
    ) == 1

    assert (
        result.tests[0]
        .status
        == "pass"
    )

    assert (
        result.tests[0]
        .directly_tests_target
        is True
    )

    assert not hasattr(
        result,
        "compiled_code",
    )


def test_dbt_artifact_reader_rejects_non_build(
    tmp_path,
):
    dbt_root = (
        _write_artifacts(
            tmp_path,
            command="run",
        )
    )

    with pytest.raises(
        DBTArtifactError,
        match=(
            "Expected dbt build artifacts"
        ),
    ):
        DBTArtifactReader(
            dbt_project_dir=(
                dbt_root
            )
        ).parse_build(
            model_name=(
                "stg_orders"
            )
        )


def test_dbt_artifact_reader_requires_target_model(
    tmp_path,
):
    dbt_root = (
        _write_artifacts(
            tmp_path
        )
    )

    with pytest.raises(
        DBTArtifactError,
        match=(
            "exactly one target model"
        ),
    ):
        DBTArtifactReader(
            dbt_project_dir=(
                dbt_root
            )
        ).parse_build(
            model_name=(
                "stg_missing"
            )
        )


def test_dbt_artifact_reader_rejects_unsafe_schema(
    tmp_path,
):
    dbt_root = (
        _write_artifacts(
            tmp_path,
            schema=(
                'dbt_dev"; DROP TABLE x; --'
            ),
        )
    )

    with pytest.raises(
        DBTArtifactError,
        match=(
            "Unsafe dbt relation identifier"
        ),
    ):
        DBTArtifactReader(
            dbt_project_dir=(
                dbt_root
            )
        ).parse_build(
            model_name=(
                "stg_orders"
            )
        )