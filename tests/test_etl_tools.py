import pandas as pd
import pytest
import requests

from models.schema import (
    DropDuplicatesOperation,
    FilterRowsOperation,
    RenameColumnsOperation,
    SelectColumnsOperation,
    SortValuesOperation,
    StringTransformOperation,
    TransformPlan,
)
from utils.exceptions import (
    DatasetError,
    ExternalAPIError,
    UnsupportedFormatError,
)


def test_filter_and_select_columns(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "name": [
                "bulbasaur",
                "ivysaur",
                "venusaur",
            ],
            "weight": [
                69,
                130,
                1000,
            ],
            "type": [
                "grass",
                "grass",
                "grass",
            ],
        }
    )

    plan = TransformPlan(
        operations=[
            FilterRowsOperation(
                type="filter_rows",
                column="name",
                operator="eq",
                value="bulbasaur",
            ),
            SelectColumnsOperation(
                type="select_columns",
                columns=[
                    "name",
                    "weight",
                ],
            ),
        ],
        summary=(
            "Keep Bulbasaur and selected columns."
        ),
    )

    result = (
        isolated_etl_tools
        .apply_transform_plan(
            dataframe,
            plan,
        )
    )

    assert len(result) == 1

    assert list(
        result.columns
    ) == [
        "name",
        "weight",
    ]

    assert (
        result.iloc[0]["name"]
        == "bulbasaur"
    )

    assert (
        result.iloc[0]["weight"]
        == 69
    )


def test_drop_duplicates(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "name": [
                "pikachu",
                "pikachu",
                "raichu",
            ]
        }
    )

    plan = TransformPlan(
        operations=[
            DropDuplicatesOperation(
                type="drop_duplicates",
                subset=["name"],
            )
        ]
    )

    result = (
        isolated_etl_tools
        .apply_transform_plan(
            dataframe,
            plan,
        )
    )

    assert len(result) == 2


def test_rename_columns(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "old_name": [
                "value"
            ]
        }
    )

    plan = TransformPlan(
        operations=[
            RenameColumnsOperation(
                type="rename_columns",
                mapping={
                    "old_name": "new_name"
                },
            )
        ]
    )

    result = (
        isolated_etl_tools
        .apply_transform_plan(
            dataframe,
            plan,
        )
    )

    assert "new_name" in result.columns

    assert (
        "old_name"
        not in result.columns
    )


def test_sort_values(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "weight": [
                100,
                10,
                50,
            ]
        }
    )

    plan = TransformPlan(
        operations=[
            SortValuesOperation(
                type="sort_values",
                columns=["weight"],
                ascending=True,
            )
        ]
    )

    result = (
        isolated_etl_tools
        .apply_transform_plan(
            dataframe,
            plan,
        )
    )

    assert list(
        result["weight"]
    ) == [
        10,
        50,
        100,
    ]


def test_string_lowercase(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "name": [
                "PIKACHU",
                "CHARIZARD",
            ]
        }
    )

    plan = TransformPlan(
        operations=[
            StringTransformOperation(
                type="string_transform",
                columns=["name"],
                action="lower",
            )
        ]
    )

    result = (
        isolated_etl_tools
        .apply_transform_plan(
            dataframe,
            plan,
        )
    )

    assert list(
        result["name"]
    ) == [
        "pikachu",
        "charizard",
    ]


def test_missing_column_is_rejected(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "name": [
                "pikachu"
            ]
        }
    )

    plan = TransformPlan(
        operations=[
            SelectColumnsOperation(
                type="select_columns",
                columns=[
                    "does_not_exist"
                ],
            )
        ]
    )

    with pytest.raises(
        DatasetError
    ):
        isolated_etl_tools.apply_transform_plan(
            dataframe,
            plan,
        )


def test_access_outside_data_directory_is_rejected(
    isolated_etl_tools,
):
    with pytest.raises(
        DatasetError
    ):
        isolated_etl_tools._resolve_data_path(
            ".env"
        )


def test_unsupported_format_is_rejected(
    isolated_etl_tools,
):
    with pytest.raises(
        UnsupportedFormatError
    ):
        isolated_etl_tools._validate_format(
            "xlsx"
        )


def test_csv_save_and_load(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "name": [
                "pikachu",
                "raichu",
            ]
        }
    )

    output_file = (
        isolated_etl_tools
        .data_root
        / "test.csv"
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=output_file,
        file_format="csv",
    )

    result = (
        isolated_etl_tools
        ._load_dataframe(
            "data/test.csv"
        )
    )

    assert len(result) == 2

    assert list(
        result["name"]
    ) == [
        "pikachu",
        "raichu",
    ]


def test_api_timeout_becomes_external_api_error(
    isolated_etl_tools,
    monkeypatch,
):
    def fake_get(
        *args,
        **kwargs,
    ):
        raise requests.Timeout()

    monkeypatch.setattr(
        "utils.etl_tools.requests.get",
        fake_get,
    )

    with pytest.raises(
        ExternalAPIError
    ):
        isolated_etl_tools.extract_load(
            url="https://example.com/api",
            output_folder="data/extract",
            format="csv",
        )


def test_api_extraction_without_real_network(
    isolated_etl_tools,
    monkeypatch,
):
    class FakeResponse:

        headers = {
            "Content-Length": "100"
        }

        content = b"fake-response"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "name": "bulbasaur",
                        "url": "url1",
                    },
                    {
                        "name": "ivysaur",
                        "url": "url2",
                    },
                ]
            }

    def fake_get(
        *args,
        **kwargs,
    ):
        return FakeResponse()

    monkeypatch.setattr(
        "utils.etl_tools.requests.get",
        fake_get,
    )

    result = (
        isolated_etl_tools.extract_load(
            url="https://example.com/api",
            output_folder="data/extract",
            format="csv",
        )
    )

    output_file = (
        isolated_etl_tools
        .data_root
        / "extract"
        / "extracted_data.csv"
    )

    assert output_file.exists()

    assert (
        "Data successfully extracted"
        in result
    )