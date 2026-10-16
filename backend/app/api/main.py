"""
API principal — Banorte IR Agent.

Rutas (SPEC §API):
  POST /api/chat        → SSE (EventSourceResponse, ping 15 s, timeout 45 s)
  POST /api/chat/sync   → respuesta síncrona con answer_md y citations
  GET  /api/documents   → catálogo de PDFs indexados
  GET  /api/files/{id}  → PDF inline desde DATA_DIR
  GET  /api/health      → estado: index, mcp, llm
  /mcp                  → servidor MCP streamable HTTP (montado)
  /                     → frontend estático (montado AL FINAL, solo si existe)

Límite de peticiones: RATE_LIMIT_PER_MIN por IP (X-Forwarded-For) para
/api/chat, /api/chat/sync y /mcp.
"""
from __future__ import annotations

import asyncio
import collections
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler as _default_http_handler
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agents import observability
from app.agents.runner import run_chat
from app.config import settings
from app.contracts import DoneEvent, ErrorEvent
from app.mcp_server.server import build_mcp
from app.retrieval.core import list_documents


# ── MCP (construir una vez al importar el módulo) ─────────────────────────────

_mcp = build_mcp()
_mcp_starlette = _mcp.streamable_http_app(streamable_http_path="/mcp")


# ── Rate limiter (ventana deslizante en memoria, por IP) ──────────────────────

class _RateLimiter:
    def __init__(self, limit: int, window_s: int = 60) -> None:
        self._limit = limit
        self._window = window_s
        self._lock = asyncio.Lock()
        self._hits: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)

    @staticmethod
    def _get_ip(request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def check(self, request: Request) -> bool:
        """True si la petición está permitida; False si excede el límite."""
        ip = self._get_ip(request)
        now = time.monotonic()
        async with self._lock:
            dq = self._hits[ip]
            while dq and now - dq[0] >= self._window:
                dq.popleft()
            if len(dq) >= self._limit:
                return False
            dq.append(now)
            return True

    def reset(self) -> None:
        """Reinicia todos los contadores (solo para tests)."""
        self._hits.clear()


_limiter = _RateLimiter(settings.RATE_LIMIT_PER_MIN)

_429_BODY = {
    "error": "rate_limit_exceeded",
    "message": "Demasiadas peticiones. Intenta en 1 minuto.",
}


async def _require_rate_limit(request: Request) -> None:
    if not await _limiter.check(request):
        raise HTTPException(status_code=429, detail=_429_BODY)


# ── ASGI wrapper para /mcp (evita BaseHTTPMiddleware en rutas streaming) ───────

class _RateLimitedAsgi:
    """Envuelve una ASGI app con comprobación de rate limit por IP."""

    def __init__(self, asgi_app, limiter: _RateLimiter) -> None:
        self._app = asgi_app
        self._limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            if not await self._limiter.check(request):
                response = JSONResponse(status_code=429, content=_429_BODY)
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI):
    observability.register()
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Banorte IR Agent", lifespan=_lifespan)


# ── Exception handler: 429 con JSON plano (consistente con /mcp) ──────────────

@app.exception_handler(HTTPException)
async def _http_ex_handler(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == 429 and isinstance(exc.detail, dict):
        return JSONResponse(status_code=429, content=exc.detail)
    return await _default_http_handler(request, exc)


# ── Modelos de request ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = Field(..., max_length=settings.MAX_MESSAGE_LEN)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_sse(event) -> dict[str, str]:
    return {"event": event.type, "data": event.model_dump_json()}


# ── POST /api/chat ─────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat_sse(body: ChatRequest, request: Request):
    """Streaming SSE con ping 15 s, timeout 45 s. Siempre termina en done."""
    await _require_rate_limit(request)

    async def _stream() -> AsyncGenerator[dict[str, str], None]:
        start = time.monotonic()
        trace_id = str(uuid.uuid4())
        try:
            async with asyncio.timeout(settings.TIMEOUT_S):
                async for event in run_chat(body.session_id, body.message):
                    yield _to_sse(event)
                    if event.type == "done":
                        return
        except TimeoutError:
            yield _to_sse(ErrorEvent(
                code="timeout",
                message="La consulta excedió el tiempo máximo.",
            ))
            yield _to_sse(DoneEvent(
                trace_id=trace_id,
                latency_ms=int((time.monotonic() - start) * 1000),
                llm_calls=0,
                tool_calls=0,
            ))
        except Exception as exc:  # noqa: BLE001
            yield _to_sse(ErrorEvent(code="internal_error", message=str(exc)))
            yield _to_sse(DoneEvent(
                trace_id=trace_id,
                latency_ms=int((time.monotonic() - start) * 1000),
                llm_calls=0,
                tool_calls=0,
            ))

    return EventSourceResponse(
        _stream(),
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── POST /api/chat/sync ────────────────────────────────────────────────────────

@app.post("/api/chat/sync")
async def chat_sync(body: ChatRequest, request: Request):
    """Misma lógica que /api/chat pero devuelve JSON al final."""
    await _require_rate_limit(request)

    start = time.monotonic()
    tokens: list[str] = []
    citations: list[dict] = []
    plan: dict | None = None
    verification: dict | None = None
    trace_id = str(uuid.uuid4())
    latency_ms = 0
    llm_calls = 0
    tool_calls = 0

    async for event in run_chat(body.session_id, body.message):
        t = event.type
        if t == "token":
            tokens.append(event.text)
        elif t == "citations":
            citations = event.items
        elif t == "plan":
            plan = event.model_dump(exclude={"type"})
        elif t == "verification":
            verification = event.model_dump(exclude={"type"})
        elif t == "done":
            trace_id = event.trace_id
            latency_ms = event.latency_ms
            llm_calls = event.llm_calls
            tool_calls = event.tool_calls

    return {
        "answer_md": "".join(tokens),
        "citations": citations,
        "plan": plan,
        "verification": verification,
        "trace_id": trace_id,
        "latency_ms": latency_ms or int((time.monotonic() - start) * 1000),
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
    }


# ── GET /api/documents ────────────────────────────────────────────────────────

@app.get("/api/documents")
async def get_documents():
    """Lista todos los PDFs indexados con sus metadatos."""
    return [d.model_dump() for d in await list_documents()]


# ── GET /api/files/{doc_id} ───────────────────────────────────────────────────

@app.get("/api/files/{doc_id}")
async def get_file(doc_id: str):
    """Sirve el PDF original inline. Valida doc_id contra el catálogo."""
    docs_map = {d.doc_id: d for d in await list_documents()}
    if doc_id not in docs_map:
        raise HTTPException(status_code=404, detail=f"doc_id '{doc_id}' no encontrado en el catálogo.")
    doc = docs_map[doc_id]
    # Prevenir path traversal: resolver y validar que queda dentro de DATA_DIR
    data_dir = settings.DATA_DIR.resolve()
    file_path = (settings.DATA_DIR / doc.filename).resolve()
    try:
        file_path.relative_to(data_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Archivo '{doc.filename}' no disponible.")
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


# ── GET /api/health ───────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Estado del servicio: index, mcp (list_tools < 2 s), llm."""
    # Índice
    current_file = settings.INDEX_DIR / "CURRENT"
    if current_file.exists():
        index_status = "ok"
        index_version: str | None = current_file.read_text(encoding="utf-8").strip()
    else:
        index_status = "no_index"
        index_version = None

    # MCP: list_tools directamente sobre la instancia (sin HTTP, < 2 s)
    try:
        tools = await asyncio.wait_for(_mcp.list_tools(), timeout=2.0)
        mcp_status = "ok"
        mcp_n_tools = len(tools)
    except Exception as exc:  # noqa: BLE001
        mcp_status = f"error: {exc}"
        mcp_n_tools = 0

    # LLM
    llm_status = "ok" if settings.GEMINI_API_KEY else "no_key"

    return {
        "api": "ok",
        "index": index_status,
        "index_version": index_version,
        "mcp": mcp_status,
        "mcp_tools": mcp_n_tools,
        "llm": llm_status,
    }


# ── /mcp (MCP streamable HTTP, con rate limit) ────────────────────────────────

app.mount("/mcp", _RateLimitedAsgi(_mcp_starlette, _limiter))


# ── / (frontend estático, AL FINAL) ──────────────────────────────────────────
# La ruta de frontend/out funciona tanto en dev (4 padres arriba de main.py
# = raíz del repo) como en el contenedor (/app/backend/app/api/main.py → /app).

_frontend_out = Path(__file__).resolve().parents[3] / "frontend" / "out"
if _frontend_out.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_out), html=True), name="static")
