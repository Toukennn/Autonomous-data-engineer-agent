from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)

import agents.etl_analyst as etl_module


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



def test_etl_agent_exposes_only_medallion_tools():
    assert set(
        etl_module.tools_by_name
    ) == {
        "extract_load_tool",
        "bronze_to_silver_tool",
        "silver_to_gold_tool",
    }

    assert (
        "transform_load_tool"
        not in etl_module.tools_by_name
    )