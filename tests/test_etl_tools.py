import json

import pandas as pd
import pytest

from models.schema import (
    AggregationSpec,
    DropDuplicatesOperation,
    FilterRowsOperation,
    GroupByAggregateOperation,
    RenameColumnsOperation,
    SelectColumnsOperation,
    SortValuesOperation,
    StringTransformOperation,
    TransformPlan,
)

from utils.api_client import APIExtractionResult
from utils.exceptions import (
    DatasetError,
    ExternalAPIError,
    UnsupportedFormatError,
)

from utils.incremental_state import (
    IncrementalStateStore
)


def _bronze_dataset_file(
    isolated_etl_tools,
    dataset_name: str = "orders",
):
    return (
        isolated_etl_tools.data_root
        / "bronze"
        / dataset_name
        / "extracted_data.csv"
    )


def _save_bronze_dataset(
    isolated_etl_tools,
    dataframe: pd.DataFrame,
    dataset_name: str = "orders",
):
    output_file = _bronze_dataset_file(
        isolated_etl_tools,
        dataset_name,
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=output_file,
        file_format="csv",
    )

    return output_file


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
            dataset_name="orders",
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
            dataset_name="orders",
            format="csv",
        )
    )

    dataset_file = (
        isolated_etl_tools.data_root
        / "bronze"
        / "orders"
        / "extracted_data.csv"
    )

    metadata_file = (
        isolated_etl_tools.data_root
        / "bronze"
        / "orders"
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

    existing = pd.DataFrame(
        {
            "id": [100],
            "name": ["existing"],
        }
    )

    _save_bronze_dataset(
        isolated_etl_tools,
        existing,
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
        dataset_name="orders",
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

    existing = pd.DataFrame(
        {
            "id": [100],
        }
    )

    _save_bronze_dataset(
        isolated_etl_tools,
        existing,
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
            dataset_name="orders",
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
            dataset_name="orders",
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
            dataset_name="orders",
            format="csv",
            state_key="orders",
            watermark_param="after_id",
            watermark_field="id",
        )


def test_incremental_checkpoint_is_passed_to_api_client(
    isolated_etl_tools,
    monkeypatch,
):
    existing = pd.DataFrame(
        {
            "id": [250],
        }
    )

    _save_bronze_dataset(
        isolated_etl_tools,
        existing,
    )

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
        dataset_name="orders",
        format="csv",
        state_key="orders",
        watermark_param="after_id",
        watermark_field="id",
    )

    assert (
        captured["watermark_value"]
        == 250
    )


def test_incremental_additive_schema_change_is_accepted(
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

    result = (
        isolated_etl_tools
        ._merge_incremental_dataframe(
            existing_file=existing_file,
            new_dataframe=incoming,
        )
    )

    assert list(
        result.columns
    ) == [
        "id",
        "name",
        "category",
    ]

    assert len(
        result
    ) == 3

    assert pd.isna(
        result.loc[
            0,
            "category",
        ]
    )

    assert pd.isna(
        result.loc[
            1,
            "category",
        ]
    )

    assert (
        result.loc[
            2,
            "category",
        ]
        == "new"
    )


def test_removed_column_is_still_rejected(
    isolated_etl_tools,
):
    existing_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    existing = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
            "email": [
                "a@example.com"
            ],
        }
    )

    isolated_etl_tools._save_dataframe(
        existing,
        existing_file,
        "csv",
    )

    incoming = pd.DataFrame(
        {
            "id": [2],
            "name": ["b"],
        }
    )

    with pytest.raises(
        DatasetError,
        match="Removed columns",
    ):
        (
            isolated_etl_tools
            ._merge_incremental_dataframe(
                existing_file=existing_file,
                new_dataframe=incoming,
            )
        )


def test_type_change_is_still_rejected(
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
            ]
        }
    )

    isolated_etl_tools._save_dataframe(
        existing,
        existing_file,
        "csv",
    )

    incoming = pd.DataFrame(
        {
            "id": [
                "three",
                "four",
            ]
        }
    )

    with pytest.raises(
        DatasetError,
        match="Type changes",
    ):
        (
            isolated_etl_tools
            ._merge_incremental_dataframe(
                existing_file=existing_file,
                new_dataframe=incoming,
            )
        )


def test_additive_schema_retry_remains_idempotent(
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
        existing,
        existing_file,
        "csv",
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

    first_merge = (
        isolated_etl_tools
        ._merge_incremental_dataframe(
            existing_file=existing_file,
            new_dataframe=incoming,
        )
    )

    isolated_etl_tools._save_dataframe(
        first_merge,
        existing_file,
        "csv",
    )

    second_merge = (
        isolated_etl_tools
        ._merge_incremental_dataframe(
            existing_file=existing_file,
            new_dataframe=incoming,
        )
    )

    assert len(
        second_merge
    ) == 3

    assert (
        list(
            second_merge["id"]
        )
        == [
            1,
            2,
            3,
        ]
    )


def test_schema_history_creates_initial_version(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
        }
    )

    history_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "schema_history.json"
    )

    output_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    fingerprint, version = (
        isolated_etl_tools
        ._persist_schema_history(
            dataframe=dataframe,
            schema_history_file=(
                history_file
            ),
            source_url=(
                "https://example.com/orders"
            ),
            output_file=output_file,
        )
    )

    assert version == 1

    with history_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        history = json.load(
            file
        )

    assert len(
        history["entries"]
    ) == 1

    assert (
        history["latest_fingerprint"]
        == fingerprint
    )

    assert (
        history["entries"][0][
            "schema"
        ]
        == {
            "id": "number",
            "name": "string",
        }
    )



def test_same_schema_does_not_create_new_version(
    isolated_etl_tools,
):
    dataframe = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
        }
    )

    history_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "schema_history.json"
    )

    output_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    first = (
        isolated_etl_tools
        ._persist_schema_history(
            dataframe=dataframe,
            schema_history_file=history_file,
            source_url=(
                "https://example.com/orders"
            ),
            output_file=output_file,
        )
    )

    second = (
        isolated_etl_tools
        ._persist_schema_history(
            dataframe=dataframe,
            schema_history_file=history_file,
            source_url=(
                "https://example.com/orders"
            ),
            output_file=output_file,
        )
    )

    assert first == second

    with history_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        history = json.load(
            file
        )

    assert len(
        history["entries"]
    ) == 1



def test_additive_schema_creates_new_history_version(
    isolated_etl_tools,
):
    history_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "schema_history.json"
    )

    output_file = (
        isolated_etl_tools.data_root
        / "orders"
        / "extracted_data.csv"
    )

    first_dataframe = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
        }
    )

    second_dataframe = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
            "category": ["x"],
        }
    )

    isolated_etl_tools._persist_schema_history(
        dataframe=first_dataframe,
        schema_history_file=history_file,
        source_url=(
            "https://example.com/orders"
        ),
        output_file=output_file,
    )

    _, version = (
        isolated_etl_tools
        ._persist_schema_history(
            dataframe=second_dataframe,
            schema_history_file=history_file,
            source_url=(
                "https://example.com/orders"
            ),
            output_file=output_file,
        )
    )

    assert version == 2

    with history_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        history = json.load(
            file
        )

    assert len(
        history["entries"]
    ) == 2

    assert (
        history["entries"][1][
            "schema"
        ]
        == {
            "id": "number",
            "name": "string",
            "category": "string",
        }
    )



def test_checkpoint_does_not_advance_when_schema_history_save_fails(
    isolated_etl_tools,
    monkeypatch,
):
    existing = pd.DataFrame(
        {
            "id": [100],
            "name": ["old"],
        }
    )

    _save_bronze_dataset(
        isolated_etl_tools,
        existing,
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
            "watermark_param": (
                "after_id"
            ),
            "watermark_field": "id",
        },
    )

    fake_result = APIExtractionResult(
        records=[
            {
                "id": 101,
                "name": "new",
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

    original_save_json = (
        isolated_etl_tools
        ._save_json_atomic
    )

    def fail_schema_history(
        payload,
        file_path,
    ):
        if (
            file_path.name
            == "schema_history.json"
        ):
            raise DatasetError(
                "simulated schema history failure"
            )

        return original_save_json(
            payload,
            file_path,
        )

    monkeypatch.setattr(
        isolated_etl_tools,
        "_save_json_atomic",
        fail_schema_history,
    )

    with pytest.raises(
        DatasetError,
        match="schema history failure",
    ):
        isolated_etl_tools.extract_load(
            url="https://example.com/orders",
            dataset_name="orders",
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


def test_api_extraction_is_saved_in_bronze_layer(
    isolated_etl_tools,
    monkeypatch,
):
    fake_result = APIExtractionResult(
        records=[
            {
                "id": 1,
                "name": "a",
            }
        ],
        metadata={
            "pages_fetched": 1,
            "records_extracted": 1,
            "bytes_downloaded": 10,
            "next_watermark": None,
        },
    )

    monkeypatch.setattr(
        isolated_etl_tools.api_client,
        "extract_records",
        lambda *args, **kwargs: (
            fake_result
        ),
    )

    isolated_etl_tools.extract_load(
        url="https://example.com/orders",
        dataset_name="orders",
        format="csv",
    )

    expected_file = _bronze_dataset_file(
        isolated_etl_tools,
    )

    assert expected_file.exists()



def test_checkpoint_with_missing_bronze_dataset_is_rejected(
    isolated_etl_tools,
):
    store = IncrementalStateStore(
        isolated_etl_tools.data_root
    )

    expected_file = _bronze_dataset_file(
        isolated_etl_tools,
    )

    store.save(
        "orders",
        cursor_value=500,
        metadata={
            "source_url": (
                "https://example.com/orders"
            ),
            "watermark_param": (
                "after_id"
            ),
            "watermark_field": "id",
            "dataset_name": "orders",
            "data_layer": "bronze",
            "output_file": str(
                expected_file
            ),
        },
    )

    with pytest.raises(
        DatasetError,
        match="Bronze dataset is missing",
    ):
        isolated_etl_tools.extract_load(
            url="https://example.com/orders",
            dataset_name="orders",
            format="csv",
            state_key="orders",
            watermark_param="after_id",
            watermark_field="id",
        )



def test_bronze_to_silver_transformation(
    isolated_etl_tools,
):
    bronze_file = (
        isolated_etl_tools.data_root
        / "bronze"
        / "orders"
        / "extracted_data.csv"
    )

    bronze = pd.DataFrame(
        {
            "id": [
                1,
                2,
            ],
            "name": [
                " ALICE ",
                " BOB ",
            ],
            "unused": [
                "x",
                "y",
            ],
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=bronze,
        file_path=bronze_file,
        file_format="csv",
    )

    plan = TransformPlan(
        operations=[
            StringTransformOperation(
                type="string_transform",
                columns=["name"],
                action="strip",
            ),
            SelectColumnsOperation(
                type="select_columns",
                columns=[
                    "id",
                    "name",
                ],
            ),
        ],
        summary=(
            "Clean names and retain "
            "Silver columns."
        ),
    )

    result = (
        isolated_etl_tools
        .transform_bronze_to_silver(
            source_dataset_name=(
                "orders"
            ),
            plan=plan,
            output_format="csv",
        )
    )

    silver_file = (
        isolated_etl_tools.data_root
        / "silver"
        / "orders"
        / "transformed_data.csv"
    )

    metadata_file = (
        isolated_etl_tools.data_root
        / "silver"
        / "orders"
        / "transformation_metadata.json"
    )

    assert silver_file.exists()
    assert metadata_file.exists()

    silver = pd.read_csv(
        silver_file
    )

    assert list(
        silver.columns
    ) == [
        "id",
        "name",
    ]

    assert list(
        silver["name"]
    ) == [
        "ALICE",
        "BOB",
    ]

    assert (
        "Bronze-to-Silver"
        in result
    )


def test_silver_transformation_does_not_modify_bronze(
    isolated_etl_tools,
):
    bronze_file = (
        isolated_etl_tools.data_root
        / "bronze"
        / "orders"
        / "extracted_data.csv"
    )

    original = pd.DataFrame(
        {
            "id": [1],
            "name": [" ORIGINAL "],
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=original,
        file_path=bronze_file,
        file_format="csv",
    )

    plan = TransformPlan(
        operations=[
            StringTransformOperation(
                type="string_transform",
                columns=["name"],
                action="strip",
            )
        ]
    )

    (
        isolated_etl_tools
        .transform_bronze_to_silver(
            source_dataset_name="orders",
            plan=plan,
        )
    )

    bronze_after = pd.read_csv(
        bronze_file
    )

    assert (
        bronze_after.iloc[0]["name"]
        == " ORIGINAL "
    )


def test_silver_transformation_requires_bronze_dataset(
    isolated_etl_tools,
):
    plan = TransformPlan(
        operations=[]
    )

    with pytest.raises(
        DatasetError,
        match="Bronze dataset does not exist",
    ):
        (
            isolated_etl_tools
            .transform_bronze_to_silver(
                source_dataset_name="orders",
                plan=plan,
            )
        )



def test_multiple_bronze_formats_are_rejected(
    isolated_etl_tools,
):
    bronze_directory = (
        isolated_etl_tools.data_root
        / "bronze"
        / "orders"
    )

    dataframe = pd.DataFrame(
        {
            "id": [1]
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=(
            bronze_directory
            / "extracted_data.csv"
        ),
        file_format="csv",
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=(
            bronze_directory
            / "extracted_data.json"
        ),
        file_format="json",
    )

    plan = TransformPlan(
        operations=[]
    )

    with pytest.raises(
        DatasetError,
        match="Multiple physical files",
    ):
        (
            isolated_etl_tools
            .transform_bronze_to_silver(
                source_dataset_name="orders",
                plan=plan,
            )
        )


def test_silver_metadata_records_layers_and_plan(
    isolated_etl_tools,
):
    bronze_file = (
        isolated_etl_tools.data_root
        / "bronze"
        / "orders"
        / "extracted_data.csv"
    )

    dataframe = pd.DataFrame(
        {
            "id": [1],
            "name": ["Alice"],
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=bronze_file,
        file_format="csv",
    )

    plan = TransformPlan(
        operations=[
            SelectColumnsOperation(
                type="select_columns",
                columns=["id"],
            )
        ],
        summary="Keep identifiers only.",
    )

    (
        isolated_etl_tools
        .transform_bronze_to_silver(
            source_dataset_name="orders",
            target_dataset_name=(
                "clean_orders"
            ),
            plan=plan,
        )
    )

    metadata_file = (
        isolated_etl_tools.data_root
        / "silver"
        / "clean_orders"
        / "transformation_metadata.json"
    )

    with metadata_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(
            file
        )

    assert (
        metadata["source_layer"]
        == "bronze"
    )

    assert (
        metadata["target_layer"]
        == "silver"
    )

    assert (
        metadata["source_dataset"]
        == "orders"
    )

    assert (
        metadata["target_dataset"]
        == "clean_orders"
    )

    assert (
        metadata[
            "transformation_plan"
        ]["summary"]
        == "Keep identifiers only."
    )



def test_silver_to_gold_aggregation(
    isolated_etl_tools,
):
    silver_file = (
        isolated_etl_tools.data_root
        / "silver"
        / "orders"
        / "transformed_data.csv"
    )

    silver = pd.DataFrame(
        {
            "order_id": [
                1,
                2,
                3,
                4,
            ],
            "country": [
                "IT",
                "IT",
                "FR",
                "FR",
            ],
            "revenue": [
                100.0,
                150.0,
                80.0,
                120.0,
            ],
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=silver,
        file_path=silver_file,
        file_format="csv",
    )

    plan = TransformPlan(
        operations=[
            GroupByAggregateOperation(
                type="groupby_aggregate",
                group_by=[
                    "country"
                ],
                aggregations=[
                    AggregationSpec(
                        column="revenue",
                        function="sum",
                        alias=(
                            "total_revenue"
                        ),
                    ),
                    AggregationSpec(
                        column="order_id",
                        function="count",
                        alias=(
                            "order_count"
                        ),
                    ),
                ],
            )
        ],
        summary=(
            "Aggregate revenue and orders "
            "by country."
        ),
    )

    result = (
        isolated_etl_tools
        .transform_silver_to_gold(
            source_dataset_name="orders",
            target_dataset_name=(
                "sales_by_country"
            ),
            plan=plan,
            output_format="csv",
        )
    )

    gold_file = (
        isolated_etl_tools.data_root
        / "gold"
        / "sales_by_country"
        / "curated_data.csv"
    )

    assert gold_file.exists()

    gold = pd.read_csv(
        gold_file
    )

    assert list(
        gold.columns
    ) == [
        "country",
        "total_revenue",
        "order_count",
    ]

    italy = (
        gold.loc[
            gold["country"] == "IT"
        ]
        .iloc[0]
    )

    france = (
        gold.loc[
            gold["country"] == "FR"
        ]
        .iloc[0]
    )

    assert (
        italy["total_revenue"]
        == 250.0
    )

    assert (
        italy["order_count"]
        == 2
    )

    assert (
        france["total_revenue"]
        == 200.0
    )

    assert (
        france["order_count"]
        == 2
    )

    assert (
        "Silver-to-Gold"
        in result
    )


def test_gold_curation_does_not_modify_silver(
    isolated_etl_tools,
):
    silver_file = (
        isolated_etl_tools.data_root
        / "silver"
        / "orders"
        / "transformed_data.csv"
    )

    original = pd.DataFrame(
        {
            "id": [
                1,
                2,
            ],
            "amount": [
                100,
                200,
            ],
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=original,
        file_path=silver_file,
        file_format="csv",
    )

    plan = TransformPlan(
        operations=[
            SelectColumnsOperation(
                type="select_columns",
                columns=["id"],
            )
        ]
    )

    (
        isolated_etl_tools
        .transform_silver_to_gold(
            source_dataset_name="orders",
            plan=plan,
        )
    )

    silver_after = pd.read_csv(
        silver_file
    )

    assert list(
        silver_after.columns
    ) == [
        "id",
        "amount",
    ]

    assert list(
        silver_after["amount"]
    ) == [
        100,
        200,
    ]



def test_gold_curation_requires_silver_dataset(
    isolated_etl_tools,
):
    plan = TransformPlan(
        operations=[]
    )

    with pytest.raises(
        DatasetError,
        match="Silver dataset does not exist",
    ):
        (
            isolated_etl_tools
            .transform_silver_to_gold(
                source_dataset_name="orders",
                plan=plan,
            )
        )



def test_multiple_silver_formats_are_rejected(
    isolated_etl_tools,
):
    silver_directory = (
        isolated_etl_tools.data_root
        / "silver"
        / "orders"
    )

    dataframe = pd.DataFrame(
        {
            "id": [1]
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=(
            silver_directory
            / "transformed_data.csv"
        ),
        file_format="csv",
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=(
            silver_directory
            / "transformed_data.json"
        ),
        file_format="json",
    )

    plan = TransformPlan(
        operations=[]
    )

    with pytest.raises(
        DatasetError,
        match="Multiple physical files",
    ):
        (
            isolated_etl_tools
            .transform_silver_to_gold(
                source_dataset_name="orders",
                plan=plan,
            )
        )



def test_gold_metadata_records_layers_and_plan(
    isolated_etl_tools,
):
    silver_file = (
        isolated_etl_tools.data_root
        / "silver"
        / "orders"
        / "transformed_data.csv"
    )

    dataframe = pd.DataFrame(
        {
            "id": [1],
            "amount": [100],
        }
    )

    isolated_etl_tools._save_dataframe(
        dataframe=dataframe,
        file_path=silver_file,
        file_format="csv",
    )

    plan = TransformPlan(
        operations=[
            SelectColumnsOperation(
                type="select_columns",
                columns=[
                    "amount"
                ],
            )
        ],
        summary=(
            "Create analytics-ready "
            "amount dataset."
        ),
    )

    (
        isolated_etl_tools
        .transform_silver_to_gold(
            source_dataset_name="orders",
            target_dataset_name=(
                "order_amounts"
            ),
            plan=plan,
        )
    )

    metadata_file = (
        isolated_etl_tools.data_root
        / "gold"
        / "order_amounts"
        / "curation_metadata.json"
    )

    with metadata_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(
            file
        )

    assert (
        metadata["source_layer"]
        == "silver"
    )

    assert (
        metadata["target_layer"]
        == "gold"
    )

    assert (
        metadata["source_dataset"]
        == "orders"
    )

    assert (
        metadata["target_dataset"]
        == "order_amounts"
    )

    assert (
        metadata[
            "curation_plan"
        ]["summary"]
        == (
            "Create analytics-ready "
            "amount dataset."
        )
    )



