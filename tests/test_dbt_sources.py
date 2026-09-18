import json

import pytest

from utils.dbt_sources import (
    DBTSourceRegistry,
)
from utils.exceptions import (
    DatasetError,
)


def _write_sync_metadata(
    *,
    data_root,
    dataset,
    warehouse_schema="bronze",
):
    directory = (
        data_root
        / "bronze"
        / dataset
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata = {
        "metadata_version": 1,
        "dataset": dataset,
        "source_layer": "bronze",
        "source_file": (
            f"bronze/{dataset}/"
            "extracted_data.csv"
        ),
        "source_schema": {
            "id": "number",
        },
        "source_schema_fingerprint": (
            f"fingerprint-{dataset}"
        ),
        "warehouse_schema": (
            warehouse_schema
        ),
        "warehouse_table": dataset,
        "load_mode": "refresh_in_place",
        "rows_loaded": 2,
        "columns_loaded": 1,
        "columns": [
            "id",
        ],
    }

    with (
        directory
        / "warehouse_sync_metadata.json"
    ).open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
        )


def test_dbt_source_registry_is_generated(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    dbt_root = (
        tmp_path
        / "dbt"
    )

    _write_sync_metadata(
        data_root=data_root,
        dataset="orders",
    )

    _write_sync_metadata(
        data_root=data_root,
        dataset="customers",
    )

    registry = DBTSourceRegistry(
        data_root=data_root,
        dbt_project_dir=dbt_root,
    )

    source_file = (
        registry
        .refresh_bronze_sources()
    )

    assert source_file.exists()

    content = (
        source_file.read_text(
            encoding="utf-8"
        )
    )

    assert (
        'name: "bronze"'
        in content
    )

    assert (
        'schema: "bronze"'
        in content
    )

    assert (
        'name: "customers"'
        in content
    )

    assert (
        'name: "orders"'
        in content
    )

    assert (
        content.index(
            'name: "customers"'
        )
        <
        content.index(
            'name: "orders"'
        )
    )


def test_dbt_source_registry_ignores_unsynced_dataset(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    unsynced = (
        data_root
        / "bronze"
        / "orders"
    )

    unsynced.mkdir(
        parents=True,
    )

    registry = DBTSourceRegistry(
        data_root=data_root,
        dbt_project_dir=(
            tmp_path
            / "dbt"
        ),
    )

    source_file = (
        registry
        .refresh_bronze_sources()
    )

    content = (
        source_file.read_text(
            encoding="utf-8"
        )
    )

    assert (
        'name: "orders"'
        not in content
    )


def test_dbt_source_registry_rejects_non_bronze_target(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    _write_sync_metadata(
        data_root=data_root,
        dataset="orders",
        warehouse_schema="public",
    )

    registry = DBTSourceRegistry(
        data_root=data_root,
        dbt_project_dir=(
            tmp_path
            / "dbt"
        ),
    )

    with pytest.raises(
        DatasetError,
        match=(
            "must target the "
            "PostgreSQL Bronze schema"
        ),
    ):
        registry\
            .refresh_bronze_sources()