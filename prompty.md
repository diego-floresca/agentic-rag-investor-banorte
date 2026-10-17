Eres T2. Lee SPEC.md (Runner, API, Eventos SSE, Despliegue). La API no conoce LangGraph: solo run_chat. Tienes
permiso de editar en el Makefile únicamente los targets bundle, dev y deploy. Presupuesto: 35 min.

- app/api/main.py: FastAPI con lifespan (observability.setup, catálogo, lector del índice). Rutas de SPEC:
  POST /api/chat con EventSourceResponse de sse-starlette (ping 15 s, Cache-Control: no-cache,
  X-Accel-Buffering: no; timeout 45 s → error y done; si el cliente se desconecta, cancela; done siempre al final);
  POST /api/chat/sync con el mismo run_chat; GET /api/documents; GET /api/files/{doc_id} (validado contra el
  catálogo, FileResponse application/pdf inline desde DATA_DIR, nunca rutas del servidor); GET /api/health
  (index = CURRENT; mcp = list_tools sobre el propio /mcp en menos de 2 s; llm = hay key).
- Límite de peticiones en memoria por IP (primer valor de X-Forwarded-For en Cloud Run): RATE_LIMIT_PER_MIN para
  /api/chat, /api/chat/sync y /mcp; responde 429 con JSON.
- Monta la app MCP de P4 en /mcp y combina su lifespan (session manager) con el de FastAPI; revisa en .venv cómo
  se hace en la versión instalada. En Cloud Run, MCP_URL = http://localhost:$PORT/mcp.
- Frontend: si existe frontend/out, móntalo AL FINAL con StaticFiles(directory=..., html=True) en "/".
- Dockerfile (raíz): python:3.12-slim, uv, `uv sync --frozen --no-dev` en backend/, copia backend/app,
  bundle/ y frontend/out/; ENV INDEX_DIR=/app/bundle/index, DATA_DIR=/app/bundle/pdfs; si RERANK=fastembed,
  descarga el modelo en el build (no en el arranque). En runtime no hace falta poppler: no se parsean PDFs.
  CMD uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080}.
- Makefile: bundle copia la versión de CURRENT (directorio, metadatos, pages.jsonl y CURRENT) a bundle/index y
  los PDFs del catálogo a bundle/pdfs, e imprime el tamaño; dev construye frontend/out si existe y levanta la
  API en :8000 sirviendo todo; deploy = bundle + `npm run build` en frontend + `gcloud run deploy $SERVICE_NAME
  --source . --region $GCP_REGION --allow-unauthenticated --memory 2Gi --cpu 1 --timeout 300 --concurrency 20
  --max-instances 2 --min-instances 0 --set-secrets GEMINI_API_KEY=gemini-api-key:latest --set-env-vars
  RUNNER_MODE=real,RETRIEVAL_MODE=mcp,INDEX_DIR=/app/bundle/index,DATA_DIR=/app/bundle/pdfs,<modelos y límites
  de .env>` y al final imprime la URL. Las variables no secretas salen de backend/.env; la key, nunca.
- Comprueba el contexto de subida sin desplegar: `gcloud meta list-files-for-upload` debe listar bundle/ y
  frontend/out/ y NO backend/.env. Si Docker está disponible, `docker build` local para detectar errores antes.

COMPUERTA C4 (local): tests/test_api.py con httpx.ASGITransport: orden SSE y done siempre (también "bloquear" y
"error"), /sync arma answer_md y citations, 404 en doc_id inválido, 429 en la petición 21 del minuto, health
responde. Después `make dev` con RUNNER_MODE=real y un `curl -N` real termina en done. NO despliegues: imprime el
comando exacto para que Diego corra `make deploy` (C5). Cuando te dé la URL, verifica health, chat SSE y que "/"
sirve la UI, y repórtalo. Commits "feat(api): SSE, MCP montado y límite" y "feat(deploy): Docker y Cloud Run".
Documentación: docs/api.md (endpoints, secuencia SSE en Mermaid, por qué SSE y no WebSocket) y docs/deploy.md
(imagen, .gcloudignore, servicio, secreto, límites, costo esperado, cómo redesplegar).