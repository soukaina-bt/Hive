import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from pyhive import hive

from app.core.config import settings

SAFE_PREFIXES = ("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN")
LIMIT_PATTERN = re.compile(r"\bLIMIT\b", re.IGNORECASE)


class HiveService:
    def __init__(self):
        self._schema_cache: Dict[str, List[str]] = {}
        self._schema_cached_at = 0.0

    def _connect(self):
        return hive.Connection(
            host=settings.hive_host,
            port=settings.hive_port,
            username=settings.hive_username,
            password=settings.hive_password or None,
            database=settings.hive_database,
            auth=settings.hive_auth,
        )

    def _guard_query(self, sql: str):
        cleaned = sql.strip().rstrip(";")
        if settings.allow_unsafe_query_types:
            return
        if not cleaned.upper().startswith(SAFE_PREFIXES):
            raise ValueError(
                "Seules les requêtes SELECT/WITH/SHOW/DESCRIBE/EXPLAIN sont autorisées. "
                "Activez ALLOW_UNSAFE_QUERY_TYPES=true si nécessaire."
            )

    def _apply_limit(self, sql: str) -> str:
        limited_sql = sql.strip().rstrip(";")
        if limited_sql.upper().startswith(("SELECT", "WITH")) and not LIMIT_PATTERN.search(limited_sql):
            limited_sql = f"{limited_sql}\nLIMIT {settings.max_query_rows}"
        return limited_sql

    def _serialize_value(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                return value
        return value

    def run_query(self, sql: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        self._guard_query(sql)
        limited_sql = self._apply_limit(sql)

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(limited_sql)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchall()
            rows = [
                {column: self._serialize_value(value) for column, value in zip(columns, row)}
                for row in raw_rows
            ]
            return columns, rows

    def get_schema(self, force_refresh: bool = False) -> Dict[str, List[str]]:
        cache_age = time.time() - self._schema_cached_at
        if self._schema_cache and not force_refresh and cache_age < settings.schema_cache_ttl_seconds:
            return self._schema_cache

        tables: Dict[str, List[str]] = {}
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            all_tables = [row[0] for row in cursor.fetchall()]
            for table in all_tables:
                cursor.execute(f"DESCRIBE {table}")
                columns = []
                for row in cursor.fetchall():
                    col_name = row[0].strip() if row and row[0] else ""
                    if not col_name or col_name.startswith("#"):
                        continue
                    columns.append(col_name)
                tables[table] = columns

        self._schema_cache = tables
        self._schema_cached_at = time.time()
        return tables


hive_service = HiveService()
