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


def _sv(state, key, default=None):
    """Lee un campo del estado que puede ser dict o Pydantic BaseModel."""
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)

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
        # thread_id fresco por mensaje: evita que el MemorySaver restaure
        # draft/findings/evidence de la iteración anterior y contamine la respuesta.
        # (findings usa reductor suma y no se puede resetear vía initial_state)
        run_thread_id = f"{session_id}:{uuid.uuid4()}"
        config = {
            "configurable": {"thread_id": run_thread_id},
            "recursion_limit": 20,
        }

        initial_state = {
            "question": message,
            "messages": [],
            "replans": 0,
            "tool_calls": 0,
            "llm_calls": 0,
            # Campos limpiados explícitamente para campos sin reductor:
            "guard": None,
            "plan": None,
            "draft": None,
            "verification": None,
            "final_answer": None,
            "citations": [],
            "evidence": {},
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
            # snapshot.values puede ser dict o GraphState (Pydantic); _sv maneja ambos.

            # Emitir plan si existe
            plan_data = _sv(final_state, "plan")
            if plan_data:
                if isinstance(plan_data, dict):
                    yield PlanEvent(
                        intent=plan_data.get("intent", ""),
                        entity=plan_data.get("entity", ""),
                        subqueries=plan_data.get("subqueries", []),
                    )
                else:
                    yield PlanEvent(
                        intent=plan_data.intent,
                        entity=plan_data.entity,
                        subqueries=[
                            sq if isinstance(sq, dict) else sq.model_dump()
                            for sq in (plan_data.subqueries or [])
                        ],
                    )

            # Emitir verificación si existe y no se emitió ya
            v_data = _sv(final_state, "verification")
            if not emitted_verification and v_data:
                if isinstance(v_data, dict):
                    yield VerificationEvent(
                        verdict=v_data.get("verdict", "partial"),
                        issues=v_data.get("issues", []),
                    )
                else:
                    yield VerificationEvent(verdict=v_data.verdict, issues=v_data.issues)

            # Emitir respuesta en trozos
            answer = _sv(final_state, "final_answer") or ""
            if not answer:
                # Fallback: si final_answer está vacío pero el draft tiene contenido
                # (output_guard pudo fallar silenciosamente), usar draft.answer_md
                draft_data = _sv(final_state, "draft")
                if draft_data:
                    answer = (
                        draft_data.get("answer_md", "")
                        if isinstance(draft_data, dict)
                        else getattr(draft_data, "answer_md", "")
                    ) or ""
            if answer:
                yield StatusEvent(stage="output", message="Generando respuesta")
                for i in range(0, len(answer), _CHUNK_SIZE):
                    yield TokenEvent(text=answer[i:i + _CHUNK_SIZE])
                    await asyncio.sleep(0)

            # Emitir citaciones
            citations = _sv(final_state, "citations") or []
            if citations:
                items = [c if isinstance(c, dict) else c.model_dump() for c in citations]
                yield CitationsEvent(items=items)

            llm_calls = _sv(final_state, "llm_calls") or 0
            tool_calls = _sv(final_state, "tool_calls") or 0
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
