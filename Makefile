# Makefile — banorte-ir-agent
# Todos los comandos de backend hacen `cd backend &&` antes de uv run.
# bundle, dev y deploy son esqueletos que P6 (T2) completa.
#
# Uso rápido:
#   make probe       Sondear PDFs en DATA_DIR
#   make ingest      Ingestar (TIER=1 por defecto, TIER=2 para páginas visuales)
#   make test        Ejecutar tests (modo fake, sin red)
#   make api         Levantar API en :8000
#   make mcp         Levantar servidor MCP en :8001 (aislado)

SHELL := /bin/bash
TIER  ?= 1
V     ?= v1

.PHONY: probe ingest index-status index-use retrieval-eval test mcp api web dev eval bundle deploy

# ── Ingesta ────────────────────────────────────────────────────────────────────

probe:
	cd backend && uv run python -m app.ingest.probe

ingest:
	cd backend && uv run python -m app.ingest.run --tier $(TIER)

index-status:
	cd backend && uv run python -c "from app.indexstore import IndexStore; import json; print(json.dumps(IndexStore().status(), indent=2, ensure_ascii=False))"

index-use:
	cd backend && uv run python -c "from app.indexstore import IndexStore; IndexStore().use_version('$(V)'); print('CURRENT → $(V)')"

# ── Retrieval / evals ─────────────────────────────────────────────────────────

retrieval-eval:
	cd backend && uv run python -m pytest ../evals/ -v

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	cd backend && uv run pytest -v

# ── Servicios en tiempo de ejecución ─────────────────────────────────────────

mcp:
	cd backend && uv run python -m app.mcp_server --host 127.0.0.1 --port 8001

api:
	cd backend && uv run uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload

web:
	cd frontend && npm run dev

# ── Dev (servidor local completo) ─────────────────────────────────────────────

dev:
	@echo "=== Servidor de desarrollo en :8000 ==="
	@[ -d frontend/out ] || echo "AVISO: frontend/out no existe; corre 'cd frontend && npm run build' para servir la UI."
	cd backend && RUNNER_MODE=$${RUNNER_MODE:-fake} uv run uvicorn app.api.main:app \
	    --host 0.0.0.0 --port 8000 --reload

# ── Evals end-to-end ─────────────────────────────────────────────────────────

eval:
	cd backend && uv run python -m pytest ../evals/ -v --tb=short

# ── Bundle: copia índice activo y PDFs del catálogo a bundle/ ─────────────────

bundle:
	@echo "=== Empaquetando índice y PDFs en bundle/ ==="
	@mkdir -p bundle/index bundle/pdfs
	@cd backend && uv run python -c "
import shutil, subprocess
from pathlib import Path
from app.config import settings
from app.indexstore import IndexStore

store = IndexStore()
ver = store.current()
if not ver:
    raise SystemExit(f'ERROR: no hay CURRENT en INDEX_DIR={settings.INDEX_DIR}')
print(f'  Versión activa: {ver}')

# Copiar directorio Qdrant + metadatos al bundle
dst = Path('../bundle/index')
dst.mkdir(parents=True, exist_ok=True)
ver_dst = dst / ver
if ver_dst.exists():
    shutil.rmtree(ver_dst)
shutil.copytree(settings.INDEX_DIR / ver, ver_dst)
for ext in ('.meta.json', '.documents.json', '.pages.jsonl'):
    f = settings.INDEX_DIR / (ver + ext)
    if f.exists():
        shutil.copy2(f, dst / f.name)
(dst / 'CURRENT').write_text(ver)

# Copiar PDFs del catálogo
docs = store.documents()
pdfs_dst = Path('../bundle/pdfs')
pdfs_dst.mkdir(parents=True, exist_ok=True)
copied = 0
for d in docs:
    src = settings.DATA_DIR / d.filename
    if src.exists():
        shutil.copy2(src, pdfs_dst / d.filename)
        copied += 1
    else:
        print(f'  ADVERTENCIA: PDF no encontrado: {src}')
print(f'  PDFs copiados: {copied}/{len(docs)}')

r = subprocess.run(['du', '-sh', '../bundle'], capture_output=True, text=True)
print(f'  Tamaño bundle: {r.stdout.split()[0] if r.returncode == 0 else \"?\"}')"
	@echo "=== bundle/ listo ==="

# ── Deploy: bundle + build frontend + gcloud run deploy ──────────────────────

deploy: bundle
	@echo "=== Construyendo frontend ==="
	@[ -d frontend ] && cd frontend && npm run build || echo "AVISO: sin frontend/"
	@echo "=== Verificando contexto de subida ==="
	@gcloud meta list-files-for-upload 2>/dev/null | grep -E "^bundle/|^frontend/out/" | head -5 || true
	@echo "=== Desplegando en Cloud Run ==="
	@set -a; [ -f backend/.env ] && . backend/.env; set +a; \
	SERVICE=$${SERVICE_NAME:-banorte-ir-agent}; \
	REGION=$${GCP_REGION:-us-central1}; \
	gcloud run deploy $$SERVICE \
	    --source . \
	    --region $$REGION \
	    --allow-unauthenticated \
	    --memory 2Gi \
	    --cpu 1 \
	    --timeout 300 \
	    --concurrency 20 \
	    --max-instances 2 \
	    --min-instances 0 \
	    --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
	    --set-env-vars "RUNNER_MODE=real,RETRIEVAL_MODE=mcp,\
INDEX_DIR=/app/bundle/index,DATA_DIR=/app/bundle/pdfs,\
LLM_MODEL=$${LLM_MODEL:-gemini-2.0-flash},\
EMBED_PROVIDER=$${EMBED_PROVIDER:-fastembed},\
EMBED_MODEL=$${EMBED_MODEL:-BAAI/bge-small-en-v1.5},\
EMBED_DIM=$${EMBED_DIM:-384},\
RERANK=$${RERANK:-},\
RATE_LIMIT_PER_MIN=$${RATE_LIMIT_PER_MIN:-20}" && \
	URL=$$(gcloud run services describe $$SERVICE --region $$REGION \
	    --format='value(status.url)' 2>/dev/null); \
	echo ""; \
	echo "=== Despliegue completo ==="; \
	echo "URL: $$URL"; \
	echo "Health: $$URL/api/health"
