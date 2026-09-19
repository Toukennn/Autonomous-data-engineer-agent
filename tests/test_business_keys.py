import json

import pandas as pd
import pytest

from models.warehouse_keys import (
    BusinessKeyContract,
)

from utils.business_keys import (
    BusinessKeyContractStore,
    business_key_fingerprint,
    validate_business_key,
)

from utils.exceptions import (
    BusinessKeyError,
    DatasetError,
)


def test_business_key_fingerprint_is_stable():
    contract = BusinessKeyContract(
        columns=[
            "order_id"
        ]
    )

    assert (
        business_key_fingerprint(
            contract
        )
        == business_key_fingerprint(
            contract
        )
    )


def test_business_key_contract_rejects_duplicate_columns():
    with pytest.raises(
        ValueError,
        match="unique",
    ):
        BusinessKeyContract(
            columns=[
                "order_id",
                "order_id",
            ]
        )


def test_business_key_contract_requires_column():
    with pytest.raises(
        ValueError,
    ):
        BusinessKeyContract(
            columns=[]
        )


def test_valid_single_column_business_key():
    dataframe = pd.DataFrame(
        {
            "order_id": [
                1,
                2,
                3,
            ],
            "amount": [
                10,
                20,
                30,
            ],
        }
    )

    result = (
        validate_business_key(
            dataframe=dataframe,
            contract=(
                BusinessKeyContract(
                    columns=[
                        "order_id"
                    ]
                )
            ),
        )
    )

    assert (
        result[
            "unique_key_count"
        ]
        == 3
    )


def test_valid_composite_business_key():
    dataframe = pd.DataFrame(
        {
            "customer_id": [
                1,
                1,
                2,
            ],
            "event_date": [
                "2026-01-01",
                "2026-01-02",
                "2026-01-01",
            ],
        }
    )

    result = (
        validate_business_key(
            dataframe=dataframe,
            contract=(
                BusinessKeyContract(
                    columns=[
                        "customer_id",
                        "event_date",
                    ]
                )
            ),
        )
    )

    assert (
        result[
            "unique_key_count"
        ]
        == 3
    )


def test_missing_business_key_column_is_rejected():
    dataframe = pd.DataFrame(
        {
            "amount": [
                10
            ]
        }
    )

    with pytest.raises(
        BusinessKeyError,
        match="missing",
    ):
        validate_business_key(
            dataframe=dataframe,
            contract=(
                BusinessKeyContract(
                    columns=[
                        "order_id"
                    ]
                )
            ),
        )


def test_null_business_key_is_rejected():
    dataframe = pd.DataFrame(
        {
            "order_id": [
                1,
                None,
            ]
        }
    )

    with pytest.raises(
        BusinessKeyError,
        match="null",
    ):
        validate_business_key(
            dataframe=dataframe,
            contract=(
                BusinessKeyContract(
                    columns=[
                        "order_id"
                    ]
                )
            ),
        )


def test_duplicate_business_key_is_rejected():
    dataframe = pd.DataFrame(
        {
            "order_id": [
                1,
                1,
            ]
        }
    )

    with pytest.raises(
        BusinessKeyError,
        match="duplicate",
    ):
        validate_business_key(
            dataframe=dataframe,
            contract=(
                BusinessKeyContract(
                    columns=[
                        "order_id"
                    ]
                )
            ),
        )


def test_empty_dataframe_is_valid():
    dataframe = pd.DataFrame(
        {
            "order_id": pd.Series(
                dtype="int64"
            )
        }
    )

    result = (
        validate_business_key(
            dataframe=dataframe,
            contract=(
                BusinessKeyContract(
                    columns=[
                        "order_id"
                    ]
                )
            ),
        )
    )

    assert (
        result[
            "row_count"
        ]
        == 0
    )


def test_business_key_can_be_saved_and_loaded(
    tmp_path,
):
    store = (
        BusinessKeyContractStore(
            tmp_path / "data"
        )
    )

    contract = (
        BusinessKeyContract(
            columns=[
                "order_id"
            ]
        )
    )

    fingerprint = store.save(
        dataset_name="orders",
        contract=contract,
    )

    loaded = store.load(
        dataset_name="orders"
    )

    assert loaded == contract

    assert fingerprint == (
        business_key_fingerprint(
            contract
        )
    )


def test_same_business_key_save_is_idempotent(
    tmp_path,
):
    store = (
        BusinessKeyContractStore(
            tmp_path / "data"
        )
    )

    contract = (
        BusinessKeyContract(
            columns=[
                "order_id"
            ]
        )
    )

    first = store.save(
        dataset_name="orders",
        contract=contract,
    )

    second = store.save(
        dataset_name="orders",
        contract=contract,
    )

    assert first == second


def test_business_key_rebinding_is_rejected(
    tmp_path,
):
    store = (
        BusinessKeyContractStore(
            tmp_path / "data"
        )
    )

    store.save(
        dataset_name="orders",
        contract=(
            BusinessKeyContract(
                columns=[
                    "order_id"
                ]
            )
        ),
    )

    with pytest.raises(
        DatasetError,
        match="cannot be changed",
    ):
        store.save(
            dataset_name="orders",
            contract=(
                BusinessKeyContract(
                    columns=[
                        "customer_id"
                    ]
                )
            ),
        )


def test_tampered_business_key_fingerprint_is_rejected(
    tmp_path,
):
    data_root = (
        tmp_path / "data"
    )

    store = (
        BusinessKeyContractStore(
            data_root
        )
    )

    store.save(
        dataset_name="orders",
        contract=(
            BusinessKeyContract(
                columns=[
                    "order_id"
                ]
            )
        ),
    )

    contract_file = (
        data_root
        / "_warehouse_keys"
        / "orders.json"
    )

    payload = json.loads(
        contract_file.read_text(
            encoding="utf-8"
        )
    )

    payload[
        "contract_fingerprint"
    ] = "tampered"

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
            dataset_name="orders"
        )


def test_business_key_dataset_binding_is_checked(
    tmp_path,
):
    data_root = (
        tmp_path / "data"
    )

    store = (
        BusinessKeyContractStore(
            data_root
        )
    )

    store.save(
        dataset_name="orders",
        contract=(
            BusinessKeyContract(
                columns=[
                    "order_id"
                ]
            )
        ),
    )

    contract_file = (
        data_root
        / "_warehouse_keys"
        / "orders.json"
    )

    payload = json.loads(
        contract_file.read_text(
            encoding="utf-8"
        )
    )

    payload[
        "dataset"
    ] = "customers"

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
            dataset_name="orders"
        )


def test_business_key_error_does_not_expose_row_values():
    dataframe = pd.DataFrame(
        {
            "email": [
                "secret@example.com",
                "secret@example.com",
            ]
        }
    )

    contract = (
        BusinessKeyContract(
            columns=[
                "email"
            ]
        )
    )

    with pytest.raises(
        BusinessKeyError
    ) as exc_info:

        validate_business_key(
            dataframe=dataframe,
            contract=contract,
        )

    details = (
        exc_info.value.details
    )

    assert (
        "secret@example.com"
        not in str(
            details
        )
    )