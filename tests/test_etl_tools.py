import pandas as pd
import pytest

from utils.api_client import APIExtractionResult
from utils.exceptions import ExternalAPIError

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
    """
    ETLTools should propagate API ingestion failures
    from APIClient.
    """

    def fake_extract_records(
        *args,
        **kwargs,
    ):
        raise ExternalAPIError(
            "API request timed out."
        )

    monkeypatch.setattr(
        isolated_etl_tools.api_client,
        "extract_records",
        fake_extract_records,
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
    """
    ETLTools should convert APIClient records into a dataset
    and save extraction metadata without performing real HTTP.
    """

    fake_result = APIExtractionResult(
        records=[
            {
                "name": "bulbasaur",
                "url": "url1",
            },
            {
                "name": "ivysaur",
                "url": "url2",
            },
        ],
        metadata={
            "source_url": (
                "https://example.com/api"
            ),
            "pages_fetched": 1,
            "records_extracted": 2,
            "bytes_downloaded": 100,
            "pagination_enabled": True,
            "records_path": "results",
            "next_path": "next",
            "authenticated": False,
            "started_at": (
                "2026-09-13T10:00:00+00:00"
            ),
            "completed_at": (
                "2026-09-13T10:00:01+00:00"
            ),
        },
    )

    def fake_extract_records(
        *args,
        **kwargs,
    ):
        return fake_result

    monkeypatch.setattr(
        isolated_etl_tools.api_client,
        "extract_records",
        fake_extract_records,
    )

    result = (
        isolated_etl_tools.extract_load(
            url="https://example.com/api",
            output_folder="data/extract",
            format="csv",
        )
    )

    dataset_file = (
        isolated_etl_tools.data_root
        / "extract"
        / "extracted_data.csv"
    )

    metadata_file = (
        isolated_etl_tools.data_root
        / "extract"
        / "extraction_metadata.json"
    )

    assert dataset_file.exists()

    assert metadata_file.exists()

    dataframe = pd.read_csv(
        dataset_file
    )

    assert len(dataframe) == 2

    assert list(
        dataframe["name"]
    ) == [
        "bulbasaur",
        "ivysaur",
    ]

    assert (
        "Data successfully extracted"
        in result
    )

    assert (
        "Pages fetched: 1"
        in result
    )