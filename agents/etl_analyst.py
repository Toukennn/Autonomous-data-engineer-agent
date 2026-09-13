from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph

from models.schema import ETLAgentSchema, TransformPlan
from utils.etl_tools import ETLTools
from utils.llm_pick import pick_llm

from utils.data_layers import DataLayer

def create_transform_plan(
    *,
    user_question: str,
    dataset_context: str,
) -> TransformPlan:
    """
    Create a validated deterministic transformation plan.

    The LLM decides WHAT transformations are required.
    ETLTools deterministically controls HOW they are executed.
    """

    planner_llm = (
        pick_llm("claude")
        .with_structured_output(
            TransformPlan
        )
    )

    prompt = f"""
You are an ETL transformation planner.

Your job is NOT to write Python code.

Create a structured transformation plan using only the
operations available in the TransformPlan schema.

The plan will be executed by trusted deterministic Python code.

User request:

{user_question}


Dataset metadata:

{dataset_context}


Rules:

- Never generate Python code.
- Never generate shell commands.
- Never perform filesystem operations.
- Never invent column names.
- Only reference columns present in the dataset metadata.
- Use the minimum number of operations required.
- Preserve columns unless the user explicitly requests otherwise.
- Operations execute in the exact order you provide.
- If a type conversion is needed before a comparison or aggregation,
  perform the cast first.
- The summary must briefly explain the transformation.
"""

    return planner_llm.invoke(
        prompt
    )


# ============================================================
# TOOLS
# ============================================================

@tool
def extract_load_tool(
    url: str,
    dataset_name: str = "extract",
    format: str = "csv",
    paginate: bool = True,
    records_path: str | None = "results",
    next_path: str | None = "next",
    use_auth: bool = False,
    state_key: str | None = None,
    watermark_param: str | None = None,
    watermark_field: str | None = None,
) -> str:
    """
    Extract data from an API endpoint and save it locally.

    Supports:

    - paginated API extraction
    - retries and rate-limit handling
    - authenticated APIs
    - incremental watermark-based ingestion
    - deterministic checkpoint persistence

    For normal full extraction, leave:

        state_key=None
        watermark_param=None
        watermark_field=None

    For incremental ingestion, all three values are required:

        state_key:
            Stable identifier for the ingestion pipeline.

        watermark_param:
            API query parameter used to request only newer records.

            Example:
                updated_after
                after_id
                modified_since

        watermark_field:
            Field inside each returned record whose maximum value
            becomes the next checkpoint.

            Example:
                id
                updated_at
                modified_at

    The actual previous watermark value is loaded internally from
    the checkpoint store and must never be supplied by the LLM.

    Important:

    - Never invent watermark parameters or fields.
    - Use incremental ingestion only when the API contract or user
      explicitly identifies the correct incremental parameter and field.
    - Never expose, request, or pass checkpoint cursor values manually.
    - Never expose API credentials.

    Args:
        url:
            API endpoint.

        dataset_name: 
            Logical name of the Bronze dataset.

            This is not a filesystem path. 

            Example: 
                orders
                customers 
                pokemon

        format:
            csv, json, or parquet.

        paginate:
            Whether pagination should be followed automatically.

        records_path:
            Dotted path containing API records.

        next_path:
            Dotted path containing the next-page URL.

        use_auth:
            Whether configured API authentication should be used.

        state_key:
            Stable checkpoint identifier used for incremental ingestion.

        watermark_param:
            API query parameter representing the previous watermark.

        watermark_field:
            Record field used to calculate the next watermark.
    
    Breaking schema-evolution rules:

        - Breaking API schema changes are rejected by deterministic code.

        - Do not attempt to bypass a rejected schema change by changing the
        state_key, watermark configuration, or output path.

        - If a schema rejection report is returned by the extraction tool,
        explain the detected schema change to the user and report the
        rejection-report location.

        - Never claim that a rejected schema change was successfully applied.

        - The schema-evolution policy is application-controlled.
        Do not attempt to override it.

    Returns:
        Description of the extraction and saved files.
    """
    etl_tools = ETLTools()

    return etl_tools.extract_load(
        url=url,
        dataset_name=dataset_name,
        format=format,
        paginate=paginate,
        records_path=records_path,
        next_path=next_path,
        use_auth=use_auth,
        state_key=state_key,
        watermark_param=watermark_param,
        watermark_field=watermark_field,
    )


@tool
def bronze_to_silver_tool(
    source_dataset_name: str,
    user_question: str,
    target_dataset_name: str | None = None,
    output_format: str = "csv",
) -> str:
    """
    Transform a Bronze dataset into a cleaned and standardized
    Silver dataset.

    Dataset names are logical identifiers, not filesystem paths.

    The transformation request is converted by the planner LLM
    into a validated TransformPlan. Trusted deterministic code
    executes the plan.

    Args:
        source_dataset_name:
            Existing Bronze dataset name.

        user_question:
            Transformation requested by the user.

        target_dataset_name:
            Optional Silver dataset name. If omitted, the source
            dataset name is reused.

        output_format:
            csv, json, or parquet.
    """

    etl_tools = ETLTools()

    dataset_context = (
        etl_tools.get_layer_dataset_context(
            layer=DataLayer.BRONZE,
            dataset_name=source_dataset_name,
        )
    )

    plan = create_transform_plan(
        user_question=user_question,
        dataset_context=dataset_context,
    )

    return (
        etl_tools
        .transform_bronze_to_silver(
            source_dataset_name=(
                source_dataset_name
            ),
            target_dataset_name=(
                target_dataset_name
            ),
            output_format=(
                output_format
            ),
            plan=plan,
        )
    )


@tool
def silver_to_gold_tool(
    source_dataset_name: str,
    user_question: str,
    target_dataset_name: str | None = None,
    output_format: str = "csv",
) -> str:
    """
    Curate a Silver dataset into an analytics-ready Gold dataset.

    Use this for business-oriented filtering, aggregation,
    KPI preparation, reporting tables, and curated outputs.

    Dataset names are logical identifiers, not filesystem paths.

    Args:
        source_dataset_name:
            Existing Silver dataset name.

        user_question:
            Curation or analytical transformation requested.

        target_dataset_name:
            Optional Gold dataset name.

        output_format:
            csv, json, or parquet.
    """

    etl_tools = ETLTools()

    dataset_context = (
        etl_tools.get_layer_dataset_context(
            layer=DataLayer.SILVER,
            dataset_name=source_dataset_name,
        )
    )

    plan = create_transform_plan(
        user_question=user_question,
        dataset_context=dataset_context,
    )

    return (
        etl_tools
        .transform_silver_to_gold(
            source_dataset_name=(
                source_dataset_name
            ),
            target_dataset_name=(
                target_dataset_name
            ),
            output_format=(
                output_format
            ),
            plan=plan,
        )
    )

# ============================================================
# TOOLKIT
# ============================================================

tools = [
    extract_load_tool,
    bronze_to_silver_tool,
    silver_to_gold_tool,
]

tools_by_name = {
    tool.name: tool
    for tool in tools
}


# ============================================================
# LLM
# ============================================================

etl_llm = pick_llm("claude")

etl_llm_with_tools = etl_llm.bind_tools(
    tools
)


# ============================================================
# GRAPH NODES
# ============================================================

def llm_node(state: ETLAgentSchema):
    """
    Ask the ETL agent what action should be taken next.

    The LLM may either:

    - call one of the available ETL tools
    - return a final answer to the user
    """

    system_prompt = """
    You are an ETL specialist agent operating inside a larger
    Data Engineer agent.

    You orchestrate a Medallion data architecture:

    External API
        ↓
    Bronze
        ↓
    Silver
        ↓
    Gold

    You have three tools:

    1. extract_load_tool

    Extract API data into the Bronze layer.

    2. bronze_to_silver_tool

    Clean, normalize, deduplicate, cast, filter, or otherwise
    standardize an existing Bronze dataset into Silver.

    3. silver_to_gold_tool

    Create analytics-ready or business-ready Gold datasets
    from Silver. Use this for aggregations, KPIs, reporting
    tables, and curated analytical outputs.


    Rules:

    - Never invent filesystem paths.
    - Never provide "data/", "bronze/", "silver/", or "gold/"
    as part of a dataset name.
    - Dataset names are logical identifiers only.
    - API extraction always writes to Bronze.
    - Silver must be created from Bronze.
    - Gold must be created from Silver.
    - Never bypass Silver by creating Gold directly from Bronze.
    - Never modify Bronze while producing Silver.
    - Never modify Silver while producing Gold.
    - Do not claim an operation succeeded unless its tool succeeded.
    - Use csv when no output format is specified.

    Multi-stage requests:

    When a user request requires several Medallion stages,
    perform them in dependency order:

    1. extract API data to Bronze
    2. transform Bronze to Silver
    3. curate Silver to Gold

    Do not skip required stages.

    After each stage succeeds, continue to the next required stage.

    Reuse the correct logical dataset names between stages.

    If an earlier stage fails, do not continue to downstream stages.
    Explain the failure instead.
"""

    conversation = [
        {
            "role": "system",
            "content": system_prompt,
        },
        *state.messages,
    ]

    response = etl_llm_with_tools.invoke(
        conversation
    )

    # Important:
    # Because ETLAgentSchema uses LangGraph's add_messages reducer,
    # we return ONLY the new message.
    return {
        "messages": [response]
    }


def tool_node(state: ETLAgentSchema):
    """
    Execute tool calls requested by the ETL LLM.
    """

    last_message = state.messages[-1]

    tool_calls = getattr(
        last_message,
        "tool_calls",
        [],
    )

    tool_messages = []

    for tool_call in tool_calls:

        tool_name = tool_call["name"]

        if tool_name not in tools_by_name:
            tool_messages.append(
                ToolMessage(
                    content=f"Unknown tool requested: {tool_name}",
                    tool_call_id=tool_call["id"],
                )
            )

            continue

        selected_tool = tools_by_name[
            tool_name
        ]

        try:
            result = selected_tool.invoke(
                tool_call["args"]
            )

        except Exception as exc:
            result = (
                f"Tool execution failed: "
                f"{type(exc).__name__}: {exc}"
            )

        tool_messages.append(
            ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
        )

    # Again, return ONLY the new messages.
    return {
        "messages": tool_messages
    }


# ============================================================
# ROUTING
# ============================================================

def route_after_llm(
    state: ETLAgentSchema,
) -> str:
    """
    Decide whether the agent should execute a tool
    or finish the workflow.
    """

    last_message = state.messages[-1]

    tool_calls = getattr(
        last_message,
        "tool_calls",
        [],
    )

    if tool_calls:
        return "tools"

    return "end"


# ============================================================
# GRAPH
# ============================================================

etl_graph = StateGraph(
    ETLAgentSchema
)

etl_graph.add_node(
    "llm",
    llm_node,
)

etl_graph.add_node(
    "tools",
    tool_node,
)


etl_graph.add_edge(
    START,
    "llm",
)


etl_graph.add_conditional_edges(
    "llm",
    route_after_llm,
    {
        "tools": "tools",
        "end": END,
    },
)


etl_graph.add_edge(
    "tools",
    "llm",
)


etl_analyst = etl_graph.compile()


# ============================================================
# LOCAL TESTING
# ============================================================

if __name__ == "__main__":

    from langchain_core.messages import HumanMessage

    test_input = {
        "messages": [
            HumanMessage(
                content=(
                    "Extract the data from "
                    "https://pokeapi.co/api/v2/pokemon "
                    "and save it as CSV in data/extract."
                )
            )
        ]
    }

    result = etl_analyst.invoke(
        test_input
    )

    print("\n--- Final ETL Agent Response ---\n")

    print(
        result["messages"][-1].content
    )
