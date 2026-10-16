# Creado en P0. Dueño: T2. No lo borres.
"""
Herramientas LangChain que envuelven el servidor MCP o el retrieval directo.

Las 3 tools replican las funciones MCP (SPEC §Tools MCP):
  - list_documents()
  - search_documents(query, ...)
  - get_page(doc_id, page)

RETRIEVAL_MODE=mcp    → las tools llaman al servidor MCP vía HTTP (P4)
RETRIEVAL_MODE=direct → las tools llaman a IndexStore / retrieval directamente (P4)

get_tools() es la única función pública; la implementación completa es P4.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # para hints sin imports circulares


def get_tools() -> list:  # type: ignore[type-arg]
    """Devuelve la lista de LangChain tools para el grafo agéntico.

    Implementado en P4.  Los researcher nodes llaman esta función.
    """
    raise NotImplementedError("P4")
