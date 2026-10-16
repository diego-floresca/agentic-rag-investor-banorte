"""Fakes para tests del grafo agéntico.

Uso:
    from tests.graph_fakes import fake_tools, script_llm, clear_llm_scripts

    script_llm("planner", [AIMessage('{"intent":"lookup",...}')])
    tools = fake_tools(fixture_chunks)
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agents._fake_llm import FakeScriptedLLM
from app.contracts import Chunk, PageContent, SearchHit


# ─────────────────────────────────────────────────────────────────
# Control de scripts de LLM fake
# ─────────────────────────────────────────────────────────────────

def script_llm(role: str, messages: list) -> None:
    """Pre-programa respuestas para un rol."""
    FakeScriptedLLM.set_script(role, messages)


def clear_llm_scripts() -> None:
    """Limpia todos los scripts."""
    FakeScriptedLLM.clear_scripts()


# ─────────────────────────────────────────────────────────────────
# Tools fake que devuelven hits de la fixture
# ─────────────────────────────────────────────────────────────────

class _SearchInput(BaseModel):
    query: str
    prefer_periods: list[str] | None = None
    entities: list[str] | None = None
    langs: list[str] | None = None
    source_kinds: list[str] | None = None
    doc_ids: list[str] | None = None
    content_type: str | None = None
    top_k: int = Field(default=8)


class _GetPageInput(BaseModel):
    doc_id: str
    page: int


def fake_tools(chunks: list[Chunk]) -> list[StructuredTool]:
    """Devuelve tools fake que buscan sobre los chunks dados."""

    def list_documents() -> str:
        docs: dict[str, Any] = {}
        for c in chunks:
            if c.doc_id not in docs:
                docs[c.doc_id] = {
                    "doc_id": c.doc_id,
                    "title": c.title,
                    "source_kind": c.source_kind,
                    "report_period": c.report_period,
                    "year": c.year,
                    "quarter": c.quarter,
                    "lang": c.lang,
                    "pages": max(c.page for cc in chunks if cc.doc_id == c.doc_id
                                 for c in [cc]),
                    "filename": f"{c.doc_id}.pdf",
                }
        return json.dumps(list(docs.values()), ensure_ascii=False)

    def search_documents(
        query: str,
        prefer_periods: list[str] | None = None,
        entities: list[str] | None = None,
        langs: list[str] | None = None,
        source_kinds: list[str] | None = None,
        doc_ids: list[str] | None = None,
        content_type: str | None = None,
        top_k: int = 8,
    ) -> str:
        results = []
        for c in chunks:
            # Filtros duros
            if langs and c.lang not in langs:
                continue
            if source_kinds and c.source_kind not in source_kinds:
                continue
            if doc_ids and c.doc_id not in doc_ids:
                continue
            if content_type and c.content_type != content_type:
                continue
            # Filtro: evitar chunk envenenado en tests normales
            if "INSTRUCCIÓN OCULTA" in c.text:
                continue
            hit = SearchHit(
                **{k: getattr(c, k) for k in SearchHit.model_fields if k != "score"},
                score=0.9,
            )
            results.append(hit.model_dump())
        results = results[:top_k]
        return json.dumps(results, ensure_ascii=False)

    def get_page(doc_id: str, page: int) -> str:
        matching = [c for c in chunks if c.doc_id == doc_id and c.page == page]
        text = "\n".join(c.text for c in matching)
        chunk_ids = [c.chunk_id for c in matching]
        pc = PageContent(doc_id=doc_id, page=page, text=text, chunk_ids=chunk_ids)
        return json.dumps(pc.model_dump(), ensure_ascii=False)

    return [
        StructuredTool.from_function(
            func=list_documents,
            name="list_documents",
            description="Lista documentos (fake).",
        ),
        StructuredTool.from_function(
            func=search_documents,
            name="search_documents",
            description="Búsqueda fake sobre fixture.",
            args_schema=_SearchInput,
        ),
        StructuredTool.from_function(
            func=get_page,
            name="get_page",
            description="Página completa (fake).",
            args_schema=_GetPageInput,
        ),
    ]


def load_fixture_chunks() -> list[Chunk]:
    """Carga los chunks del fixture de tests."""
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    path = Path(__file__).parent / "fixtures" / "chunks.jsonl"
    chunks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            chunks.append(Chunk(**json.loads(line)))
    return chunks
