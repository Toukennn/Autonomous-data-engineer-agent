import json

import pytest

from utils.exceptions import DatasetError
from utils.incremental_state import (
    IncrementalStateStore,
)


@pytest.fixture
def state_store(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    data_root.mkdir()

    return IncrementalStateStore(
        data_root=data_root
    )


def test_missing_state_returns_none(
    state_store,
):
    result = state_store.load(
        "pokemon_api"
    )

    assert result is None


def test_checkpoint_can_be_saved_and_loaded(
    state_store,
):
    state_store.save(
        "pokemon_api",
        cursor_value=100,
        metadata={
            "source": "pokemon",
        },
    )

    result = state_store.load(
        "pokemon_api"
    )

    assert result is not None

    assert (
        result["cursor_value"]
        == 100
    )

    assert (
        result["metadata"]["source"]
        == "pokemon"
    )

    assert (
        result["version"]
        == 1
    )


def test_checkpoint_can_be_updated(
    state_store,
):
    state_store.save(
        "pokemon_api",
        cursor_value=100,
    )

    state_store.save(
        "pokemon_api",
        cursor_value=200,
    )

    result = state_store.load(
        "pokemon_api"
    )

    assert (
        result["cursor_value"]
        == 200
    )


@pytest.mark.parametrize(
    "state_key",
    [
        "../secret",
        "../../etc/passwd",
        "folder/state",
        "folder\\state",
        "",
        "   ",
    ],
)
def test_unsafe_state_keys_are_rejected(
    state_store,
    state_key,
):
    with pytest.raises(
        DatasetError
    ):
        state_store.save(
            state_key,
            cursor_value=1,
        )


def test_corrupted_checkpoint_is_rejected(
    state_store,
):
    path = (
        state_store.state_root
        / "broken.json"
    )

    state_store.state_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        "{invalid-json",
        encoding="utf-8",
    )

    with pytest.raises(
        DatasetError
    ):
        state_store.load(
            "broken"
        )


def test_checkpoint_is_json(
    state_store,
):
    path = state_store.save(
        "orders_api",
        cursor_value="2026-09-13T12:00:00Z",
    )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        payload = json.load(
            file
        )

    assert (
        payload["state_key"]
        == "orders_api"
    )

    assert (
        payload["cursor_value"]
        == "2026-09-13T12:00:00Z"
    )

    assert (
        "updated_at"
        in payload
    )