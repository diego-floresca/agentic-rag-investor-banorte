"""
test_api.py — COMPUERTA C4 (API).

Verifica (httpx.ASGITransport, sin red):
  1. Orden SSE canónico: events incluyen done y done es el último.
  2. "bloquear" → error antes de done; done es el último.
  3. "error"    → error antes de done; done es el último.
  4. /sync arma answer_md (str) y citations (list).
  5. GET /api/files/<inválido> → 404.
  6. Petición 21 desde la misma IP → 429.
  7. GET /api/health → 200 con campo "api".
"""
from __future__ import annotations

import os

# Modos fake antes de cualquier importación de la app
os.environ.setdefault("EMBED_PROVIDER", "fake")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("RUNNER_MODE", "fake")

import pytest
import httpx

from app.api.main import app, _limiter


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    """AsyncClient con ASGITransport; resetea el rate limiter entre tests."""
    _limiter.reset()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _collect_sse_event_types(response: httpx.Response) -> list[str]:
    """Recoge los tipos de eventos SSE del stream (líneas 'event: <tipo>')."""
    types: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            types.append(line.split(":", 1)[1].strip())
    return types


# ── 1. Orden SSE canónico ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_sse_contains_done_at_end(client):
    """Secuencia canónica termina en done."""
    async with client.stream(
        "POST", "/api/chat",
        json={"message": "¿cuál fue la utilidad neta?"},
        headers={"X-Forwarded-For": "1.1.1.1"},
    ) as response:
        assert response.status_code == 200
        types = await _collect_sse_event_types(response)

    assert types, "No se recibieron eventos SSE"
    assert "done" in types, f"'done' no está en los eventos: {types}"
    assert types[-1] == "done", f"El último evento no es 'done': {types}"


# ── 2. "bloquear" → error + done ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_sse_bloquear(client):
    """Mensaje con 'bloquear' emite error y termina en done."""
    async with client.stream(
        "POST", "/api/chat",
        json={"message": "bloquear esto"},
        headers={"X-Forwarded-For": "1.1.1.2"},
    ) as response:
        assert response.status_code == 200
        types = await _collect_sse_event_types(response)

    assert "error" in types, f"Falta 'error' en: {types}"
    assert types[-1] == "done", f"El último evento no es 'done': {types}"
    # error debe aparecer antes de done
    assert types.index("error") < types.index("done")


# ── 3. "error" → error + done ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_sse_error(client):
    """Mensaje con 'error' emite error y termina en done."""
    async with client.stream(
        "POST", "/api/chat",
        json={"message": "causar error simulado"},
        headers={"X-Forwarded-For": "1.1.1.3"},
    ) as response:
        assert response.status_code == 200
        types = await _collect_sse_event_types(response)

    assert "error" in types, f"Falta 'error' en: {types}"
    assert types[-1] == "done", f"El último evento no es 'done': {types}"
    assert types.index("error") < types.index("done")


# ── 4. /sync arma answer_md y citations ───────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_sync_answer_md_and_citations(client):
    """/sync devuelve answer_md (str) y citations (list)."""
    response = await client.post(
        "/api/chat/sync",
        json={"message": "¿cuál fue la utilidad neta?"},
        headers={"X-Forwarded-For": "1.1.1.4"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer_md" in data, f"Falta answer_md en: {data.keys()}"
    assert isinstance(data["answer_md"], str)
    assert "citations" in data, f"Falta citations en: {data.keys()}"
    assert isinstance(data["citations"], list)
    assert len(data["answer_md"]) > 0, "answer_md está vacío"
    assert len(data["citations"]) > 0, "citations está vacía"


# ── 5. 404 en doc_id inválido ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_404_unknown_doc(client):
    """GET /api/files/<inválido> → 404."""
    response = await client.get("/api/files/doc-que-no-existe-xyzw-9999")
    assert response.status_code == 404


# ── 6. 429 en la petición 21 del minuto ──────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_429_on_21st_request(client):
    """La petición 21 desde la misma IP en 1 min recibe 429."""
    limit = 20
    ip_header = {"X-Forwarded-For": "10.99.0.1"}  # IP única para este test

    for i in range(limit):
        r = await client.post(
            "/api/chat/sync",
            json={"message": "hola"},
            headers=ip_header,
        )
        assert r.status_code == 200, f"Petición {i + 1} falló con {r.status_code}"

    r = await client.post(
        "/api/chat/sync",
        json={"message": "hola"},
        headers=ip_header,
    )
    assert r.status_code == 429, f"Esperado 429, recibido {r.status_code}"
    body = r.json()
    assert body.get("error") == "rate_limit_exceeded"


# ── 7. Health responde ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_responds(client):
    """GET /api/health → 200 con campo api='ok'."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("api") == "ok"
    assert "mcp" in data
    assert "llm" in data
    assert "index" in data
