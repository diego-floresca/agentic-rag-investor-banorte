"""Nodo output_guard: post-procesamiento de la respuesta final.

Acciones:
1. Bloquea recomendaciones de inversión explícitas en el draft.
2. Si guard.flags contiene "investment_advice": agrega aviso reglamentario.
3. Convierte referencias [chunk_id] en [n] numeradas.
4. Construye la lista de Citations con metadatos del chunk.
5. Escribe final_answer y citations en el estado.
"""
from __future__ import annotations

import re

from app.contracts import Citation, Draft, GraphState


_INVESTMENT_ADVICE_NOTICE = (
    "\n\n---\n"
    "> **Aviso:** Este sistema proporciona información financiera del corpus de reportes "
    "disponibles. No constituye asesoramiento de inversión. Consulta a un asesor financiero "
    "certificado antes de tomar decisiones de inversión."
)

# Patrones de recomendación en el draft (más estrictos que en guard)
_DRAFT_RECOMMENDATION_PATTERNS = [
    re.compile(r"\b(recomiendo|recomendamos|sugiero|sugiero|aconsejo)\s+(comprar|vender|invertir)", re.I),
    re.compile(r"\b(deberías?|debes?)\s+(comprar|vender|invertir)", re.I),
    re.compile(r"\b(I recommend|you should)\s+(buy|sell|invest)", re.I),
]

_CHUNK_REF = re.compile(r"\[([^\]]+:[^\]]+)\]")


def output_guard_node(state: GraphState) -> dict:
    """Post-procesa el draft y construye la respuesta final."""
    draft: Draft | None = state.draft
    if draft is None:
        # Sin draft: usar direct_answer del plan si existe
        direct = state.plan.direct_answer if state.plan else None
        return {
            "final_answer": direct or "No se encontró respuesta.",
            "citations": [],
        }

    answer = draft.answer_md

    # 1. Bloquear recomendaciones explícitas en el draft
    for pattern in _DRAFT_RECOMMENDATION_PATTERNS:
        if pattern.search(answer):
            answer = pattern.sub("[recomendación omitida]", answer)

    # 2. Añadir aviso si hay flag de consejo de inversión
    if state.guard and "investment_advice" in (state.guard.flags or []):
        answer += _INVESTMENT_ADVICE_NOTICE

    # 3. Convertir [chunk_id] → [n] y construir Citations
    citations: list[Citation] = []
    chunk_to_n: dict[str, int] = {}

    def _replace_ref(m: re.Match) -> str:
        cid = m.group(1)
        if cid not in chunk_to_n:
            n = len(chunk_to_n) + 1
            chunk_to_n[cid] = n
            # Construir Citation desde evidence
            chunk = state.evidence.get(cid)
            if chunk:
                citations.append(Citation(
                    n=n,
                    chunk_id=cid,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    report_period=chunk.report_period,
                    page=chunk.page,
                ))
            else:
                # chunk no en evidence: citar con datos mínimos
                parts = cid.split(":")
                citations.append(Citation(
                    n=n,
                    chunk_id=cid,
                    doc_id=parts[0] if parts else cid,
                    title=parts[0] if parts else cid,
                    report_period="—",
                    page=0,
                ))
        return f"[{chunk_to_n[cid]}]"

    answer_with_nums = _CHUNK_REF.sub(_replace_ref, answer)

    return {
        "final_answer": answer_with_nums,
        "citations": citations,
    }
