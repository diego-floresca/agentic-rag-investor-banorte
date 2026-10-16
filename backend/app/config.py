# Creado en P0. Dueño: T2. No lo borres.
"""Configuración centralizada. Todos los módulos importan desde aquí.
Uso: from app.config import settings
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env está dos niveles arriba de este archivo (app/config.py → app/ → backend/)
_ENV_FILE = (Path(__file__).parent.parent / ".env").resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ─────────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    LLM_PROVIDER: str = "gemini"          # gemini | fake
    LLM_MODEL: str = "gemini-2.0-flash"
    LLM_CONCURRENCY: int = 8

    # ── Embeddings ───────────────────────────────────────────────────────────
    EMBED_PROVIDER: str = "fastembed"     # fastembed | gemini | fake | none
    EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBED_DIM: int = 384
    EMBED_CONCURRENCY: int = 4

    # ── BM25 / sparse ────────────────────────────────────────────────────────
    BM25_VOCAB_SIZE: int = 65536

    # ── Rutas ────────────────────────────────────────────────────────────────
    DATA_DIR: Path = Path("~/data").expanduser()
    WORK_DIR: Path = Path("~/reto2_work").expanduser()
    INDEX_DIR: Path = Path("~/reto2_index").expanduser()

    # ── Retrieval ────────────────────────────────────────────────────────────
    RETRIEVAL_MODE: str = "mcp"           # mcp | direct
    RERANK: str = ""                      # fastembed | "" (vacío = sin rerank)
    TOP_K: int = 8
    TOP_K_MAX: int = 20
    PREFETCH_K: int = 20

    # ── Agente ────────────────────────────────────────────────────────────────
    RUNNER_MODE: str = "fake"             # fake | real
    GRAPH_MODE: str = "full"              # full | simple
    MAX_SUBQUERIES: int = 4
    MAX_TOOL_CALLS_RESEARCHER: int = 3
    MAX_TOOL_CALLS_ANALYST: int = 3
    MAX_REPLANS: int = 1
    TIMEOUT_S: int = 45

    # ── API ───────────────────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    RATE_LIMIT_PER_MIN: int = 20
    MAX_MESSAGE_LEN: int = 2000

    # ── MCP ───────────────────────────────────────────────────────────────────
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8001

    # ── Observabilidad ────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    SERVICE_NAME: str = "banorte-ir-agent"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    # ── Modelos validadores ───────────────────────────────────────────────────
    def model_post_init(self, __context: object) -> None:  # noqa: ANN001
        # Expandir tildes por si vienen como string desde .env
        object.__setattr__(self, "DATA_DIR", Path(self.DATA_DIR).expanduser().resolve())
        object.__setattr__(self, "WORK_DIR", Path(self.WORK_DIR).expanduser().resolve())
        object.__setattr__(self, "INDEX_DIR", Path(self.INDEX_DIR).expanduser().resolve())


settings = Settings()
