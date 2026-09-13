import json

import pandas as pd
import pytest

from utils.api_client import APIExtractionResult
from utils.exceptions import SchemaEvolutionError
from utils.incremental_state import IncrementalStateStore
from utils.schema_evolution import (
    compare_schemas,
    dataframe_schema,
    dataframe_schema_fingerprint,
    schema_fingerprint,
    schema_transition_fingerprint,
)

def test_identical_schema_has_no_changes():
    existing = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["a", "b"],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": [3, 4],
            "name": ["c", "d"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.has_changes is False

    assert diff.added_columns == ()
    assert diff.removed_columns == ()
    assert diff.type_changes == {}


def test_added_column_is_detected():
    existing = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": [2],
            "name": ["b"],
            "category": ["x"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.has_changes is True

    assert diff.added_columns == (
        "category",
    )

    assert diff.is_additive_only is True

    assert diff.is_breaking is False


def test_removed_column_is_detected():
    existing = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
            "email": ["a@example.com"],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": [2],
            "name": ["b"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.removed_columns == (
        "email",
    )

    assert diff.is_breaking is True


def test_type_change_is_detected():
    existing = pd.DataFrame(
        {
            "id": [1, 2],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": ["one", "two"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.type_changes == {
        "id": (
            "number",
            "string",
        )
    }

    assert diff.is_breaking is True


def test_integer_to_float_is_not_schema_change():
    existing = pd.DataFrame(
        {
            "price": [
                10,
                20,
            ]
        }
    )

    incoming = pd.DataFrame(
        {
            "price": [
                10.5,
                20.5,
            ]
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.has_changes is False


def test_dataframe_schema_uses_logical_types():
    dataframe = pd.DataFrame(
        {
            "id": [
                1,
                2,
            ],
            "price": [
                1.5,
                2.5,
            ],
            "active": [
                True,
                False,
            ],
            "name": [
                "a",
                "b",
            ],
        }
    )

    schema = dataframe_schema(
        dataframe
    )

    assert schema == {
        "id": "number",
        "price": "number",
        "active": "boolean",
        "name": "string",
    }


def test_schema_fingerprint_is_stable():
    first = {
        "id": "number",
        "name": "string",
    }

    second = {
        "id": "number",
        "name": "string",
    }

    assert (
        schema_fingerprint(first)
        == schema_fingerprint(second)
    )


def test_schema_fingerprint_changes_when_schema_changes():
    old_schema = {
        "id": "number",
        "name": "string",
    }

    new_schema = {
        "id": "number",
        "name": "string",
        "category": "string",
    }

    assert (
        schema_fingerprint(
            old_schema
        )
        != schema_fingerprint(
            new_schema
        )
    )


def test_dataframe_values_do_not_change_schema_fingerprint():
    first = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["a", "b"],
        }
    )

    second = pd.DataFrame(
        {
            "id": [100, 200],
            "name": ["x", "y"],
        }
    )

    assert (
        dataframe_schema_fingerprint(
            first
        )
        == dataframe_schema_fingerprint(
            second
        )
    )


def test_schema_transition_fingerprint_is_stable():
    existing = {
        "id": "number",
        "name": "string",
    }

    incoming = {
        "id": "number",
    }

    assert (
        schema_transition_fingerprint(
            existing,
            incoming,
        )
        == schema_transition_fingerprint(
            existing,
            incoming,
        )
    )


def test_breaking_schema_change_is_reported_without_advancing_checkpoint(
    isolated_etl_tools,
    monkeypatch,
):
    existing_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    existing = pd.DataFrame(
        {
            "id": [100],
            "name": ["old"],
        }
    )

    isolated_etl_tools._save_dataframe(
        existing,
        existing_file,
        "csv",
    )

    store = IncrementalStateStore(
        isolated_etl_tools.data_root
    )

    store.save(
        "orders",
        cursor_value=100,
        metadata={
            "source_url": (
                "https://example.com/orders"
            ),
            "watermark_param": "after_id",
            "watermark_field": "id",
        },
    )

    fake_result = APIExtractionResult(
        records=[
            {
                "id": 101
                # "name" disappeared
            }
        ],
        metadata={
            "pages_fetched": 1,
            "records_extracted": 1,
            "bytes_downloaded": 10,
            "next_watermark": 101,
        },
    )

    monkeypatch.setattr(
        isolated_etl_tools.api_client,
        "extract_records",
        lambda *args, **kwargs: (
            fake_result
        ),
    )

    with pytest.raises(
        SchemaEvolutionError,
        match="Rejection report",
    ):
        isolated_etl_tools.extract_load(
            url="https://example.com/orders",
            output_folder="data/orders",
            format="csv",
            state_key="orders",
            watermark_param="after_id",
            watermark_field="id",
        )

    # Checkpoint unchanged.
    state = store.load(
        "orders"
    )

    assert (
        state["cursor_value"]
        == 100
    )

    # Durable dataset unchanged.
    durable = (
        isolated_etl_tools
        ._load_dataframe(
            str(existing_file)
        )
    )

    assert list(
        durable.columns
    ) == [
        "id",
        "name",
    ]

    assert len(
        durable
    ) == 1

    # Rejection persisted.
    rejection_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "schema_change_rejections.json"
    )

    with rejection_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        report = json.load(
            file
        )

    assert len(
        report["events"]
    ) == 1

    assert (
        report["events"][0][
            "removed_columns"
        ]
        == ["name"]
    )

    assert (
        report["events"][0][
            "decision"
        ]
        == "rejected"
    )


def test_same_breaking_schema_change_is_not_reported_twice(
    isolated_etl_tools,
):
    rejection_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "schema_change_rejections.json"
    )

    output_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    details = {
        "existing_schema": {
            "id": "number",
            "name": "string",
        },
        "incoming_schema": {
            "id": "number",
        },
        "added_columns": [],
        "removed_columns": [
            "name"
        ],
        "type_changes": {},
    }

    first = (
        isolated_etl_tools
        ._persist_schema_rejection(
            details=details,
            rejection_file=rejection_file,
            source_url=(
                "https://example.com/orders"
            ),
            output_file=output_file,
            previous_watermark=100,
        )
    )

    second = (
        isolated_etl_tools
        ._persist_schema_rejection(
            details=details,
            rejection_file=rejection_file,
            source_url=(
                "https://example.com/orders"
            ),
            output_file=output_file,
            previous_watermark=100,
        )
    )

    assert first == second

    with rejection_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        report = json.load(
            file
        )

    assert len(
        report["events"]
    ) == 1