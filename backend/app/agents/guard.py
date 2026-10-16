"""Nodo input_guard: valida y sanea la pregunta del usuario.

Reglas deterministas aplicadas antes del LLM:
- Longitud: máx. settings.MAX_MESSAGE_LEN caracteres.
- Patrones de inyección en español e inglés.
- Enmascaramiento de CURP, RFC y tarjetas.
- Pedir consejo de inversión NO se bloquea: se marca en flags para que
  output_guard agregue el aviso reglamentario.

GuardResult.allowed=False → el grafo termina con error guard_blocked.
GuardResult.flags contiene etiquetas como "investment_advice".
"""
from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from app.agents.llm import extract_text, get_llm
from app.config import settings
from app.contracts import GraphState, GuardResult

# ─────────────────────────────────────────────────────────────────
# Patrones de inyección (deterministas)
# ─────────────────────────────────────────────────────────────────

_INJECTION_PATTERNS: list[re.Pattern] = [
    # Clásico "ignora tus instrucciones"
    re.compile(r"ignor[ae]\s+(tus|sus|las|todas\s+las)\s+instrucciones", re.I),
    re.compile(r"ignore\s+(your|all|previous|prior)\s+instructions", re.I),
    re.compile(r"disregard\s+(your|all|previous|prior)\s+instructions", re.I),
    re.compile(r"forget\s+(everything|all|your)\s+(?:previous\s+)?instructions", re.I),
    # Jailbreak
    re.compile(r"\bDAN\b"),
    re.compile(r"act\s+as\s+(?:an?\s+)?(?:unrestricted|jailbroken|evil|DAN)", re.I),
    re.compile(r"actúa\s+como\s+(?:una?\s+)?(?:IA|inteligencia)?\s*sin\s+restricciones", re.I),
    # Exfiltración de system prompt
    re.compile(r"(repeat|print|show|reveal|tell me)\s+(your\s+)?(system\s+prompt|instructions)", re.I),
    re.compile(r"(repite|muestra|revela|dime)\s+(tu\s+)?(prompt|instrucciones\s+del\s+sistema)", re.I),
    # Delimitadores de prompt típicos
    re.compile(r"<\s*/?system\s*>", re.I),
    re.compile(r"\[INST\]|\[/INST\]"),
]

# Consejo de inversión (se marca, no se bloquea)
_ADVICE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(debes?|deberías?|conviene?|recomiend[ao]|aconsej[ao])\s+(comprar|vender|invertir)", re.I),
    re.compile(r"\b(should|recommend|advise)\s+(buy|sell|invest)", re.I),
    re.compile(r"\b(qué|cuál|cómo)\s+(acción|acción|accion|stock|título)\s+(comprar|vender)", re.I),
]

# PII — máscaras (se reemplazan antes de enviar al LLM)
_PII_RULES: list[tuple[re.Pattern, str]] = [
    # CURP: 18 caracteres alfanuméricos con patrón específico
    (re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b"), "[CURP]"),
    # RFC persona física (13) o moral (12)
    (re.compile(r"\b[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}\b"), "[RFC]"),
    # Tarjetas de crédito/débito (13-19 dígitos, con o sin separadores)
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[TARJETA]"),
]


def _mask_pii(text: str) -> str:
    for pattern, replacement in _PII_RULES:
        text = pattern.sub(replacement, text)
    return text


def _check_injection(text: str) -> bool:
    """True si se detecta intento de inyección."""
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def _check_advice(text: str) -> bool:
    return any(p.search(text) for p in _ADVICE_PATTERNS)


# ─────────────────────────────────────────────────────────────────
# Nodo LangGraph
# ─────────────────────────────────────────────────────────────────

def input_guard_node(state: GraphState) -> dict:
    """Nodo input_guard: validación determinista + LLM safety check.

    Actualiza state con guard: GuardResult.
    """
    question = state.question or ""

    # 1. Longitud
    if len(question) > settings.MAX_MESSAGE_LEN:
        return {
            "guard": GuardResult(
                allowed=False,
                reason=f"Pregunta demasiado larga (máx. {settings.MAX_MESSAGE_LEN} caracteres).",
            )
        }

    # 2. Inyección de prompt (determinista)
    if _check_injection(question):
        return {
            "guard": GuardResult(
                allowed=False,
                reason="Pregunta bloqueada: intento de inyección de instrucciones detectado.",
                flags=["injection"],
            )
        }

    # 3. Enmascarar PII
    clean_question = _mask_pii(question)

    # 4. Consejo de inversión (marca pero no bloquea)
    flags: list[str] = []
    if _check_advice(clean_question):
        flags.append("investment_advice")

    # 5. LLM safety check (MODEL_GUARD)
    llm = get_llm("guard")
    prompt = (
        "Eres un guardia de seguridad para un sistema de preguntas sobre reportes financieros.\n"
        "Evalúa si la siguiente pregunta es apropiada para ese sistema.\n"
        "Responde SOLO en JSON con el esquema: "
        '{"allowed": bool, "reason": "...", "flags": [...]}\n'
        "Reglas:\n"
        "- Bloquea: preguntas sobre temas completamente ajenos (clima, recetas, código malicioso, etc.)\n"
        "- Bloquea: preguntas con contenido ofensivo o dañino\n"
        "- Permite: preguntas financieras, de negocio o sobre el corpus de reportes\n"
        "- Permite: saludos y preguntas de ayuda sobre el sistema\n"
        "- Si pide consejo de inversión: allowed=true, agrega 'investment_advice' a flags\n"
        f"\nPregunta: {clean_question}"
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = extract_text(response)
        result = _parse_guard_json(content, flags)
    except Exception:  # noqa: BLE001
        # Ante fallo del LLM: permitir con advertencia (fail-open para UX)
        result = GuardResult(allowed=True, reason="LLM guard no disponible.", flags=flags)

    return {"guard": result, "question": clean_question, "llm_calls": state.llm_calls + 1}


def _parse_guard_json(content: str, extra_flags: list[str]) -> GuardResult:
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    # Extrae primer objeto JSON del contenido
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return GuardResult(allowed=True, reason="respuesta no parseable", flags=extra_flags)
    try:
        data = json.loads(m.group())
        flags = list(data.get("flags", [])) + extra_flags
        return GuardResult(
            allowed=bool(data.get("allowed", True)),
            reason=str(data.get("reason", "")),
            flags=flags,
        )
    except (json.JSONDecodeError, KeyError):
        return GuardResult(allowed=True, reason="parse error", flags=extra_flags)
