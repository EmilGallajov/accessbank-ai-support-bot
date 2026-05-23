"""ChromaDB-backed knowledge base. Top-K retrieval only — never the full KB."""
from __future__ import annotations

import os
from typing import Any

# Disable chromadb's anonymous telemetry before the library loads — the bundled
# posthog client signature is incompatible with our pinned version and floods
# the console with harmless warnings otherwise.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

import chromadb
from chromadb.config import Settings

from . import config, llm

COLLECTION_NAME = "accessbank_kb"

_chroma_client: chromadb.api.ClientAPI | None = None


def _client() -> chromadb.api.ClientAPI:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(config.CHROMA_PATH),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
    return _chroma_client


def get_or_create_collection() -> Any:
    return _client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection() -> Any:
    try:
        _client().delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    return get_or_create_collection()


def add_documents(
    *,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    embeddings: list[list[float]] | None = None,
) -> None:
    coll = get_or_create_collection()
    if embeddings is None:
        embeddings = llm.embed(documents)
    coll.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)


def query(text: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
    """Return the top-K relevant KB chunks with metadata and similarity scores."""
    coll = get_or_create_collection()
    if coll.count() == 0:
        return []

    k = top_k or config.KB_TOP_K
    embeddings = llm.embed([text])
    if not embeddings:
        return []
    res = coll.query(
        query_embeddings=embeddings,
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    out: list[dict[str, Any]] = []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        out.append({
            "text": doc,
            "metadata": meta or {},
            "distance": dist,
            "similarity": 1.0 - float(dist) if dist is not None else None,
        })
    return out


def count() -> int:
    return get_or_create_collection().count()
