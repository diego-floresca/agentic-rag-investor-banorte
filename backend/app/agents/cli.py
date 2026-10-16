"""CLI del agente: imprime un evento por línea (NDJSON).

Uso:
    uv run python -m app.agents.cli "¿Cuál fue la utilidad neta en 2T26?"

Variables de entorno:
    RUNNER_MODE=real       para usar el grafo real
    RETRIEVAL_MODE=direct  para búsqueda directa (sin MCP)
"""
from __future__ import annotations

import asyncio
import json
import sys
import time


async def _run(question: str) -> None:
    from app.agents.runner import run_chat  # noqa: PLC0415

    session_id = "cli-session"
    start = time.monotonic()

    async for event in run_chat(session_id, question):
        line = json.dumps(event.model_dump(), ensure_ascii=False)
        print(line, flush=True)

    elapsed = (time.monotonic() - start) * 1000
    print(f"[cli] latencia total: {elapsed:.0f} ms", file=sys.stderr)


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: uv run python -m app.agents.cli '<pregunta>'", file=sys.stderr)
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    asyncio.run(_run(question))


if __name__ == "__main__":
    main()
