from langchain.tools import tool
from langchain_core.messages import (
    AIMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph

from models.schema import ETLAgentSchema, TransformPlan
from utils.etl_tools import ETLTools
from utils.llm_pick import pick_llm

from utils.data_layers import DataLayer

from config.settings import (
    get_runtime_settings,
)

import logging

from datetime import (
    datetime,
    timezone,
)
from time import perf_counter
from uuid import uuid4

from utils.execution_observability import (
    ExecutionRunStore,
)

from typing import Literal

from models.data_quality import (
    DataQualityContract,
)

from utils.exceptions import (
    DataQualityError,
)

runtime_settings = (
    get_runtime_settings()
)

ETL_MAX_TOOL_CALLS = (
    runtime_settings
    .etl_max_tool_calls
)

execution_store = (
    ExecutionRunStore(
        runtime_settings.data_root
    )
)

logger = logging.getLogger(
    __name__
)


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


def create_quality_contract(
    *,
    user_question: str,
    dataset_name: str,
) -> DataQualityContract:
    """
    Convert explicit user quality requirements into
    a validated DataQualityContract.

    The LLM decides WHAT quality rules the user asked
    for. Deterministic code controls persistence and
    enforcement.
    """

    planner_llm = (
        pick_llm("medium")
        .with_structured_output(
            DataQualityContract
        )
    )

    prompt = f"""
You are a data-quality contract planner.

Your job is NOT to inspect or modify datasets.

Create a structured DataQualityContract containing
ONLY quality requirements explicitly requested by
the user.

Target logical dataset:

{dataset_name}

User request:

{user_question}

Supported quality rules:

- not_null
- unique
- accepted_values
- range
- row_count

Rules:

- Never invent quality constraints.
- Never infer business rules that the user did not request.
- Never invent column names.
- Never generate Python code.
- Never generate filesystem paths.
- Never create rules merely because they seem like good practice.
- Use only the supported quality-rule schemas.
- Nullability must use an explicit not_null rule.
- A range rule must contain at least one bound.
- accepted_values must contain only values explicitly provided
  or unambiguously required by the user.
- If the user requests uniqueness across multiple columns,
  preserve the complete composite key.
- contract_version must be 1.
"""

    planned = (
        planner_llm.invoke(
            prompt
        )
    )

    # Contract identity is application-controlled.
    # The planner controls only the requested rules.
    return DataQualityContract(
        contract_version=1,
        name=(
            f"{dataset_name}_quality"
        ),
        rules=planned.rules,
    )


# A safe metadata helper
def _safe_tool_metadata(
    tool_name: str,
    args: dict,
) -> dict:
    """
    Return only non-sensitive operational
    metadata for execution observability.
    """

    allowed_fields = {
        "extract_load_tool": {
            "dataset_name",
            "format",
            "paginate",
            "state_key",
            "watermark_param",
            "watermark_field",
        },
        "bronze_to_silver_tool": {
            "source_dataset_name",
            "target_dataset_name",
            "output_format",
        },
        "silver_to_gold_tool": {
            "source_dataset_name",
            "target_dataset_name",
            "output_format",
        },
        "configure_quality_contract_tool": {
            "layer",
            "dataset_name",
        },
    }

    allowed = (
        allowed_fields.get(
            tool_name,
            set(),
        )
    )

    return {
        key: args[key]
        for key in allowed
        if key in args
    }


def _safe_quality_failure_metadata(
    exc: DataQualityError,
) -> dict:
    """
    Extract aggregate, non-row-level quality
    information for execution observability.
    """

    details = (
        exc.details
        if isinstance(
            exc.details,
            dict,
        )
        else {}
    )

    quality_result = (
        details.get(
            "quality_result"
        )
    )

    if not isinstance(
        quality_result,
        dict,
    ):
        quality_result = {}

    metadata = {
        "layer": (
            details.get(
                "layer"
            )
        ),
        "dataset": (
            details.get(
                "dataset"
            )
        ),
        "contract_name": (
            details.get(
                "contract_name"
            )
        ),
        "contract_version": (
            details.get(
                "contract_version"
            )
        ),
        "contract_fingerprint": (
            details.get(
                "contract_fingerprint"
            )
        ),
        "passed": (
            quality_result.get(
                "passed"
            )
        ),
        "total_checks": (
            quality_result.get(
                "total_checks"
            )
        ),
        "failed_checks": (
            quality_result.get(
                "failed_checks"
            )
        ),
    }

    return {
        key: value
        for key, value
        in metadata.items()
        if value is not None
    }


# we do not want an observability write failure to invalidate a successfully executed ETL operation.
def _record_event_safely(
    **kwargs,
) -> None:
    try:
        execution_store.record_event(
            **kwargs
        )

    except Exception as exc:
        logger.warning(
            "Failed to persist ETL "
            "execution event: %s",
            exc,
        )


def _complete_run_safely(
    *,
    run_id: str,
    status: str,
    failure_reason: str | None = None,
) -> None:
    try:
        execution_store.complete_run(
            run_id=run_id,
            status=status,
            failure_reason=(
                failure_reason
            ),
        )

    except Exception as exc:
        logger.warning(
            "Failed to finalize ETL "
            "execution run: %s",
            exc,
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


@tool
def configure_quality_contract_tool(
    layer: Literal[
        "silver",
        "gold",
    ],
    dataset_name: str,
    user_question: str,
) -> str:
    """
    Create a deterministic data-quality contract for
    a Silver or Gold logical dataset.

    Use this only when the user explicitly specifies
    quality expectations.

    Examples include:

    - order_id must not be null
    - order_id must be unique
    - amount must be >= 0
    - status must be one of paid, pending, cancelled
    - the dataset must contain at least 1 row

    This tool may create a new contract but may not
    overwrite a different existing contract.

    Args:
        layer:
            Target Medallion layer.
            Must be "silver" or "gold".

        dataset_name:
            Logical target dataset name.
            This is not a filesystem path.

        user_question:
            The user's explicit quality requirements.

    Important:

    - Never invent quality rules.
    - Never create a quality contract unless the user
      requested data-quality expectations.
    - Never use this tool to bypass a failed quality gate.
    - Never attempt to weaken or overwrite an existing
      quality contract.
    """

    target_layer = (
        DataLayer(
            layer
        )
    )

    contract = (
        create_quality_contract(
            user_question=(
                user_question
            ),
            dataset_name=(
                dataset_name
            ),
        )
    )

    etl_tools = ETLTools()

    return (
        etl_tools
        .configure_quality_contract(
            layer=target_layer,
            dataset_name=(
                dataset_name
            ),
            contract=contract,
        )
    )


# ============================================================
# TOOLKIT
# ============================================================

tools = [
    extract_load_tool,
    bronze_to_silver_tool,
    silver_to_gold_tool,
    configure_quality_contract_tool,
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

def initialize_run_node(
    state: ETLAgentSchema,
):
    """
    Initialize structured observability for
    one ETL-agent invocation.
    """

    if state.run_id:
        return {}

    run_id = str(
        uuid4()
    )

    try:
        execution_store.start_run(
            run_id=run_id,
            max_tool_calls=(
                ETL_MAX_TOOL_CALLS
            ),
        )

    except Exception as exc:
        logger.warning(
            "Failed to initialize ETL "
            "execution observability: %s",
            exc,
        )

    return {
        "run_id": run_id
    }


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

    You have four tools:

    1. extract_load_tool

    Extract API data into Bronze.

    2. bronze_to_silver_tool

    Create cleaned/standardized Silver datasets
    from Bronze.

    3. silver_to_gold_tool

    Create curated Gold datasets from Silver.

    4. configure_quality_contract_tool

    Create a persisted data-quality contract for a
    Silver or Gold logical dataset when the user
    explicitly specifies quality requirements.


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


    Data-quality rules:

    - Never invent a quality contract unless the user explicitly
    requests quality requirements.
    - Never invent quality constraints.
    - Quality contracts apply to target Silver or Gold datasets.
    - If a user requests quality constraints for a dataset that is
    about to be created, configure the contract BEFORE creating
    that dataset so the first candidate is gated.
    - Never attempt to overwrite or weaken an existing contract.
    - Never bypass a failed quality gate.
    - There is no skip-quality-check mechanism.
    - If a quality gate fails, the workflow must stop.
    - Never claim a quality-rejected dataset was created successfully.

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


def tool_node(
    state: ETLAgentSchema,
):
    """
    Execute exactly one ETL tool call.

    Safety guarantees:

    - dependent ETL operations execute sequentially
    - unknown tools terminate the workflow
    - tool failures terminate the workflow
    - total tool executions are bounded
    """

    last_message = (
        state.messages[-1]
    )

    tool_calls = getattr(
        last_message,
        "tool_calls",
        [],
    )

    # ============================================================
    # DEFENSIVE CHECK
    # ============================================================

    if not tool_calls:
        return {
            "workflow_failed": True,
            "failure_reason": (
                "Tool node was entered without "
                "a tool call."
            ),
        }

    # ============================================================
    # ONE DEPENDENT TOOL PER TURN
    # ============================================================

    if len(tool_calls) != 1:

        reason = (
            "ETL orchestration requires exactly "
            "one tool call per agent turn so each "
            "dependent stage can be validated before "
            "the next stage begins."
        )

        tool_messages = [
            ToolMessage(
                content=(
                    f"Tool execution rejected: "
                    f"{reason}"
                ),
                tool_call_id=(
                    tool_call["id"]
                ),
            )
            for tool_call in tool_calls
        ]

        return {
            "messages": tool_messages,
            "workflow_failed": True,
            "failure_reason": reason,
        }

    tool_call = tool_calls[0]

    next_count = (
        state.tool_call_count
        + 1
    )

    # ============================================================
    # TOOL-CALL BUDGET
    # ============================================================

    if (
        next_count
        > ETL_MAX_TOOL_CALLS
    ):

        reason = (
            "ETL tool-call limit exceeded. "
            f"Maximum allowed: "
            f"{ETL_MAX_TOOL_CALLS}."
        )

        return {
            "messages": [
                ToolMessage(
                    content=(
                        "Tool execution rejected: "
                        f"{reason}"
                    ),
                    tool_call_id=(
                        tool_call["id"]
                    ),
                )
            ],
            "tool_call_count": (
                next_count
            ),
            "workflow_failed": True,
            "failure_reason": reason,
        }

    tool_name = (
        tool_call["name"]
    )

    # ============================================================
    # TOOL ALLOWLIST
    # ============================================================

    if (
        tool_name
        not in tools_by_name
    ):

        reason = (
            "Unknown or unauthorized ETL "
            f"tool requested: {tool_name}"
        )

        return {
            "messages": [
                ToolMessage(
                    content=reason,
                    tool_call_id=(
                        tool_call["id"]
                    ),
                )
            ],
            "tool_call_count": (
                next_count
            ),
            "workflow_failed": True,
            "failure_reason": reason,
        }

    selected_tool = (
        tools_by_name[
            tool_name
        ]
    )

    # ============================================================
    # EXECUTION
    # ============================================================

    started_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    started_clock = (
        perf_counter()
    )

    try:
        result = (
            selected_tool.invoke(
                tool_call["args"]
            )
        )

    except Exception as exc:

        completed_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        duration_ms = (
            (
                perf_counter()
                - started_clock
            )
            * 1000
        )

        failure_metadata = {
            **_safe_tool_metadata(
                tool_name,
                tool_call["args"],
            ),
            "error_type": (
                type(exc).__name__
            ),
        }

        if isinstance(
            exc,
            DataQualityError,
        ):
            failure_metadata[
                "quality_gate"
            ] = (
                _safe_quality_failure_metadata(
                    exc
                )
            )

        _record_event_safely(
            run_id=state.run_id,
            event_type="tool",
            name=tool_name,
            status="failed",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            metadata=(
                failure_metadata
            ),
        )

        reason = (
            f"{tool_name} failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return {
            "messages": [
                ToolMessage(
                    content=(
                        "Tool execution failed: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    tool_call_id=(
                        tool_call["id"]
                    ),
                )
            ],
            "tool_call_count": (
                next_count
            ),
            "workflow_failed": True,
            "failure_reason": reason,
        }


    # ============================================================
    # SUCCESS OBSERVABILITY
    # ============================================================

    completed_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    duration_ms = (
        (
            perf_counter()
            - started_clock
        )
        * 1000
    )

    _record_event_safely(
        run_id=state.run_id,
        event_type="tool",
        name=tool_name,
        status="success",
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        metadata=(
            _safe_tool_metadata(
                tool_name,
                tool_call["args"],
            )
        ),
    )


    # ============================================================
    # SUCCESS
    # ============================================================

    return {
        "messages": [
            ToolMessage(
                content=str(
                    result
                ),
                tool_call_id=(
                    tool_call["id"]
                ),
            )
        ],
        "tool_call_count": (
            next_count
        ),
        "workflow_failed": False,
        "failure_reason": "",
    }

def failure_node(
    state: ETLAgentSchema,
):
    """
    Return a deterministic final response after
    a guarded ETL workflow failure.

    No additional LLM call is made.
    """

    reason = (
        state.failure_reason
        or "Unknown ETL workflow failure."
    )

    _complete_run_safely(
        run_id=state.run_id,
        status="failed",
        failure_reason=(
            state.failure_reason
        ),
    )

    return {
        "messages": [
            AIMessage(
                content=(
                    "The ETL workflow stopped "
                    "safely because a required "
                    "stage failed.\n\n"
                    f"Reason: {reason}\n\n"
                    "No downstream ETL stages "
                    "were executed after the failure."
                )
            )
        ]
    }


def complete_run_node(
    state: ETLAgentSchema,
):
    """
    Finalize a successful ETL-agent run.
    """

    _complete_run_safely(
        run_id=state.run_id,
        status="completed",
    )

    return {}

# ============================================================
# ROUTING
# ============================================================

def route_after_tools(
    state: ETLAgentSchema,
) -> str:
    """
    Continue only after a successful tool call.
    """

    if state.workflow_failed:
        return "failure"

    return "llm"


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

    return "complete"



# ============================================================
# GRAPH
# ============================================================

etl_graph = StateGraph(
    ETLAgentSchema
)

etl_graph.add_node(
    "initialize",
    initialize_run_node,
)

etl_graph.add_node(
    "llm",
    llm_node,
)

etl_graph.add_node(
    "tools",
    tool_node,
)

etl_graph.add_node(
    "complete",
    complete_run_node,
)

etl_graph.add_node(
    "failure",
    failure_node,
)


# ============================================================
# ENTRY
# ============================================================

etl_graph.add_edge(
    START,
    "initialize",
)

etl_graph.add_edge(
    "initialize",
    "llm",
)


# ============================================================
# AFTER LLM
# ============================================================

etl_graph.add_conditional_edges(
    "llm",
    route_after_llm,
    {
        "tools": "tools",
        "complete": "complete",
    },
)


# ============================================================
# AFTER TOOL EXECUTION
# ============================================================

etl_graph.add_conditional_edges(
    "tools",
    route_after_tools,
    {
        "llm": "llm",
        "failure": "failure",
    },
)


# ============================================================
# TERMINAL NODES
# ============================================================

etl_graph.add_edge(
    "complete",
    END,
)

etl_graph.add_edge(
    "failure",
    END,
)


# ============================================================
# COMPILE
# ============================================================

etl_analyst = (
    etl_graph.compile()
)


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
