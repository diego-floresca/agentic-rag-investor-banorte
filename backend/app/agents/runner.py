# Creado en P0. Dueño: T2. No lo borres.
"""
Runner: frontera entre el grafo agéntico y la API.

API pública:
    async run_chat(session_id, message) -> AsyncIterator[SSEEvent]

RUNNER_MODE=fake  → importa runner_fake (sin red, para tests y CI)
RUNNER_MODE=real  → importa runner_real (implementado en P4 por T2)

El import del runner real es perezoso (ocurre solo si RUNNER_MODE=real)
para no arrastrar dependencias de LangGraph en tests unitarios.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.config import settings
from app.contracts import SSEEvent

if TYPE_CHECKING:
    pass  # evita importaciones circulares en type hints


async def run_chat(session_id: str, message: str) -> AsyncIterator[SSEEvent]:
    """Ejecuta el grafo agéntico y emite SSEEvents.

    Parámetros
    ----------
    session_id : str
        Identificador de la sesión (para historial y trazas).
    message : str
        Mensaje del usuario (máx. settings.MAX_MESSAGE_LEN caracteres).

    Yields
    ------
    SSEEvent
        Eventos en orden: status → plan → tool_call/tool_result → finding
        → verification → token* → citations → done.
        Siempre termina en DoneEvent o ErrorEvent + DoneEvent.
    """
    mode = settings.RUNNER_MODE.lower()

    if mode == "fake":
        from app.agents.runner_fake import run_chat as _run  # noqa: PLC0415
        async for event in _run(session_id, message):
            yield event
    elif mode == "real":
        # Importación perezosa: no cargar LangGraph en tests que usan RUNNER_MODE=fake
        from app.agents.runner_real import run_chat as _run  # noqa: PLC0415  # type: ignore[import]
        async for event in _run(session_id, message):
            yield event
    else:
        raise ValueError(f"RUNNER_MODE desconocido: {mode!r}")
