"""
test_retrieval.py — COMPUERTA C2 (retrieval).

Verifica que core.search_documents:
  - Filtros duros (langs, source_kinds, doc_ids, content_type) devuelven solo lo pedido.
  - prefer_periods trae primero el periodo pedido pero no excluye los demás.
  - Diversidad: máximo 2 hits por (doc_id, page).
  - top_k=21 falla con error claro.
  - Query de 501 caracteres falla con error claro.
  - get_page devuelve el texto crudo de la página.

Fixture: fixture_index (session-scoped, creada en conftest.py con EMBED_PROVIDER=fake).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("EMBED_PROVIDER", "fake")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("RUNNER_MODE", "fake")


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

async def _search(query: str, **kwargs):
    from app.retrieval.core import search_documents
    return await search_documents(query, **kwargs)


# ─────────────────────────────────────────────────────────────────
# Validación de entrada
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_top_k_too_large(fixture_index):
    """top_k=21 debe lanzar ValueError con mensaje claro."""
    with pytest.raises(ValueError, match="≤ 20"):
        await _search("utilidad neta", top_k=21)


@pytest.mark.asyncio
async def test_query_too_long(fixture_index):
    """Query de 501 caracteres debe lanzar ValueError con mensaje claro."""
    long_query = "x" * 501
    with pytest.raises(ValueError, match="500"):
        await _search(long_query)


# ─────────────────────────────────────────────────────────────────
# Filtros duros
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_filter_lang_en(fixture_index):
    """Filtro duro langs=['en'] devuelve SOLO chunks en inglés."""
    hits = await _search("net interest income", langs=["en"], top_k=10)
    assert len(hits) > 0, "Debe haber al menos un chunk en inglés"
    for h in hits:
        assert h.lang == "en", f"Chunk {h.chunk_id} tiene lang={h.lang!r}, esperado 'en'"


@pytest.mark.asyncio
async def test_hard_filter_lang_es(fixture_index):
    """Filtro duro langs=['es'] devuelve SOLO chunks en español."""
    hits = await _search("utilidad neta", langs=["es"], top_k=10)
    assert len(hits) > 0
    for h in hits:
        assert h.lang == "es", f"Chunk {h.chunk_id} tiene lang={h.lang!r}, esperado 'es'"


@pytest.mark.asyncio
async def test_hard_filter_source_kind_anual(fixture_index):
    """Filtro duro source_kinds=['anual'] devuelve SOLO chunks del reporte anual."""
    hits = await _search("utilidad", source_kinds=["anual"], top_k=10)
    assert len(hits) > 0, "Debe haber chunks del reporte anual"
    for h in hits:
        assert h.source_kind == "anual", (
            f"Chunk {h.chunk_id} tiene source_kind={h.source_kind!r}, esperado 'anual'"
        )


@pytest.mark.asyncio
async def test_hard_filter_doc_ids(fixture_index):
    """Filtro duro doc_ids=['empresa-ficticia-anual'] devuelve solo ese documento."""
    hits = await _search("capital", doc_ids=["empresa-ficticia-anual"], top_k=10)
    assert len(hits) > 0, "Debe haber chunks en empresa-ficticia-anual"
    for h in hits:
        assert h.doc_id == "empresa-ficticia-anual", (
            f"Chunk {h.chunk_id} tiene doc_id={h.doc_id!r}"
        )


@pytest.mark.asyncio
async def test_hard_filter_content_type_table(fixture_index):
    """Filtro duro content_type='table' devuelve SOLO chunks de tabla."""
    hits = await _search("cartera crédito", content_type="table", top_k=10)
    assert len(hits) > 0, "Debe haber chunks de tipo 'table'"
    for h in hits:
        assert h.content_type == "table", (
            f"Chunk {h.chunk_id} tiene content_type={h.content_type!r}, esperado 'table'"
        )


@pytest.mark.asyncio
async def test_hard_filter_content_type_prose(fixture_index):
    """Filtro duro content_type='prose' devuelve SOLO chunks de prosa."""
    hits = await _search("margen financiero", content_type="prose", top_k=10)
    assert len(hits) > 0, "Debe haber chunks de prosa"
    for h in hits:
        assert h.content_type == "prose", (
            f"Chunk {h.chunk_id} tiene content_type={h.content_type!r}"
        )


# ─────────────────────────────────────────────────────────────────
# Filtros blandos (prefer_periods)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prefer_periods_does_not_exclude_other_periods(fixture_index):
    """Con prefer_periods=['2T26'], deben aparecer también chunks del periodo '2025'."""
    # Buscar sin filtros duros para obtener el universo completo
    hits_all = await _search("utilidad", top_k=20)
    periods_all = {h.report_period for h in hits_all}

    hits_biased = await _search("utilidad", prefer_periods=["2T26"], top_k=20)
    periods_biased = {h.report_period for h in hits_biased}

    # Los periodos distintos del biased deben incluir más que solo "2T26"
    # (el filtro es blando: otros periodos siguen saliendo)
    assert len(hits_biased) > 0
    # Si hay chunks de múltiples periodos, el resultado biased debe incluir ambos
    if len(periods_all) > 1:
        assert len(periods_biased) > 1, (
            "prefer_periods no debe excluir otros periodos. "
            f"Solo se obtuvieron: {periods_biased}"
        )


@pytest.mark.asyncio
async def test_prefer_periods_top_result_is_preferred_period(fixture_index):
    """Con prefer_periods=['2T26'] el primer resultado debe ser del periodo '2T26'."""
    hits = await _search("utilidad neta cartera", prefer_periods=["2T26"], top_k=10)
    assert len(hits) > 0
    # El primer resultado debe ser del periodo preferido
    assert hits[0].report_period == "2T26", (
        f"Primer hit tiene report_period={hits[0].report_period!r}, esperado '2T26'"
    )


# ─────────────────────────────────────────────────────────────────
# Diversidad
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_diversity_max_2_hits_per_page(fixture_index):
    """Máximo 2 hits por (doc_id, page) en cualquier resultado."""
    hits = await _search("empresa ficticia reporte", top_k=20)

    page_counts: dict[tuple[str, int], int] = {}
    for h in hits:
        key = (h.doc_id, h.page)
        page_counts[key] = page_counts.get(key, 0) + 1

    for (doc_id, page), count in page_counts.items():
        assert count <= 2, (
            f"({doc_id}, page={page}) aparece {count} veces, máximo es 2"
        )


# ─────────────────────────────────────────────────────────────────
# get_page
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_page_returns_text(fixture_index):
    """get_page devuelve PageContent con texto no vacío."""
    from app.retrieval.core import get_page

    pc = await get_page("empresa-ficticia", 1)
    assert pc.doc_id == "empresa-ficticia"
    assert pc.page == 1
    assert len(pc.text) > 0
    assert len(pc.chunk_ids) > 0


@pytest.mark.asyncio
async def test_get_page_invalid_doc_raises(fixture_index):
    """get_page con doc_id inexistente lanza ValueError."""
    from app.retrieval.core import get_page

    with pytest.raises(ValueError, match="doc_id"):
        await get_page("documento-que-no-existe", 1)


# ─────────────────────────────────────────────────────────────────
# SearchHit no lleva embed_text
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_hits_have_no_embed_text(fixture_index):
    """Los SearchHit no deben incluir el campo embed_text."""
    hits = await _search("utilidad neta", top_k=5)
    assert len(hits) > 0
    for h in hits:
        h_dict = h.model_dump()
        assert "embed_text" not in h_dict, f"SearchHit contiene embed_text: {h.chunk_id}"
