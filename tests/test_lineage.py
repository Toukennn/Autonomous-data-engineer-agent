import pytest

from utils.data_layers import DataLayer
from utils.exceptions import DatasetError
from utils.lineage import (
    LineageStore,
    payload_fingerprint,
)


def test_payload_fingerprint_is_stable():
    first = payload_fingerprint(
        {
            "b": 2,
            "a": 1,
        }
    )

    second = payload_fingerprint(
        {
            "a": 1,
            "b": 2,
        }
    )

    assert first == second


def test_lineage_store_records_extraction(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    store = LineageStore(
        data_root
    )

    event_id = (
        store.record_extraction(
            source_url=(
                "https://example.com/orders"
            ),
            target_dataset="orders",
            target_schema_fingerprint="abc123",
            output_format="csv",
        )
    )

    assert event_id

    events = (
        store.get_events()
    )

    assert len(events) == 1

    event = events[0]

    assert (
        event["operation"]
        == "extract"
    )

    assert (
        event["source"]["type"]
        == "api"
    )

    assert (
        event["target"]["layer"]
        == "bronze"
    )

    assert (
        event["target"]["dataset"]
        == "orders"
    )


def test_lineage_store_records_transition(
    tmp_path,
):
    store = LineageStore(
        tmp_path
        / "data"
    )

    store.record_transition(
        operation="transform",
        source_layer=DataLayer.BRONZE,
        source_dataset="orders",
        source_schema_fingerprint="source123",
        target_layer=DataLayer.SILVER,
        target_dataset="clean_orders",
        target_schema_fingerprint="target456",
        plan_payload={
            "operations": [],
            "summary": "Test plan",
        },
        output_format="csv",
    )

    events = (
        store.get_events()
    )

    assert len(events) == 1

    event = events[0]

    assert (
        event["source"]["layer"]
        == "bronze"
    )

    assert (
        event["target"]["layer"]
        == "silver"
    )

    assert (
        event["target"]["dataset"]
        == "clean_orders"
    )

    assert (
        "plan_fingerprint"
        in event["metadata"]
    )


def test_lineage_events_are_appended(
    tmp_path,
):
    store = LineageStore(
        tmp_path
        / "data"
    )

    store.record_extraction(
        source_url="https://example.com/orders",
        target_dataset="orders",
        target_schema_fingerprint="abc",
        output_format="csv",
    )

    store.record_transition(
        operation="transform",
        source_layer=DataLayer.BRONZE,
        source_dataset="orders",
        source_schema_fingerprint="abc",
        target_layer=DataLayer.SILVER,
        target_dataset="orders",
        target_schema_fingerprint="def",
        plan_payload={
            "operations": [],
            "summary": "",
        },
        output_format="csv",
    )

    assert len(
        store.get_events()
    ) == 2


def test_corrupted_lineage_is_rejected(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    lineage_directory = (
        data_root
        / "_lineage"
    )

    lineage_directory.mkdir(
        parents=True
    )

    lineage_file = (
        lineage_directory
        / "lineage.json"
    )

    lineage_file.write_text(
        "{not-valid-json",
        encoding="utf-8",
    )

    store = LineageStore(
        data_root
    )

    with pytest.raises(
        DatasetError,
        match="Failed to load lineage",
    ):
        store.get_events()



