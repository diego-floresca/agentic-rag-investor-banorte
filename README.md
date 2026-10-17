# agentic-rag-investor-banorte

Chat RAG agéntico sobre los reportes de relación con inversionistas de Banorte. Responde en español con cifras exactas y referencia de página.

**URL pública:** https://banorte-ir-agent-851077316741.us-central1.run.app

---

## Qué hace

Un analista escribe una pregunta en lenguaje natural ("¿Cuál fue la utilidad neta en 2T26?"). El sistema:

1. Valida y descompone la pregunta en sub-consultas.
2. Busca evidencia en el corpus de PDFs (Qdrant híbrido: dense + BM25, RRF).
3. Redacta la respuesta con cada cifra vinculada a su chunk y página.
4. Verifica que cada número citado aparezca en la evidencia.
5. Transmite la respuesta en tiempo real vía SSE.

## Arquitectura rápida

```
Usuario → Next.js UI → POST /api/chat (SSE)
                         └─ LangGraph
                              input_guard → planner → researcher×N → analyst → verifier → output_guard
                                                           └─ search_documents (Qdrant direct)
                         └─ GET /api/documents
                         └─ GET /api/files/{doc_id}

Un solo contenedor Cloud Run: FastAPI + frontend estático + índice Qdrant en imagen
```

Docs detalladas: [`docs/architecture.md`](docs/architecture.md)

---

## Comandos principales

```bash
make ingest       # indexar PDFs en ~/data (Qdrant local)
make bundle       # copiar índice + PDFs a bundle/ (contexto de imagen)
make deploy       # bundle + build Next.js + gcloud run deploy
make api          # servidor FastAPI local (puerto 8000)
make web          # frontend Next.js en dev (puerto 3000)
make dev          # api + web en paralelo
make test         # tests sin red (EMBED_PROVIDER=fake, LLM_PROVIDER=fake)
make eval         # evaluación de retrieval contra golden.jsonl
```

---

## Variables de entorno relevantes

| Variable | Default en Cloud Run | Descripción |
|---|---|---|
| `RUNNER_MODE` | `real` | `real` = LangGraph completo; `fake` = datos fijos |
| `RETRIEVAL_MODE` | `direct` | `direct` = Qdrant en proceso; `mcp` = servidor MCP externo |
| `LLM_MODEL` | `gemini-3.8-flash` | Modelo Gemini para guard/planner/researcher/verifier |
| `MODEL_ANALYST` | `gemini-3.8-flash` | Modelo para el analista (puede ser más capaz) |
| `GEMINI_API_KEY` | Secret Manager | Clave de la API de Gemini |
| `TIMEOUT_S` | `120` | Timeout de cada petición de chat |
| `GRAPH_MODE` | `full` | `full` = fan-out paralelo; `simple` = researcher secuencial |

---

## Stack

| Capa | Tecnología |
|---|---|
| LLM | Gemini (via `langchain-google-genai`) |
| Grafo | LangGraph + MemorySaver |
| Embeddings | `fastembed` (BAAI/bge-small-en-v1.5, 384d) |
| Índice | Qdrant embedded (dense + BM25, colección `ir`) |
| API | FastAPI + `sse-starlette` |
| Frontend | Next.js `output: export` (estático) + CSS Modules |
| Despliegue | Cloud Run · us-central1 · imagen única ~95 MB |

---

## Decisiones de diseño clave

- **Un solo contenedor**: el índice Qdrant, los PDFs y el frontend compilado viajan dentro de la imagen Docker. Sin dependencias de almacenamiento externo en runtime; la única red es la API de Gemini.
- **RETRIEVAL_MODE=direct**: se usa Qdrant en el mismo proceso en lugar del servidor MCP; MCP requeriría un proceso separado en puerto 8001 que no existe en Cloud Run.
- **AFC deshabilitado explícitamente** (`AutomaticFunctionCallingConfig(disable=True)`): el SDK de google-genai activa Automatic Function Calling por defecto. AFC intenta ejecutar las tools dentro del SDK pero son StructuredTools de LangChain en nuestro proceso; Gemini no puede llamarlas y devuelve contenido vacío.
- **Reducers `Annotated` en GraphState**: los campos `evidence`, `tool_calls` y `llm_calls` usan `_merge_evidence` y `_sum_int` para soportar escrituras concurrentes desde los researcher paralelos sin `INVALID_CONCURRENT_GRAPH_UPDATE`.
- **MemorySaver + `_sv` helper**: LangGraph serializa el estado con msgpack; los modelos Pydantic anidados pueden llegar como `dict` a los nodos siguientes. `_sv(state, key)` y los guards `isinstance(x, dict)` en `output_guard_node` evitan `AttributeError`.
- **`pdftotext -layout` por región**: el texto de tablas se extrae recortando cada franja de columna (`-x -y -W -H`). La extracción por bloques separa etiqueta y monto en líneas distintas.

---

## Lecciones de bugs encontrados y resueltos

| Bug | Síntoma | Causa raíz | Fix |
|---|---|---|---|
| Índice vacío en Cloud Run | `"index": "no_index"` en health | `*.sqlite` en `.gcloudignore` excluía el índice | Eliminada esa línea |
| Timeout con TIMEOUT_S=45 | `error: timeout` en ~60 s | Pipeline real tarda 60–90 s con 5-7 LLM calls | Subido a 120 s |
| `INVALID_CONCURRENT_GRAPH_UPDATE` | Error en researcher paralelo | `evidence`, `tool_calls`, `llm_calls` sin reductor | Añadidos `Annotated[..., reducer]` en GraphState |
| Respuesta vacía (AFC) | `answer_md: ""`, `llm_calls>0` | google-genai SDK activa AFC por defecto; Gemini no puede llamar nuestras tools locales y devuelve vacío | `AutomaticFunctionCallingConfig(disable=True)` |
| Tool calls sin ToolMessage | Empty response en `llm.invoke` final | Al romper el loop por límite, el AIMessage tenía tool_call_ids sin ToolMessage pareja | Se añaden ToolMessages stub para los calls no procesados |
| `plan.intent` AttributeError | `llm_calls: 0`, sin respuesta | `snapshot.values` devuelve dict plano, no Pydantic | `_sv()` helper + guards `isinstance` en `runner_real.py` |

---

## Documentación

| Doc | Contenido |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Diagrama completo y flujo de una pregunta |
| [`docs/agentic-rag.md`](docs/agentic-rag.md) | Nodos del grafo LangGraph, decisiones, límites |
| [`docs/retrieval-mcp.md`](docs/retrieval-mcp.md) | Búsqueda híbrida, RRF, servidor MCP |
| [`docs/api.md`](docs/api.md) | Endpoints REST/SSE, rate limit, health |
| [`docs/frontend.md`](docs/frontend.md) | Componentes UI, SSE hook, decisiones de diseño |
| [`docs/deploy.md`](docs/deploy.md) | Docker, Cloud Run, `.gcloudignore`, coste |
| [`SPEC.md`](SPEC.md) | Contratos, tipos, límites del sistema |
