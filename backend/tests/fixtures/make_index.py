"""
Publica un índice v1 con los chunks de chunks.jsonl usando EMBED_PROVIDER=fake.

Uso: uv run python backend/tests/fixtures/make_index.py [--index-dir PATH]
También importable como módulo desde conftest.py (fixture_index).

Funciones:
  publish_index(index_dir) -> str        : escribe metadata (CURRENT, documents, pages)
  create_qdrant_index(index_dir, version): crea la colección Qdrant con embeddings fake
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

HERE = Path(__file__).parent
CHUNKS_PATH = HERE / "chunks.jsonl"


def publish_index(index_dir: Path) -> str:
    """Publica v1 con los chunks de fixtures; devuelve la versión publicada."""
    os.environ.setdefault("EMBED_PROVIDER", "fake")
    os.environ.setdefault("LLM_PROVIDER", "fake")
    os.environ.setdefault("RUNNER_MODE", "fake")

    from app.indexstore import IndexStore  # noqa: PLC0415
    from app.contracts import DocumentInfo, PageContent, Chunk  # noqa: PLC0415

    store = IndexStore(index_dir=index_dir)
    version = store.new_version()

    chunks: list[Chunk] = []
    doc_ids: set[str] = set()
    with CHUNKS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            chunks.append(Chunk.model_validate(raw))
            doc_ids.add(raw["doc_id"])

    documents = [
        DocumentInfo(
            doc_id=doc_id,
            title=f"Documento Ficticio {doc_id}",
            source_kind="reporte",
            report_period="2T26",
            year=2026,
            quarter=2,
            lang="es",
            pages=5,
            filename=f"{doc_id}.pdf",
        )
        for doc_id in sorted(doc_ids)
    ]

    pages_dict: dict[tuple[str, int], list[str]] = {}
    for chunk in chunks:
        key = (chunk.doc_id, chunk.page)
        pages_dict.setdefault(key, []).append(chunk.chunk_id)

    pages = [
        PageContent(
            doc_id=doc_id,
            page=page,
            text=f"[Texto crudo página {page} de {doc_id}]",
            chunk_ids=cids,
        )
        for (doc_id, page), cids in sorted(pages_dict.items())
    ]

    meta = {
        "chunks": len(chunks),
        "documents": len(documents),
        "embed_provider": "fake",
        "version": version,
    }

    store.publish(version, meta, documents, pages)
    return version


def create_qdrant_index(index_dir: Path, version: str, embed_dim: int | None = None) -> None:
    """Crea la colección Qdrant en la versión dada con embeddings fake.

    Llamar DESPUÉS de publish_index(). El directorio version_dir debe existir.
    """
    from qdrant_client import QdrantClient  # noqa: PLC0415
    from qdrant_client import models as qm  # noqa: PLC0415
    from app.retrieval.embeddings import FakeEmbedder  # noqa: PLC0415
    from app.retrieval.sparse import document_vector  # noqa: PLC0415
    from app.contracts import Chunk  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415

    # Usar la dimensión real de settings (respeta EMBED_DIM del .env)
    if embed_dim is None:
        embed_dim = settings.EMBED_DIM

    # Cargar chunks
    chunks: list[Chunk] = []
    with CHUNKS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                chunks.append(Chunk.model_validate(json.loads(line)))

    # Embeddings fake (deterministas)
    embedder = FakeEmbedder(dim=embed_dim)
    dense_vecs: list[list[float]] = asyncio.run(
        embedder.embed_documents([c.embed_text for c in chunks])
    )

    # Abrir (o crear) el directorio de la versión
    version_dir = index_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(version_dir))

    # Recrear la colección
    if client.collection_exists("ir"):
        client.delete_collection("ir")

    client.create_collection(
        collection_name="ir",
        vectors_config={"dense": qm.VectorParams(size=embed_dim, distance=qm.Distance.COSINE)},
        sparse_vectors_config={"bm25": qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
    )

    # Construir puntos
    points: list[qm.PointStruct] = []
    for i, (chunk, vec) in enumerate(zip(chunks, dense_vecs)):
        bm25_dict = document_vector(chunk.embed_text)
        payload = chunk.model_dump(exclude={"embed_text"})
        points.append(
            qm.PointStruct(
                id=i + 1,
                vector={
                    "dense": vec,
                    "bm25": qm.SparseVector(
                        indices=list(bm25_dict.keys()),
                        values=list(bm25_dict.values()),
                    ),
                },
                payload=payload,
            )
        )

    client.upsert(collection_name="ir", points=points)


if __name__ == "__main__":
    import argparse
    import tempfile

    parser = argparse.ArgumentParser()
    parser.add_argument("--index-dir", type=Path, default=None)
    parser.add_argument("--with-qdrant", action="store_true", default=False)
    args = parser.parse_args()

    idx_dir = args.index_dir or Path(tempfile.mkdtemp(prefix="test_index_"))
    v = publish_index(idx_dir)
    print(f"Publicado {v} en {idx_dir}")

    if args.with_qdrant:
        create_qdrant_index(idx_dir, v)
        print(f"Índice Qdrant creado en {idx_dir / v}")
