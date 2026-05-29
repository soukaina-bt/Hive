import asyncio
import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.security import create_access_token, security, verify_token
from app.models.schemas import (
    LoginRequest,
    LoginResponse,
    NLQRequest,
    OverviewResponse,
    QueryRequest,
    QueryResponse,
    SchemaResponse,
)
from app.services.gemini_service import gemini_service
from app.services.hive_service import hive_service
from app.services.overview_service import overview_service
from app.services.query_executor import execute_safe

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# ── Background job registry ────────────────────────────────────────────────────
# Stores overview computation jobs: job_id → {status, result, error}
_jobs: Dict[str, Dict[str, Any]] = {}
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="hive-bg")


class JobStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    ERROR    = "error"


def _run_overview_job(job_id: str, force_refresh: bool) -> None:
    """Executed in a background thread — never blocks the event loop."""
    _jobs[job_id]["status"] = JobStatus.RUNNING
    try:
        result = overview_service.get_overview(force_refresh=force_refresh)
        _jobs[job_id]["status"]  = JobStatus.DONE
        _jobs[job_id]["result"]  = result
        _jobs[job_id]["done_at"] = time.time()
    except Exception as exc:
        logger.error("Overview job %s failed:\n%s", job_id, traceback.format_exc())
        _jobs[job_id]["status"]  = JobStatus.ERROR
        _jobs[job_id]["error"]   = f"{type(exc).__name__}: {exc}"
        _jobs[job_id]["done_at"] = time.time()


# ── Auth ───────────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    if (payload.username != settings.app_admin_username
            or payload.password != settings.app_admin_password):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    return LoginResponse(access_token=create_access_token(payload.username))


def current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    return verify_token(credentials)


# ── Schema ─────────────────────────────────────────────────────────────────────

@router.get("/schema", response_model=SchemaResponse)
def get_schema(refresh: bool = Query(False), _: str = Depends(current_user)):
    tables = hive_service.get_schema(force_refresh=refresh)
    return SchemaResponse(database=settings.hive_database, tables=tables)


# ── Overview — async job pattern ───────────────────────────────────────────────
#
#  POST /api/overview/start          → { job_id }          (immediate)
#  GET  /api/overview/status/{id}    → { status, result? } (poll every 3 s)
#
#  The old GET /api/overview is kept as an alias that auto-starts + blocks
#  with long-polling (max 25 s per call) for backwards compatibility.
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/overview/start")
def overview_start(refresh: bool = Query(False), _: str = Depends(current_user)):
    """Start an overview computation job; returns immediately with a job_id."""
    # Re-use an existing running job if one is already in flight
    for jid, job in _jobs.items():
        if job["status"] in (JobStatus.PENDING, JobStatus.RUNNING) and job.get("refresh") == refresh:
            return {"job_id": jid, "status": job["status"]}

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": JobStatus.PENDING, "result": None, "error": None, "refresh": refresh, "done_at": None}
    _executor.submit(_run_overview_job, job_id, refresh)
    return {"job_id": job_id, "status": JobStatus.PENDING}


@router.get("/overview/status/{job_id}")
def overview_status(job_id: str, _: str = Depends(current_user)):
    """Poll for job completion. Frontend calls this every 3 s."""
    # Clean up jobs that finished more than 120 s ago (TTL)
    _JOB_TTL = 120
    stale = [jid for jid, j in list(_jobs.items())
             if j.get("done_at") and time.time() - j["done_at"] > _JOB_TTL]
    for jid in stale:
        _jobs.pop(jid, None)

    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job inconnu")

    if job["status"] == JobStatus.DONE:
        # Return result but keep the job in registry until TTL expires
        # so concurrent polls on the same job_id don't get 404
        return {"status": JobStatus.DONE, "result": job["result"]}

    if job["status"] == JobStatus.ERROR:
        error = job["error"]
        # Keep job until TTL for the same reason
        return {"status": JobStatus.ERROR, "error": error}

    return {"status": job["status"]}


@router.get("/overview", response_model=OverviewResponse)
def get_overview(refresh: bool = Query(False), _: str = Depends(current_user)):
    """
    Legacy synchronous endpoint.
    Returns cached data instantly if available; otherwise starts a job
    and waits up to 25 s before returning 202 (let client poll).
    """
    # If cache is warm, return immediately — zero Hive cost
    if overview_service.is_cached() and not refresh:
        try:
            return OverviewResponse(**overview_service.get_overview(force_refresh=False))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Cache cold — tell the frontend to use the async flow
    raise HTTPException(
        status_code=202,
        detail="ASYNC_REQUIRED",
    )


# ── Query / NLQ ────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
def run_query(payload: QueryRequest, _: str = Depends(current_user)):
    try:
        columns, rows = execute_safe(payload.sql)
        chart = gemini_service.suggest_chart_from_result(columns, rows, preferred_chart=payload.preferred_chart)
        return QueryResponse(
            sql=payload.sql, columns=columns, rows=rows, row_count=len(rows),
            chart_suggestion=chart, explanation="Requête exécutée avec succès",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/nlq", response_model=QueryResponse)
def run_nlq(payload: NLQRequest, _: str = Depends(current_user)):
    try:
        schema_text = payload.schema_context or ""
        if not schema_text:
            schema = hive_service.get_schema()
            schema_text = "\n".join(f"{t}: {', '.join(c)}" for t, c in schema.items())

        generated = gemini_service.generate_hiveql(payload.question, schema_text, payload.preferred_chart)
        sql = generated.get("sql", "")
        if not sql:
            raise HTTPException(status_code=400, detail=generated.get("explanation", "Aucun SQL généré"))

        columns, rows = execute_safe(sql)
        chart = (
            gemini_service.suggest_chart_from_result(columns, rows, preferred_chart=payload.preferred_chart)
            if payload.preferred_chart and payload.preferred_chart != "auto"
            else generated.get("chart") or gemini_service.suggest_chart_from_result(columns, rows)
        )
        return QueryResponse(
            sql=sql, columns=columns, rows=rows, row_count=len(rows),
            chart_suggestion=chart, explanation=generated.get("explanation", "Requête générée par Gemini"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
