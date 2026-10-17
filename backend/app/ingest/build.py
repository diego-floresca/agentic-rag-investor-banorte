"""E8+E9 build.py — Embeddings Gemini + construcción del índice Qdrant."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.config import settings
from app.contracts import Chunk, DocumentInfo, PageContent
from app.indexstore import IndexStore
from app.retrieval.embeddings import get_embedder
from app.retrieval.sparse import document_vector


async def _embed_all(texts: list[str]) -> list[list[float]]:
    """Vectoriza todos los textos con EMBED_CONCURRENCY de concurrencia."""
    embedder = get_embedder()
    semaphore = asyncio.Semaphore(settings.EMBED_CONCURRENCY)

    async def embed_one(text: str) -> list[float]:
        async with semaphore:
            vecs = await embedder.embed_documents([text])
            return vecs[0]

    tasks = [embed_one(t) for t in texts]
    return await asyncio.gather(*tasks)


def build_index(
    chunks_dir: Path,
    doc_info_list: list[DocumentInfo],
    pages_dir: Path,
    work_dir: Path,
) -> str:
    """
    Construye el índice Qdrant con todos los chunks.

    Returns version string (e.g. "v1").
    """
    # Cargar todos los chunks
    all_chunks: list[Chunk] = []
    chunk_files = list(chunks_dir.glob("*.jsonl"))

    for cfile in sorted(chunk_files):
        with cfile.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    all_chunks.append(Chunk.model_validate(json.loads(line)))

    if not all_chunks:
        print("[build] No hay chunks para indexar.")
        return ""

    print(f"[build] {len(all_chunks)} chunks cargados desde {len(chunk_files)} archivos.")

    # Verificar: 3 textos distintos → 3 vectores distintos
    sample_texts = [c.embed_text for c in all_chunks[:3]]
    if len(sample_texts) >= 3:
        embedder = get_embedder()
        sample_vecs = asyncio.run(embedder.embed_documents(sample_texts))
        # Verificar distinción
        for i in range(len(sample_vecs)):
            for j in range(i + 1, len(sample_vecs)):
                if sample_vecs[i] == sample_vecs[j] and sample_texts[i] != sample_texts[j]:
                    print(f"[build] ADVERTENCIA: textos distintos producen vectores iguales (i={i}, j={j})")

    # Medir latencia de una llamada
    t0 = time.time()
    asyncio.run(get_embedder().embed_documents([all_chunks[0].embed_text]))
    latency_one = time.time() - t0

    # Proyección total
    projected_s = latency_one * len(all_chunks) / settings.EMBED_CONCURRENCY
    print(
        f"[build] Proyección embeddings: {len(all_chunks)} chunks × "
        f"{latency_one*1000:.1f}ms ÷ {settings.EMBED_CONCURRENCY} workers = "
        f"{projected_s:.1f}s"
    )

    if projected_s > 360:
        print(
            f"[build] ADVERTENCIA: proyección ({projected_s:.1f}s) supera 360s. "
            "No se lanzará la indexación."
        )
        return ""

    # Vectorizar todos los chunks
    print("[build] Vectorizando chunks...")
    t_embed_start = time.time()
    texts = [c.embed_text for c in all_chunks]
    all_vecs = asyncio.run(_embed_all(texts))
    t_embed = time.time() - t_embed_start
    print(f"[build] Embeddings completados en {t_embed:.1f}s")

    # Crear índice Qdrant
    from qdrant_client import QdrantClient
    from qdrant_client import models as qmodels

    store = IndexStore()
    version = store.new_version()
    version_dir = store._index_dir / version

    print(f"[build] Creando colección Qdrant en {version_dir} (versión {version})...")

    client = QdrantClient(path=str(version_dir))

    client.recreate_collection(
        collection_name=IndexStore.COLLECTION,
        vectors_config={
            "dense": qmodels.VectorParams(
                size=settings.EMBED_DIM,
                distance=qmodels.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            "bm25": qmodels.SparseVectorParams(
                modifier=qmodels.Modifier.IDF,
            )
        },
    )

    # Crear índices de payload
    payload_fields = [
        ("doc_id", qmodels.PayloadSchemaType.KEYWORD),
        ("page", qmodels.PayloadSchemaType.INTEGER),
        ("report_period", qmodels.PayloadSchemaType.KEYWORD),
        ("entity", qmodels.PayloadSchemaType.KEYWORD),
        ("lang", qmodels.PayloadSchemaType.KEYWORD),
        ("source_kind", qmodels.PayloadSchemaType.KEYWORD),
        ("content_type", qmodels.PayloadSchemaType.KEYWORD),
    ]
    for field_name, field_type in payload_fields:
        client.create_payload_index(
            collection_name=IndexStore.COLLECTION,
            field_name=field_name,
            field_schema=field_type,
        )

    # Upsert en batches de 256
    batch_size = 256
    n_chunks = len(all_chunks)

    for batch_start in range(0, n_chunks, batch_size):
        batch_end = min(batch_start + batch_size, n_chunks)
        batch_chunks = all_chunks[batch_start:batch_end]
        batch_vecs = all_vecs[batch_start:batch_end]

        points: list[qmodels.PointStruct] = []
        for i, (chunk, dense_vec) in enumerate(zip(batch_chunks, batch_vecs)):
            sparse_vec = document_vector(chunk.embed_text)
            payload = chunk.model_dump()
            # Excluir embed_text del payload (solo para búsqueda, no para recuperación)
            payload.pop("embed_text", None)

            point = qmodels.PointStruct(
                id=batch_start + i,
                vector={
                    "dense": dense_vec,
                    "bm25": qmodels.SparseVector(
                        indices=list(sparse_vec.keys()),
                        values=list(sparse_vec.values()),
                    ),
                },
                payload=payload,
            )
            points.append(point)

        client.upsert(
            collection_name=IndexStore.COLLECTION,
            points=points,
        )
        print(
            f"[build] Indexados {min(batch_end, n_chunks)}/{n_chunks} chunks"
        )

    # Escribir pages.jsonl
    page_files = list(pages_dir.glob("*.jsonl"))
    page_contents: list[dict] = []
    for pfile in sorted(page_files):
        with pfile.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    page_data = json.loads(line)
                    # Recolectar chunk_ids para esta página
                    doc_id = page_data.get("doc_id", "")
                    page_num = page_data.get("page", 0)
                    chunk_ids = [
                        c.chunk_id for c in all_chunks
                        if c.doc_id == doc_id and c.page == page_num
                    ]
                    page_contents.append({
                        "doc_id": doc_id,
                        "page": page_num,
                        "text": page_data.get("raw_text", ""),
                        "chunk_ids": chunk_ids,
                    })

    # Publicar versión
    meta = {
        "version": version,
        "n_chunks": n_chunks,
        "n_docs": len(doc_info_list),
        "embed_model": settings.EMBED_MODEL,
        "embed_dim": settings.EMBED_DIM,
        "embed_provider": settings.EMBED_PROVIDER,
    }

    store.publish(
        version=version,
        meta=meta,
        documents=doc_info_list,
        pages=(PageContent(**p) for p in page_contents),
    )

    print(f"[build] Índice {version} publicado. {n_chunks} chunks, {len(doc_info_list)} documentos.")
    return version
