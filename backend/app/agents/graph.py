"""Grafo multi-agente LangGraph.

Topología (GRAPH_MODE=full):
  START → input_guard → planner → dispatch_researchers → researcher(×N, paralelo)
        → analyst → verifier → [approve→output_guard→END | revise→planner (replan)]
        → output_guard → END

Topología (GRAPH_MODE=simple — plan B):
  START → input_guard → planner → researcher_seq → analyst → verifier → output_guard → END

Punto de entrada público:
    build_graph(llm_factory, tools, mode) -> CompiledGraph
    get_graph() -> CompiledGraph  (singleton con lazy init)
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.analyst import make_analyst_node
from app.agents.guard import input_guard_node
from app.agents.output_guard import output_guard_node
from app.agents.planner import planner_node
from app.agents.researcher import make_researcher_node
from app.agents.verifier import verifier_node
from app.config import settings
from app.contracts import GraphState, Plan


# ─────────────────────────────────────────────────────────────────
# Enrutamiento
# ─────────────────────────────────────────────────────────────────

def _route_after_guard(state: GraphState) -> str:
    if state.guard and not state.guard.allowed:
        return "blocked"
    return "planner"


def _make_route_after_planner(effective_mode: str):
    """Fábrica: crea la función de enrutamiento capturando el modo."""
    def _route(state: GraphState) -> str | list:
        plan: Plan | None = state.plan
        if plan is None:
            return "analyst"
        if plan.intent in ("conversacional", "fuera_de_alcance") or plan.direct_answer:
            return "output_guard"
        if effective_mode == "simple":
            return "researcher_seq"
        if not plan.subqueries:
            return "analyst"
        # Fan-out: un Send por subconsulta
        return [Send("researcher", {"state": state, "subquery": sq}) for sq in plan.subqueries]
    return _route


def _route_after_verifier(state: GraphState) -> str:
    verdict = state.verification.verdict if state.verification else "revise"
    if verdict == "approve":
        return "output_guard"
    if state.replans >= settings.MAX_REPLANS:
        return "output_guard"  # no más reintentos
    return "replan"


# ─────────────────────────────────────────────────────────────────
# Nodo replan: incrementa contador y devuelve al planner
# ─────────────────────────────────────────────────────────────────

def replan_node(state: GraphState) -> dict:
    return {"replans": state.replans + 1, "findings": [], "evidence": {}, "draft": None}


# ─────────────────────────────────────────────────────────────────
# Nodo blocked: termina cuando el guard bloquea
# ─────────────────────────────────────────────────────────────────

def blocked_node(state: GraphState) -> dict:
    return {
        "final_answer": state.guard.reason if state.guard else "Bloqueado.",
        "citations": [],
    }


# ─────────────────────────────────────────────────────────────────
# Wrapper de nodo researcher para recibir Send payload
# ─────────────────────────────────────────────────────────────────

def _make_researcher_wrapper(researcher_fn):
    """Crea un nodo que acepta tanto Send payload como estado directo."""
    async def wrapper(state: GraphState) -> dict:
        return await researcher_fn(state, subquery=None)
    return wrapper


def _make_researcher_send_wrapper(researcher_fn):
    """Acepta payload de Send: {'state': GraphState, 'subquery': SubQuery}."""
    async def wrapper(payload: dict) -> dict:
        state: GraphState = payload["state"]
        subquery = payload["subquery"]
        return await researcher_fn(state, subquery=subquery)
    return wrapper


# ─────────────────────────────────────────────────────────────────
# Constructor del grafo
# ─────────────────────────────────────────────────────────────────

def build_graph(
    llm_factory: Callable | None = None,
    tools: list | None = None,
    mode: Literal["full", "simple"] | None = None,
):
    """Construye y compila el grafo LangGraph.

    Parámetros
    ----------
    llm_factory : callable opcional
        Si se provee, se usa en lugar de get_llm (para tests con fakes).
        Actualmente los nodos llaman get_llm() directamente; este param está
        disponible para futuras inyecciones.
    tools : list[BaseTool] opcional
        Tools de retrieval; si None se usan las configuradas por settings.
    mode : "full" | "simple" | None
        None → usa settings.GRAPH_MODE.
    """
    from app.agents.tools import get_tools  # noqa: PLC0415

    effective_mode = (mode or settings.GRAPH_MODE).lower()
    retrieval_tools = tools if tools is not None else get_tools()

    researcher_fn = make_researcher_node(retrieval_tools)
    analyst_fn = make_analyst_node(retrieval_tools)

    graph = StateGraph(GraphState)

    # ── Nodos ───────────────────────────────────────────────────────
    graph.add_node("input_guard", input_guard_node)
    graph.add_node("planner", planner_node)
    graph.add_node("analyst", analyst_fn)
    graph.add_node("verifier", verifier_node)
    graph.add_node("output_guard", output_guard_node)
    graph.add_node("blocked", blocked_node)
    graph.add_node("replan", replan_node)

    if effective_mode == "simple":
        # Modo simple: researcher secuencial para la primera subconsulta
        seq_researcher = _make_researcher_wrapper(researcher_fn)
        graph.add_node("researcher_seq", seq_researcher)
    else:
        # Modo full: researcher recibe Send payload
        send_researcher = _make_researcher_send_wrapper(researcher_fn)
        graph.add_node("researcher", send_researcher)

    # ── Aristas ─────────────────────────────────────────────────────
    graph.add_edge(START, "input_guard")

    graph.add_conditional_edges(
        "input_guard",
        _route_after_guard,
        {"blocked": "blocked", "planner": "planner"},
    )

    graph.add_edge("blocked", END)

    route_planner = _make_route_after_planner(effective_mode)

    if effective_mode == "simple":
        graph.add_conditional_edges(
            "planner",
            route_planner,
            {"output_guard": "output_guard", "analyst": "analyst", "researcher_seq": "researcher_seq"},
        )
        graph.add_edge("researcher_seq", "analyst")
    else:
        # Fan-out: route_planner puede devolver lista de Send
        graph.add_conditional_edges(
            "planner",
            route_planner,
            {"output_guard": "output_guard", "analyst": "analyst", "researcher": "researcher"},
        )
        graph.add_edge("researcher", "analyst")

    graph.add_edge("analyst", "verifier")

    graph.add_conditional_edges(
        "verifier",
        _route_after_verifier,
        {"output_guard": "output_guard", "replan": "replan"},
    )

    graph.add_edge("replan", "planner")
    graph.add_edge("output_guard", END)

    # ── Compilar con MemorySaver ─────────────────────────────────────
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# ─────────────────────────────────────────────────────────────────
# Singleton (lazy)
# ─────────────────────────────────────────────────────────────────

_graph_instance = None


def get_graph():
    """Devuelve el grafo compilado (singleton). Se construye en la primera llamada."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_graph()
    return _graph_instance
