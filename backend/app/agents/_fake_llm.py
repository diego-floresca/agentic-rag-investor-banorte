"""FakeChatModel guionizable para tests.

Uso en tests (graph_fakes.py):
    FakeScriptedLLM.set_script("analyst", [AIMessage("respuesta")])

El grafo llama get_llm(role); en tests usa LLM_PROVIDER=fake.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


_scripts: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


class FakeScriptedLLM(BaseChatModel):
    """LLM determinista: consume respuestas pre-programadas por rol."""

    role: str = "default"

    @classmethod
    def set_script(cls, role: str, messages: list[BaseMessage]) -> None:
        with _lock:
            _scripts[role].extend(messages)

    @classmethod
    def clear_scripts(cls) -> None:
        with _lock:
            _scripts.clear()

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        with _lock:
            q = _scripts[self.role]
            if q:
                msg = q.popleft()
            else:
                # Sin script: devuelve JSON vacío según rol
                msg = AIMessage(content=_default_response(self.role))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "fake_scripted"

    # Necesario para with_structured_output
    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


def _default_response(role: str) -> str:
    defaults = {
        "guard": '{"allowed": true, "reason": "ok", "flags": []}',
        "planner": (
            '{"intent": "lookup", "entity": "grupo", "subqueries": ['
            '{"id": "sq-0", "query_es": "consulta", "query_en": "query",'
            ' "filters": {}}], "needs_calc": false, "direct_answer": null}'
        ),
        "analyst": '{"answer_md": "Respuesta fake.", "calculations": []}',
        "verifier": '{"verdict": "approve", "issues": [], "feedback": ""}',
    }
    return defaults.get(role, '{"allowed": true, "reason": "ok", "flags": []}')
