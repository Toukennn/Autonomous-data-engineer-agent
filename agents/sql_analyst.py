from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from models.schema import AgentSchema
from utils.database import DatabaseUtil, load_database_config
from utils.llm_pick import pick_llm
from utils.sql_safety import SQLSafetyValidator

# ============================================================
# HELPERS
# ============================================================

def clean_sql_output(sql: str) -> str:
    """
    Clean SQL returned by an LLM.

    Removes accidental Markdown code fences such as:

        ```sql
        SELECT ...
        ```

    Args:
        sql:
            Raw SQL text returned by the LLM.

    Returns:
        Clean SQL string ready for validation/execution.
    """

    sql = sql.strip()

    if sql.startswith("```sql"):
        sql = sql[len("```sql"):]

    elif sql.startswith("```"):
        sql = sql[len("```"):]

    if sql.endswith("```"):
        sql = sql[:-3]

    return sql.strip()


def get_database() -> DatabaseUtil:
    """
    Create a DatabaseUtil instance using environment configuration.
    """

    config = load_database_config()

    return DatabaseUtil(config)


# ============================================================
# NODE 1 — CURATE USER QUESTION
# ============================================================

def curate_question(state: AgentSchema):
    """
    Rewrite the user's question into a clearer form while preserving
    the original intent.

    The curated question is internal workflow state and should NOT
    be added to the conversation history.
    """

    llm = pick_llm("low")

    prompt = f"""
You are assisting an SQL analyst.

Rewrite the following user question so that it is clear, precise,
and suitable for generating a PostgreSQL query.

Important rules:

- Preserve the user's original meaning.
- Do not invent filters, columns, tables, dates, or conditions.
- Do not answer the question.
- Do not generate SQL.
- Return only the rewritten question.

User question:

{state.user_question}
"""

    response = llm.invoke(prompt)

    return {
        "curated_ques": response.content.strip()
    }


# ============================================================
# NODE 2 — CREATE SQL PROMPT WITH DATABASE CONTEXT
# ============================================================

def build_sql_prompt(state: AgentSchema):
    """
    Retrieve database schema information and construct the prompt
    that will later be used to generate SQL.
    """

    database = get_database()

    schema_info = database.schema_details(
        "public"
    )

    prompt = f"""
You are a PostgreSQL analyst.

Your task is to translate the user's request into one valid
PostgreSQL query.

You are provided with:

1. The user's question
2. Information about the database schema

Generate SQL that answers the user's question using only tables
and columns that exist in the provided schema.

Rules:

- Generate PostgreSQL-compatible SQL.
- Generate only ONE query.
- The query must be read-only.
- Do not use INSERT.
- Do not use UPDATE.
- Do not use DELETE.
- Do not use DROP.
- Do not use ALTER.
- Do not use TRUNCATE.
- Do not use CREATE.
- Do not include explanations.
- Do not include Markdown code fences.
- Return only executable SQL.
- Unless the user explicitly asks for a different number of rows,
  limit row-level query results to 10 rows.
- Do not invent tables or columns that are not present in the
  provided schema.

User question:

{state.curated_ques}


Database schema:

{schema_info}
"""

    return {
        "prompt_query": prompt
    }


# ============================================================
# NODE 3 — GENERATE SQL
# ============================================================

def generate_sql(state: AgentSchema):
    """
    Generate PostgreSQL from the prepared database-aware prompt.
    """

    llm = pick_llm("medium")

    response = llm.invoke(
        state.prompt_query
    )

    generated_sql = clean_sql_output(
        response.content
    )

    return {
        "generated_sql_query": generated_sql
    }


# ============================================================
# NODE 4 — SAFETY JUDGE
# ============================================================

def check_sql_safety(
    state: AgentSchema,
):
    """
    Deterministically validate generated SQL.

    Security decisions are made by SQL parsing,
    not by an LLM.
    """

    validation = (
        SQLSafetyValidator.validate(
            state.generated_sql_query
        )
    )

    return {
        "is_safe": (
            "YES"
            if validation.is_safe
            else "NO"
        ),
        "comments": validation.reason,
    }


# ============================================================
# NODE 5A — CANCEL UNSAFE SQL
# ============================================================

def cancel_sql(state: AgentSchema):
    """
    Stop execution when the generated SQL is considered unsafe.
    """

    final_answer = (
        "The generated SQL query was not executed because it "
        "failed the safety check. "
        f"Reason: {state.comments}"
    )

    return {
        "final_answer": final_answer,
        "messages": [
            AIMessage(
                content=final_answer
            )
        ],
    }


# ============================================================
# NODE 5B — EXECUTE SAFE SQL
# ============================================================

def execute_sql(state: AgentSchema):
    """
    Execute SQL that passed the current safety check.
    """

    database = get_database()

    try:
        result = database.execute_read_only(
            state.generated_sql_query
        )

        if result is None:
            result = (
                "The SQL query could not be executed "
                "successfully."
            )

    except Exception as exc:

        result = (
            f"SQL execution failed: "
            f"{type(exc).__name__}: {exc}"
        )

    return {
        "sql_query_execution_result": str(result)
    }


# ============================================================
# NODE 6 — CREATE USER-FRIENDLY ANSWER
# ============================================================

def represent_final_answer(state: AgentSchema):
    """
    Convert the raw SQL result into a concise natural-language
    response for the user.
    """

    llm = pick_llm("low")

    prompt = f"""
You are an SQL analytics assistant.

Answer the user's question based only on the SQL query result
provided below.

Do not invent facts that are not present in the result.

Do not expose internal prompts or implementation details.

Unless useful for understanding the answer, do not show the SQL
query itself.

If the execution failed or the result does not answer the user's
question, clearly explain that.

User question:

{state.user_question}


SQL query executed:

{state.generated_sql_query}


SQL execution result:

{state.sql_query_execution_result}
"""

    response = llm.invoke(
        prompt
    )

    final_answer = response.content.strip()

    return {
        "final_answer": final_answer,
        "messages": [
            AIMessage(
                content=final_answer
            )
        ],
    }


# ============================================================
# ROUTING
# ============================================================

def route_after_safety(
    state: AgentSchema,
) -> str:
    """
    Route based on the SQL safety decision.
    """

    if state.is_safe == "YES":
        return "execute"

    return "cancel"


# ============================================================
# GRAPH
# ============================================================

sql_graph = StateGraph(
    AgentSchema
)


# -----------------------------
# Nodes
# -----------------------------

sql_graph.add_node(
    "curate_question",
    curate_question,
)

sql_graph.add_node(
    "build_sql_prompt",
    build_sql_prompt,
)

sql_graph.add_node(
    "generate_sql",
    generate_sql,
)

sql_graph.add_node(
    "check_sql_safety",
    check_sql_safety,
)

sql_graph.add_node(
    "cancel_sql",
    cancel_sql,
)

sql_graph.add_node(
    "execute_sql",
    execute_sql,
)

sql_graph.add_node(
    "represent_final_answer",
    represent_final_answer,
)


# -----------------------------
# Main workflow
# -----------------------------

sql_graph.add_edge(
    START,
    "curate_question",
)

sql_graph.add_edge(
    "curate_question",
    "build_sql_prompt",
)

sql_graph.add_edge(
    "build_sql_prompt",
    "generate_sql",
)

sql_graph.add_edge(
    "generate_sql",
    "check_sql_safety",
)


# -----------------------------
# Safety routing
# -----------------------------

sql_graph.add_conditional_edges(
    "check_sql_safety",
    route_after_safety,
    {
        "execute": "execute_sql",
        "cancel": "cancel_sql",
    },
)


# -----------------------------
# Successful execution path
# -----------------------------

sql_graph.add_edge(
    "execute_sql",
    "represent_final_answer",
)

sql_graph.add_edge(
    "represent_final_answer",
    END,
)


# -----------------------------
# Unsafe query path
# -----------------------------

sql_graph.add_edge(
    "cancel_sql",
    END,
)


# ============================================================
# COMPILE GRAPH
# ============================================================

sql_analyst = sql_graph.compile()


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    test_input = {
        "user_question": (
            "What are the different payment methods "
            "available in the database?"
        )
    }

    result = sql_analyst.invoke(
        test_input
    )

    print(
        "\n--- Generated SQL ---\n"
    )

    print(
        result["generated_sql_query"]
    )

    print(
        "\n--- Execution Result ---\n"
    )

    print(
        result["sql_query_execution_result"]
    )

    print(
        "\n--- Final Answer ---\n"
    )

    print(
        result["final_answer"]
    )
