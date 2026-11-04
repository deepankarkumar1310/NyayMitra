"""Build (or rebuild) the ChromaDB index from backend/knowledge/*.md.

Usage (from the backend folder):
    python -m app.ingest
"""

from . import config
from .rag import _collection, chunk_text, parse_knowledge_file


def main() -> None:
    files = sorted(config.KNOWLEDGE_DIR.glob("*.md"))
    if not files:
        raise SystemExit(f"No knowledge files found in {config.KNOWLEDGE_DIR}")

    collection = _collection()
    existing = collection.get()["ids"]
    if existing:
        collection.delete(ids=existing)

    ids, docs, metas = [], [], []
    for path in files:
        meta, body = parse_knowledge_file(path)
        for i, chunk in enumerate(chunk_text(body)):
            ids.append(f"{path.stem}-{i}")
            docs.append(f"{meta['title']}\n\n{chunk}")
            metas.append(
                {"doc": path.stem, "title": meta["title"], "source": meta["source"], "url": meta["url"]}
            )

    collection.add(ids=ids, documents=docs, metadatas=metas)
    print(f"Indexed {len(docs)} chunks from {len(files)} files into {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()
