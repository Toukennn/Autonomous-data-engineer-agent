from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

from config.settings import get_runtime_settings
from utils.database import DatabaseUtil, load_database_config
from utils.execution_observability import ExecutionRunStore


class DemoAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question cannot be blank.")
        return value


class DemoIngestRequest(BaseModel):
    api_url: str = Field(min_length=1, max_length=2_048)
    gold_goal: str = Field(min_length=1, max_length=4_000)

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("API URL must be an absolute HTTP or HTTPS URL.")
        return value

    @field_validator("gold_goal")
    @classmethod
    def normalize_gold_goal(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Gold requirement cannot be blank.")
        return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _find_event(record: dict, *names: str) -> dict | None:
    wanted = set(names)
    for event in record.get("events", []):
        if event.get("name") in wanted:
            return event
    return None


def _stage(stage_id: str, label: str, detail: str, status: str) -> dict:
    return {
        "id": stage_id,
        "label": label,
        "detail": detail,
        "status": status,
    }


def _ask_stages(record: dict, job_status: str) -> list[dict]:
    validation = _find_event(record, "governed_sql_validation")
    execution = _find_event(record, "read_only_query")

    if validation is None:
        return [
            _stage("generate", "Generate governed SQL", "Translate the question into one PostgreSQL query.", "failed" if job_status == "failed" else "active"),
            _stage("validate", "Validate SQL", "SQLGlot + governed catalog allowlist.", "pending"),
            _stage("execute", "Execute read-only query", "Only approved Silver/Gold relations can reach PostgreSQL.", "pending"),
            _stage("answer", "Format answer", "Ground the response in the SQL result.", "pending"),
        ]

    if validation.get("status") == "rejected":
        return [
            _stage("generate", "Generate governed SQL", "SQL generated.", "completed"),
            _stage("validate", "Validate SQL", "Deterministic governance blocked execution.", "blocked"),
            _stage("execute", "Execute read-only query", "No database execution occurred.", "skipped"),
            _stage("answer", "Format answer", "Return the guardrail outcome.", "completed" if job_status != "running" else "active"),
        ]

    if execution is None:
        return [
            _stage("generate", "Generate governed SQL", "SQL generated.", "completed"),
            _stage("validate", "Validate SQL", "SQL passed deterministic validation.", "completed"),
            _stage("execute", "Execute read-only query", "Running against governed PostgreSQL analytics relations.", "active" if job_status == "running" else "failed"),
            _stage("answer", "Format answer", "Waiting for execution.", "pending"),
        ]

    if execution.get("status") == "failed":
        return [
            _stage("generate", "Generate governed SQL", "SQL generated.", "completed"),
            _stage("validate", "Validate SQL", "SQL passed deterministic validation.", "completed"),
            _stage("execute", "Execute read-only query", "Database execution failed safely.", "failed"),
            _stage("answer", "Format answer", "No successful result to format.", "skipped"),
        ]

    return [
        _stage("generate", "Generate governed SQL", "SQL generated.", "completed"),
        _stage("validate", "Validate SQL", "SQL passed deterministic validation.", "completed"),
        _stage("execute", "Execute read-only query", "Read-only execution completed.", "completed"),
        _stage("answer", "Format answer", "Turning the bounded result into a concise answer.", "active" if job_status == "running" else "completed"),
    ]


def _tool_stage(event: dict | None, previous_ok: bool, job_status: str) -> str:
    if event is not None:
        status = event.get("status")
        if status == "success":
            return "completed"
        if status == "rejected":
            return "blocked"
        return "failed"
    if previous_ok and job_status == "running":
        return "active"
    return "pending"


def _ingest_stages(record: dict, job_status: str) -> list[dict]:
    extract = _find_event(record, "extract_load_tool")
    silver = _find_event(record, "dbt_bronze_to_silver_tool", "bronze_to_silver_tool")
    gold = _find_event(record, "dbt_silver_to_gold_tool", "silver_to_gold_tool")

    extract_status = (
        "active"
        if extract is None and job_status == "running"
        else _tool_stage(extract, True, job_status)
    )
    extract_ok = extract is not None and extract.get("status") == "success"
    silver_status = _tool_stage(silver, extract_ok, job_status)
    silver_ok = silver is not None and silver.get("status") == "success"
    gold_status = _tool_stage(gold, silver_ok, job_status)

    if job_status == "completed":
        publish_status = "completed"
    elif job_status in {"failed", "blocked"}:
        publish_status = "skipped"
    elif gold is not None and gold.get("status") == "success":
        publish_status = "active"
    else:
        publish_status = "pending"

    return [
        _stage("extract", "Extract API → Bronze", "Fetch, validate, and persist source records.", extract_status),
        _stage("silver", "Warehouse sync + dbt Silver", "Load governed Bronze data and build the Silver model.", silver_status),
        _stage("gold", "Build dbt Gold mart", "Apply the requested analytics-ready transformation.", gold_status),
        _stage("publish", "Publish governed mart", "Make Gold available to the SQL analyst.", publish_status),
    ]


def _guardrail(record: dict) -> dict | None:
    for event in record.get("events", []):
        status = event.get("status")
        metadata = event.get("metadata") or {}

        if event.get("event_type") == "sql_safety" and status == "rejected":
            return {
                "triggered": True,
                "kind": "sql_safety",
                "title": "SQL guardrail blocked execution",
                "message": "The generated SQL failed deterministic governance checks and was not executed.",
            }

        if status == "failed" and "quality_gate" in metadata:
            return {
                "triggered": True,
                "kind": "quality_gate",
                "title": "Data-quality gate blocked promotion",
                "message": "The candidate dataset failed an enforced quality contract, so downstream promotion stopped.",
            }

        if status == "failed" and metadata.get("error_type") == "SchemaEvolutionError":
            return {
                "triggered": True,
                "kind": "schema_evolution",
                "title": "Breaking schema change rejected",
                "message": "The deterministic schema-evolution policy rejected the source change.",
            }

    return None


def _safe_complete(store: ExecutionRunStore, run_id: str, status: str) -> None:
    try:
        store.complete_run(
            run_id=run_id,
            status=status,
            failure_reason="Demo execution failed." if status == "failed" else None,
        )
    except Exception:
        pass


def create_demo_router(
    *,
    require_demo_api_key: Callable,
    execution_lock,
    execution_pool,
) -> APIRouter:
    """
    Human-facing demo API.

    It deliberately uses the same execution lock/pool as /query,
    calls the specialist agent directly (skipping the router LLM),
    and never persists the visitor's API key or prompt.
    """

    router = APIRouter(
        prefix="/demo",
        tags=["demo"],
        dependencies=[Depends(require_demo_api_key)],
    )

    runtime = get_runtime_settings()
    store = ExecutionRunStore(runtime.data_root)
    jobs_lock = threading.Lock()
    jobs: dict[str, dict] = {}

    def create_job(
        *,
        run_id: str,
        mode: Literal["ask", "ingest"],
        dataset_name: str | None = None,
        gold_relation: str | None = None,
    ) -> None:
        with jobs_lock:
            jobs[run_id] = {
                "run_id": run_id,
                "mode": mode,
                "status": "running",
                "started_at": _utc_now(),
                "completed_at": None,
                "dataset_name": dataset_name,
                "gold_relation": gold_relation,
                "result": None,
                "error": None,
            }

    def update_job(run_id: str, **updates) -> None:
        with jobs_lock:
            jobs[run_id].update(updates)

    def get_job(run_id: str) -> dict:
        with jobs_lock:
            job = jobs.get(run_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Demo run not found.")
            return dict(job)

    def acquire_slot() -> None:
        if not execution_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=503,
                detail="Agent service is busy. Try again shortly.",
                headers={"Retry-After": "5"},
            )

    def start_record(run_id: str, mode: Literal["ask", "ingest"]) -> None:
        try:
            store.start_run(
                run_id=run_id,
                agent="sql_analyst" if mode == "ask" else "etl_analyst",
                max_tool_calls=None if mode == "ask" else runtime.etl_max_tool_calls,
            )
        except Exception:
            execution_lock.release()
            raise HTTPException(
                status_code=500,
                detail="Could not initialize demo run.",
            ) from None

    def run_ask(*, run_id: str, question: str) -> None:
        try:
            from agents.sql_analyst import sql_analyst

            state = sql_analyst.invoke(
                {
                    "user_question": question,
                    "run_id": run_id,
                }
            )

            columns = list(state.get("sql_result_columns", []))
            rows = [
                [_safe_value(value) for value in row]
                for row in state.get("sql_result_rows", [])
            ]
            record = store.get_run(run_id)
            guardrail = _guardrail(record)

            if state.get("is_safe") != "YES":
                status = "blocked"
            elif state.get("sql_execution_failed", False):
                status = "failed"
            else:
                status = "completed"

            update_job(
                run_id,
                status=status,
                completed_at=_utc_now(),
                result={
                    "answer": state.get("final_answer", ""),
                    "generated_sql": state.get("generated_sql_query", ""),
                    "columns": columns,
                    "rows": rows,
                    "truncated": state.get("sql_result_truncated", False),
                    "referenced_relations": state.get("referenced_relations", []),
                    "guardrail": guardrail,
                },
            )

        except Exception:
            _safe_complete(store, run_id, "failed")
            update_job(
                run_id,
                status="failed",
                completed_at=_utc_now(),
                error="The SQL analyst run failed. Internal details were not exposed.",
            )
        finally:
            execution_lock.release()

    def run_ingest(
        *,
        run_id: str,
        api_url: str,
        gold_goal: str,
        dataset_name: str,
        gold_relation: str,
    ) -> None:
        try:
            from agents.etl_analyst import etl_analyst

            prompt = f"""
Build a warehouse-backed PostgreSQL + dbt pipeline.

Source API:
{api_url}

Use this exact logical dataset name for Bronze, Silver, and Gold:
{dataset_name}

The user wants the Gold mart to contain:
{gold_goal}

Requirements:
- Extract the public JSON API into Bronze.
- Use the warehouse-backed dbt path.
- Build Silver from Bronze with dbt.
- Build Gold from Silver with dbt.
- Keep the logical dataset name exactly {dataset_name}.
- Do not bypass Silver.
- Do not invent quality requirements the user did not request.
- Use deterministic tools for all physical execution.
- Top-level JSON arrays are valid record collections.
- A top-level "results" list is also a valid record collection.
- If the API shape cannot be handled safely, fail instead of guessing.
""".strip()

            state = etl_analyst.invoke(
                {
                    "messages": [HumanMessage(content=prompt)],
                    "run_id": run_id,
                }
            )

            record = store.get_run(run_id)
            guardrail = _guardrail(record)
            workflow_failed = state.get("workflow_failed", False)

            if workflow_failed:
                status = "blocked" if guardrail is not None else "failed"
            else:
                status = "completed"

            messages = state.get("messages", [])
            answer = getattr(messages[-1], "content", "") if messages else ""

            update_job(
                run_id,
                status=status,
                completed_at=_utc_now(),
                result={
                    "answer": answer or "",
                    "dataset_name": dataset_name,
                    "gold_relation": gold_relation if status == "completed" else None,
                    "guardrail": guardrail,
                },
            )

        except Exception:
            _safe_complete(store, run_id, "failed")
            update_job(
                run_id,
                status="failed",
                completed_at=_utc_now(),
                error="The ETL analyst run failed. Internal details were not exposed.",
            )
        finally:
            execution_lock.release()

    @router.get("/catalog")
    def catalog() -> dict:
        database = DatabaseUtil(load_database_config())
        analytics_catalog = database.analytics_catalog(
            target_schema=runtime.dbt_target_schema
        )

        relations = []
        for schema in analytics_catalog.get("schemas", []):
            schema_name = schema.get("name", "")
            layer = schema.get("layer", "")
            for relation in schema.get("relations", []):
                relation_name = relation.get("name", "")
                if not schema_name or not relation_name:
                    continue
                relations.append(
                    {
                        "layer": layer,
                        "relation": f"{schema_name}.{relation_name}",
                        "columns": [
                            column.get("name", "")
                            for column in relation.get("columns", [])
                            if column.get("name")
                        ],
                    }
                )

        return {"relations": relations}

    @router.post("/ask", status_code=202)
    def ask(request: DemoAskRequest, response: Response) -> dict:
        acquire_slot()
        run_id = str(uuid4())
        start_record(run_id, "ask")
        create_job(run_id=run_id, mode="ask")

        try:
            execution_pool.submit(
                run_ask,
                run_id=run_id,
                question=request.question,
            )
        except Exception:
            _safe_complete(store, run_id, "failed")
            update_job(
                run_id,
                status="failed",
                completed_at=_utc_now(),
                error="Could not start the SQL analyst.",
            )
            execution_lock.release()
            raise HTTPException(
                status_code=500,
                detail="Could not start demo run.",
            ) from None

        response.headers["X-Run-ID"] = run_id
        return {
            "run_id": run_id,
            "mode": "ask",
            "status": "running",
        }

    @router.post("/ingest", status_code=202)
    def ingest(request: DemoIngestRequest, response: Response) -> dict:
        acquire_slot()
        run_id = str(uuid4())
        dataset_name = "demo_" + UUID(run_id).hex[:8]
        gold_relation = (
            f"{runtime.dbt_target_schema}_gold."
            f"mart_{dataset_name}"
        )

        start_record(run_id, "ingest")
        create_job(
            run_id=run_id,
            mode="ingest",
            dataset_name=dataset_name,
            gold_relation=gold_relation,
        )

        try:
            execution_pool.submit(
                run_ingest,
                run_id=run_id,
                api_url=request.api_url,
                gold_goal=request.gold_goal,
                dataset_name=dataset_name,
                gold_relation=gold_relation,
            )
        except Exception:
            _safe_complete(store, run_id, "failed")
            update_job(
                run_id,
                status="failed",
                completed_at=_utc_now(),
                error="Could not start the ETL analyst.",
            )
            execution_lock.release()
            raise HTTPException(
                status_code=500,
                detail="Could not start demo run.",
            ) from None

        response.headers["X-Run-ID"] = run_id
        return {
            "run_id": run_id,
            "mode": "ingest",
            "status": "running",
            "dataset_name": dataset_name,
            "gold_relation": gold_relation,
        }

    @router.get("/runs/{run_id}")
    def run_status(run_id: str) -> dict:
        try:
            normalized = str(UUID(run_id))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(
                status_code=404,
                detail="Demo run not found.",
            ) from None

        job = get_job(normalized)
        try:
            record = store.get_run(normalized)
        except Exception:
            raise HTTPException(
                status_code=404,
                detail="Demo run not found.",
            ) from None

        guardrail = None
        if job.get("result"):
            guardrail = job["result"].get("guardrail")
        if guardrail is None:
            guardrail = _guardrail(record)

        stages = (
            _ask_stages(record, job["status"])
            if job["mode"] == "ask"
            else _ingest_stages(record, job["status"])
        )

        return {
            "run_id": normalized,
            "mode": job["mode"],
            "status": job["status"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "dataset_name": job.get("dataset_name"),
            "gold_relation": job.get("gold_relation"),
            "stages": stages,
            "guardrail": guardrail,
            "result": job.get("result"),
            "error": job.get("error"),
        }

    return router
