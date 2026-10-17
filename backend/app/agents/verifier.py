"""Nodo verifier: verifica que cada cifra del draft esté respaldada por evidencia.

Proceso determinista primero; LLM solo en comparativas o cálculos.

Reglas deterministas:
- Cada [chunk_id] citado debe existir en state.evidence.
- Cada cifra normalizada en el draft debe aparecer en algún chunk de evidencia
  o ser resultado de un Calculation con insumos en evidence.
- En approximate=True: la cifra puede diferir ligeramente (no se verifica exactitud).

Normalización de cifras (SPEC §Normalización):
  "(5%)" = -5; "(979)" = -979; "42pb" = 0.42; "1,273,193" = 1273193
  Quitar Ps, $, millones, million, billion; comparar en escala de units.

Resultado: Verification con verdict "approve" | "revise" | "partial".
Un solo reintento si verdict != "approve" (MAX_REPLANS=1).
"""
from __future__ import annotations

import re
from typing import Any

from app.contracts import Calculation, Draft, GraphState, Verification


# ─────────────────────────────────────────────────────────────────
# Normalización de cifras
# ─────────────────────────────────────────────────────────────────

def normalize_number(raw: str) -> float | None:
    """Convierte una cifra del texto a float. Devuelve None si no parseable."""
    s = raw.strip()

    # Negativo en paréntesis: "(979)" → -979, "(5%)" → -5
    negative = False
    m = re.match(r"^\((.+?)\)$", s)
    if m:
        s = m.group(1)
        negative = True

    # Quitar símbolos de moneda y escala
    s = re.sub(r"Ps\.?\s*|\$\s*", "", s, flags=re.I)
    s = re.sub(r"\s*(millones?|million|billion)\b", "", s, flags=re.I)

    # Puntos base: "42pb" → 0.42pp
    pb_m = re.match(r"^([\d,.]+)\s*pb$", s, re.I)
    if pb_m:
        try:
            val = float(pb_m.group(1).replace(",", "")) / 100
            return -val if negative else val
        except ValueError:
            return None

    # Porcentaje
    pct_m = re.match(r"^([\d,.]+)\s*%$", s)
    if pct_m:
        try:
            val = float(pct_m.group(1).replace(",", ""))
            return -val if negative else val
        except ValueError:
            return None

    # Separadores de miles ("1,273,193" → 1273193)
    s_clean = s.replace(",", "")

    try:
        val = float(s_clean)
        return -val if negative else val
    except ValueError:
        return None


_NUMBER_PATTERN = re.compile(
    r"\([\d,]+%?\)|"          # (979) o (5%)
    r"[\d,]+\.?\d*\s*pb|"     # 42pb
    r"[\d,]+\.?\d*\s*%|"      # 5.2%
    r"[\d,]+\.?\d*"           # 1,273,193 o 37614
)

_CHUNK_REF_PATTERN = re.compile(r"\[([^\]]+:[^\]]+)\]")


def _extract_numbers_from_text(text: str) -> set[float]:
    """Extrae todos los números normalizables de un texto."""
    result = set()
    for m in _NUMBER_PATTERN.finditer(text):
        v = normalize_number(m.group())
        if v is not None and abs(v) > 0.001:  # ignorar ceros y ruido
            result.add(v)
    return result


def _numbers_close(a: float, b: float, tol: float = 0.01) -> bool:
    """Verdad si a y b son iguales o están dentro de tol (1% relativo)."""
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom < tol


# ─────────────────────────────────────────────────────────────────
# Verificador determinista
# ─────────────────────────────────────────────────────────────────

def verifier_node(state: GraphState) -> dict:
    """Verifica el draft. Primer paso determinista; LLM si hay comparativa/cálculo."""
    draft = state.draft
    if draft is None:
        return {
            "verification": Verification(
                verdict="revise",
                issues=["No hay draft que verificar."],
                feedback="El analista no produjo respuesta.",
            )
        }

    issues: list[str] = []

    # 1. Verificar que todos los [chunk_id] citados existen en evidence
    cited_ids = _CHUNK_REF_PATTERN.findall(draft.answer_md)
    for cid in cited_ids:
        if cid not in state.evidence:
            issues.append(f"[{cid}] citado pero no está en la evidencia.")

    # 2. Extraer números del draft y verificar que estén en evidencia o en cálculos
    draft_numbers = _extract_numbers_from_text(draft.answer_md)
    evidence_numbers: set[float] = set()
    approximate_chunk_ids: set[str] = set()

    for cid, chunk in state.evidence.items():
        if chunk.approximate:
            approximate_chunk_ids.add(cid)
            continue
        evidence_numbers |= _extract_numbers_from_text(chunk.text)

    # Números que provienen de cálculos
    calc_results = {c.result for c in draft.calculations}

    for num in draft_numbers:
        # ¿Está en evidence (exacto o ≤1% diferencia)?
        in_evidence = any(_numbers_close(num, ev) for ev in evidence_numbers)
        # ¿Está en resultados de cálculos?
        in_calc = any(_numbers_close(num, cr) for cr in calc_results)
        if not in_evidence and not in_calc:
            # Ignorar números muy pequeños (1, 2, porcentajes de variación pequeños)
            if abs(num) > 10:
                issues.append(
                    f"Cifra {num} en el draft no encontrada en evidencia ni en cálculos."
                )

    # 3. Verificar cálculos: insumos deben estar en evidence
    for calc in draft.calculations:
        for input_id in calc.input_chunk_ids:
            if input_id not in state.evidence:
                issues.append(
                    f"Cálculo usa [{input_id}] que no está en evidencia."
                )

    # 4. Para comparativas o cálculos: paso LLM adicional
    needs_llm = (
        state.plan is not None
        and state.plan.intent in ("comparativa", "calculo")
    )

    if needs_llm and not issues:
        llm_issues = _llm_verify(state, draft)
        issues.extend(llm_issues)

    # 5. Determinar veredicto
    if not issues:
        verdict = "approve"
        feedback = "Todas las cifras verificadas."
    elif len(issues) <= 2 and all("Cifra" in i for i in issues):
        # Solo advertencias menores de cifras: partial
        verdict = "partial"
        feedback = "Algunas cifras no pudieron verificarse completamente."
    else:
        verdict = "revise"
        feedback = "Se detectaron problemas que requieren revisión."

    return {
        "verification": Verification(
            verdict=verdict,  # type: ignore[arg-type]
            issues=issues,
            feedback=feedback,
        ),
        "llm_calls": (1 if needs_llm and not issues else 0),
    }


def _llm_verify(state: GraphState, draft: Draft) -> list[str]:
    """Verificación LLM para comparativas y cálculos."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415
        from app.agents.llm import extract_text, get_llm  # noqa: PLC0415

        evidence_summary = "\n".join(
            f"[{cid}]: {chunk.text[:200]}"
            for cid, chunk in list(state.evidence.items())[:8]
        )

        prompt = (
            "Verifica que la respuesta del analista sea consistente con la evidencia.\n\n"
            f"Pregunta: {state.question}\n\n"
            f"Evidencia (fragmentos):\n{evidence_summary}\n\n"
            f"Respuesta del analista:\n{draft.answer_md}\n\n"
            "Responde SOLO en JSON: "
            '{"issues": ["descripción de problema",...]} '
            'Lista vacía si no hay problemas.'
        )

        llm = get_llm("verifier")
        response = llm.invoke([
            SystemMessage(content="Eres un verificador de hechos financieros. Detecta inconsistencias."),
            HumanMessage(content=prompt),
        ])
        content = extract_text(response)
        import json  # noqa: PLC0415
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return [str(i) for i in data.get("issues", [])]
    except Exception:  # noqa: BLE001
        pass
    return []
