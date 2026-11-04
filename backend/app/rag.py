"""Retrieval over the verified knowledge base (MiniLM embeddings + ChromaDB).

Heavy libraries are imported lazily so the API (and the test suite) can start
without loading the embedding model until the first query.
"""

import re
from functools import lru_cache
from pathlib import Path

from . import config

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_knowledge_file(path: Path) -> tuple[dict, str]:
    """Split a knowledge markdown file into (metadata, body)."""
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    match = FRONT_MATTER.match(raw)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip().lower()] = value.strip()
        raw = raw[match.end():]
    meta.setdefault("title", path.stem)
    meta.setdefault("source", meta["title"])
    meta.setdefault("url", "")
    return meta, raw.strip()


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    """Chunk by markdown section/paragraph, packing paragraphs up to max_chars."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


@lru_cache(maxsize=1)
def _collection():
    import chromadb
    from chromadb.utils.embedding_functions import (
        SentenceTransformerEmbeddingFunction,
    )

    config.ensure_dirs()
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    embed = SentenceTransformerEmbeddingFunction(model_name=config.EMBED_MODEL)
    return client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        embedding_function=embed,
        metadata={"hnsw:space": "cosine"},
    )


def retrieve(query: str, k: int = config.TOP_K) -> list[dict]:
    """Return up to k knowledge chunks most similar to the query."""
    query = query.strip()
    if not query:
        return []
    collection = _collection()
    if collection.count() == 0:
        return []
    result = collection.query(query_texts=[query], n_results=min(k, collection.count()))
    chunks = []
    for text, meta, dist in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        chunks.append(
            {
                "text": text,
                "doc": meta.get("doc", ""),
                "title": meta.get("title", ""),
                "source": meta.get("source", ""),
                "url": meta.get("url", ""),
                "score": round(1 - float(dist), 3),
            }
        )
    return chunks
