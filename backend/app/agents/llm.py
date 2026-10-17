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
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from app.config import settings

# Cargar el .env en os.environ para que MODEL_GUARD, MODEL_ANALYST,
# THINKING_* estén disponibles vía os.environ.get().
# pydantic-settings los lee para poblar Settings pero NO los exporta a os.environ.
_ENV_FILE = (Path(__file__).parent.parent.parent / ".env").resolve()
try:
    from dotenv import load_dotenv  # noqa: PLC0415
    load_dotenv(_ENV_FILE, override=False)  # override=False: las vars de shell tienen prioridad
except ImportError:
    pass


def extract_text(response_or_content) -> str:
    """Normaliza la respuesta de cualquier Gemini (incluyendo thinking).

    Gemini con thinking devuelve response.content como lista de partes
    [{type: "thinking", text: ...}, {type: "text", text: ...}].
    Esta función extrae y une solo las partes de texto.
    """
    raw = response_or_content.content if hasattr(response_or_content, "content") else response_or_content
    if isinstance(raw, list):
        return "\n".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in raw
        )
    return str(raw)


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
    from google.genai.types import AutomaticFunctionCallingConfig  # noqa: PLC0415

    suffix = _ROLE_UPPER.get(role, "GUARD")
    model_name = os.environ.get(f"MODEL_{suffix}", settings.LLM_MODEL)
    thinking_raw = os.environ.get(f"THINKING_{suffix}", "false").lower()
    use_thinking = thinking_raw in ("1", "true", "yes")

    kwargs: dict = {
        "model": model_name,
        "temperature": 0,
        "google_api_key": settings.GEMINI_API_KEY or None,
        # Deshabilitar AFC: el google-genai SDK lo activa por defecto.
        # AFC intenta ejecutar las tools dentro del SDK pero son StructuredTools
        # de LangChain que solo existen en nuestro proceso; Gemini no puede
        # llamarlas y devuelve contenido vacío.
        "model_kwargs": {
            "automatic_function_calling": AutomaticFunctionCallingConfig(disable=True),
        },
    }

    if use_thinking:
        # thinking_config con budget; si no tiene budget explícito usar "auto"
        kwargs["thinking_config"] = {"thinking_budget": "auto"}

    return ChatGoogleGenerativeAI(**kwargs)
