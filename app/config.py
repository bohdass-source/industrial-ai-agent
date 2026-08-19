from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://agent:agent@localhost:5432/industrial"
    checkpointer_dsn: str = "postgresql://agent:agent@localhost:5432/industrial"

    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str | None = None
    llm_temperature: float = 0.0

    embeddings_model: str = "text-embedding-3-small"
    embeddings_api_key: str = ""
    embeddings_base_url: str | None = None

    collection_name: str = "industrial_manuals"
    rag_k: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
