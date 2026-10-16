"""Nodo planner: genera el Plan de búsqueda a partir de la pregunta.

Una sola llamada LLM (MODEL_GUARD). Recibe los últimos 6 mensajes del
historial y el catálogo de documentos indexados para restringir periodos.

Reglas:
- Solo periodos que existen en el catálogo; si no existe → direct_answer.
- query_es y query_en con terminología del idioma.
- prefer_periods y entities son filtros blandos (no excluyen).
- En comparativas: primero UNA subconsulta al doc más reciente que
  trae ambos periodos en la misma tabla; subqueries secundarias si falta.
- Máximo MAX_SUBQUERIES subconsultas.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_llm
from app.config import settings
from app.contracts import Filters, GraphState, Plan, SubQuery


_SYSTEM_PROMPT = """Eres el planificador de un sistema RAG sobre reportes financieros de inversionistas de Banorte.

Tu tarea: dado el historial de conversación y el catálogo de documentos, genera un Plan en JSON.

ESQUEMA DE SALIDA (JSON puro, sin markdown):
{
  "intent": "lookup"|"comparativa"|"calculo"|"conversacional"|"fuera_de_alcance",
  "entity": "<área del negocio: grupo|cartera|captacion|resultados|capital|balance|otro>",
  "subqueries": [
    {
      "id": "sq-0",
      "query_es": "<consulta en español con terminología financiera>",
      "query_en": "<misma consulta en inglés con terminología financiera>",
      "filters": {
        "prefer_periods": ["2T26"],
        "entities": ["cartera"],
        "langs": null,
        "source_kinds": null,
        "doc_ids": null,
        "content_type": null
      }
    }
  ],
  "needs_calc": false,
  "direct_answer": null
}

CLASIFICACIÓN DE INTENT — PRIORIDAD ALTA (evalúa PRIMERO):
- "conversacional": saludos ("hola", "buenos días"), preguntas sobre qué hace el sistema ("¿para qué sirves?", "¿qué puedes hacer?", "¿para qué estás diseñado?"), despedidas, agradecimientos, o cualquier pregunta que NO requiera buscar en los reportes. Usa direct_answer con una respuesta breve en español.
- "fuera_de_alcance": preguntas que no tienen relación con reportes financieros o el negocio de Banorte (clima, recetas, código, etc.). Usa direct_answer explicando el alcance.
- "lookup": buscar una cifra concreta en el corpus (utilidad, cartera, ratio, etc.).
- "comparativa": comparar dos periodos o entidades.
- "calculo": calcular un ratio o variación a partir de cifras del corpus.

REGLAS:
1. Si intent es "conversacional" o "fuera_de_alcance": subqueries=[], direct_answer con la respuesta. NO generes subqueries para estas intenciones.
2. Solo usa periodos del catálogo. Si el periodo pedido no existe: direct_answer explicando que no hay datos.
3. En comparativas (2 periodos): PRIMERO una subconsulta al documento más reciente con prefer_periods=[ambos].
4. Máximo """ + str(settings.MAX_SUBQUERIES) + """ subconsultas.
5. needs_calc=true solo si hay que calcular un ratio o variación no disponible directamente.
6. filters.prefer_periods y filters.entities son BLANDOS: orientan sin excluir.

EJEMPLOS DE CONVERSACIONAL:
- "hola" → intent: "conversacional", direct_answer: "¡Hola! Soy el asistente de relación con inversionistas de Banorte. Puedo ayudarte a consultar cifras financieras de los reportes trimestrales, presentaciones y estados financieros. ¿Qué deseas saber?"
- "¿para qué estás diseñado?" → intent: "conversacional", direct_answer: "Estoy diseñado para responder preguntas sobre los reportes de relación con inversionistas de Banorte: utilidades, cartera, captación, capital, resultados y más. Pregúntame sobre cualquier cifra financiera de los periodos disponibles."
- "gracias" → intent: "conversacional", direct_answer: "Con gusto. ¿Hay algo más en lo que pueda ayudarte?"
"""


def planner_node(state: GraphState) -> dict:
    """Genera un Plan a partir de la pregunta y el historial."""
    question = state.question

    # Catálogo de periodos disponibles
    catalog_summary = _build_catalog_summary()

    # Últimos 6 mensajes del historial (contexto de conversación)
    history_msgs = list(state.messages)[-6:] if state.messages else []
    history_text = _format_history(history_msgs)

    replan_ctx = ""
    if state.replans > 0 and state.plan:
        issues = []
        if state.verification:
            issues = state.verification.issues
        replan_ctx = (
            f"\n\nEsta es una REPLANIFICACIÓN (intento {state.replans}).\n"
            f"Plan anterior: {state.plan.model_dump_json()}\n"
            f"Problemas del verificador: {issues}\n"
            "Genera un plan diferente que resuelva los problemas."
        )

    user_content = (
        f"Catálogo de documentos disponibles:\n{catalog_summary}\n\n"
        f"Historial reciente:\n{history_text}\n\n"
        f"Pregunta actual: {question}"
        f"{replan_ctx}"
    )

    llm = get_llm("planner")
    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        plan = _parse_plan(content)
    except Exception as exc:  # noqa: BLE001
        # Fallback: plan directo con error
        plan = Plan(
            intent="fuera_de_alcance",
            entity="grupo",
            subqueries=[],
            direct_answer=f"Error al planificar: {exc}",
        )

    return {"plan": plan, "llm_calls": state.llm_calls + 1}


def _build_catalog_summary() -> str:
    """Devuelve una descripción breve del catálogo indexado."""
    try:
        import asyncio  # noqa: PLC0415
        from app.retrieval import core  # noqa: PLC0415

        async def _get():
            return await core.list_documents()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures  # noqa: PLC0415
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    docs = pool.submit(asyncio.run, _get()).result()
            else:
                docs = loop.run_until_complete(_get())
        except RuntimeError:
            docs = asyncio.run(_get())

        if not docs:
            return "Sin documentos indexados."
        lines = [f"- {d.doc_id}: {d.title} | periodo: {d.report_period}" for d in docs]
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return "Catálogo no disponible."


def _format_history(messages: list) -> str:
    if not messages:
        return "(sin historial)"
    parts = []
    for m in messages:
        role = type(m).__name__.replace("Message", "")
        content = m.content if hasattr(m, "content") else str(m)
        parts.append(f"{role}: {content[:200]}")
    return "\n".join(parts)


def _parse_plan(content: str) -> Plan:
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return Plan(
            intent="fuera_de_alcance",
            entity="grupo",
            subqueries=[],
            direct_answer="No pude interpretar la pregunta.",
        )
    try:
        data = json.loads(m.group())
        subqueries = []
        for sq in data.get("subqueries", [])[:settings.MAX_SUBQUERIES]:
            f = sq.get("filters", {}) or {}
            subqueries.append(SubQuery(
                id=sq.get("id", f"sq-{len(subqueries)}"),
                query_es=sq.get("query_es", ""),
                query_en=sq.get("query_en", ""),
                filters=Filters(
                    prefer_periods=f.get("prefer_periods"),
                    entities=f.get("entities"),
                    langs=f.get("langs"),
                    source_kinds=f.get("source_kinds"),
                    doc_ids=f.get("doc_ids"),
                    content_type=f.get("content_type"),
                ),
            ))
        intent = data.get("intent", "lookup")
        valid_intents = {"lookup", "comparativa", "calculo", "conversacional", "fuera_de_alcance"}
        if intent not in valid_intents:
            intent = "lookup"
        return Plan(
            intent=intent,  # type: ignore[arg-type]
            entity=data.get("entity", "grupo"),
            subqueries=subqueries,
            needs_calc=bool(data.get("needs_calc", False)),
            direct_answer=data.get("direct_answer"),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return Plan(
            intent="fuera_de_alcance",
            entity="grupo",
            subqueries=[],
            direct_answer="No pude interpretar el plan.",
        )
