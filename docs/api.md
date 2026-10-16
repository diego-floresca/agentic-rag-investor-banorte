# API — Banorte IR Agent

## Qué es

La capa HTTP que expone el grafo agéntico al frontend y a integraciones externas.
Sirve cinco rutas REST/SSE, monta el servidor MCP en `/mcp` y, si existe, el
frontend estático en `/`. Todo corre en un solo proceso uvicorn.

**Usuario final:** el analista que escribe una pregunta en lenguaje natural y
recibe la cifra exacta con su cita de página. Nunca ve latencia de arranque
(min-instances=0 en Cloud Run se compensa con la primera petición).

---

## Cómo encaja

```
Frontend (Next.js)  →  POST /api/chat  →  runner.run_chat()  →  LangGraph
                    →  POST /api/chat/sync                    →  LangGraph
                    →  GET  /api/documents  →  IndexStore
                    →  GET  /api/files/{doc_id}  →  DATA_DIR
                    →  GET  /api/health

Agentes/LLMs        →  /mcp  →  MCP streamable HTTP  →  IndexStore
```

Recibe: peticiones HTTP del browser o de clientes MCP.  
Entrega: eventos SSE, JSON, PDFs inline, estado de salud.  
Habla con: `app.agents.runner.run_chat`, `app.indexstore.IndexStore`,
`app.mcp_server.server.build_mcp`.

---

## Cómo funciona

### Secuencia SSE (`POST /api/chat`)

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as API
    participant R as runner.run_chat()

    B->>A: POST /api/chat {session_id, message}
    A->>A: verificar rate limit (IP, 20/min)
    A->>R: run_chat(session_id, message)
    loop eventos (hasta 45 s)
        R-->>A: SSEEvent (status/plan/tool_call/…/token/citations/done)
        A-->>B: event: <tipo>\ndata: <json>\n\n
    end
    Note over A,B: ping ": ping" cada 15 s (keep-alive en proxies)
    alt timeout 45 s
        A-->>B: event: error + event: done
    else cliente desconectado
        A: cancela el generador
    end
    A-->>B: event: done  (siempre el último)
```

**¿Por qué SSE y no WebSocket?**

| Criterio | SSE | WebSocket |
|---|---|---|
| Unidireccional (servidor → cliente) | Nativo | Requiere protocolo extra |
| Reconexión automática | Estándar HTTP | Manual |
| Proxies y CDN | Compatible sin config | Requiere upgrade |
| Multiplexado bidireccional | No necesario aquí | Sobrecarga innecesaria |
| Estado de sesión | Stateless HTTP | Requiere gestión de sesión |

El chat es unidireccional: el usuario envía un mensaje y el servidor emite eventos
hasta `done`. WebSocket agregaría complejidad sin beneficio.

### Orden canónico de eventos

```
status(guard) → status(planner) → plan → status(researcher)
→ tool_call × N → tool_result × N → finding
→ status(verifier) → verification
→ status(output) → token × M → citations → done
```

Variantes:
- Bloqueado: `status(guard) → error(guard_blocked) → done`
- Error interno: `… → error(internal_error) → done`
- Timeout: `… → error(timeout) → done`

### Rate limiter

Ventana deslizante en memoria por IP (primer valor de `X-Forwarded-For`).
`RATE_LIMIT_PER_MIN` peticiones en 60 s para `/api/chat`, `/api/chat/sync` y
`/mcp`. Responde `429 {"error":"rate_limit_exceeded", "message":"…"}`.

---

## Endpoints

### `POST /api/chat`
Streaming SSE.

**Request:** `{"session_id": "…", "message": "¿…?" }`  
`message` máximo `MAX_MESSAGE_LEN` (2000) caracteres.  
**Response:** `Content-Type: text/event-stream`, 10 tipos de eventos (SPEC §Eventos SSE).  
Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.  
Ping keep-alive cada 15 s.

### `POST /api/chat/sync`
Misma lógica que `/api/chat`; agrega todos los eventos y devuelve JSON.

**Response:**
```json
{
  "answer_md": "La utilidad neta fue **35,453** millones [^1].",
  "citations": [{"n":1, "chunk_id":"…", "doc_id":"…", "title":"…", "report_period":"2T26", "page":5}],
  "plan": {"intent":"lookup", "entity":"grupo", "subqueries":[…]},
  "verification": {"verdict":"approve", "issues":[]},
  "trace_id": "uuid",
  "latency_ms": 2341,
  "llm_calls": 3,
  "tool_calls": 2
}
```

### `GET /api/documents`
Lista todos los PDFs indexados.  
**Response:** `list[DocumentInfo]` (SPEC §DocumentInfo).

### `GET /api/files/{doc_id}`
Sirve el PDF original inline desde `DATA_DIR`.  
Valida `doc_id` contra el catálogo; devuelve `404` si no existe.  
Previene path traversal: resuelve y comprueba que la ruta quede dentro de `DATA_DIR`.  
**Response:** `application/pdf`, `Content-Disposition: inline`.

### `GET /api/health`
Estado del servicio.

**Response:**
```json
{
  "api": "ok",
  "index": "ok",          // "ok" | "no_index"
  "index_version": "v1",
  "mcp": "ok",            // "ok" | "error: …"
  "mcp_tools": 3,
  "llm": "ok"             // "ok" | "no_key"
}
```

- `index`: comprueba que `INDEX_DIR/CURRENT` existe.
- `mcp`: llama `list_tools()` directamente sobre la instancia (sin HTTP, < 2 s).
- `llm`: verifica que `GEMINI_API_KEY` no está vacía.

### `/mcp`
Servidor MCP streamable HTTP (ver `docs/retrieval-mcp.md`).  
Protegido por el mismo rate limiter vía wrapper ASGI puro (sin `BaseHTTPMiddleware`
para no interferir con el streaming MCP).

### `/`
Frontend Next.js compilado (`frontend/out/`) si el directorio existe.  
Montado con `StaticFiles(html=True)` al final para no enmascarar las rutas API.

---

## Decisiones y alternativas

| Decisión | Elegida | Alternativa descartada | Por qué |
|---|---|---|---|
| Protocolo streaming | SSE | WebSocket | Unidireccional, sin estado, proxies sin config |
| Rate limiter | En memoria por IP | Redis | Sin dependencias externas; Cloud Run tiene max 20 instancias y concurrency 20 |
| MCP rate limit | ASGI wrapper puro | `BaseHTTPMiddleware` | Evita buffering en respuestas streaming |
| Timeout | `asyncio.timeout` (45 s) | `asyncio.wait_for` | Misma semántica, más legible en Python 3.11+ |
| Health MCP check | `list_tools()` directo | HTTP a `/mcp` | Evita llamada circular; prueba el mismo código |
| Frontend mount | `StaticFiles` al final | Servidor Nginx separado | Un solo contenedor, menos coste en Cloud Run |

---

## Contrato (SPEC §API, §Eventos SSE, §Límites)

- `POST /api/chat` → SSE con 10 tipos de evento; siempre termina en `done`.
- `POST /api/chat/sync` → JSON con `answer_md`, `citations`, `plan`, `verification`.
- `GET /api/health` → `index = CURRENT`; `mcp = list_tools < 2 s`; `llm = key exists`.
- Rate limit: `RATE_LIMIT_PER_MIN` (20) por IP en ventana de 60 s.
- Timeout: `TIMEOUT_S` (45 s) → `error(timeout) + done`.

---

## Límites y qué cambiaría en producción

- **Rate limiter en memoria**: si hay varias instancias de Cloud Run, el límite es
  por instancia (no global). Con `max-instances=2` y `concurrency=20` el riesgo es
  bajo. En producción real: Redis con Lua atomic counter.
- **Sin autenticación**: Cloud Run con `--allow-unauthenticated`. En producción
  añadir IAM o API key header.
- **`min-instances=0`**: cold start de ~8 s la primera petición. Si la latencia
  importa: subir a `min-instances=1`.

---

## Cómo probarlo

```bash
# Tests unitarios (sin red)
make test

# Servidor local con runner fake
make dev

# Health
curl http://localhost:8000/api/health

# SSE real
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "¿cuál fue la utilidad neta en 2T26?"}'

# Sync
curl -X POST http://localhost:8000/api/chat/sync \
  -H "Content-Type: application/json" \
  -d '{"message": "¿cuál fue la utilidad neta en 2T26?"}' | python3 -m json.tool
```
