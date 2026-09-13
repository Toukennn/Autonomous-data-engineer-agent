from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph

from models.schema import ETLAgentSchema, TransformPlan
from utils.etl_tools import ETLTools
from utils.llm_pick import pick_llm


# ============================================================
# TOOLS
# ============================================================

@tool
def extract_load_tool(
    url: str,
    output_folder: str = "data/extract",
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

        output_folder:
            Folder inside the project's data directory.

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

    Returns:
        Description of the extraction and saved files.
    """
    etl_tools = ETLTools()

    return etl_tools.extract_load(
        url=url,
        output_folder=output_folder,
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
def transform_load_tool(
    input_file_path: str,
    output_folder: str = "data/transform",
    output_format: str = "csv",
    user_question: str = "",
) -> str:
    """
    Safely transform an existing dataset according to the user's request.

    The LLM creates a structured transformation plan.
    The plan is validated with Pydantic and executed using deterministic
    Pandas operations.

    Arbitrary Python execution is not allowed.

    Args:
        input_file_path:
            Input dataset located inside the project's data directory.

        output_folder:
            Folder inside the data directory where the transformed
            dataset should be saved.

        output_format:
            csv, json, or parquet.

        user_question:
            Natural-language transformation request.

    Returns:
        Description of the executed transformation.
    """

    etl_tools = ETLTools()

    dataset_context = (
        etl_tools.get_dataset_context(
            input_file_path
        )
    )

    planner_llm = (
        pick_llm("claude")
        .with_structured_output(
            TransformPlan
        )
    )

    prompt = f"""
You are an ETL transformation planner.

Your job is NOT to write Python code.

Instead, create a structured transformation plan using only
the transformation operations available in the provided schema.

The plan will later be executed by trusted deterministic Python code.

User request:

{user_question}


Dataset metadata:

{dataset_context}


Important rules:

- Never generate Python code.
- Never generate shell commands.
- Never attempt file-system operations.
- Never invent column names.
- Only use columns present in the dataset metadata.
- Use the minimum number of transformation operations needed.
- Preserve columns unless the user explicitly requests otherwise.
- Operations are executed in the exact order you provide them.
- If type conversion is required before a comparison or aggregation,
  place the cast operation before that operation.
- The summary should briefly describe the transformation.
"""

    plan = planner_llm.invoke(
        prompt
    )

    return etl_tools.transform_load(
        input_file_path=input_file_path,
        output_folder=output_folder,
        output_format=output_format,
        plan=plan,
    )


# ============================================================
# TOOLKIT
# ============================================================

tools = [
    extract_load_tool,
    transform_load_tool,
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

Your responsibility is to perform ETL-related tasks.

You have access to two tools:

1. extract_load_tool

    Use this when the user wants to extract data from an API
    and save it locally. The tool also supports persistent incremental
    ingestion when the API exposes a known watermark mechanism.

2. transform_load_tool

   Use this when the user wants to clean, filter, aggregate,
   reshape, transform, or otherwise modify an existing dataset.

Rules:

- Use the appropriate tool whenever the task requires an ETL operation.
- Do not claim an operation succeeded unless a tool actually executed it.
- If the user does not specify an extraction folder, use:
  data/extract
- If the user does not specify a transformation folder, use:
  data/transform
- If the user does not specify an output format, use:
  csv
- After the required tool operations are completed, provide a short,
  clear summary of what was done.
- Do not expose unnecessary implementation details.

Incremental API ingestion rules:

- Use normal full extraction unless incremental ingestion is
  explicitly requested or the API's incremental contract is known.

- Incremental ingestion requires ALL of:
  1. a stable state_key
  2. the API's watermark query parameter
  3. the corresponding watermark field in returned records

- Never invent watermark_param or watermark_field.

- If the required incremental fields are unknown, do not guess them.

- Never provide or invent a previous cursor/watermark value.
  Checkpoint values are loaded internally by deterministic code.

- Reuse the exact same state_key for subsequent runs of the same
  incremental ingestion pipeline.

- A state_key must not be reused for a different API or different
  watermark configuration.

- The checkpoint is application-controlled. Do not attempt to read,
  modify, reset, or expose checkpoint files directly.

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
