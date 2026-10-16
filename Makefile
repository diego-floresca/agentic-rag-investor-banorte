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

# ── Dev (servidor local completo) — esqueleto P6 ────────────────────────────

dev:
	@echo "TODO: implementado en P6 (T2). Levanta api + web en paralelo."

# ── Evals end-to-end ─────────────────────────────────────────────────────────

eval:
	cd backend && uv run python -m pytest ../evals/ -v --tb=short

# ── Bundle y despliegue — esqueletos P6 ──────────────────────────────────────

bundle:
	@echo "TODO: implementado en P6 (T2). Copia index + frontend/out a bundle/."

deploy:
	@echo "TODO: implementado en P6 (T2). Ejecuta gcloud run deploy."
