# Creado en P0. Dueño: T2. No lo borres.
"""
LangChain StructuredTool wrappers para las 3 funciones de retrieval.

Modos (RETRIEVAL_MODE):
  direct: llama a app.retrieval.core directamente (sin red).
  mcp:    llama al servidor MCP vía HTTP (usa mcp 2.x SDK, NO langchain-mcp-adapters
          que es incompatible con mcp ≥ 2.x).

Las 3 tools exponen los mismos nombres y esquemas en ambos modos:
  list_documents, search_documents, get_page

get_tools(mode) es la única función pública; llámala en cada nodo del grafo
que necesite tools (planner, researcher). Las tools son stateless.
"""
from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.config import settings


# ─────────────────────────────────────────────────────────────────
# Esquemas de entrada (Pydantic v2)
# ─────────────────────────────────────────────────────────────────

class _ListDocumentsInput(BaseModel):
    pass  # sin parámetros


class _SearchDocumentsInput(BaseModel):
    query: str = Field(description="Consulta en español o inglés (máx. 500 caracteres)")
    prefer_periods: Optional[list[str]] = Field(
        default=None,
        description="Periodos preferidos, e.g. ['2T26', '1T26']. Blando: no excluye.",
    )
    entities: Optional[list[str]] = Field(
        default=None,
        description="Entidades/áreas preferidas, e.g. ['cartera', 'resultados']. Blando.",
    )
    langs: Optional[list[str]] = Field(
        default=None,
        description="Filtro duro de idioma, e.g. ['es'] o ['en'].",
    )
    source_kinds: Optional[list[str]] = Field(
        default=None,
        description="Filtro duro de tipo: 'reporte','anual','presentacion','transcripcion',...",
    )
    doc_ids: Optional[list[str]] = Field(
        default=None,
        description="Filtro duro: lista exacta de doc_id.",
    )
    content_type: Optional[str] = Field(
        default=None,
        description="Filtro duro: 'prose'|'table'|'figure'|'page_text'.",
    )
    top_k: int = Field(default=8, ge=1, le=20, description="Número de resultados (máx. 20).")


class _GetPageInput(BaseModel):
    doc_id: str = Field(description="Identificador del documento (slug del nombre de archivo).")
    page: int = Field(ge=1, description="Número de página (base 1).")


# ─────────────────────────────────────────────────────────────────
# Modo DIRECT
# ─────────────────────────────────────────────────────────────────

def _make_direct_tools() -> list[StructuredTool]:
    import asyncio  # noqa: PLC0415
    from app.retrieval import core  # noqa: PLC0415

    def _run_async(coro):
        """Ejecuta una coroutine desde contexto sync (runner usa asyncio en el grafo)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures  # noqa: PLC0415
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    async def _list_documents_async(**_kwargs) -> str:
        docs = await core.list_documents()
        return json.dumps([d.model_dump() for d in docs], ensure_ascii=False)

    async def _search_documents_async(
        query: str,
        prefer_periods: Optional[list[str]] = None,
        entities: Optional[list[str]] = None,
        langs: Optional[list[str]] = None,
        source_kinds: Optional[list[str]] = None,
        doc_ids: Optional[list[str]] = None,
        content_type: Optional[str] = None,
        top_k: int = 8,
    ) -> str:
        hits = await core.search_documents(
            query=query,
            prefer_periods=prefer_periods,
            entities=entities,
            langs=langs,
            source_kinds=source_kinds,
            doc_ids=doc_ids,
            content_type=content_type,
            top_k=top_k,
        )
        return json.dumps([h.model_dump() for h in hits], ensure_ascii=False)

    async def _get_page_async(doc_id: str, page: int) -> str:
        pc = await core.get_page(doc_id, page)
        return json.dumps(pc.model_dump(), ensure_ascii=False)

    return [
        StructuredTool.from_function(
            coroutine=_list_documents_async,
            name="list_documents",
            description=(
                "Lista todos los documentos indexados. "
                "Úsala para conocer doc_id y periodos antes de filtrar."
            ),
            args_schema=_ListDocumentsInput,
        ),
        StructuredTool.from_function(
            coroutine=_search_documents_async,
            name="search_documents",
            description=(
                "Búsqueda híbrida sobre el corpus. "
                "prefer_periods y entities son blandos (priorizan sin excluir). "
                "langs, source_kinds, doc_ids y content_type son duros."
            ),
            args_schema=_SearchDocumentsInput,
        ),
        StructuredTool.from_function(
            coroutine=_get_page_async,
            name="get_page",
            description=(
                "Texto crudo de una página completa. "
                "Usa doc_id y page de un SearchHit cuando necesitas más contexto."
            ),
            args_schema=_GetPageInput,
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# Modo MCP
# ─────────────────────────────────────────────────────────────────

def _make_mcp_tools(mcp_url: str) -> list[StructuredTool]:
    """Crea tools que llaman al servidor MCP vía HTTP.

    Usa mcp SDK 2.x directamente (NO langchain-mcp-adapters: incompatible con mcp ≥ 2).
    Crea una conexión nueva por llamada (stateless, adecuado para P3).
    """
    from mcp.client.streamable_http import streamable_http_client  # noqa: PLC0415
    from mcp.client.session import ClientSession  # noqa: PLC0415

    async def _call(tool_name: str, args: dict) -> str:
        async with streamable_http_client(mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                # structured_content['result'] tiene el valor deserializado
                if result.structured_content and "result" in result.structured_content:
                    value = result.structured_content["result"]
                    return json.dumps(value, ensure_ascii=False)
                # Fallback: concatenar TextContent
                texts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(texts)

    async def _list_documents_mcp(**_kwargs) -> str:
        return await _call("list_documents", {})

    async def _search_documents_mcp(
        query: str,
        prefer_periods: Optional[list[str]] = None,
        entities: Optional[list[str]] = None,
        langs: Optional[list[str]] = None,
        source_kinds: Optional[list[str]] = None,
        doc_ids: Optional[list[str]] = None,
        content_type: Optional[str] = None,
        top_k: int = 8,
    ) -> str:
        args = {
            "query": query,
            "prefer_periods": prefer_periods,
            "entities": entities,
            "langs": langs,
            "source_kinds": source_kinds,
            "doc_ids": doc_ids,
            "content_type": content_type,
            "top_k": top_k,
        }
        return await _call("search_documents", args)

    async def _get_page_mcp(doc_id: str, page: int) -> str:
        return await _call("get_page", {"doc_id": doc_id, "page": page})

    return [
        StructuredTool.from_function(
            coroutine=_list_documents_mcp,
            name="list_documents",
            description=(
                "Lista todos los documentos indexados. "
                "Úsala para conocer doc_id y periodos antes de filtrar."
            ),
            args_schema=_ListDocumentsInput,
        ),
        StructuredTool.from_function(
            coroutine=_search_documents_mcp,
            name="search_documents",
            description=(
                "Búsqueda híbrida sobre el corpus. "
                "prefer_periods y entities son blandos (priorizan sin excluir). "
                "langs, source_kinds, doc_ids y content_type son duros."
            ),
            args_schema=_SearchDocumentsInput,
        ),
        StructuredTool.from_function(
            coroutine=_get_page_mcp,
            name="get_page",
            description=(
                "Texto crudo de una página completa. "
                "Usa doc_id y page de un SearchHit cuando necesitas más contexto."
            ),
            args_schema=_GetPageInput,
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────

def get_tools(mode: str | None = None) -> list[StructuredTool]:
    """Devuelve las 3 LangChain tools en el modo configurado.

    mode: "direct" | "mcp" | None  (None → usa settings.RETRIEVAL_MODE)
    """
    effective_mode = (mode or settings.RETRIEVAL_MODE).lower()

    if effective_mode == "direct":
        return _make_direct_tools()

    if effective_mode == "mcp":
        mcp_url = f"http://{settings.MCP_HOST}:{settings.MCP_PORT}/mcp"
        return _make_mcp_tools(mcp_url)

    raise ValueError(
        f"RETRIEVAL_MODE desconocido: {effective_mode!r}. Usa 'direct' o 'mcp'."
    )
