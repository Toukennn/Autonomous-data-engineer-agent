from uuid import uuid4

import pandas as pd

from config.settings import (
    get_database_settings,
    get_runtime_settings,
)

from models.schema import (
    DBTTransformPlan,
)

from models.warehouse_keys import (
    BusinessKeyContract,
)

from utils.api_client import (
    APIExtractionResult,
)

from utils.data_layers import (
    DataLayer,
    dataset_file_fingerprint,
)

from utils.database import (
    DatabaseUtil,
)

from utils.etl_tools import (
    ETLTools,
)

from utils.incremental_state import (
    IncrementalStateStore,
)

from utils.sql_safety import (
    SQLSafetyValidator,
)


# ============================================================
# PHASE 2J — TWO-RUN INCREMENTAL E2E
# ============================================================


def require(
    condition: bool,
    message: str,
) -> None:
    """
    Fail the E2E immediately when one expected
    invariant is not satisfied.
    """

    if not condition:
        raise RuntimeError(
            "Phase 2J E2E assertion failed: "
            f"{message}"
        )


class TwoRunIncrementalSource:
    """
    Deterministic API boundary for the Phase 2J E2E.

    The first extraction returns:

        1 Alice
        2 Bob

    The second extraction returns:

        1 Alicia    <- changed existing key
        3 Charlie   <- new key

    updated_at acts as the incremental watermark.

    id acts as the immutable business key.
    """

    def __init__(
        self,
    ) -> None:

        self.observed_watermarks = []

    def extract_records(
        self,
        *args,
        **kwargs,
    ) -> APIExtractionResult:

        watermark_value = (
            kwargs.get(
                "watermark_value"
            )
        )

        self.observed_watermarks.append(
            watermark_value
        )

        # ========================================================
        # RUN 1
        # ========================================================

        if watermark_value is None:

            records = [
                {
                    "id": 1,
                    "name": "Alice",
                    "amount": 10,
                    "updated_at": 100,
                },
                {
                    "id": 2,
                    "name": "Bob",
                    "amount": 20,
                    "updated_at": 100,
                },
            ]

            return APIExtractionResult(
                records=records,
                metadata={
                    "pages_fetched": 1,
                    "records_extracted": (
                        len(
                            records
                        )
                    ),
                    "bytes_downloaded": 200,
                    "next_watermark": 100,
                },
            )

        # ========================================================
        # RUN 2
        # ========================================================

        if watermark_value == 100:

            records = [
                {
                    "id": 1,
                    "name": "Alicia",
                    "amount": 15,
                    "updated_at": 200,
                },
                {
                    "id": 3,
                    "name": "Charlie",
                    "amount": 30,
                    "updated_at": 200,
                },
            ]

            return APIExtractionResult(
                records=records,
                metadata={
                    "pages_fetched": 1,
                    "records_extracted": (
                        len(
                            records
                        )
                    ),
                    "bytes_downloaded": 200,
                    "next_watermark": 200,
                },
            )

        raise RuntimeError(
            "Unexpected Phase 2J E2E "
            "watermark value: "
            f"{watermark_value!r}"
        )


def dataframe_rows(
    dataframe: pd.DataFrame,
) -> list[tuple]:
    """
    Normalize one DataFrame into deterministic
    row tuples for E2E assertions.
    """

    ordered = (
        dataframe
        .sort_values(
            "id"
        )
        .reset_index(
            drop=True
        )
    )

    return list(
        ordered[
            [
                "id",
                "name",
                "amount",
                "updated_at",
            ]
        ]
        .itertuples(
            index=False,
            name=None,
        )
    )


def main():
    """
    Prove the complete Phase 2J incremental path:

        controlled API batches
                ↓
        incremental checkpoint
                ↓
        business-key Bronze snapshot
                ↓
        PostgreSQL merge/upsert
                ↓
        dbt Silver view
                ↓
        dbt Gold incremental model
                ↓
        governed read-only SQL
    """

    # Every E2E invocation receives its own
    # logical datasets and PostgreSQL relations.
    #
    # This prevents previous manual E2E runs from
    # contaminating the result.

    suffix = (
        uuid4()
        .hex[
            :8
        ]
    )

    bronze_dataset = (
        f"orders_phase2j_{suffix}"
    )

    silver_dataset = (
        f"orders_phase2j_clean_{suffix}"
    )

    gold_dataset = (
        f"orders_phase2j_gold_{suffix}"
    )

    state_key = (
        f"orders_phase2j_state_{suffix}"
    )

    source_url = (
        "https://example.com/"
        "phase2j/orders"
    )

    print(
        "\n"
        + "=" * 80
    )

    print(
        "PHASE 2J — TWO-RUN "
        "INCREMENTAL E2E"
    )

    print(
        "=" * 80
    )

    print(
        f"Bronze dataset: {bronze_dataset}"
    )

    print(
        f"Silver dataset: {silver_dataset}"
    )

    print(
        f"Gold dataset: {gold_dataset}"
    )

    # ============================================================
    # APPLICATION COMPONENTS
    # ============================================================

    tools = ETLTools()

    source = (
        TwoRunIncrementalSource()
    )

    # Only the external HTTP response is controlled.
    # Everything downstream is the real application.
    tools.api_client = source

    database = (
        DatabaseUtil(
            get_database_settings()
            .psycopg_config()
        )
    )

    runtime = (
        get_runtime_settings()
    )

    # ============================================================
    # BUSINESS KEY CONTRACT
    # ============================================================

    tools\
        .business_key_contract_store\
        .save(
            dataset_name=(
                bronze_dataset
            ),
            contract=(
                BusinessKeyContract(
                    columns=[
                        "id"
                    ]
                )
            ),
        )

    identity_plan = (
        DBTTransformPlan(
            operations=[],
            summary=(
                "Preserve the keyed "
                "dataset grain."
            ),
        )
    )

    # ============================================================
    # RUN 1 — INITIAL STATE
    # ============================================================

    print(
        "\n"
        + "-" * 80
    )

    print(
        "RUN 1"
    )

    print(
        "-" * 80
    )

    extraction_1 = (
        tools.extract_load(
            url=source_url,
            dataset_name=(
                bronze_dataset
            ),
            format="csv",
            paginate=False,
            state_key=state_key,
            watermark_param=(
                "updated_after"
            ),
            watermark_field=(
                "updated_at"
            ),
        )
    )

    print(
        extraction_1
    )

    warehouse_1 = (
        tools
        .load_bronze_to_warehouse(
            dataset_name=(
                bronze_dataset
            )
        )
    )

    print(
        "\n"
        + warehouse_1
    )

    tools.create_dbt_silver_model(
        source_dataset=(
            bronze_dataset
        ),
        target_dataset=(
            silver_dataset
        ),
        plan=identity_plan,
    )

    tools.create_dbt_gold_model(
        source_dataset=(
            silver_dataset
        ),
        target_dataset=(
            gold_dataset
        ),
        plan=identity_plan,
    )

    gold_build_1 = (
        tools.build_dbt_dataset(
            layer=(
                DataLayer.GOLD
            ),
            dataset_name=(
                gold_dataset
            ),
        )
    )

    require(
        gold_build_1.materialization
        == "incremental",
        (
            "Gold must be governed as "
            "incremental on run 1."
        ),
    )

    require(
        gold_build_1.incremental_eligible
        is True,
        (
            "Gold must be incrementally "
            "eligible on run 1."
        ),
    )

    require(
        (
            gold_build_1
            .incremental_key_column_count
        )
        == 1,
        (
            "Gold must carry exactly one "
            "incremental key column."
        ),
    )

    # ============================================================
    # RUN 2 — UPDATE + INSERT
    # ============================================================

    print(
        "\n"
        + "-" * 80
    )

    print(
        "RUN 2"
    )

    print(
        "-" * 80
    )

    extraction_2 = (
        tools.extract_load(
            url=source_url,
            dataset_name=(
                bronze_dataset
            ),
            format="csv",
            paginate=False,
            state_key=state_key,
            watermark_param=(
                "updated_after"
            ),
            watermark_field=(
                "updated_at"
            ),
        )
    )

    print(
        extraction_2
    )

    warehouse_2 = (
        tools
        .load_bronze_to_warehouse(
            dataset_name=(
                bronze_dataset
            )
        )
    )

    print(
        "\n"
        + warehouse_2
    )

    silver_build_2 = (
        tools.build_dbt_dataset(
            layer=(
                DataLayer.SILVER
            ),
            dataset_name=(
                silver_dataset
            ),
        )
    )

    gold_build_2 = (
        tools.build_dbt_dataset(
            layer=(
                DataLayer.GOLD
            ),
            dataset_name=(
                gold_dataset
            ),
        )
    )

    require(
        silver_build_2.materialization
        == "view",
        (
            "Silver must remain a view "
            "on run 2."
        ),
    )

    require(
        gold_build_2.materialization
        == "incremental",
        (
            "Gold must remain incremental "
            "on run 2."
        ),
    )

    require(
        gold_build_2.incremental_eligible
        is True,
        (
            "Gold must remain incrementally "
            "eligible on run 2."
        ),
    )

    # ============================================================
    # EXPECTED FINAL STATE
    # ============================================================

    expected_rows = [
        (
            1,
            "Alicia",
            15,
            200,
        ),
        (
            2,
            "Bob",
            20,
            100,
        ),
        (
            3,
            "Charlie",
            30,
            200,
        ),
    ]

    # ============================================================
    # VERIFY API CHECKPOINT FLOW
    # ============================================================

    require(
        source.observed_watermarks
        == [
            None,
            100,
        ],
        (
            "Second extraction did not receive "
            "the checkpoint from run 1."
        ),
    )

    state_store = (
        IncrementalStateStore(
            tools.data_root
        )
    )

    checkpoint = (
        state_store.load(
            state_key
        )
    )

    require(
        checkpoint is not None,
        "Final checkpoint is missing.",
    )

    require(
        checkpoint[
            "cursor_value"
        ]
        == 200,
        (
            "Final checkpoint did not advance "
            "to watermark 200."
        ),
    )

    # ============================================================
    # VERIFY DURABLE BRONZE
    # ============================================================

    bronze_file = (
        tools.data_root
        / "bronze"
        / bronze_dataset
        / "extracted_data.csv"
    )

    require(
        bronze_file.exists(),
        "Durable Bronze file is missing.",
    )

    bronze_dataframe = (
        pd.read_csv(
            bronze_file
        )
    )

    require(
        dataframe_rows(
            bronze_dataframe
        )
        == expected_rows,
        (
            "Durable Bronze does not contain "
            "the expected final keyed snapshot."
        ),
    )

    require(
        (
            bronze_dataframe[
                "id"
            ]
            .duplicated()
            .sum()
        )
        == 0,
        (
            "Durable Bronze contains duplicate "
            "business keys."
        ),
    )

    current_fingerprint = (
        dataset_file_fingerprint(
            bronze_file
        )
    )

    require(
        checkpoint[
            "metadata"
        ][
            "dataset_fingerprint"
        ]
        == current_fingerprint,
        (
            "Checkpoint is not bound to the "
            "final durable Bronze snapshot."
        ),
    )

    # ============================================================
    # VERIFY POSTGRESQL BRONZE
    # ============================================================

    bronze_query = (
        "SELECT "
        "id, name, amount, updated_at "
        f"FROM bronze.{bronze_dataset} "
        "ORDER BY id;"
    )

    bronze_result = (
        database
        .execute_read_only_result(
            bronze_query
        )
    )

    require(
        list(
            bronze_result.rows
        )
        == expected_rows,
        (
            "PostgreSQL Bronze does not match "
            "the final durable Bronze snapshot."
        ),
    )

    # ============================================================
    # VERIFY GOLD MODEL GOVERNANCE
    # ============================================================

    gold_metadata = (
        tools
        .dbt_model_metadata_store
        .load(
            layer=(
                DataLayer.GOLD
            ),
            dataset_name=(
                gold_dataset
            ),
        )
    )

    require(
        gold_metadata is not None,
        "Gold model metadata is missing.",
    )

    require(
        gold_metadata.materialization
        == "incremental",
        (
            "Persisted Gold materialization "
            "is not incremental."
        ),
    )

    require(
        gold_metadata.incremental_eligible
        is True,
        (
            "Persisted Gold metadata does not "
            "mark the model incremental-safe."
        ),
    )

    require(
        gold_metadata.incremental_key_columns
        == (
            "id",
        ),
        (
            "Gold did not preserve the expected "
            "business-key lineage."
        ),
    )

    # ============================================================
    # GOVERNED ANALYTICS CATALOG
    # ============================================================

    catalog = (
        database.analytics_catalog(
            target_schema=(
                runtime
                .dbt_target_schema
            )
        )
    )

    gold_schema = (
        f"{runtime.dbt_target_schema}"
        "_gold"
    )

    gold_model_name = (
        tools
        .dbt_gold_model_manager
        .model_name_for_dataset(
            gold_dataset
        )
    )

    governed_query = (
        "SELECT "
        "id, name, amount, updated_at "
        f"FROM {gold_schema}."
        f"{gold_model_name} "
        "ORDER BY id;"
    )

    validation = (
        SQLSafetyValidator.validate(
            governed_query,
            analytics_catalog=(
                catalog
            ),
        )
    )

    require(
        validation.is_safe,
        (
            "Final Gold query was rejected by "
            "the governed SQL safety boundary: "
            f"{validation.reason}"
        ),
    )

    gold_result = (
        database
        .execute_read_only_result(
            governed_query
        )
    )

    require(
        list(
            gold_result.rows
        )
        == expected_rows,
        (
            "Governed Gold query does not "
            "return the expected final state."
        ),
    )

    # ============================================================
    # VERIFY INCREMENTAL LINEAGE
    # ============================================================

    events = (
        tools.lineage_store
        .get_events()
    )

    warehouse_events = [
        event
        for event
        in events
        if (
            event.get(
                "operation"
            )
            == "warehouse_sync"
            and (
                event.get(
                    "target",
                    {},
                )
                .get(
                    "table"
                )
                == bronze_dataset
            )
        )
    ]

    require(
        len(
            warehouse_events
        )
        == 2,
        (
            "Expected exactly two warehouse "
            "synchronization lineage events."
        ),
    )

    require(
        all(
            event[
                "metadata"
            ][
                "load_mode"
            ]
            == "merge_upsert"
            for event
            in warehouse_events
        ),
        (
            "Both warehouse runs must use "
            "merge_upsert."
        ),
    )

    require(
        warehouse_events[
            -1
        ][
            "metadata"
        ][
            "checkpoint_bound"
        ]
        is True,
        (
            "Final warehouse synchronization "
            "is not checkpoint-bound."
        ),
    )

    gold_events = [
        event
        for event
        in events
        if (
            event.get(
                "operation"
            )
            == "dbt_build"
            and (
                event.get(
                    "target",
                    {},
                )
                .get(
                    "layer"
                )
                == "gold"
            )
            and (
                event.get(
                    "target",
                    {},
                )
                .get(
                    "dataset"
                )
                == gold_dataset
            )
        )
    ]

    require(
        len(
            gold_events
        )
        == 2,
        (
            "Expected exactly two Gold dbt "
            "lineage events."
        ),
    )

    require(
        all(
            event[
                "metadata"
            ][
                "materialization"
            ]
            == "incremental"
            for event
            in gold_events
        ),
        (
            "Both Gold builds must be recorded "
            "as incremental."
        ),
    )

    require(
        all(
            event[
                "metadata"
            ][
                "incremental"
            ][
                "eligible"
            ]
            is True
            for event
            in gold_events
        ),
        (
            "Gold lineage must remain "
            "incremental-safe."
        ),
    )

    require(
        all(
            event[
                "metadata"
            ][
                "incremental"
            ][
                "key_column_count"
            ]
            == 1
            for event
            in gold_events
        ),
        (
            "Gold lineage must report exactly "
            "one incremental key column."
        ),
    )

    # ============================================================
    # SUCCESS
    # ============================================================

    print(
        "\n"
        + "=" * 80
    )

    print(
        "PHASE 2J E2E PASSED"
    )

    print(
        "=" * 80
    )

    print(
        "\nFinal Bronze / PostgreSQL / Gold state:"
    )

    for row in expected_rows:
        print(
            row
        )

    print(
        "\nFinal checkpoint: 200"
    )

    print(
        "Warehouse mode: merge_upsert"
    )

    print(
        "Gold materialization: incremental"
    )

    print(
        "Governed SQL validation: PASS"
    )

    print(
        "\nGold relation:"
    )

    print(
        f"{gold_schema}."
        f"{gold_model_name}"
    )

    print(
        "\nPhase 2J incremental pipeline "
        "is working end-to-end."
    )


if __name__ == "__main__":
    main()