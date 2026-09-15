import pytest

from utils.execution_observability import (
    ExecutionRunStore,
)

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)

import agents.etl_analyst as etl_module

from utils.exceptions import (
    DataQualityError,
)

@pytest.fixture(
    autouse=True
)
def isolated_execution_store(
    tmp_path,
    monkeypatch,
):
    store = (
        ExecutionRunStore(
            tmp_path
            / "data"
        )
    )

    monkeypatch.setattr(
        etl_module,
        "execution_store",
        store,
    )

    return store

class FakeLLM:
    """
    Deterministic replacement for the ETL orchestration LLM.
    """

    def __init__(
        self,
        responses,
    ):
        self.responses = iter(
            responses
        )

    def invoke(
        self,
        conversation,
    ):
        return next(
            self.responses
        )


class FakeTool:
    """
    Deterministic replacement for a LangChain tool.
    """

    def __init__(
        self,
        name,
        calls,
        result,
    ):
        self.name = name
        self.calls = calls
        self.result = result

    def invoke(
        self,
        args,
    ):
        self.calls.append(
            {
                "name": self.name,
                "args": args,
            }
        )

        return self.result


def make_tool_call(
    *,
    name,
    call_id,
    args,
):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def test_etl_agent_orchestrates_medallion_in_order(
    monkeypatch,
):
    calls = []

    fake_llm = FakeLLM(
        [
            # ====================================================
            # API -> BRONZE
            # ====================================================
            make_tool_call(
                name="extract_load_tool",
                call_id="call-extract",
                args={
                    "url": (
                        "https://example.com/orders"
                    ),
                    "dataset_name": "orders",
                    "format": "csv",
                    "paginate": False,
                },
            ),

            # ====================================================
            # BRONZE -> SILVER
            # ====================================================
            make_tool_call(
                name="bronze_to_silver_tool",
                call_id="call-silver",
                args={
                    "source_dataset_name": (
                        "orders"
                    ),
                    "target_dataset_name": (
                        "clean_orders"
                    ),
                    "user_question": (
                        "Clean and standardize "
                        "the orders dataset."
                    ),
                    "output_format": "csv",
                },
            ),

            # ====================================================
            # SILVER -> GOLD
            # ====================================================
            make_tool_call(
                name="silver_to_gold_tool",
                call_id="call-gold",
                args={
                    "source_dataset_name": (
                        "clean_orders"
                    ),
                    "target_dataset_name": (
                        "sales_summary"
                    ),
                    "user_question": (
                        "Create the analytics-ready "
                        "sales summary."
                    ),
                    "output_format": "csv",
                },
            ),

            # ====================================================
            # FINAL AGENT RESPONSE
            # ====================================================
            AIMessage(
                content=(
                    "The Bronze, Silver, and Gold "
                    "pipeline completed successfully."
                )
            ),
        ]
    )

    monkeypatch.setattr(
        etl_module,
        "etl_llm_with_tools",
        fake_llm,
    )

    fake_tools = {
        "extract_load_tool": FakeTool(
            name="extract_load_tool",
            calls=calls,
            result="Bronze completed.",
        ),
        "bronze_to_silver_tool": FakeTool(
            name="bronze_to_silver_tool",
            calls=calls,
            result="Silver completed.",
        ),
        "silver_to_gold_tool": FakeTool(
            name="silver_to_gold_tool",
            calls=calls,
            result="Gold completed.",
        ),
    }

    monkeypatch.setattr(
        etl_module,
        "tools_by_name",
        fake_tools,
    )

    result = (
        etl_module.etl_analyst.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Extract orders, clean them, "
                            "and build a sales summary."
                        )
                    )
                ]
            }
        )
    )

    # ============================================================
    # EXACT PIPELINE ORDER
    # ============================================================

    assert [
        call["name"]
        for call in calls
    ] == [
        "extract_load_tool",
        "bronze_to_silver_tool",
        "silver_to_gold_tool",
    ]

    # ============================================================
    # DATASET DEPENDENCIES
    # ============================================================

    assert (
        calls[0]["args"]["dataset_name"]
        == "orders"
    )

    assert (
        calls[1]["args"][
            "source_dataset_name"
        ]
        == "orders"
    )

    assert (
        calls[1]["args"][
            "target_dataset_name"
        ]
        == "clean_orders"
    )

    assert (
        calls[2]["args"][
            "source_dataset_name"
        ]
        == "clean_orders"
    )

    assert (
        calls[2]["args"][
            "target_dataset_name"
        ]
        == "sales_summary"
    )

    assert (
        result["messages"][-1].content
        == (
            "The Bronze, Silver, and Gold "
            "pipeline completed successfully."
        )
    )



def test_etl_agent_exposes_only_safe_tools():
    assert set(
        etl_module.tools_by_name
    ) == {
        "extract_load_tool",
        "bronze_to_silver_tool",
        "silver_to_gold_tool",
        "configure_quality_contract_tool",
    }

    assert (
        "transform_load_tool"
        not in etl_module.tools_by_name
    )



class FailingTool:
    def __init__(
        self,
        name,
        calls,
    ):
        self.name = name
        self.calls = calls

    def invoke(
        self,
        args,
    ):
        self.calls.append(
            {
                "name": self.name,
                "args": args,
            }
        )

        raise RuntimeError(
            "simulated failure"
        )



def test_etl_agent_stops_after_tool_failure(
    monkeypatch,
    isolated_execution_store,
):
    calls = []

    fake_llm = FakeLLM(
        [
            make_tool_call(
                name="extract_load_tool",
                call_id="extract",
                args={
                    "url": (
                        "https://example.com/orders"
                    ),
                    "dataset_name": "orders",
                },
            ),

            # This response must NEVER be consumed.
            make_tool_call(
                name="bronze_to_silver_tool",
                call_id="silver",
                args={
                    "source_dataset_name": (
                        "orders"
                    ),
                    "user_question": (
                        "Clean orders."
                    ),
                },
            ),
        ]
    )

    monkeypatch.setattr(
        etl_module,
        "etl_llm_with_tools",
        fake_llm,
    )

    monkeypatch.setattr(
        etl_module,
        "tools_by_name",
        {
            "extract_load_tool": (
                FailingTool(
                    "extract_load_tool",
                    calls,
                )
            ),
        },
    )

    result = (
        etl_module.etl_analyst.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Extract and clean orders."
                        )
                    )
                ]
            }
        )
    )

    assert [
        call["name"]
        for call in calls
    ] == [
        "extract_load_tool"
    ]

    assert (
        "stopped safely"
        in result[
            "messages"
        ][-1].content.lower()
    )

    run_id = result["run_id"]

    execution = (
        isolated_execution_store
        .get_run(
            run_id
        )
    )

    assert (
        execution["status"]
        == "failed"
    )

    assert (
        execution["completed_at"]
        is not None
    )

    assert (
        execution["failure_reason"]
        is not None
    )

    assert len(
        execution["events"]
    ) == 1

    assert (
        execution["events"][0]["status"]
        == "failed"
    )


def test_etl_agent_stops_at_tool_call_limit(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        etl_module,
        "ETL_MAX_TOOL_CALLS",
        2,
    )

    fake_llm = FakeLLM(
        [
            make_tool_call(
                name="extract_load_tool",
                call_id="call-1",
                args={
                    "url": "https://example.com/a",
                    "dataset_name": "a",
                },
            ),
            make_tool_call(
                name="extract_load_tool",
                call_id="call-2",
                args={
                    "url": "https://example.com/b",
                    "dataset_name": "b",
                },
            ),
            make_tool_call(
                name="extract_load_tool",
                call_id="call-3",
                args={
                    "url": "https://example.com/c",
                    "dataset_name": "c",
                },
            ),
        ]
    )

    monkeypatch.setattr(
        etl_module,
        "etl_llm_with_tools",
        fake_llm,
    )

    fake_tool = FakeTool(
        name="extract_load_tool",
        calls=calls,
        result="ok",
    )

    monkeypatch.setattr(
        etl_module,
        "tools_by_name",
        {
            "extract_load_tool": (
                fake_tool
            ),
        },
    )

    result = (
        etl_module.etl_analyst.invoke(
            {
                "messages": [
                    HumanMessage(
                        content="Loop forever."
                    )
                ]
            }
        )
    )

    assert len(calls) == 2

    assert (
        "limit exceeded"
        in result[
            "messages"
        ][-1].content.lower()
    )



def test_etl_agent_rejects_multiple_tool_calls_per_turn(
    monkeypatch,
):
    calls = []

    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "extract_load_tool",
                "args": {
                    "url": (
                        "https://example.com/orders"
                    ),
                    "dataset_name": "orders",
                },
                "id": "extract",
                "type": "tool_call",
            },
            {
                "name": "bronze_to_silver_tool",
                "args": {
                    "source_dataset_name": (
                        "orders"
                    ),
                    "user_question": (
                        "Clean orders."
                    ),
                },
                "id": "silver",
                "type": "tool_call",
            },
        ],
    )

    monkeypatch.setattr(
        etl_module,
        "etl_llm_with_tools",
        FakeLLM([response]),
    )

    monkeypatch.setattr(
        etl_module,
        "tools_by_name",
        {
            "extract_load_tool": FakeTool(
                "extract_load_tool",
                calls,
                "ok",
            ),
            "bronze_to_silver_tool": FakeTool(
                "bronze_to_silver_tool",
                calls,
                "ok",
            ),
        },
    )

    result = (
        etl_module.etl_analyst.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Extract and clean orders."
                        )
                    )
                ]
            }
        )
    )

    assert calls == []

    assert (
        "exactly one tool call"
        in result[
            "messages"
        ][-1].content.lower()
    )


def test_etl_agent_records_structured_execution(
    monkeypatch,
    isolated_execution_store,
):
    calls = []

    fake_llm = FakeLLM(
        [
            make_tool_call(
                name="extract_load_tool",
                call_id="extract",
                args={
                    "url": (
                        "https://example.com/orders"
                    ),
                    "dataset_name": (
                        "orders"
                    ),
                },
            ),
            AIMessage(
                content="Completed."
            ),
        ]
    )

    monkeypatch.setattr(
        etl_module,
        "etl_llm_with_tools",
        fake_llm,
    )

    monkeypatch.setattr(
        etl_module,
        "tools_by_name",
        {
            "extract_load_tool": FakeTool(
                "extract_load_tool",
                calls,
                "Bronze completed.",
            )
        },
    )

    result = (
        etl_module.etl_analyst.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Extract orders."
                        )
                    )
                ]
            }
        )
    )

    run_id = result["run_id"]

    execution = (
        isolated_execution_store
        .get_run(
            run_id
        )
    )

    assert (
        execution["status"]
        == "completed"
    )

    assert len(
        execution["events"]
    ) == 1

    event = (
        execution["events"][0]
    )

    assert (
        event["name"]
        == "extract_load_tool"
    )

    assert (
        event["status"]
        == "success"
    )

    assert (
        event["duration_ms"]
        >= 0
    )

    assert (
        event["metadata"][
            "dataset_name"
        ]
        == "orders"
    )

    # Raw API URLs are deliberately
    # not persisted in execution logs.
    assert (
        "https://example.com/orders"
        not in str(execution)
    )



def test_etl_agent_configures_quality_before_silver(
    monkeypatch,
):
    calls = []

    fake_llm = FakeLLM(
        [
            make_tool_call(
                name=(
                    "configure_quality_contract_tool"
                ),
                call_id="quality",
                args={
                    "layer": "silver",
                    "dataset_name": (
                        "clean_orders"
                    ),
                    "user_question": (
                        "order_id must be non-null "
                        "and amount must be >= 0."
                    ),
                },
            ),
            make_tool_call(
                name=(
                    "bronze_to_silver_tool"
                ),
                call_id="silver",
                args={
                    "source_dataset_name": (
                        "orders"
                    ),
                    "target_dataset_name": (
                        "clean_orders"
                    ),
                    "user_question": (
                        "Clean the orders."
                    ),
                    "output_format": "csv",
                },
            ),
            AIMessage(
                content="Completed."
            ),
        ]
    )

    monkeypatch.setattr(
        etl_module,
        "etl_llm_with_tools",
        fake_llm,
    )

    fake_tools = {
        "configure_quality_contract_tool": (
            FakeTool(
                name=(
                    "configure_quality_contract_tool"
                ),
                calls=calls,
                result=(
                    "Quality contract configured."
                ),
            )
        ),
        "bronze_to_silver_tool": (
            FakeTool(
                name=(
                    "bronze_to_silver_tool"
                ),
                calls=calls,
                result="Silver completed.",
            )
        ),
    }

    monkeypatch.setattr(
        etl_module,
        "tools_by_name",
        fake_tools,
    )

    result = (
        etl_module.etl_analyst.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Create clean_orders and "
                            "require order_id to be "
                            "non-null and amount >= 0."
                        )
                    )
                ]
            }
        )
    )

    assert [
        call["name"]
        for call in calls
    ] == [
        "configure_quality_contract_tool",
        "bronze_to_silver_tool",
    ]

    assert (
        calls[0]["args"][
            "dataset_name"
        ]
        == "clean_orders"
    )

    assert (
        calls[1]["args"][
            "target_dataset_name"
        ]
        == "clean_orders"
    )

    assert (
        result["messages"][-1].content
        == "Completed."
    )


class QualityFailingTool:
    def __init__(
        self,
        name,
        calls,
    ):
        self.name = name
        self.calls = calls

    def invoke(
        self,
        args,
    ):
        self.calls.append(
            {
                "name": self.name,
                "args": args,
            }
        )

        raise DataQualityError(
            (
                "Candidate silver dataset "
                "failed quality."
            ),
            details={
                "layer": "silver",
                "dataset": (
                    "clean_orders"
                ),
                "contract_name": (
                    "clean_orders_quality"
                ),
                "contract_version": 1,
                "contract_fingerprint": (
                    "quality123"
                ),
                "quality_result": {
                    "passed": False,
                    "total_checks": 3,
                    "failed_checks": 1,
                    "checks": [],
                },
            },
        )


def test_quality_failure_is_recorded_safely(
    monkeypatch,
    isolated_execution_store,
):
    calls = []

    raw_requirement = (
        "Clean the private orders and "
        "require amount >= 0."
    )

    fake_llm = FakeLLM(
        [
            make_tool_call(
                name=(
                    "bronze_to_silver_tool"
                ),
                call_id="silver",
                args={
                    "source_dataset_name": (
                        "orders"
                    ),
                    "target_dataset_name": (
                        "clean_orders"
                    ),
                    "user_question": (
                        raw_requirement
                    ),
                    "output_format": "csv",
                },
            ),
        ]
    )

    monkeypatch.setattr(
        etl_module,
        "etl_llm_with_tools",
        fake_llm,
    )

    monkeypatch.setattr(
        etl_module,
        "tools_by_name",
        {
            "bronze_to_silver_tool": (
                QualityFailingTool(
                    "bronze_to_silver_tool",
                    calls,
                )
            )
        },
    )

    result = (
        etl_module.etl_analyst
        .invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Run the Silver "
                            "transformation."
                        )
                    )
                ]
            }
        )
    )

    execution = (
        isolated_execution_store
        .get_run(
            result["run_id"]
        )
    )

    assert (
        execution["status"]
        == "failed"
    )

    event = (
        execution["events"][0]
    )

    assert (
        event["metadata"][
            "error_type"
        ]
        == "DataQualityError"
    )

    quality = (
        event["metadata"][
            "quality_gate"
        ]
    )

    assert (
        quality["dataset"]
        == "clean_orders"
    )

    assert (
        quality[
            "contract_fingerprint"
        ]
        == "quality123"
    )

    assert (
        quality["total_checks"]
        == 3
    )

    assert (
        quality["failed_checks"]
        == 1
    )

    assert (
        raw_requirement
        not in str(execution)
    )