# Imagen de producción — banorte-ir-agent
# Construye e instala el backend Python, copia el índice (bundle/)
# y el frontend compilado (frontend/out/).
#
# Prerrequisitos antes de `docker build .`:
#   make bundle          → bundle/index/ + bundle/pdfs/
#   cd frontend && npm run build   → frontend/out/
#
# Variables de entorno requeridas en runtime:
#   GEMINI_API_KEY  (montada como secreto en Cloud Run)

FROM python:3.12-slim

# ── Dependencias del sistema ───────────────────────────────────────
# uv: gestor de paquetes Python
# En runtime no se parsean PDFs → poppler no es necesario
RUN pip install --no-cache-dir uv

WORKDIR /app

# ── Dependencias Python (capa separada para aprovechar caché) ──────
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev

# ── Código fuente de la aplicación ────────────────────────────────
COPY backend/app ./backend/app/

# ── Índice Qdrant + PDFs (generado por `make bundle`) ─────────────
COPY bundle/ ./bundle/

# ── Frontend compilado (generado por `npm run build`) ─────────────
# El directorio debe existir antes de docker build (make deploy lo garantiza).
COPY frontend/out/ ./frontend/out/

# ── Modelo de reranking (descarga en build, no en arranque) ───────
ARG RERANK=""
RUN if [ "$RERANK" = "fastembed" ]; then \
      cd backend && uv run python -c \
      "from fastembed import TextCrossEncoder; \
       TextCrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"; \
    fi

# ── Variables de entorno de runtime ───────────────────────────────
ENV INDEX_DIR=/app/bundle/index \
    DATA_DIR=/app/bundle/pdfs \
    PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend" \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Shell form para que ${PORT:-8080} se expanda en runtime
CMD uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080}
