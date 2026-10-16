"""Runner real: construye el grafo una vez y traduce eventos a SSEEvent.

- Construye el grafo en la primera llamada (lazy).
- Usa astream con stream_mode="custom" para recibir eventos emitidos via get_stream_writer.
- Transmite la respuesta en trozos de ~20 caracteres.
- Ante excepción: emite error + done.
- Siempre termina en DoneEvent.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

from app.agents.graph import get_graph
from app.agents.observability import register as _register_otel
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
from app.config import settings

_CHUNK_SIZE = 20  # caracteres por TokenEvent

# Registrar observabilidad al importar (una vez)
_register_otel()

# Grafo compilado (singleton)
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = get_graph()
    return _graph


async def run_chat(session_id: str, message: str) -> AsyncIterator[SSEEvent]:
    """Ejecuta el grafo y emite SSEEvents."""
    start = time.monotonic()
    trace_id = str(uuid.uuid4())
    graph = _get_graph()

    yield StatusEvent(stage="guard", message="Validando pregunta")

    try:
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 20,
        }

        initial_state = {
            "question": message,
            "messages": [],
            "replans": 0,
            "tool_calls": 0,
            "llm_calls": 0,
        }

        final_state = None
        emitted_verification = False

        async for chunk in graph.astream(
            initial_state,
            config=config,
            stream_mode="custom",
        ):
            # chunk es lo que emitió get_stream_writer en los nodos
            event = _translate_custom_event(chunk)
            if event:
                yield event

        # Obtener estado final para extraer la respuesta y métricas
        final_state = await _get_final_state(graph, config)

        if final_state:
            # Emitir plan si existe
            if final_state.get("plan"):
                plan = final_state["plan"]
                yield PlanEvent(
                    intent=plan.intent,
                    entity=plan.entity,
                    subqueries=[sq.model_dump() for sq in plan.subqueries],
                )

            # Emitir verificación si existe y no se emitió ya
            if not emitted_verification and final_state.get("verification"):
                v = final_state["verification"]
                yield VerificationEvent(verdict=v.verdict, issues=v.issues)

            # Emitir respuesta en trozos
            answer = final_state.get("final_answer", "")
            if answer:
                yield StatusEvent(stage="output", message="Generando respuesta")
                for i in range(0, len(answer), _CHUNK_SIZE):
                    yield TokenEvent(text=answer[i:i + _CHUNK_SIZE])
                    await asyncio.sleep(0)

            # Emitir citaciones
            citations = final_state.get("citations", [])
            if citations:
                yield CitationsEvent(items=[c.model_dump() for c in citations])

            llm_calls = final_state.get("llm_calls", 0)
            tool_calls = final_state.get("tool_calls", 0)
        else:
            llm_calls = 0
            tool_calls = 0

    except Exception as exc:  # noqa: BLE001
        yield ErrorEvent(code="internal_error", message=str(exc))
        llm_calls = 0
        tool_calls = 0

    yield DoneEvent(
        trace_id=trace_id,
        latency_ms=int((time.monotonic() - start) * 1000),
        llm_calls=llm_calls,
        tool_calls=tool_calls,
    )


def _translate_custom_event(data: dict) -> SSEEvent | None:
    """Convierte un dict emitido por get_stream_writer en un SSEEvent."""
    if not isinstance(data, dict):
        return None
    event_type = data.get("type", "")
    try:
        if event_type == "status":
            return StatusEvent(stage=data["stage"], message=data["message"])
        if event_type == "plan":
            return PlanEvent(
                intent=data["intent"],
                entity=data["entity"],
                subqueries=data["subqueries"],
            )
        if event_type == "tool_call":
            return ToolCallEvent(
                agent=data["agent"],
                subquery_id=data["subquery_id"],
                tool=data["tool"],
                args=data["args"],
            )
        if event_type == "tool_result":
            return ToolResultEvent(
                agent=data["agent"],
                subquery_id=data["subquery_id"],
                tool=data["tool"],
                n_results=data["n_results"],
                pages=data["pages"],
            )
        if event_type == "finding":
            return FindingEvent(
                subquery_id=data["subquery_id"],
                sufficient=data["sufficient"],
                gap=data.get("gap"),
            )
        if event_type == "verification":
            return VerificationEvent(verdict=data["verdict"], issues=data["issues"])
    except (KeyError, TypeError):
        pass
    return None


async def _get_final_state(graph, config: dict) -> dict | None:
    """Obtiene el estado final del grafo desde el checkpoint."""
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.values:
            return snapshot.values
    except Exception:  # noqa: BLE001
        pass
    return None
