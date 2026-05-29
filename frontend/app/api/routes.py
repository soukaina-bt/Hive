from fastapi import APIRouter, Depends, HTTPException, Query
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

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    if payload.username != settings.app_admin_username or payload.password != settings.app_admin_password:
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    return LoginResponse(access_token=create_access_token(payload.username))


def current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    return verify_token(credentials)


@router.get("/schema", response_model=SchemaResponse)
def get_schema(refresh: bool = Query(False), _: str = Depends(current_user)):
    tables = hive_service.get_schema(force_refresh=refresh)
    return SchemaResponse(database=settings.hive_database, tables=tables)


@router.get("/overview", response_model=OverviewResponse)
def get_overview(refresh: bool = Query(False), _: str = Depends(current_user)):
    import traceback, logging
    logger = logging.getLogger(__name__)
    try:
        return OverviewResponse(**overview_service.get_overview(force_refresh=refresh))
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Overview failed:\n%s", tb)
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/query", response_model=QueryResponse)
def run_query(payload: QueryRequest, _: str = Depends(current_user)):
    try:
        columns, rows = hive_service.run_query(payload.sql)
        chart = gemini_service.suggest_chart_from_result(columns, rows, preferred_chart=payload.preferred_chart)
        return QueryResponse(
            sql=payload.sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            chart_suggestion=chart,
            explanation="Requête exécutée avec succès",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/nlq", response_model=QueryResponse)
def run_nlq(payload: NLQRequest, _: str = Depends(current_user)):
    try:
        schema_text = payload.schema_context or ""
        if not schema_text:
            schema = hive_service.get_schema()
            schema_text = "\n".join(f"{table}: {', '.join(columns)}" for table, columns in schema.items())

        generated = gemini_service.generate_hiveql(payload.question, schema_text, payload.preferred_chart)
        sql = generated.get("sql", "")
        if not sql:
            raise HTTPException(status_code=400, detail=generated.get("explanation", "Aucun SQL généré"))
        columns, rows = hive_service.run_query(sql)
        chart = (
            gemini_service.suggest_chart_from_result(columns, rows, preferred_chart=payload.preferred_chart)
            if payload.preferred_chart and payload.preferred_chart != "auto"
            else generated.get("chart") or gemini_service.suggest_chart_from_result(columns, rows)
        )
        return QueryResponse(
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            chart_suggestion=chart,
            explanation=generated.get("explanation", "Requête générée par Gemini"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
