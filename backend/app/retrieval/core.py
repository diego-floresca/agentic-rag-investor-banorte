# Creado en P0. Dueño: T2. No lo borres.
"""
Retrieval puro — sin MCP, sin dependencias de red.

Las 3 funciones públicas son las mismas que expone el servidor MCP:
  list_documents() -> list[DocumentInfo]
  get_page(doc_id, page) -> PageContent
  search_documents(...) -> list[SearchHit]

Algoritmo de búsqueda (SPEC §Tools MCP):
  1. Prefetch 20 dense + 20 BM25 con Qdrant → RRF nativo.
  2. Si hay filtros blandos (prefer_periods / entities): corre la misma
     búsqueda con y sin ellos, fusiona con RRF(k=60). Piden, no excluyen.
  3. Diversidad: máximo 2 hits por (doc_id, page).
  4. RERANK=fastembed: fastembed 0.9.0 no incluye TextCrossEncoder → desactivado.
     Cuando T1 actualice fastembed, descomentar el bloque marcado.

NOTA DE IMPORTACIÓN:
  get_embedder() es de T1 (app/retrieval/embeddings.py).
  query_vector() / query_sparse() es de T1 (app/retrieval/sparse.py).
  T1 puede renombrar query_vector a query_sparse; actualizar import si ocurre.
"""
from __future__ import annotations

import logging
from typing import Any

from qdrant_client import models

from app.config import settings
from app.contracts import DocumentInfo, PageContent, SearchHit
from app.indexstore import IndexStore

logger = logging.getLogger(__name__)

# ── RERANK check ─────────────────────────────────────────────────
_RERANK_AVAILABLE = False
if settings.RERANK.lower() == "fastembed":
    try:
        from fastembed import TextCrossEncoder  # type: ignore[import]  # noqa: F401
        _RERANK_AVAILABLE = True
    except ImportError:
        logger.warning(
            "RERANK=fastembed pero fastembed %s no incluye TextCrossEncoder. "
            "RERANK desactivado. Actualiza fastembed cuando sea compatible.",
            getattr(__import__("fastembed"), "__version__", "?"),
        )

# ── IndexStore singleton — inyectable desde tests ─────────────────
_store: IndexStore | None = None


def set_store(store: IndexStore | None) -> None:
    """Inyecta un IndexStore (tests). En producción no llamar."""
    global _store  # noqa: PLW0603
    _store = store


def _get_store() -> IndexStore:
    global _store  # noqa: PLW0603
    if _store is None:
        _store = IndexStore()
    return _store


# ─────────────────────────────────────────────────────────────────
# list_documents
# ─────────────────────────────────────────────────────────────────

async def list_documents() -> list[DocumentInfo]:
    """Lista todos los documentos del índice activo."""
    return _get_store().documents()


# ─────────────────────────────────────────────────────────────────
# get_page
# ─────────────────────────────────────────────────────────────────

async def get_page(doc_id: str, page: int) -> PageContent:
    """Devuelve el texto crudo de una página.

    Valida doc_id contra el catálogo; lanza ValueError si no existe.
    """
    store = _get_store()
    catalog = {d.doc_id for d in store.documents()}
    if doc_id not in catalog:
        raise ValueError(
            f"doc_id {doc_id!r} no existe en el índice. "
            f"Documentos disponibles: {sorted(catalog)}"
        )
    pc = store.page(doc_id, page)
    if pc is None:
        raise ValueError(f"Página {page} no encontrada en {doc_id!r}.")
    return pc


# ─────────────────────────────────────────────────────────────────
# search_documents — algoritmo híbrido con filtros blandos
# ─────────────────────────────────────────────────────────────────

async def search_documents(
    query: str,
    prefer_periods: list[str] | None = None,
    entities: list[str] | None = None,
    langs: list[str] | None = None,
    source_kinds: list[str] | None = None,
    doc_ids: list[str] | None = None,
    content_type: str | None = None,
    top_k: int = 8,
) -> list[SearchHit]:
    """Búsqueda híbrida (dense + BM25, RRF) con filtros blandos y diversidad.

    Validaciones:
      top_k ≤ 20, len(query) ≤ 500.
    Filtros duros:  langs, source_kinds, doc_ids, content_type.
    Filtros blandos: prefer_periods, entities (no excluyen, ordenan).
    """
    # ── Validación ────────────────────────────────────────────────
    if top_k > settings.TOP_K_MAX:
        raise ValueError(
            f"top_k debe ser ≤ {settings.TOP_K_MAX} (recibido: {top_k})."
        )
    if len(query) > 500:
        raise ValueError(
            f"query demasiado larga: {len(query)} caracteres (máximo 500)."
        )

    # ── Embeddings (T1) ──────────────────────────────────────────
    from app.retrieval.embeddings import get_embedder  # noqa: PLC0415
    # query_vector está en sparse.py (T1); T1 puede renombrarlo a query_sparse
    from app.retrieval.sparse import query_vector as _query_sparse  # noqa: PLC0415

    embedder = get_embedder()
    q_dense: list[float] = await embedder.embed_query(query)
    q_sparse_dict: dict[int, float] = _query_sparse(query)
    q_sparse = models.SparseVector(
        indices=list(q_sparse_dict.keys()),
        values=list(q_sparse_dict.values()),
    )

    # ── Cliente Qdrant ────────────────────────────────────────────
    client = _get_store().get_reader().get_client()
    if client is None:
        raise RuntimeError("No hay índice activo. Ejecuta `make ingest` primero.")

    PREFETCH = settings.PREFETCH_K

    # ── Filtros duros ─────────────────────────────────────────────
    hard_conds: list[models.Condition] = []
    if langs:
        hard_conds.append(
            models.FieldCondition(key="lang", match=models.MatchAny(any=langs))
        )
    if source_kinds:
        hard_conds.append(
            models.FieldCondition(key="source_kind", match=models.MatchAny(any=source_kinds))
        )
    if doc_ids:
        hard_conds.append(
            models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids))
        )
    if content_type:
        hard_conds.append(
            models.FieldCondition(key="content_type", match=models.MatchValue(value=content_type))
        )
    hard_filter = models.Filter(must=hard_conds) if hard_conds else None

    # ── Filtros blandos ───────────────────────────────────────────
    soft_conds: list[models.Condition] = []
    if prefer_periods:
        soft_conds.append(
            models.FieldCondition(key="report_period", match=models.MatchAny(any=prefer_periods))
        )
    if entities:
        soft_conds.append(
            models.FieldCondition(key="entity", match=models.MatchAny(any=entities))
        )

    # ── Ejecución de consultas ────────────────────────────────────
    if soft_conds:
        combined_conds = hard_conds + soft_conds
        combined_filter = models.Filter(must=combined_conds)

        biased = _qdrant_hybrid(client, q_dense, q_sparse, combined_filter, PREFETCH)
        unbiased = _qdrant_hybrid(client, q_dense, q_sparse, hard_filter, PREFETCH)
        candidates = _rrf_merge([biased, unbiased], k=60)
    else:
        raw = _qdrant_hybrid(client, q_dense, q_sparse, hard_filter, PREFETCH)
        candidates = [(p.payload.get("chunk_id", str(p.id)), p.score, p.payload or {}) for p in raw]

    # ── RERANK (fastembed 0.9.0 sin TextCrossEncoder → desactivado) ──
    # if _RERANK_AVAILABLE:
    #     from fastembed import TextCrossEncoder  # noqa: PLC0415
    #     candidates = _rerank_cross_encoder(query, candidates[:20])

    # ── Diversidad ────────────────────────────────────────────────
    candidates = _apply_diversity(candidates, max_per_page=2)

    # ── Construir SearchHit ───────────────────────────────────────
    hits: list[SearchHit] = []
    for _cid, score, payload in candidates[:top_k]:
        # embed_text no va en SearchHit
        payload_clean = {k: v for k, v in payload.items() if k != "embed_text"}
        try:
            hits.append(SearchHit(**payload_clean, score=score))
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo construir SearchHit desde payload: %s", exc)

    return hits


# ─────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────

def _qdrant_hybrid(
    client: Any,
    q_dense: list[float],
    q_sparse: models.SparseVector,
    filter_cond: models.Filter | None,
    limit: int,
) -> list[Any]:  # list[ScoredPoint]
    """Ejecuta prefetch dense + BM25 con RRF nativo de Qdrant."""
    prefetch: list[models.Prefetch] = [
        models.Prefetch(
            query=q_dense,
            using="dense",
            filter=filter_cond,
            limit=limit,
        )
    ]
    if q_sparse.indices:
        prefetch.append(
            models.Prefetch(
                query=q_sparse,
                using="bm25",
                filter=filter_cond,
                limit=limit,
            )
        )

    result = client.query_points(
        collection_name=IndexStore.COLLECTION,
        prefetch=prefetch,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return result.points


def _rrf_merge(
    result_lists: list[list[Any]],
    k: int = 60,
) -> list[tuple[str, float, dict]]:
    """Fusión RRF manual para combinar resultados biased + unbiased.

    Devuelve lista de (chunk_id, rrf_score, payload) ordenada por score desc.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for ranked_list in result_lists:
        for rank, point in enumerate(ranked_list, start=1):
            payload: dict = point.payload or {}
            cid = str(payload.get("chunk_id", point.id))
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in payloads:
                payloads[cid] = payload

    return [
        (cid, scores[cid], payloads[cid])
        for cid in sorted(scores, key=lambda c: -scores[c])
    ]


def _apply_diversity(
    candidates: list[tuple[str, float, dict]],
    max_per_page: int = 2,
) -> list[tuple[str, float, dict]]:
    """Limita a max_per_page hits por (doc_id, page)."""
    counts: dict[tuple[str, int], int] = {}
    result: list[tuple[str, float, dict]] = []
    for item in candidates:
        cid, score, payload = item
        key = (payload.get("doc_id", ""), int(payload.get("page", 0)))
        n = counts.get(key, 0)
        if n < max_per_page:
            counts[key] = n + 1
            result.append(item)
    return result
