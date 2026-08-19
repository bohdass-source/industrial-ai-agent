"""Индексация мануалов в pgvector.

Запуск:
    python -m app.rag.manual_index              # пересоздать коллекцию
    python -m app.rag.manual_index --if-missing # пропустить существующую
"""

import argparse
from pathlib import Path

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

MANUALS_DIR = Path(__file__).resolve().parent.parent / "data" / "manuals"


def load_documents() -> list[Document]:
    docs = []
    for path in sorted(MANUALS_DIR.glob("*.md")):
        docs.append(Document(
            page_content=path.read_text(encoding="utf-8"),
            metadata={"source": path.name, "error_code": path.stem},  # E142
        ))
    return docs


def build_index(if_missing: bool = False) -> None:
    embeddings = OpenAIEmbeddings(
        model=settings.embeddings_model,
        api_key=settings.embeddings_api_key,
        base_url=settings.embeddings_base_url,
        check_embedding_ctx_length=False,
    )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n## ", "\n### ", "\n", " ", ""],
    )
    chunks = splitter.split_documents(load_documents())

    store = PGVector(
        embeddings=embeddings,
        connection=settings.database_url,
        collection_name=settings.collection_name,
        use_jsonb=True,
    )

    store.create_vector_extension()
    store.create_tables_if_not_exists()

    with store._make_sync_session() as session:
        existing = store.get_collection(session)

    if if_missing and existing is not None:
        print("Index already exists, skipping")
        return

    if existing is not None:
        store.delete_collection()
    store.create_collection()

    with store._make_sync_session() as session:
        created = store.get_collection(session)
    if created is None:
        raise RuntimeError(
            f"PGVector collection '{settings.collection_name}' was not created"
        )

    store.add_documents(chunks)
    print(f"Indexed {len(chunks)} chunks from manuals")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index manuals into pgvector")
    parser.add_argument(
        "--if-missing",
        action="store_true",
        help="Пропустить, если коллекция уже существует",
    )
    args = parser.parse_args()
    build_index(if_missing=args.if_missing)
