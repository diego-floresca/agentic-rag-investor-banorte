# SPEC v4 — propiedad y contratos

## Propiedad
T1 indexación: backend/app/ingest/, backend/app/indexstore.py, backend/app/retrieval/embeddings.py,
  backend/app/retrieval/sparse.py, backend/tests/test_ingest*.py, evals/, docs/indexing.md, docs/evals.md
T2 backend: backend/app/ (excepto lo de T1), backend/tests/ (excepto test_ingest*), Dockerfile, .gcloudignore,
  deploy/, skills/contabilidad-bancaria/, docs/architecture.md (solo el borrador de P0), docs/retrieval-mcp.md, docs/agentic-rag.md,
  docs/api.md, docs/deploy.md
T3 frontend y docs: frontend/, skills/banorte-ui/, docs/frontend.md, docs/architecture.md (final), README.md
Compartidos (P0 los crea): backend/pyproject.toml, backend/uv.lock, Makefile, backend/app/contracts.py,
  backend/app/config.py, SPEC.md, CLAUDE.md, AGENTS.md

## Rutas fuera del repo
DATA_DIR=~/data (PDFs) · WORK_DIR=~/reto2_work (artefactos) · INDEX_DIR=~/reto2_index (índice versionado)
bundle/index/ y bundle/pdfs/ (en el repo, ignorados por git, incluidos por .gcloudignore): copia de la versión
vigente del índice y de los PDFs del catálogo, que la imagen sirve en /api/files

## Variantes por página (las calcula E0)
kind: "text" | "table" | "mixed" | "visual" | "scanned"
  scanned: menos de 50 caracteres y una imagen que cubre más del 60% de la página
  visual: muchos dibujos vectoriales o imágenes y menos de 300 caracteres de texto fuera de etiquetas
regions: lista de franjas [x0, x1] detectadas por canales verticales (E3)

## Índice versionado (app/indexstore.py; el único que abre Qdrant)
INDEX_DIR: v1/ v2/ … (QdrantClient(path=…), colección ir) · v<N>.meta.json · v<N>.documents.json ·
v<N>.pages.jsonl (texto crudo por página para get_page) · CURRENT ("v<N>", escrito con os.replace)
API: new_version(); publish(version, meta, documents); current(); documents(); page(doc_id, page);
  status(); get_reader() -> IndexReader (lee CURRENT con stat y reabre si cambió, bajo threading.Lock).
En Cloud Run INDEX_DIR=/app/bundle/index y es de solo lectura.

## Artefactos de ingesta (WORK_DIR)
probe.json, probe.md, catalog.json
pages/<sha12>.jsonl  ParsedPage {doc_id, page, width, height, kind, regions, band_section, headings,
                     chars, raw_text}
chunks/<sha12>.jsonl  Chunk sin vectores
emb_cache.sqlite      emb(key TEXT PRIMARY KEY, vec BLOB); key = sha256(provider|model|dim|kind|texto)
sha12 = 12 primeros hex del sha256 del archivo. Cada etapa omite un documento ya procesado con el mismo sha.

## DocumentInfo
doc_id (slug del nombre sin extensión: minúsculas, sin acentos, todo lo que no sea letra o dígito pasa a un
solo "_"), title, source_kind, report_period, year, quarter, lang, pages, filename
source_kind: "reporte" | "presentacion" | "transcripcion" | "estado_financiero" | "riesgos" | "anual" | "otro"
report_period normalizado: "2T26" (2Q26 → 2T26), "2025" para anuales

## Chunk (payload en Qdrant)
chunk_id "{doc_id}:p{page}:c{n}" · doc_id · title · source_kind · report_period · year · quarter · lang
page: int (primera) · pages: list[int] (más de una si un párrafo cruza de página)
section_path: list[str]  # [sección de la banda o del título, subtítulo, título de la tabla]
entity: str  # de entities.yaml a partir de section_path; "grupo" por defecto
content_type: "prose" | "table" | "figure" | "page_text"
table_id: str | None · units: str | None · header: list[str] · header_ok: bool
text · embed_text · tokens · tier (1 o 2) · approximate: bool (true solo en figure)
Vectores: "dense" (EMBED_DIM, coseno) y "bm25" (disperso, modifier IDF)

## Registro de tabla (formato de una fila en text)
<padre › … › etiqueta> | <encabezado>: <valor> | <encabezado>: <valor> …
Ejemplo: Ingresos de Intereses Netos | 2T25: 35,453 | 1T26: 39,477 | 2T26: 37,614 | Var. Vs. 1T26: (5%)
Si header_ok=false los valores van sin encabezado: Utilidad Neta | 14,618 | 15,458 | 15,550
Los subtotales se nombran: Créditos comerciales (subtotal) | 714,910
Un chunk de tabla = línea de contexto (título · unidades · encabezado) + hasta ~350 tokens de registros.

## embed_text
"[{title} · {report_period} · {' › '.join(section_path)} · {entity} · {units}]\n{text}"

## Embeddings (app/retrieval/embeddings.py)
Embedder: name, dim, async embed_documents(texts), async embed_query(text). get_embedder() según
EMBED_PROVIDER, envuelto en caché. Una llamada por texto, EMBED_CONCURRENCY simultáneas, reintentos ante 429/5xx.
fake: vector determinista por sha256, normalizado.

## BM25 (app/retrieval/sparse.py)
tokenize: minúsculas, sin acentos, sin stemming, palabras vacías es/en, cifras como un término sin separador de
miles ("1,273,193" → "1273193"), periodos como un término ("2t26"). Índices = crc32(token) & 0x7FFFFFFF;
documento 1 + ln(tf); consulta 1.0. Indexación y consulta usan solo estas funciones.

## Tools MCP (servidor "banorte-ir", streamable HTTP en /mcp)
list_documents() -> list[DocumentInfo]
search_documents(query: str, prefer_periods: list[str] | None = None, entities: list[str] | None = None,
  langs: list[str] | None = None, source_kinds: list[str] | None = None, doc_ids: list[str] | None = None,
  content_type: str | None = None, top_k: int = 8) -> list[SearchHit]   # top_k ≤ 20, len(query) ≤ 500
get_page(doc_id: str, page: int) -> PageContent   # texto crudo de la página + chunk_ids
SearchHit = Chunk sin embed_text + score; PageContent = {doc_id, page, text, chunk_ids}
Algoritmo: prefetch denso 20 + bm25 20, RRF. prefer_periods y entities son blandos: misma búsqueda con y
sin ese filtro, fusionadas con RRF (piden, no excluyen). langs, source_kinds, doc_ids y content_type son duros. Diversidad: máximo 2 hits por (doc_id, page).
RERANK=fastembed reordena los 20 candidatos con un cross-encoder antes de cortar a top_k.
Las mismas 3 funciones existen como tools de LangChain (agents/tools.py, RETRIEVAL_MODE=mcp|direct).

## Modelos de los agentes
GuardResult {allowed, reason, flags} · Filters {prefer_periods?, entities?, langs?, source_kinds?, doc_ids?,
content_type?} · SubQuery {id, query_es, query_en, filters} · Plan {intent: "lookup"|"comparativa"|"calculo"|
"conversacional"|"fuera_de_alcance", entity, subqueries (máx. 4), needs_calc, direct_answer} ·
Finding {subquery_id, evidence_ids (máx. 6), sufficient, gap} · Calculation {expression, result,
input_chunk_ids} · Draft {answer_md con citas [chunk_id], calculations} · Verification {verdict:
"approve"|"revise"|"partial", issues, feedback} · Citation {n, chunk_id, doc_id, title, report_period, page}
GraphState: messages, question, guard, plan, findings (reductor suma), evidence (dict), draft, verification,
final_answer, citations, replans, tool_calls, llm_calls

## Runner (frontera entre grafo y API)
app/agents/runner.py: async run_chat(session_id, message) -> AsyncIterator[SSEEvent]; RUNNER_MODE=fake|real
(import perezoso del real). runner_fake emite la secuencia canónica sin red; mensaje con "bloquear" → guard
bloqueado, con "error" → error. Siempre termina en done. GRAPH_MODE=full|simple (simple = un investigador
secuencial, mismos eventos).

## Fixtures
backend/tests/fixtures/pdfs/: 2 PDFs sintéticos generados por código (empresa ficticia): uno de una columna con
una tabla con encabezado de periodos y subtítulos internos, y otro de dos columnas tipo balance.
backend/tests/fixtures/chunks.jsonl: 14 chunks ficticios (incluye un registro de tabla y un chunk envenenado con
una instrucción oculta). make_index.py publica una versión con EMBED_PROVIDER=fake.

## Límites
max_subqueries=4, max_tool_calls_researcher=3, max_tool_calls_analyst=3, max_replans=1, timeout_s=45,
LLM_CONCURRENCY=8, RATE_LIMIT_PER_MIN=20

## Normalización de cifras (verificador y evals)
"(5%)" = -5; "(979)" = -979; "42pb" = 0.42 pp; "1,273,193" = 1273193; quitar "Ps", "$", "millones",
"million", "billion" y comparar en la escala de units; ignorar años, páginas y etiquetas de periodo.

## API
POST /api/chat {session_id, message (máx. 2000)} -> SSE · POST /api/chat/sync -> {answer_md, citations, plan,
verification, trace_id, latency_ms, llm_calls, tool_calls} · GET /api/documents · GET /api/files/{doc_id}
(application/pdf inline) · GET /api/health -> {api, mcp, llm, index} · /mcp (MCP) · / (frontend estático)

## Eventos SSE
status {stage, message} · plan {intent, entity, subqueries} · tool_call {agent, subquery_id, tool, args} ·
tool_result {agent, subquery_id, tool, n_results, pages} · finding {subquery_id, sufficient, gap} ·
verification {verdict, issues} · token {text} · citations {items} · error {code, message} ·
done {trace_id, latency_ms, llm_calls, tool_calls}. Orden: progreso → token* → citations → done.

## Evals
evals/retrieval_golden.jsonl {id, category, question, expected: [{doc_id, page}], note}
  categorías: dato_puntual, comparativa, entidad, cruce_idioma, prosa_vs_tabla
evals/golden.jsonl {id, category, question, expected_numbers, expected_pages, must_refuse}
  categorías adicionales: calculo, sin_respuesta, consejo, fuera_de_alcance, inyeccion

## Despliegue
Servicio banorte-ir-agent · región us-central1 · un contenedor: / (frontend/out), /api, /mcp ·
secreto gemini-api-key · 2 GiB, 1 CPU, timeout 300, concurrency 20, max-instances 2, min-instances 0