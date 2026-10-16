# Creado en P0. Dueño: T2. No lo borres.
"""
runner_fake: emite la secuencia canónica de SSEEvents sin llamadas a red.

Secuencia canónica (SPEC §Runner):
  status → plan → tool_call → tool_result → finding → verification
  → token → token → citations → done

Variantes:
  mensaje contiene "bloquear"  → status + error(guard_blocked) + done
  mensaje contiene "error"     → status + error(internal_error) + done
  cualquier otro               → secuencia canónica

Siempre termina en DoneEvent.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

from app.contracts import (
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    FindingEvent,
    PlanEvent,
    SSEEvent,
    StatusEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    VerificationEvent,
)

# Secuencia canónica
_FAKE_SUB_ID = "sq-0"
_FAKE_CHUNK_ID = "empresa-ficticia:p1:c0"


async def run_chat(session_id: str, message: str) -> AsyncIterator[SSEEvent]:
    """Emite la secuencia de SSEEvents sin red.  Ver cabecera del módulo."""
    start = time.monotonic()
    trace_id = str(uuid.uuid4())

    yield StatusEvent(stage="guard", message="Validando pregunta")
    await asyncio.sleep(0)

    msg_lower = message.lower()

    # ── Variante: bloquear ────────────────────────────────────────
    if "bloquear" in msg_lower:
        yield ErrorEvent(
            code="guard_blocked",
            message="Pregunta fuera de alcance o no permitida.",
        )
        yield DoneEvent(
            trace_id=trace_id,
            latency_ms=int((time.monotonic() - start) * 1000),
            llm_calls=0,
            tool_calls=0,
        )
        return

    # ── Variante: error ───────────────────────────────────────────
    if "error" in msg_lower:
        yield ErrorEvent(
            code="internal_error",
            message="Error interno simulado por runner_fake.",
        )
        yield DoneEvent(
            trace_id=trace_id,
            latency_ms=int((time.monotonic() - start) * 1000),
            llm_calls=0,
            tool_calls=0,
        )
        return

    # ── Secuencia canónica ────────────────────────────────────────
    yield StatusEvent(stage="planner", message="Planificando consulta")
    await asyncio.sleep(0)

    yield PlanEvent(
        intent="lookup",
        entity="grupo",
        subqueries=[{"id": _FAKE_SUB_ID, "query_es": message, "query_en": message}],
    )
    await asyncio.sleep(0)

    yield StatusEvent(stage="researcher", message="Buscando evidencia")
    await asyncio.sleep(0)

    yield ToolCallEvent(
        agent="researcher",
        subquery_id=_FAKE_SUB_ID,
        tool="search_documents",
        args={"query": message, "top_k": 8},
    )
    await asyncio.sleep(0)

    yield ToolResultEvent(
        agent="researcher",
        subquery_id=_FAKE_SUB_ID,
        tool="search_documents",
        n_results=1,
        pages=[1],
    )
    await asyncio.sleep(0)

    yield FindingEvent(
        subquery_id=_FAKE_SUB_ID,
        sufficient=True,
        gap=None,
    )
    await asyncio.sleep(0)

    yield StatusEvent(stage="verifier", message="Verificando cifras")
    await asyncio.sleep(0)

    yield VerificationEvent(
        verdict="approve",
        issues=[],
    )
    await asyncio.sleep(0)

    yield StatusEvent(stage="output", message="Generando respuesta")
    await asyncio.sleep(0)

    yield TokenEvent(text="Respuesta ")
    await asyncio.sleep(0)
    yield TokenEvent(text="simulada.")
    await asyncio.sleep(0)

    yield CitationsEvent(
        items=[
            {
                "n": 1,
                "chunk_id": _FAKE_CHUNK_ID,
                "doc_id": "empresa-ficticia",
                "title": "Empresa Ficticia — Reporte 2T26",
                "report_period": "2T26",
                "page": 1,
            }
        ]
    )
    await asyncio.sleep(0)

    yield DoneEvent(
        trace_id=trace_id,
        latency_ms=int((time.monotonic() - start) * 1000),
        llm_calls=1,
        tool_calls=1,
    )
