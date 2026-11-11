from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NOESIS_", extra="ignore")
    database_url: str = "sqlite:///./noesis.db"
    data_dir: str = "./data"
    storage_backend: str = "local"
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    api_key: str = ""
    contact_email: str = ""
    ncbi_api_key: str = ""
    ads_token: str = ""
    core_api_key: str = ""
    s2_api_key: str = ""
    github_token: str = ""
    patentsview_api_key: str = ""
    neo4j_url: str = ""               # e.g. neo4j://localhost:7687 (optional projection target)
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    offline: bool = True
    http_timeout: float = 20.0
    crawl_budget_per_job: int = 40
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    llm_max_calls: int = 30
    queue_mode: str = "inline"        # inline (FastAPI background tasks) | db (durable queue, run `noesis worker`)
    auth_mode: str = "api_key"        # api_key | users (accounts + per-user project isolation)
    secret_key: str = ""
    token_ttl_hours: int = 12
    allow_registration: bool = False
    lease_seconds: int = 900
    max_attempts: int = 3
    embedder: str = ""                # optional dense embedder, e.g. st:all-MiniLM-L6-v2 (needs sentence-transformers)
    index_max_docs: int = 100000         # in-process index ceiling (most recent docs are indexed); beyond this use an external vector store
    index_max_features: int = 200000
    rate_limit_per_min: int = 60        # per client, on expensive endpoints (query/analyze/upload/sync); 0 disables
    login_rate_limit_per_min: int = 10  # per client, on login attempts
    max_pages: int = 400
    max_replans: int = 2               # query mode: extra retrieval rounds with broader queries when a hypothesis has too little evidence
    rerank: bool = True                # BM25 + reciprocal-rank-fusion rerank of retrieval candidates
    veracity_min_sources: int = 2      # Veracity Gate: independent sources required before an answer is shown
    veracity_min_posterior: float = 0.6


@lru_cache
def get_settings() -> Settings:
    return Settings()
