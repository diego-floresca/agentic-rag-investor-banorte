"""LLM factory.

Uso:
    llm = get_llm("guard")     # ChatGoogleGenerativeAI o FakeLLM según LLM_PROVIDER
    llm = get_llm("analyst")   # puede tener thinking habilitado si THINKING_ANALYST=true

Variables de entorno relevantes (pueden ir en .env):
    LLM_PROVIDER        gemini | fake
    MODEL_GUARD         modelo para guard/planner/verifier (default: settings.LLM_MODEL)
    MODEL_ANALYST       modelo para el analista (default: settings.LLM_MODEL)
    THINKING_GUARD      true|false (default: false)
    THINKING_ANALYST    true|false (default: false)
"""
from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel

from app.config import settings


def get_llm(role: str) -> BaseChatModel:
    """Devuelve un ChatModel configurado para el rol indicado.

    Roles conocidos: guard, planner, researcher, analyst, verifier
    LLM_PROVIDER=fake → FakeChatModel guionizable (para tests).
    LLM_PROVIDER=gemini → ChatGoogleGenerativeAI con temperatura 0.
    """
    provider = settings.LLM_PROVIDER.lower()

    if provider == "fake":
        from app.agents._fake_llm import FakeScriptedLLM  # noqa: PLC0415
        return FakeScriptedLLM(role=role)

    if provider == "gemini":
        return _make_gemini(role)

    raise ValueError(f"LLM_PROVIDER desconocido: {provider!r}. Usa 'gemini' o 'fake'.")


# ─────────────────────────────────────────────────────────────────
# Gemini
# ─────────────────────────────────────────────────────────────────

_ROLE_UPPER = {
    "guard": "GUARD",
    "planner": "GUARD",     # comparte modelo con guard (rápido)
    "researcher": "GUARD",
    "analyst": "ANALYST",
    "verifier": "GUARD",
}


def _make_gemini(role: str) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: PLC0415

    suffix = _ROLE_UPPER.get(role, "GUARD")
    model_name = os.environ.get(f"MODEL_{suffix}", settings.LLM_MODEL)
    thinking_raw = os.environ.get(f"THINKING_{suffix}", "false").lower()
    use_thinking = thinking_raw in ("1", "true", "yes")

    kwargs: dict = {
        "model": model_name,
        "temperature": 0,
        "google_api_key": settings.GEMINI_API_KEY or None,
    }

    if use_thinking:
        # thinking_config con budget; si no tiene budget explícito usar "auto"
        kwargs["thinking_config"] = {"thinking_budget": "auto"}

    return ChatGoogleGenerativeAI(**kwargs)
