from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FinSight AI"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 9300
    auth_jwt_secret: SecretStr = SecretStr("")
    auth_token_minutes: int = 30

    database_url: str = "postgresql+psycopg://finsight:finsight@localhost:55432/finsight"
    redis_url: str = "redis://127.0.0.1:56479/0"
    object_storage_root: str = ".local/object-storage"
    evaluation_runs_root: str = ".local/evaluation-runs"
    evaluation_golden_path: str | None = None
    evaluation_suite_path: str | None = None
    mineru_api_url: str = "http://127.0.0.1:59390"

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"

    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    milvus_uri: str = "http://localhost:59530"
    milvus_collection: str = "finsight_document_chunks_v1"
    embedding_dimension: int = 1024

    tushare_token: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
