import json

import pytest

from models.data_quality import (
    DataQualityContract,
    NotNullRule,
    RangeRule,
)
from utils.data_layers import (
    DataLayer,
)
from utils.data_quality_contracts import (
    DataQualityContractStore,
    quality_contract_fingerprint,
)
from utils.exceptions import (
    DatasetError,
)


def make_contract():
    return DataQualityContract(
        name="orders_quality",
        rules=[
            NotNullRule(
                type="not_null",
                column="order_id",
            ),
            RangeRule(
                type="range",
                column="amount",
                min_value=0,
            ),
        ],
    )


def test_contract_fingerprint_is_stable():
    contract = make_contract()

    first = (
        quality_contract_fingerprint(
            contract
        )
    )

    second = (
        quality_contract_fingerprint(
            contract
        )
    )

    assert first == second


def test_contract_can_be_saved_and_loaded(
    tmp_path,
):
    store = (
        DataQualityContractStore(
            tmp_path / "data"
        )
    )

    contract = make_contract()

    fingerprint = store.save(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        contract=contract,
    )

    loaded = store.load(
        layer=DataLayer.SILVER,
        dataset_name="orders",
    )

    assert loaded == contract

    assert fingerprint == (
        quality_contract_fingerprint(
            contract
        )
    )


def test_missing_contract_returns_none(
    tmp_path,
):
    store = (
        DataQualityContractStore(
            tmp_path / "data"
        )
    )

    result = store.load(
        layer=DataLayer.GOLD,
        dataset_name="missing",
    )

    assert result is None


def test_contract_layers_are_isolated(
    tmp_path,
):
    store = (
        DataQualityContractStore(
            tmp_path / "data"
        )
    )

    contract = make_contract()

    store.save(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        contract=contract,
    )

    assert (
        store.load(
            layer=DataLayer.GOLD,
            dataset_name="orders",
        )
        is None
    )


def test_contract_overwrite_replaces_previous_version(
    tmp_path,
):
    store = (
        DataQualityContractStore(
            tmp_path / "data"
        )
    )

    first = DataQualityContract(
        name="orders_quality",
        contract_version=1,
        rules=[],
    )

    second = DataQualityContract(
        name="orders_quality",
        contract_version=2,
        rules=[
            NotNullRule(
                type="not_null",
                column="order_id",
            )
        ],
    )

    store.save(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        contract=first,
    )

    store.save(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        contract=second,
    )

    loaded = store.load(
        layer=DataLayer.SILVER,
        dataset_name="orders",
    )

    assert loaded == second


def test_corrupted_contract_is_rejected(
    tmp_path,
):
    data_root = (
        tmp_path / "data"
    )

    store = (
        DataQualityContractStore(
            data_root
        )
    )

    contract_file = (
        data_root
        / "_contracts"
        / "silver"
        / "orders.json"
    )

    contract_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    contract_file.write_text(
        "{not valid json",
        encoding="utf-8",
    )

    with pytest.raises(
        DatasetError,
        match="Failed to load",
    ):
        store.load(
            layer=DataLayer.SILVER,
            dataset_name="orders",
        )


def test_tampered_contract_fingerprint_is_rejected(
    tmp_path,
):
    data_root = (
        tmp_path / "data"
    )

    store = (
        DataQualityContractStore(
            data_root
        )
    )

    store.save(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        contract=make_contract(),
    )

    contract_file = (
        data_root
        / "_contracts"
        / "silver"
        / "orders.json"
    )

    payload = json.loads(
        contract_file.read_text(
            encoding="utf-8"
        )
    )

    payload[
        "contract_fingerprint"
    ] = "wrong"

    contract_file.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        DatasetError,
        match="fingerprint",
    ):
        store.load(
            layer=DataLayer.SILVER,
            dataset_name="orders",
        )


def test_dataset_binding_mismatch_is_rejected(
    tmp_path,
):
    data_root = (
        tmp_path / "data"
    )

    store = (
        DataQualityContractStore(
            data_root
        )
    )

    store.save(
        layer=DataLayer.SILVER,
        dataset_name="orders",
        contract=make_contract(),
    )

    contract_file = (
        data_root
        / "_contracts"
        / "silver"
        / "orders.json"
    )

    payload = json.loads(
        contract_file.read_text(
            encoding="utf-8"
        )
    )

    payload["dataset"] = (
        "customers"
    )

    contract_file.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        DatasetError,
        match="dataset binding",
    ):
        store.load(
            layer=DataLayer.SILVER,
            dataset_name="orders",
        )


def test_contract_metadata_is_available(
    tmp_path,
):
    store = (
        DataQualityContractStore(
            tmp_path / "data"
        )
    )

    store.save(
        layer=DataLayer.GOLD,
        dataset_name="revenue",
        contract=make_contract(),
    )

    metadata = store.get_metadata(
        layer=DataLayer.GOLD,
        dataset_name="revenue",
    )

    assert metadata is not None

    assert (
        metadata["layer"]
        == "gold"
    )

    assert (
        metadata["dataset"]
        == "revenue"
    )

    assert (
        metadata["rule_count"]
        == 2
    )