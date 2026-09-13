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

from utils.incremental_state import (
    IncrementalStateStore
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


def test_incremental_checkpoint_advances_after_save(
    isolated_etl_tools,
    monkeypatch,
):
    fake_result = APIExtractionResult(
        records=[
            {
                "id": 101,
                "name": "a",
            },
            {
                "id": 102,
                "name": "b",
            },
        ],
        metadata={
            "source_url": "https://example.com/orders",
            "pages_fetched": 1,
            "records_extracted": 2,
            "bytes_downloaded": 20,
            "pagination_enabled": True,
            "records_path": "results",
            "next_path": "next",
            "authenticated": False,
            "incremental_enabled": True,
            "watermark_param": "after_id",
            "watermark_field": "id",
            "previous_watermark": 100,
            "next_watermark": 102,
        },
    )

    store = IncrementalStateStore(
        isolated_etl_tools.data_root
    )

    store.save(
        "orders",
        cursor_value=100,
        metadata={
            "source_url": "https://example.com/orders",
            "watermark_param": "after_id",
            "watermark_field": "id",
        },
    )

    def fake_extract_records(
        *args,
        **kwargs,
    ):
        assert (
            kwargs["watermark_value"]
            == 100
        )

        return fake_result

    monkeypatch.setattr(
        isolated_etl_tools.api_client,
        "extract_records",
        fake_extract_records,
    )

    isolated_etl_tools.extract_load(
        url="https://example.com/orders",
        output_folder="data/orders",
        format="csv",
        state_key="orders",
        watermark_param="after_id",
        watermark_field="id",
    )

    state = store.load(
        "orders"
    )

    assert (
        state["cursor_value"]
        == 102
    )


def test_checkpoint_does_not_advance_when_dataset_save_fails(
    isolated_etl_tools,
    monkeypatch,
):
    fake_result = APIExtractionResult(
        records=[
            {
                "id": 101
            }
        ],
        metadata={
            "pages_fetched": 1,
            "records_extracted": 1,
            "bytes_downloaded": 10,
            "next_watermark": 101,
        },
    )

    store = IncrementalStateStore(
        isolated_etl_tools.data_root
    )

    store.save(
        "orders",
        cursor_value=100,
    )

    monkeypatch.setattr(
        isolated_etl_tools.api_client,
        "extract_records",
        lambda *args, **kwargs: fake_result,
    )

    def fail_save(
        *args,
        **kwargs,
    ):
        raise DatasetError(
            "simulated disk failure"
        )

    monkeypatch.setattr(
        isolated_etl_tools,
        "_save_dataframe_atomic",
        fail_save,
    )

    with pytest.raises(
        DatasetError,
        match="simulated disk failure",
    ):
        isolated_etl_tools.extract_load(
            url="https://example.com/orders",
            output_folder="data/orders",
            format="csv",
            state_key="orders",
            watermark_param="after_id",
            watermark_field="id",
        )

    state = store.load(
        "orders"
    )

    assert (
        state["cursor_value"]
        == 100
    )


def test_incremental_retry_does_not_duplicate_rows(
    isolated_etl_tools,
):
    existing_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    existing = pd.DataFrame(
        {
            "id": [100, 101],
            "name": ["old", "new"],
        }
    )

    isolated_etl_tools._save_dataframe(
        existing,
        existing_file,
        "csv",
    )

    repeated_batch = pd.DataFrame(
        {
            "id": [101, 102],
            "name": ["new", "latest"],
        }
    )

    result = (
        isolated_etl_tools
        ._merge_incremental_dataframe(
            existing_file=existing_file,
            new_dataframe=repeated_batch,
        )
    )

    assert list(
        result["id"]
    ) == [
        100,
        101,
        102,
    ]


def test_incomplete_incremental_configuration_is_rejected(
    isolated_etl_tools,
):
    with pytest.raises(
        DatasetError,
        match="watermark field",
    ):
        isolated_etl_tools.extract_load(
            url="https://example.com/orders",
            output_folder="data/orders",
            format="csv",
            state_key="orders",
            watermark_param="after_id",
        )


def test_incremental_state_key_cannot_be_reused_for_another_source(
    isolated_etl_tools,
):
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

    with pytest.raises(
        DatasetError,
        match="different source_url",
    ):
        isolated_etl_tools.extract_load(
            url="https://other.example.com/orders",
            output_folder="data/orders",
            format="csv",
            state_key="orders",
            watermark_param="after_id",
            watermark_field="id",
        )


def test_incremental_checkpoint_is_passed_to_api_client(
    isolated_etl_tools,
    monkeypatch,
):
    store = IncrementalStateStore(
        isolated_etl_tools.data_root
    )

    store.save(
        "orders",
        cursor_value=250,
        metadata={
            "source_url": (
                "https://example.com/orders"
            ),
            "watermark_param": "after_id",
            "watermark_field": "id",
        },
    )

    captured = {}

    def fake_extract_records(
        *args,
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return APIExtractionResult(
            records=[],
            metadata={
                "pages_fetched": 1,
                "records_extracted": 0,
                "bytes_downloaded": 10,
                "next_watermark": 250,
            },
        )

    monkeypatch.setattr(
        isolated_etl_tools.api_client,
        "extract_records",
        fake_extract_records,
    )

    isolated_etl_tools.extract_load(
        url="https://example.com/orders",
        output_folder="data/orders",
        format="csv",
        state_key="orders",
        watermark_param="after_id",
        watermark_field="id",
    )

    assert (
        captured["watermark_value"]
        == 250
    )


def test_incremental_schema_change_reports_added_columns(
    isolated_etl_tools,
):
    existing_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    existing = pd.DataFrame(
        {
            "id": [
                1,
                2,
            ],
            "name": [
                "a",
                "b",
            ],
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=existing,
        file_path=existing_file,
        file_format="csv",
    )

    incoming = pd.DataFrame(
        {
            "id": [
                3
            ],
            "name": [
                "c"
            ],
            "category": [
                "new"
            ],
        }
    )

    with pytest.raises(
        DatasetError,
        match="Added columns",
    ):
        (
            isolated_etl_tools
            ._merge_incremental_dataframe(
                existing_file=existing_file,
                new_dataframe=incoming,
            )
        )