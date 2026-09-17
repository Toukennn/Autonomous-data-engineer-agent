import json

import pytest

from models.data_quality import (
    AcceptedValuesRule,
    DataQualityContract,
    NotNullRule,
    RangeRule,
    RowCountRule,
    UniqueRule,
)
from utils.data_layers import (
    DataLayer,
)
from utils.dbt_quality import (
    DBTQualityTestManager,
)
from utils.exceptions import (
    DatasetError,
)


def _contract():
    return DataQualityContract(
        name="orders_quality",
        rules=[
            NotNullRule(
                type="not_null",
                column="order_id",
            ),
            UniqueRule(
                type="unique",
                columns=[
                    "order_id",
                    "customer_id",
                ],
            ),
            AcceptedValuesRule(
                type="accepted_values",
                column="status",
                values=[
                    "placed",
                    "shipped",
                    "completed",
                ],
            ),
            RangeRule(
                type="range",
                column="amount",
                min_value=0,
                inclusive_min=True,
            ),
            RowCountRule(
                type="row_count",
                min_rows=1,
                max_rows=10000,
            ),
        ],
    )


def test_dbt_quality_contract_is_generated(
    tmp_path,
):
    manager = DBTQualityTestManager(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        )
    )

    result = (
        manager
        .sync_model_contract(
            layer=DataLayer.SILVER,
            dataset_name="orders",
            model_name="stg_orders",
            columns=[
                "order_id",
                "customer_id",
                "status",
                "amount",
            ],
            contract=_contract(),
        )
    )

    assert (
        result.contract_configured
        is True
    )

    assert result.rule_count == 5

    assert (
        result.properties_file
        is not None
    )

    payload = json.loads(
        result.properties_file
        .read_text(
            encoding="utf-8"
        )
    )

    model = payload[
        "models"
    ][0]

    assert (
        model["name"]
        == "stg_orders"
    )

    assert (
        len(
            model[
                "data_tests"
            ]
        )
        == 2
    )

    columns = {
        column["name"]: column
        for column
        in model["columns"]
    }

    assert (
        "order_id"
        in columns
    )

    assert (
        "status"
        in columns
    )

    assert (
        "amount"
        in columns
    )


def test_dbt_quality_rejects_missing_column(
    tmp_path,
):
    manager = DBTQualityTestManager(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        )
    )

    contract = DataQualityContract(
        name="orders_quality",
        rules=[
            NotNullRule(
                type="not_null",
                column="missing_column",
            ),
        ],
    )

    with pytest.raises(
        DatasetError,
        match=(
            "missing model columns"
        ),
    ):
        manager\
            .sync_model_contract(
                layer=(
                    DataLayer.SILVER
                ),
                dataset_name="orders",
                model_name="stg_orders",
                columns=[
                    "order_id",
                ],
                contract=contract,
            )


def test_no_contract_removes_stale_tests(
    tmp_path,
):
    manager = DBTQualityTestManager(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        )
    )

    configured = (
        manager
        .sync_model_contract(
            layer=DataLayer.SILVER,
            dataset_name="orders",
            model_name="stg_orders",
            columns=[
                "order_id",
                "customer_id",
                "status",
                "amount",
            ],
            contract=_contract(),
        )
    )

    assert (
        configured.properties_file
        is not None
    )

    assert (
        configured.properties_file
        .exists()
    )

    cleared = (
        manager
        .sync_model_contract(
            layer=DataLayer.SILVER,
            dataset_name="orders",
            model_name="stg_orders",
            columns=[
                "order_id",
                "customer_id",
                "status",
                "amount",
            ],
            contract=None,
        )
    )

    assert (
        cleared.contract_configured
        is False
    )

    assert (
        configured.properties_file
        .exists()
        is False
    )


def test_bronze_quality_translation_is_rejected(
    tmp_path,
):
    manager = DBTQualityTestManager(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        )
    )

    with pytest.raises(
        DatasetError,
        match=(
            "Silver and Gold only"
        ),
    ):
        manager\
            .sync_model_contract(
                layer=DataLayer.BRONZE,
                dataset_name="orders",
                model_name="stg_orders",
                columns=[
                    "order_id",
                ],
                contract=None,
            )