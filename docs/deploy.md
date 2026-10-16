# Despliegue — Banorte IR Agent

## Qué es

Un solo contenedor Docker que sirve `/api`, `/mcp` y `/` (frontend estático)
en Cloud Run. El índice Qdrant y los PDFs están dentro de la imagen
(`bundle/`), sin dependencias de almacenamiento externo. La única dependencia
de red en runtime es la API de Gemini.

---

## Imagen Docker

### Estructura de capas

```
FROM python:3.12-slim
│
├── pip install uv
├── COPY backend/pyproject.toml + uv.lock → uv sync --frozen --no-dev
│     (capa separada: solo se reconstruye si cambian las deps)
├── COPY backend/app/          → código Python
├── COPY bundle/               → índice Qdrant + PDFs
├── COPY frontend/out/         → frontend compilado
└── ENV + CMD
```

### Variables de entorno en runtime

| Variable | Valor en Cloud Run | Descripción |
|---|---|---|
| `INDEX_DIR` | `/app/bundle/index` | Índice Qdrant (solo lectura) |
| `DATA_DIR` | `/app/bundle/pdfs` | PDFs del catálogo |
| `RUNNER_MODE` | `real` | Activa LangGraph completo |
| `RETRIEVAL_MODE` | `mcp` | Retrieval vía servidor MCP interno |
| `GEMINI_API_KEY` | secreto GCP | Montado desde Secret Manager |
| `LLM_MODEL` | `gemini-2.0-flash` | Modelo de generación |
| `EMBED_PROVIDER` | `fastembed` | Embeddings locales (sin red) |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Modelo de embeddings |
| `EMBED_DIM` | `384` | Dimensión de los vectores densos |
| `RERANK` | `` (vacío) | `fastembed` si se instala el cross-encoder |
| `RATE_LIMIT_PER_MIN` | `20` | Límite de peticiones por IP |
| `PORT` | asignado por Cloud Run | Puerto en el que escucha uvicorn |

### PATH y PYTHONPATH

```dockerfile
ENV PATH="/app/backend/.venv/bin:$PATH"
ENV PYTHONPATH="/app/backend"
```

El `.venv` creado por `uv sync` contiene todas las dependencias Python.
`PYTHONPATH` permite que `from app.xxx import …` funcione desde cualquier
directorio.

---

## Secreto en GCP

```bash
# Crear el secreto (una vez)
echo -n "$GEMINI_API_KEY" | \
  gcloud secrets create gemini-api-key --data-file=-

# Verificar acceso de la cuenta de servicio de Cloud Run
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

El secreto se monta como variable de entorno con `--set-secrets GEMINI_API_KEY=gemini-api-key:latest`.
**Nunca** aparece en el `Dockerfile`, en `backend/.env` subido, ni en logs.

---

## .gcloudignore

Sin `.gcloudignore` propio, `gcloud` usaría `.gitignore` y la imagen saldría
**sin** `bundle/` ni `frontend/out/` (ambos están gitignored).

El `.gcloudignore` en la raíz del repo:
- **Incluye** implícitamente `bundle/` y `frontend/out/` (al no excluirlos).
- **Excluye** `backend/.env`, `.venv/`, `node_modules/`, `__pycache__/`,
  `tests/`, `evals/`, etc.

Verificación antes de desplegar:

```bash
gcloud meta list-files-for-upload | grep -E "^bundle/|^frontend/out/"
```

---

## Servicio Cloud Run

| Parámetro | Valor | Razón |
|---|---|---|
| Región | `us-central1` | Baja latencia a API de Gemini (us) |
| Memoria | `2 GiB` | fastembed + Qdrant en memoria + modelo |
| CPU | `1` | Carga de pico < 20 req concurrentes |
| Timeout | `300 s` | Consultas largas con múltiples LLM calls |
| Concurrency | `20` | 1 CPU maneja hasta 20 req async sin contención |
| Max instancias | `2` | Coste acotado; rate limiter en memoria tolera 2 |
| Min instancias | `0` | Ahorra coste en periodos sin tráfico |
| Autenticación | Sin auth | `--allow-unauthenticated` para demo pública |

---

## Flujo de despliegue

```bash
# 1. Generar bundle (índice + PDFs)
make bundle

# 2. Todo junto (bundle + frontend + gcloud deploy)
make deploy
```

`make deploy` ejecuta en orden:
1. `make bundle` → copia el índice activo y los PDFs a `bundle/`.
2. `cd frontend && npm run build` → genera `frontend/out/`.
3. `gcloud meta list-files-for-upload` → verifica que `bundle/` y `frontend/out/` están incluidos.
4. `gcloud run deploy banorte-ir-agent --source . …` → Cloud Build construye la imagen y despliega.
5. Imprime la URL del servicio.

---

## Cómo redesplegar

```bash
# Solo código (sin reindexar)
make deploy

# Con nuevo índice
make ingest          # o make ingest TIER=2
make deploy

# Forzar reconstrucción sin caché
gcloud run deploy banorte-ir-agent --source . --region us-central1 \
  --no-cache
```

---

## Verificación post-despliegue

```bash
URL=https://banorte-ir-agent-xxx-uc.a.run.app

# Health
curl $URL/api/health | python3 -m json.tool

# SSE chat
curl -N -X POST $URL/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "¿cuál fue la utilidad neta en 2T26?"}'

# UI en el browser
open $URL
```

---

## Coste esperado

Con tráfico de demo (< 100 req/día, RUNNER_MODE=real):

| Componente | Estimación |
|---|---|
| Cloud Run (0 idle) | ~0 USD/mes fuera de peticiones |
| Cloud Run (peticiones) | ~1-3 USD/mes |
| Gemini API (Flash) | ~0.01 USD/1M tokens; demo < 1 USD/mes |
| Cloud Build | ~0.003 USD/min de build |
| Secret Manager | < 0.10 USD/mes |
| **Total estimado** | **< 5 USD/mes** |

Con `min-instances=1` (elimina cold start): +~15 USD/mes.

---

## Límites y qué cambiaría en producción

- **Rate limiter por instancia**: con `max-instances=2`, el límite efectivo es
  hasta 40 req/min por IP (2 instancias × 20). En producción: Redis counter.
- **Sin TLS propio**: Cloud Run provee HTTPS automáticamente.
- **Sin CDN**: el frontend estático se sirve desde Cloud Run. En producción:
  Firebase Hosting o Cloud CDN para los assets.
- **Índice de solo lectura**: `INDEX_DIR` es un volumen de solo lectura en Cloud
  Run. Para reindexar hay que redesplegar la imagen. Alternativa: Cloud Storage +
  mount FUSE.
- **Secreto único**: un solo `GEMINI_API_KEY`. En producción: rotación automática
  de secretos con Secret Manager.
