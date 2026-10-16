"""
test_mcp.py — COMPUERTA C2 (MCP).

Verifica:
  1. build_mcp() registra exactamente 3 tools.
  2. El servidor aislado en :8101 lista 3 tools vía cliente MCP.
  3. Una búsqueda desde el servidor devuelve hits.
  4. get_tools("direct") y get_tools("mcp") exponen los mismos nombres.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import pytest

os.environ.setdefault("EMBED_PROVIDER", "fake")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("RUNNER_MODE", "fake")

_MCP_PORT = 8101
_MCP_URL = f"http://127.0.0.1:{_MCP_PORT}/mcp"

# ─────────────────────────────────────────────────────────────────
# Fixture: servidor en background
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mcp_server_url(fixture_index):
    """Inicia el servidor MCP en :8101 en un hilo daemon.

    fixture_index ya inyectó core._store en conftest.py.
    """
    from app.mcp_server.server import build_mcp

    mcp = build_mcp()

    def _run():
        asyncio.run(mcp.run_streamable_http_async(host="127.0.0.1", port=_MCP_PORT))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.6)  # esperar startup

    yield _MCP_URL


# ─────────────────────────────────────────────────────────────────
# 1. build_mcp tiene exactamente 3 tools (sin HTTP)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_mcp_has_3_tools(fixture_index):
    """build_mcp registra exactamente 3 tools."""
    from app.mcp_server.server import build_mcp

    mcp = build_mcp()
    tools = await mcp.list_tools()
    assert len(tools) == 3, f"Esperadas 3 tools, encontradas {len(tools)}"

    names = {t.name for t in tools}
    assert names == {"list_documents", "search_documents", "get_page"}


# ─────────────────────────────────────────────────────────────────
# 2. Servidor aislado en :8101 lista 3 tools
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_server_lists_3_tools(mcp_server_url):
    """El servidor HTTP en :8101 lista exactamente 3 tools vía cliente MCP."""
    from mcp.client.streamable_http import streamable_http_client
    from mcp.client.session import ClientSession

    async with streamable_http_client(mcp_server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            tools = result.tools
            assert len(tools) == 3, f"Esperadas 3 tools, encontradas {len(tools)}"
            names = {t.name for t in tools}
            assert names == {"list_documents", "search_documents", "get_page"}


# ─────────────────────────────────────────────────────────────────
# 3. Búsqueda desde servidor devuelve hits
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_search_returns_hits(mcp_server_url):
    """search_documents vía MCP HTTP devuelve al menos 1 hit."""
    import json
    from mcp.client.streamable_http import streamable_http_client
    from mcp.client.session import ClientSession

    async with streamable_http_client(mcp_server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_documents",
                {"query": "utilidad neta cartera", "top_k": 5},
            )
            # Extraer JSON del resultado
            assert not result.is_error, f"Tool retornó error: {result}"
            if result.structured_content and "result" in result.structured_content:
                hits_raw = result.structured_content["result"]
            else:
                # Fallback: parse TextContent
                hits_raw = json.loads(result.content[0].text)
            assert len(hits_raw) > 0, "La búsqueda debe devolver al menos 1 hit"


@pytest.mark.asyncio
async def test_mcp_list_documents_returns_docs(mcp_server_url):
    """list_documents vía MCP HTTP devuelve documentos del catálogo."""
    import json
    from mcp.client.streamable_http import streamable_http_client
    from mcp.client.session import ClientSession

    async with streamable_http_client(mcp_server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("list_documents", {})
            assert not result.is_error
            if result.structured_content and "result" in result.structured_content:
                value = result.structured_content["result"]
                # El tool devuelve JSON string; structured_content lo envuelve sin parsear
                docs = json.loads(value) if isinstance(value, str) else value
            else:
                docs = json.loads(result.content[0].text)
            assert len(docs) >= 1
            # Verificar que al menos un doc tiene los campos esperados
            assert "doc_id" in docs[0]
            assert "report_period" in docs[0]


# ─────────────────────────────────────────────────────────────────
# 4. get_tools("direct") y get_tools("mcp") mismos nombres
# ─────────────────────────────────────────────────────────────────

def test_get_tools_same_names_direct(fixture_index):
    """get_tools('direct') devuelve tools con los 3 nombres esperados."""
    from app.agents.tools import get_tools

    tools = get_tools("direct")
    names = {t.name for t in tools}
    assert names == {"list_documents", "search_documents", "get_page"}


def test_get_tools_same_names_mcp():
    """get_tools('mcp') devuelve tools con los mismos 3 nombres que 'direct'."""
    from app.agents.tools import get_tools

    direct_names = {t.name for t in get_tools("direct")}
    mcp_names = {t.name for t in get_tools("mcp")}
    assert direct_names == mcp_names, (
        f"direct: {direct_names}, mcp: {mcp_names}"
    )


def test_get_tools_unknown_mode_raises():
    """get_tools con modo desconocido lanza ValueError."""
    from app.agents.tools import get_tools

    with pytest.raises(ValueError, match="desconocido"):
        get_tools("invalid_mode")
