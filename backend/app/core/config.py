import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "Hive Dashboard Builder")
    app_env:  str = os.getenv("APP_ENV",  "development")
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    hive_host:     str = os.getenv("HIVE_HOST",     "localhost")
    hive_port:     int = int(os.getenv("HIVE_PORT", "10000"))
    hive_username: str = os.getenv("HIVE_USERNAME", "cloudera")
    hive_password: str = os.getenv("HIVE_PASSWORD", "")
    hive_database: str = os.getenv("HIVE_DATABASE", "default")
    hive_auth:     str = os.getenv("HIVE_AUTH",     "NONE")

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model:   str = os.getenv("GEMINI_MODEL",   "gemini-2.5-flash")

    app_secret_key:      str = os.getenv("APP_SECRET_KEY",      "change_me")
    app_admin_username:  str = os.getenv("APP_ADMIN_USERNAME",  "admin")
    app_admin_password:  str = os.getenv("APP_ADMIN_PASSWORD",  "admin123")

    allow_unsafe_query_types: bool = os.getenv("ALLOW_UNSAFE_QUERY_TYPES", "false").lower() == "true"
    max_query_rows:           int  = int(os.getenv("MAX_QUERY_ROWS",           "2000"))
    schema_cache_ttl_seconds: int  = int(os.getenv("SCHEMA_CACHE_TTL_SECONDS", "300"))

    # Overview cache: keep results 10 min so Hive is not hit on every page load
    overview_cache_ttl_seconds: int = int(os.getenv("OVERVIEW_CACHE_TTL_SECONDS", "600"))

    # TABLESAMPLE percent for overview queries (10 = scan 10% of HDFS blocks).
    # Lower = faster but less precise.  Must be 1-100 and a divisor of 100.
    # Accepted values: 1, 2, 4, 5, 10, 20, 25, 50, 100
    overview_sample_pct: int = int(os.getenv("OVERVIEW_SAMPLE_PCT", "10"))

    cors_origins: List[str] = None

    def __post_init__(self):
        origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        self.cors_origins = _split_csv(origins)
        # Clamp sample pct to sensible value
        if self.overview_sample_pct not in (1, 2, 4, 5, 10, 20, 25, 50, 100):
            self.overview_sample_pct = 10


settings = Settings()
