import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from pyhive import hive

from app.core.config import settings

SAFE_PREFIXES = ("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN")
LIMIT_PATTERN = re.compile(r"\bLIMIT\b", re.IGNORECASE)

# Max parallel DESCRIBE calls when loading schema
_SCHEMA_WORKERS = 8

# Local mode settings injected into every connection — bypasses YARN/MapReduce
# on CDH 5.13 (Hive 1.1.0) where MapRedTask fails with return code 2
_LOCAL_MODE_CONFIG = {
    'hive.server2.idle.session.timeout': '0',
    # Force local execution — no YARN scheduling
    'hive.exec.mode.local.auto': 'true',
    'hive.exec.mode.local.auto.inputbytes.max': '536870912',
    'hive.exec.mode.local.auto.tasks.max': '8',
    # Fetch task for simple SELECTs (zero MR overhead)
    'hive.fetch.task.conversion': 'more',
    'hive.fetch.task.conversion.threshold': '536870912',
    # Single reducer — less shuffle overhead
    'mapreduce.job.reduces': '1',
    # Disable vectorized execution (buggy on Hive 1.1.0)
    'hive.vectorized.execution.enabled': 'false',
    # Map joins for small tables
    'hive.auto.convert.join': 'true',
    'hive.auto.convert.join.noconditionaltask': 'true',
    'hive.auto.convert.join.noconditionaltask.size': '20971520',
    'hive.optimize.skewjoin': 'false',
}


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
            configuration=_LOCAL_MODE_CONFIG,
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

    def run_query_with_settings(self, settings_stmts: list, sql: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Execute SET statements then SELECT in the same session."""
        self._guard_query(sql)
        limited_sql = self._apply_limit(sql)

        with self._connect() as conn:
            cursor = conn.cursor()
            for stmt in settings_stmts:
                stmt = stmt.strip().rstrip(";")
                if stmt:
                    try:
                        cursor.execute(stmt)
                    except Exception:
                        pass  # Ignore SET failures on old Hive versions
            cursor.execute(limited_sql)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchall()
            rows = [
                {column: self._serialize_value(value) for column, value in zip(columns, row)}
                for row in raw_rows
            ]
            return columns, rows

    def _describe_table(self, table: str) -> Tuple[str, List[str]]:
        """Fetch column names for a single table."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"DESCRIBE {table}")
            columns = []
            for row in cursor.fetchall():
                col_name = row[0].strip() if row and row[0] else ""
                if not col_name or col_name.startswith("#"):
                    continue
                columns.append(col_name)
        return table, columns

    def get_schema(self, force_refresh: bool = False) -> Dict[str, List[str]]:
        cache_age = time.time() - self._schema_cached_at
        if self._schema_cache and not force_refresh and cache_age < settings.schema_cache_ttl_seconds:
            return self._schema_cache

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            all_tables = [row[0] for row in cursor.fetchall()]

        tables: Dict[str, List[str]] = {}
        with ThreadPoolExecutor(max_workers=min(_SCHEMA_WORKERS, len(all_tables) or 1)) as pool:
            futures = {pool.submit(self._describe_table, t): t for t in all_tables}
            for future in as_completed(futures):
                try:
                    tname, cols = future.result()
                    tables[tname] = cols
                except Exception as exc:
                    tname = futures[future]
                    import logging
                    logging.getLogger(__name__).warning("DESCRIBE %s failed: %s", tname, exc)
                    tables[tname] = []

        self._schema_cache = tables
        self._schema_cached_at = time.time()
        return tables


hive_service = HiveService()
