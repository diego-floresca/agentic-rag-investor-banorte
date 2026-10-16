# Creado en P0. Dueño: T2. No lo borres.
"""
Servidor MCP "banorte-ir" — expone 3 tools sobre el índice de PDFs.

Tecnología: mcp 2.x → MCPServer (FastMCP fue renombrado en 2.0).

Modos:
  montado en /mcp (P6 lo monta en la app FastAPI):
      from app.mcp_server.server import build_mcp
      mcp = build_mcp()
      mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp")
      # montar como sub-app en FastAPI

  aislado para pruebas y MCP Inspector (make mcp → :8001):
      python -m app.mcp_server --host 127.0.0.1 --port 8001

Tools (corpus puede ser bilingüe ES/EN):
  list_documents   → catálogo completo de PDFs indexados
  search_documents → búsqueda híbrida dense+BM25 con filtros y reranking
  get_page         → texto crudo de una página para contexto extendido
"""
from __future__ import annotations

import json
import logging

from mcp.server.mcpserver import MCPServer

from app.config import settings

logger = logging.getLogger(__name__)


def build_mcp() -> MCPServer:
    """Construye y devuelve el MCPServer con las 3 tools registradas."""

    mcp = MCPServer(
        name="banorte-ir",
        description=(
            "Servidor MCP de solo lectura sobre el corpus de relación con inversionistas. "
            "El corpus contiene reportes trimestrales, presentaciones, estados financieros y "
            "transcripciones de conferencias (puede estar en español e inglés). "
            "Los periodos se expresan como '2T26' (Q2 2026) o '2025' (anual). "
            "Un reporte típico incluye tablas con varios periodos; "
            "usa prefer_periods para priorizar —no excluir— periodos concretos."
        ),
    )

    # ── Tool: list_documents ─────────────────────────────────────

    @mcp.tool(
        description=(
            "Lista todos los documentos (PDFs) disponibles en el índice. "
            "Úsala primero para conocer qué documentos existen, sus doc_id, "
            "periodos (report_period) y tipos (source_kind). "
            "Útil para filtrar búsquedas posteriores con doc_ids o source_kinds."
        )
    )
    async def list_documents() -> str:
        from app.retrieval.core import list_documents as _list  # noqa: PLC0415

        docs = await _list()
        return json.dumps([d.model_dump() for d in docs], ensure_ascii=False)

    # ── Tool: search_documents ───────────────────────────────────

    @mcp.tool(
        description=(
            "Búsqueda semántica híbrida (dense + BM25 con RRF) sobre el corpus. "
            "Devuelve hasta top_k SearchHit (máximo 20), ordenados por relevancia. "
            "FILTROS BLANDOS (piden, no excluyen): "
            "  prefer_periods: lista de periodos preferidos, e.g. ['2T26', '1T26']. "
            "    El reporte de 2T26 contiene tablas con columnas para 2T25, 1T26 y 2T26. "
            "    Si el usuario pregunta '¿cuál fue la utilidad en 2T26?' usa prefer_periods=['2T26']. "
            "  entities: áreas del negocio (e.g. ['cartera', 'resultados']). "
            "FILTROS DUROS (excluyen): "
            "  langs: e.g. ['es'] o ['en'] — el corpus puede ser bilingüe. "
            "  source_kinds: ['reporte','anual','presentacion','transcripcion',...]. "
            "  doc_ids: lista exacta de doc_id del catálogo. "
            "  content_type: 'prose'|'table'|'figure'|'page_text'. "
            "Si no encuentras la cifra, prueba get_page para ver la página completa."
        )
    )
    async def search_documents(  # noqa: PLR0913
        query: str,
        prefer_periods: list[str] | None = None,
        entities: list[str] | None = None,
        langs: list[str] | None = None,
        source_kinds: list[str] | None = None,
        doc_ids: list[str] | None = None,
        content_type: str | None = None,
        top_k: int = 8,
    ) -> str:
        from app.retrieval.core import search_documents as _search  # noqa: PLC0415

        hits = await _search(
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

    # ── Tool: get_page ───────────────────────────────────────────

    @mcp.tool(
        description=(
            "Recupera el texto crudo de una página completa del documento. "
            "Úsala cuando un SearchHit no contiene suficiente contexto: "
            "pasa su doc_id y page para ver toda la página, incluyendo "
            "encabezados de tabla, notas al pie y texto contiguo. "
            "doc_id es el slug del nombre del archivo (en minúsculas, sin acentos). "
            "page es el número de página (base 1) del PDF original."
        )
    )
    async def get_page(doc_id: str, page: int) -> str:
        from app.retrieval.core import get_page as _get_page  # noqa: PLC0415

        pc = await _get_page(doc_id, page)
        return json.dumps(pc.model_dump(), ensure_ascii=False)

    return mcp


# ─────────────────────────────────────────────────────────────────
# Modo aislado (make mcp)
# ─────────────────────────────────────────────────────────────────

def main() -> None:
    """Inicia el servidor en modo aislado para pruebas y MCP Inspector."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Servidor MCP banorte-ir (aislado)")
    parser.add_argument("--host", default=settings.MCP_HOST, help="Host (default: %(default)s)")
    parser.add_argument("--port", type=int, default=settings.MCP_PORT, help="Puerto (default: %(default)s)")
    args = parser.parse_args()

    mcp = build_mcp()
    logger.info("Iniciando servidor MCP banorte-ir en %s:%d/mcp", args.host, args.port)
    asyncio.run(
        mcp.run_streamable_http_async(host=args.host, port=args.port)
    )


if __name__ == "__main__":
    main()
