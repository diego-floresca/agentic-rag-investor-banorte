"""Nodo researcher: busca evidencia para una SubQuery.

- Recibe una SubQuery (vía Send en modo full, o secuencialmente en modo simple).
- Hasta MAX_TOOL_CALLS_RESEARCHER llamadas a herramientas.
- Estrategia: busca en español → inglés → reformula → relaja filtros → get_page.
- Devuelve un Finding con evidence_ids y sufficient.
- Emite eventos SSE: tool_call, tool_result vía get_stream_writer.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.config import settings
from app.contracts import Chunk, Finding, GraphState, SubQuery


_SYSTEM_PROMPT = """Eres un investigador que busca evidencia en un corpus de reportes financieros.

Tienes acceso a:
- search_documents(query, prefer_periods, entities, langs, source_kinds, doc_ids, content_type, top_k)
- get_page(doc_id, page)

Reglas:
1. Busca primero en español con la query_es, luego en inglés con query_en si no hay suficiente evidencia.
2. Si los resultados no responden la pregunta, reformula la consulta con sinónimos financieros.
3. Si header_ok=false en un resultado, usa get_page para obtener la página completa.
4. Máximo """ + str(settings.MAX_TOOL_CALLS_RESEARCHER) + """ llamadas a herramientas en total.
5. Devuelve un JSON con: {"sufficient": bool, "evidence_ids": ["chunk_id",...], "gap": "...o null"}
6. evidence_ids: los chunk_ids más relevantes (máx. 6).
7. sufficient=false si no encontraste respuesta satisfactoria.

Responde SOLO con el JSON final cuando hayas terminado de buscar.
"""


def make_researcher_node(tools: list[BaseTool]):
    """Fábrica que crea el nodo researcher con las tools inyectadas."""

    tools_by_name = {t.name: t for t in tools}

    async def researcher_node(state: GraphState, subquery: SubQuery | None = None) -> dict:
        from langgraph.config import get_stream_writer  # noqa: PLC0415
        writer = get_stream_writer()

        # Puede llegar como Send payload o como campo del estado
        sq = subquery or (state.plan.subqueries[0] if state.plan and state.plan.subqueries else None)
        if sq is None:
            return {"findings": [Finding(subquery_id="unknown", sufficient=False, gap="Sin subconsulta")]}

        tool_calls_used = 0
        evidence_ids: list[str] = []
        new_evidence: dict[str, Chunk] = {}
        new_tool_calls = 0

        messages: list = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Subconsulta id={sq.id}\n"
                f"query_es: {sq.query_es}\n"
                f"query_en: {sq.query_en}\n"
                f"filters: {sq.filters.model_dump_json()}"
            )),
        ]

        from app.agents.llm import get_llm  # noqa: PLC0415
        llm = get_llm("researcher")
        llm_with_tools = llm.bind_tools(tools)

        while tool_calls_used < settings.MAX_TOOL_CALLS_RESEARCHER:
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            # ¿Terminó con JSON final?
            if not hasattr(response, "tool_calls") or not response.tool_calls:
                break

            for tc in response.tool_calls:
                if tool_calls_used >= settings.MAX_TOOL_CALLS_RESEARCHER:
                    break
                tool_name = tc["name"]
                tool_args = tc["args"]

                # Emitir tool_call SSE
                writer({
                    "type": "tool_call",
                    "agent": "researcher",
                    "subquery_id": sq.id,
                    "tool": tool_name,
                    "args": tool_args,
                })

                # Ejecutar tool
                tool = tools_by_name.get(tool_name)
                if tool is None:
                    result_str = json.dumps({"error": f"tool {tool_name!r} no encontrada"})
                else:
                    try:
                        result_str = await tool.ainvoke(tool_args)
                    except Exception as exc:  # noqa: BLE001
                        result_str = json.dumps({"error": str(exc)})

                tool_calls_used += 1
                new_tool_calls += 1

                # Extraer hits y acumular evidencia
                pages_seen: list[int] = []
                n_results = 0
                try:
                    parsed = json.loads(result_str)
                    if isinstance(parsed, list):
                        for hit in parsed:
                            cid = hit.get("chunk_id", "")
                            if cid and cid not in evidence_ids:
                                evidence_ids.append(cid)
                                try:
                                    new_evidence[cid] = Chunk(**{
                                        k: hit[k] for k in Chunk.model_fields if k in hit
                                    })
                                except Exception:  # noqa: BLE001
                                    pass
                            p = hit.get("page")
                            if p and p not in pages_seen:
                                pages_seen.append(p)
                        n_results = len(parsed)
                    elif isinstance(parsed, dict) and "chunk_ids" in parsed:
                        # get_page result
                        n_results = len(parsed.get("chunk_ids", []))
                        p = parsed.get("page")
                        if p:
                            pages_seen.append(p)
                except Exception:  # noqa: BLE001
                    pass

                # Emitir tool_result SSE
                writer({
                    "type": "tool_result",
                    "agent": "researcher",
                    "subquery_id": sq.id,
                    "tool": tool_name,
                    "n_results": n_results,
                    "pages": pages_seen,
                })

                messages.append(ToolMessage(
                    content=result_str,
                    tool_call_id=tc.get("id", ""),
                ))

        # Parsear respuesta final del LLM
        finding = _parse_finding(messages[-1], sq.id, evidence_ids[:6])

        return {
            "findings": [finding],
            "evidence": new_evidence,
            "tool_calls": state.tool_calls + new_tool_calls,
            "llm_calls": state.llm_calls + tool_calls_used + 1,
        }

    return researcher_node


def _parse_finding(last_msg: Any, subquery_id: str, evidence_ids: list[str]) -> Finding:
    import re  # noqa: PLC0415
    content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            ids = data.get("evidence_ids", evidence_ids)[:6]
            return Finding(
                subquery_id=subquery_id,
                evidence_ids=ids,
                sufficient=bool(data.get("sufficient", len(ids) > 0)),
                gap=data.get("gap"),
            )
        except Exception:  # noqa: BLE001
            pass
    return Finding(
        subquery_id=subquery_id,
        evidence_ids=evidence_ids[:6],
        sufficient=len(evidence_ids) > 0,
        gap=None,
    )
