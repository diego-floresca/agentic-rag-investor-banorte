# Creado en P0. Dueño: T2. No lo borres.
"""Contratos Pydantic v2 compartidos por todos los módulos.
Todos los modelos vienen de SPEC.md; no modifiques sin permiso de Diego.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────
# Documentos
# ─────────────────────────────────────────────────────────────────

SourceKind = Literal[
    "reporte",
    "presentacion",
    "transcripcion",
    "estado_financiero",
    "riesgos",
    "anual",
    "otro",
]


class DocumentInfo(BaseModel):
    """Metadatos de un PDF del catálogo."""

    doc_id: str
    title: str
    source_kind: SourceKind
    report_period: str          # normalizado: "2T26", "2025", etc.
    year: int
    quarter: Optional[int] = None
    lang: str                   # "es" | "en" | "es-en"
    pages: int
    filename: str


# ─────────────────────────────────────────────────────────────────
# Ingesta
# ─────────────────────────────────────────────────────────────────

PageKind = Literal["text", "table", "mixed", "visual", "scanned"]


class ParsedPage(BaseModel):
    """Resultado de E5: página analizada con metadatos estructurales."""

    doc_id: str
    page: int
    width: float
    height: float
    kind: PageKind
    regions: list[list[float]]  # lista de franjas [x0, x1]
    band_section: Optional[str] = None
    headings: list[str] = Field(default_factory=list)
    chars: int
    raw_text: str


ContentType = Literal["prose", "table", "figure", "page_text"]


class Chunk(BaseModel):
    """Unidad indexable en Qdrant (payload)."""

    chunk_id: str                   # "{doc_id}:p{page}:c{n}"
    doc_id: str
    title: str
    source_kind: str
    report_period: str
    year: int
    quarter: Optional[int] = None
    lang: str
    page: int                       # primera página
    pages: list[int]                # todas las páginas (párrafos que cruzan)
    section_path: list[str]
    entity: str                     # de entities.yaml; "grupo" por defecto
    content_type: ContentType
    table_id: Optional[str] = None
    units: Optional[str] = None
    header: list[str] = Field(default_factory=list)
    header_ok: bool = True
    text: str
    embed_text: str
    tokens: int
    tier: int = 1
    approximate: bool = False       # True solo en figure


class SearchHit(BaseModel):
    """Chunk sin embed_text + score, resultado de una búsqueda."""

    chunk_id: str
    doc_id: str
    title: str
    source_kind: str
    report_period: str
    year: int
    quarter: Optional[int] = None
    lang: str
    page: int
    pages: list[int]
    section_path: list[str]
    entity: str
    content_type: str
    table_id: Optional[str] = None
    units: Optional[str] = None
    header: list[str] = Field(default_factory=list)
    header_ok: bool = True
    text: str
    tokens: int
    tier: int = 1
    approximate: bool = False
    score: float


class PageContent(BaseModel):
    """Texto crudo de una página con sus chunk_ids."""

    doc_id: str
    page: int
    text: str
    chunk_ids: list[str]


# ─────────────────────────────────────────────────────────────────
# Eventos SSE (10 tipos — SPEC §Eventos SSE)
# ─────────────────────────────────────────────────────────────────

class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    stage: str
    message: str


class PlanEvent(BaseModel):
    type: Literal["plan"] = "plan"
    intent: str
    entity: str
    subqueries: list[dict]


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    agent: str
    subquery_id: str
    tool: str
    args: dict


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    agent: str
    subquery_id: str
    tool: str
    n_results: int
    pages: list[int]


class FindingEvent(BaseModel):
    type: Literal["finding"] = "finding"
    subquery_id: str
    sufficient: bool
    gap: Optional[str] = None


class VerificationEvent(BaseModel):
    type: Literal["verification"] = "verification"
    verdict: str
    issues: list[str]


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class CitationsEvent(BaseModel):
    type: Literal["citations"] = "citations"
    items: list[dict]


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    trace_id: str
    latency_ms: int
    llm_calls: int
    tool_calls: int


SSEEvent = Union[
    StatusEvent,
    PlanEvent,
    ToolCallEvent,
    ToolResultEvent,
    FindingEvent,
    VerificationEvent,
    TokenEvent,
    CitationsEvent,
    ErrorEvent,
    DoneEvent,
]

# ─────────────────────────────────────────────────────────────────
# Modelos del grafo agéntico
# ─────────────────────────────────────────────────────────────────

class GuardResult(BaseModel):
    allowed: bool
    reason: str
    flags: list[str] = Field(default_factory=list)


class Filters(BaseModel):
    prefer_periods: Optional[list[str]] = None
    entities: Optional[list[str]] = None
    langs: Optional[list[str]] = None
    source_kinds: Optional[list[str]] = None
    doc_ids: Optional[list[str]] = None
    content_type: Optional[str] = None


class SubQuery(BaseModel):
    id: str
    query_es: str
    query_en: str
    filters: Filters = Field(default_factory=Filters)


class Plan(BaseModel):
    intent: Literal[
        "lookup", "comparativa", "calculo", "conversacional", "fuera_de_alcance"
    ]
    entity: str
    subqueries: list[SubQuery] = Field(default_factory=list)  # máx. 4
    needs_calc: bool = False
    direct_answer: Optional[str] = None


class Finding(BaseModel):
    subquery_id: str
    evidence_ids: list[str] = Field(default_factory=list)  # máx. 6
    sufficient: bool
    gap: Optional[str] = None


class Calculation(BaseModel):
    expression: str
    result: float
    input_chunk_ids: list[str] = Field(default_factory=list)


class Draft(BaseModel):
    answer_md: str          # con citas [chunk_id]
    calculations: list[Calculation] = Field(default_factory=list)


class Verification(BaseModel):
    verdict: Literal["approve", "revise", "partial"]
    issues: list[str] = Field(default_factory=list)
    feedback: str = ""


class Citation(BaseModel):
    n: int
    chunk_id: str
    doc_id: str
    title: str
    report_period: str
    page: int


# ─────────────────────────────────────────────────────────────────
# Estado del grafo LangGraph
# ─────────────────────────────────────────────────────────────────

def _sum_findings(left: list[Finding], right: list[Finding]) -> list[Finding]:
    """Reductor: acumula findings de todos los researcher nodes."""
    return left + right


def _merge_evidence(left: dict, right: dict) -> dict:
    """Reductor: fusiona evidencia de researchers paralelos (fan-out)."""
    merged = dict(left)
    merged.update(right)
    return merged


def _sum_int(left: int, right: int) -> int:
    """Reductor suma para contadores de llamadas (cada nodo devuelve su delta)."""
    return left + right


class GraphState(BaseModel):
    """Estado mutable del grafo; usa Annotated para reductores de LangGraph."""

    model_config = {"arbitrary_types_allowed": True}

    # messages usa el reductor de LangGraph (append + dedup)
    messages: Annotated[list, add_messages] = Field(default_factory=list)
    question: str = ""
    guard: Optional[GuardResult] = None
    plan: Optional[Plan] = None
    # findings usa reductor suma para que varios researcher nodes puedan escribir
    findings: Annotated[list[Finding], _sum_findings] = Field(default_factory=list)
    # evidence usa reductor merge para que researchers paralelos no colisionen
    evidence: Annotated[dict[str, Chunk], _merge_evidence] = Field(default_factory=dict)
    draft: Optional[Draft] = None
    verification: Optional[Verification] = None
    final_answer: Optional[str] = None
    citations: list[Citation] = Field(default_factory=list)
    replans: int = 0
    # tool_calls y llm_calls usan reductor suma: cada nodo devuelve su delta
    tool_calls: Annotated[int, _sum_int] = 0
    llm_calls: Annotated[int, _sum_int] = 0
