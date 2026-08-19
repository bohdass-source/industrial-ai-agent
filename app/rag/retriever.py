"""RAG-доступ к мануалам через pgvector."""

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from app.config import settings

_store: PGVector | None = None


def get_store() -> PGVector:
    global _store
    if _store is None:
        embeddings = OpenAIEmbeddings(
            model=settings.embeddings_model,
            api_key=settings.embeddings_api_key,
            base_url=settings.embeddings_base_url,
            check_embedding_ctx_length=False,
        )
        _store = PGVector(
            embeddings=embeddings,
            connection=settings.database_url,
            collection_name=settings.collection_name,
            use_jsonb=True,
        )
    return _store


def search_manual_rag(query: str, error_code: str | None = None, k: int = 5) -> str:
    """Возвращает фрагменты документации. Если задан error_code — фильтруем по нему."""
    store = get_store()
    kwargs = {"filter": {"error_code": error_code}} if error_code else {}
    docs = store.similarity_search(query, k=k, **kwargs)
    if not docs:
        return "По запросу ничего не найдено в документации."
    chunks = [f"[Фрагмент {i} из {d.metadata.get('source')}]\n{d.page_content}"
              for i, d in enumerate(docs, 1)]
    return "\n\n---\n\n".join(chunks)
