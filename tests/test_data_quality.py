import pandas as pd
import pytest

from models.data_quality import (
    AcceptedValuesRule,
    DataQualityContract,
    NotNullRule,
    RangeRule,
    RowCountRule,
    UniqueRule,
)
from utils.data_quality import (
    evaluate_data_quality,
)
from utils.exceptions import (
    DatasetError,
)


def test_quality_contract_passes():
    dataframe = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "status": [
                "paid",
                "pending",
                "paid",
            ],
            "amount": [
                10.0,
                20.0,
                30.0,
            ],
        }
    )

    contract = DataQualityContract(
        name="orders",
        rules=[
            NotNullRule(
                type="not_null",
                column="id",
            ),
            UniqueRule(
                type="unique",
                columns=["id"],
            ),
            AcceptedValuesRule(
                type="accepted_values",
                column="status",
                values=[
                    "paid",
                    "pending",
                ],
            ),
            RangeRule(
                type="range",
                column="amount",
                min_value=0,
            ),
            RowCountRule(
                type="row_count",
                min_rows=1,
            ),
        ],
    )

    result = evaluate_data_quality(
        dataframe=dataframe,
        contract=contract,
    )

    assert result.passed is True
    assert result.failed_checks == 0
    assert result.total_checks == 5


def test_not_null_rule_detects_nulls():
    dataframe = pd.DataFrame(
        {
            "id": [
                1,
                None,
                3,
            ]
        }
    )

    contract = DataQualityContract(
        name="test",
        rules=[
            NotNullRule(
                type="not_null",
                column="id",
            )
        ],
    )

    result = evaluate_data_quality(
        dataframe=dataframe,
        contract=contract,
    )

    assert result.passed is False

    assert (
        result
        .checks[0]
        .violation_count
        == 1
    )


def test_unique_rule_detects_duplicates():
    dataframe = pd.DataFrame(
        {
            "id": [
                1,
                1,
                2,
            ]
        }
    )

    contract = DataQualityContract(
        name="test",
        rules=[
            UniqueRule(
                type="unique",
                columns=["id"],
            )
        ],
    )

    result = evaluate_data_quality(
        dataframe=dataframe,
        contract=contract,
    )

    assert result.passed is False

    assert (
        result
        .checks[0]
        .violation_count
        == 1
    )


def test_accepted_values_detects_invalid_value():
    dataframe = pd.DataFrame(
        {
            "status": [
                "paid",
                "invalid",
            ]
        }
    )

    contract = DataQualityContract(
        name="test",
        rules=[
            AcceptedValuesRule(
                type="accepted_values",
                column="status",
                values=["paid"],
            )
        ],
    )

    result = evaluate_data_quality(
        dataframe=dataframe,
        contract=contract,
    )

    assert result.passed is False

    assert (
        result
        .checks[0]
        .violation_count
        == 1
    )


def test_range_rule_detects_out_of_range():
    dataframe = pd.DataFrame(
        {
            "amount": [
                10,
                -5,
                20,
            ]
        }
    )

    contract = DataQualityContract(
        name="test",
        rules=[
            RangeRule(
                type="range",
                column="amount",
                min_value=0,
            )
        ],
    )

    result = evaluate_data_quality(
        dataframe=dataframe,
        contract=contract,
    )

    assert result.passed is False

    assert (
        result
        .checks[0]
        .violation_count
        == 1
    )


def test_row_count_rule_detects_failure():
    dataframe = pd.DataFrame(
        {
            "id": [1, 2]
        }
    )

    contract = DataQualityContract(
        name="test",
        rules=[
            RowCountRule(
                type="row_count",
                min_rows=3,
            )
        ],
    )

    result = evaluate_data_quality(
        dataframe=dataframe,
        contract=contract,
    )

    assert result.passed is False

    assert (
        result
        .checks[0]
        .violation_count
        == 1
    )


def test_quality_contract_rejects_missing_column():
    dataframe = pd.DataFrame(
        {
            "id": [1]
        }
    )

    contract = DataQualityContract(
        name="test",
        rules=[
            NotNullRule(
                type="not_null",
                column="missing_column",
            )
        ],
    )

    with pytest.raises(
        DatasetError,
        match="missing columns",
    ):
        evaluate_data_quality(
            dataframe=dataframe,
            contract=contract,
        )