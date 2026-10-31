from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = SERVER_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_DIR / ".env"), str(SERVER_DIR / ".env")), extra="ignore"
    )

    app_name: str = "CX Sentinel AI"
    environment: str = "development"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Either a full DATABASE_URL, or the individual DB_* parts (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME).
    database_url: str = ""
    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = "cx_sentinel"
    db_ssl: bool | None = None  # None = enable TLS automatically for TiDB Cloud hosts
    db_fallback_sqlite: bool = True
    sqlite_path: str = str(SERVER_DIR / "data" / "cx_sentinel.db")
    auto_migrate: bool = True

    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480

    demo_mode: bool = True
    seed_demo_data: bool = True
    auto_run_analysis: bool = True
    demo_password: str = "CxSentinel#2026"

    llm_provider: str = "none"  # none | openrouter | openai_compatible
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-3.5-haiku"
    llm_timeout_seconds: int = 30
    llm_price_in_per_1k: float = 0.0008
    llm_price_out_per_1k: float = 0.004

    embedding_backend: str = "auto"  # auto | tfidf | sentence-transformers

    baseline_days: int = 14
    recent_days: int = 7
    min_issue_support: int = 12
    min_persistence_days: int = 3
    min_group_size: int = 10  # k-anonymity floor for segment reporting
    refund_sla_hours: int = 120
    approval_cost_threshold_inr: float = 50000.0

    tool_failure_rate: float = 0.18  # simulated transient failure rate of enterprise APIs
    tool_max_retries: int = 3
    data_retention_days: int = 365

    data_dir: str = str(SERVER_DIR / "data")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.db_host:
            return (f"mysql+pymysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4")
        return "mysql+pymysql://cx_user:cx_password@localhost:3306/cx_sentinel?charset=utf8mb4"

    @property
    def db_ssl_enabled(self) -> bool:
        return self.db_ssl if self.db_ssl is not None else "tidbcloud.com" in (self.db_host + self.database_url)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
