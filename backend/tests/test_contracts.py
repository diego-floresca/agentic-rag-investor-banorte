"""
test_contracts.py — COMPUERTA C0.

Verifica:
1. runner_fake emite secuencia canónica en orden y termina en done.
2. runner_fake con "bloquear" → error(guard_blocked) + done.
3. runner_fake con "error" → error(internal_error) + done.
4. Los 14 chunks del fixture validan contra Chunk.
5. make_index publica v1 y el reader la abre correctamente.
6. Segunda publicación cambia CURRENT y el mismo reader abre v2.
7. sparse tokeniza "1,273,193" → ["1273193"] y "2T26" → ["2t26"].
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ── Modo fake obligatorio ──────────────────────────────────────────
os.environ["EMBED_PROVIDER"] = "fake"
os.environ["LLM_PROVIDER"] = "fake"
os.environ["RUNNER_MODE"] = "fake"

HERE = Path(__file__).parent
CHUNKS_PATH = HERE / "fixtures" / "chunks.jsonl"


# ─────────────────────────────────────────────────────────────────
# 1-3. runner_fake
# ─────────────────────────────────────────────────────────────────

async def _collect(session_id: str, message: str) -> list[dict]:
    from app.agents.runner_fake import run_chat
    return [e.model_dump() for e in [e async for e in run_chat(session_id, message)]]


@pytest.mark.asyncio
async def test_runner_fake_canonical_order():
    """Secuencia canónica: status → plan → tool_call → tool_result
    → finding → verification → token → citations → done."""
    events = await _collect("s1", "¿Cuál fue la utilidad neta en 2T26?")

    types = [e["type"] for e in events]

    # Verificar presencia de todos los tipos en orden correcto
    assert "status" in types
    assert "plan" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "finding" in types
    assert "verification" in types
    assert "token" in types
    assert "citations" in types
    assert types[-1] == "done", f"Último evento debe ser 'done', fue: {types[-1]}"

    # El orden relativo importa
    idx = {t: types.index(t) for t in ["plan", "tool_call", "tool_result", "finding", "verification", "citations", "done"]}
    assert idx["plan"] < idx["tool_call"]
    assert idx["tool_call"] < idx["tool_result"]
    assert idx["tool_result"] < idx["finding"]
    assert idx["finding"] < idx["verification"]
    assert idx["citations"] < idx["done"]


@pytest.mark.asyncio
async def test_runner_fake_bloquear():
    """Mensaje con 'bloquear' → error guard_blocked + done."""
    events = await _collect("s2", "bloquear esta consulta")

    types = [e["type"] for e in events]
    assert types[-1] == "done"

    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) >= 1
    assert error_events[0]["code"] == "guard_blocked"


@pytest.mark.asyncio
async def test_runner_fake_error():
    """Mensaje con 'error' → error internal_error + done."""
    events = await _collect("s3", "provocar error interno")

    types = [e["type"] for e in events]
    assert types[-1] == "done"

    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) >= 1
    assert error_events[0]["code"] == "internal_error"


# ─────────────────────────────────────────────────────────────────
# 4. Chunks fixture validan contra Chunk
# ─────────────────────────────────────────────────────────────────

def test_fixture_chunks_validate():
    """Los 14 chunks del JSONL validan contra Chunk (Pydantic v2)."""
    from app.contracts import Chunk

    chunks = []
    with CHUNKS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            chunk = Chunk.model_validate(raw)
            chunks.append(chunk)

    assert len(chunks) == 14, f"Se esperaban 14 chunks, se encontraron {len(chunks)}"

    # El chunk envenenado debe estar presente (el verificador lo detecta)
    poisoned = [c for c in chunks if "INSTRUCCIÓN OCULTA" in c.text]
    assert len(poisoned) == 1, "Debe haber exactamente 1 chunk envenenado como fixture"

    # Al menos un chunk de tipo tabla con registro en formato SPEC
    table_chunks = [c for c in chunks if c.content_type == "table"]
    assert len(table_chunks) >= 3

    # Al menos un chunk con header_ok=False
    no_header = [c for c in chunks if not c.header_ok]
    assert len(no_header) >= 1


# ─────────────────────────────────────────────────────────────────
# 5-6. IndexStore: publicar v1, abrir, publicar v2, reabrir
# ─────────────────────────────────────────────────────────────────

def test_index_publish_and_read():
    """make_index publica v1; el reader la abre y lee los documentos."""
    from app.indexstore import IndexStore
    from tests.fixtures.make_index import publish_index

    with tempfile.TemporaryDirectory(prefix="test_idx_") as tmp:
        idx_dir = Path(tmp)

        v1 = publish_index(idx_dir)
        assert v1 == "v1"

        store = IndexStore(index_dir=idx_dir)
        assert store.current() == "v1"

        reader = store.get_reader()
        docs = reader.documents()
        assert len(docs) >= 1

        # page() devuelve PageContent
        first_doc = docs[0]
        pc = reader.page(first_doc.doc_id, 1)
        assert pc is not None
        assert pc.doc_id == first_doc.doc_id
        assert pc.page == 1


def test_index_second_publish_changes_current():
    """Segunda publicación cambia CURRENT; el mismo reader detecta el cambio."""
    from app.indexstore import IndexStore
    from app.contracts import DocumentInfo, PageContent
    from tests.fixtures.make_index import publish_index

    with tempfile.TemporaryDirectory(prefix="test_idx2_") as tmp:
        idx_dir = Path(tmp)

        # Publicar v1
        publish_index(idx_dir)

        store = IndexStore(index_dir=idx_dir)
        reader = store.get_reader()

        # Forzar primera lectura (carga v1)
        _ = reader.documents()
        assert reader.current_version() == "v1"

        # Publicar v2 manualmente
        v2 = store.new_version()
        assert v2 == "v2"

        doc_v2 = DocumentInfo(
            doc_id="doc-v2",
            title="Doc V2",
            source_kind="reporte",
            report_period="3T26",
            year=2026,
            quarter=3,
            lang="es",
            pages=1,
            filename="doc_v2.pdf",
        )
        pages_v2 = [PageContent(doc_id="doc-v2", page=1, text="Texto v2", chunk_ids=[])]
        store.publish(v2, {"version": "v2"}, [doc_v2], pages_v2)

        # El reader debe detectar el cambio de CURRENT y reabrir
        docs_v2 = reader.documents()
        assert reader.current_version() == "v2"
        assert any(d.doc_id == "doc-v2" for d in docs_v2)


# ─────────────────────────────────────────────────────────────────
# 7. sparse BM25 tokenizer
# ─────────────────────────────────────────────────────────────────

def test_sparse_number_normalization():
    """'1,273,193' se convierte al token '1273193' (sin separador de miles)."""
    from app.retrieval.sparse import tokenize

    tokens = tokenize("El monto fue de 1,273,193 pesos")
    assert "1273193" in tokens, f"Tokens: {tokens}"
    assert "1" not in tokens  # no debe quedar el fragmento "1"
    assert "273" not in tokens


def test_sparse_period_as_single_term():
    """'2T26' se convierte al token '2t26' (periodo como término único)."""
    from app.retrieval.sparse import tokenize

    tokens = tokenize("Resultado del 2T26 fue positivo")
    assert "2t26" in tokens, f"Tokens: {tokens}"
    # No debe fragmentarse en "2" y "t26"
    assert "t26" not in tokens


def test_sparse_vectors_distinct():
    """3 textos distintos producen 3 vectores document distintos."""
    from app.retrieval.sparse import document_vector

    texts = [
        "Utilidad neta 2T26",
        "Cartera de crédito 1T26",
        "Índice de morosidad 2025",
    ]
    vecs = [document_vector(t) for t in texts]

    # Cada vector debe tener al menos un índice
    for v in vecs:
        assert len(v) > 0

    # Los tres deben ser distintos
    assert vecs[0] != vecs[1]
    assert vecs[1] != vecs[2]
    assert vecs[0] != vecs[2]
