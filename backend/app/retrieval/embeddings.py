# Creado en P0. Dueño: T1. No lo borres.
"""
Módulo de embeddings según SPEC §Embeddings.

Clase base: Embedder (name, dim, embed_documents, embed_query).
Implementaciones:
  - FakeEmbedder: vector determinista por sha256, normalizado.
  - NoneEmbedder: lanza NotImplementedError (para desactivar embeddings).
  - GeminiEmbedder: lanza NotImplementedError "T1" (implementado por T1).
  - FastEmbedEmbedder: usa fastembed local (implementado por T1).
Cache SQLite: emb_cache.sqlite en WORK_DIR; clave = sha256(provider|model|dim|kind|texto).
get_embedder(): fábrica que lee EMBED_PROVIDER de settings.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import sqlite3
import struct
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.config import settings


# ─────────────────────────────────────────────────────────────────
# Clase base
# ─────────────────────────────────────────────────────────────────

class Embedder(ABC):
    """Interfaz de embeddings. Todas las implementaciones heredan de aquí."""

    name: str
    dim: int

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectoriza una lista de textos (documentos).  Una llamada por texto."""
        ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Vectoriza una consulta."""
        ...


# ─────────────────────────────────────────────────────────────────
# FakeEmbedder  —  para tests sin red (EMBED_PROVIDER=fake)
# ─────────────────────────────────────────────────────────────────

def _sha256_vec(text: str, dim: int) -> list[float]:
    """Vector determinista de 'dim' dimensiones derivado del sha256 del texto, normalizado."""
    seed = hashlib.sha256(text.encode()).digest()
    # Generar suficientes bytes para 'dim' floats (4 bytes cada uno)
    needed = dim * 4
    buf = bytearray()
    counter = 0
    while len(buf) < needed:
        h = hashlib.sha256(seed + counter.to_bytes(4, "little")).digest()
        buf.extend(h)
        counter += 1
    # Interpretar como enteros sin signo (evita NaN que produce "f"/float32).
    # NOTA T1: struct.unpack_from(f"{dim}f", ...) produce NaN para ciertos patrones
    # de bytes; usamos unsigned int y mapeamos a [-1, 1].
    raw_ints = struct.unpack_from(f"{dim}I", bytes(buf[:needed]))
    raw = [(v / 2_147_483_648.0) - 1.0 for v in raw_ints]
    # Normalizar a módulo 1
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


class FakeEmbedder(Embedder):
    """Embedder determinista sin red.  Garantiza: 3 textos distintos → 3 vectores distintos."""

    name = "fake"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_sha256_vec(t, self.dim) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return _sha256_vec(text, self.dim)


# ─────────────────────────────────────────────────────────────────
# NoneEmbedder  —  cuando embeddings están desactivados
# ─────────────────────────────────────────────────────────────────

class NoneEmbedder(Embedder):
    """Siempre lanza error.  Útil para verificar que nada llama a embed sin querer."""

    name = "none"
    dim = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("EMBED_PROVIDER=none: embeddings desactivados")

    async def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError("EMBED_PROVIDER=none: embeddings desactivados")


# ─────────────────────────────────────────────────────────────────
# GeminiEmbedder  —  implementado por T1
# ─────────────────────────────────────────────────────────────────

class GeminiEmbedder(Embedder):
    """Embedder con google-genai SDK. Una llamada por texto."""

    name = "gemini"
    dim: int

    def __init__(self, model: str = settings.EMBED_MODEL, dim: int = settings.EMBED_DIM) -> None:
        self.dim = dim
        self._model = model
        # Lazy client creation
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # noqa: PLC0415
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._client

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectoriza lista de textos con EMBED_CONCURRENCY y reintentos."""
        try:
            from tenacity import retry, stop_after_attempt, wait_exponential  # noqa: PLC0415
            has_tenacity = True
        except ImportError:
            has_tenacity = False

        semaphore = asyncio.Semaphore(settings.EMBED_CONCURRENCY)

        async def _embed_one(text: str) -> list[float]:
            async with semaphore:
                client = self._get_client()
                response = await client.aio.models.embed_content(
                    model=self._model,
                    contents=[text],
                    config={"output_dimensionality": self.dim},
                )
                return list(response.embeddings[0].values)

        if has_tenacity:
            from tenacity import retry, stop_after_attempt, wait_exponential  # noqa: PLC0415

            @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
            async def _embed_one_with_retry(text: str) -> list[float]:
                return await _embed_one(text)

            tasks = [_embed_one_with_retry(t) for t in texts]
        else:
            tasks = [_embed_one(t) for t in texts]

        return list(await asyncio.gather(*tasks))

    async def embed_query(self, text: str) -> list[float]:
        """Vectoriza una consulta."""
        vecs = await self.embed_documents([text])
        return vecs[0]


# ─────────────────────────────────────────────────────────────────
# Caché SQLite
# ─────────────────────────────────────────────────────────────────

class CachedEmbedder(Embedder):
    """Envuelve cualquier Embedder con un caché SQLite en WORK_DIR.

    Clave: sha256(provider|model|dim|kind|texto)  donde kind = "doc" | "query".
    """

    def __init__(self, inner: Embedder, cache_path: Path | None = None) -> None:
        self._inner = inner
        self.name = inner.name
        self.dim = inner.dim
        cache_path = cache_path or (settings.WORK_DIR / "emb_cache.sqlite")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(cache_path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB)"
        )
        self._conn.commit()

    def _key(self, kind: str, text: str) -> str:
        raw = f"{self._inner.name}|{self.dim}|{kind}|{text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _load(self, key: str) -> list[float] | None:
        row = self._conn.execute(
            "SELECT vec FROM emb WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return list(struct.unpack(f"{self.dim}f", row[0]))

    def _store(self, key: str, vec: list[float]) -> None:
        blob = struct.pack(f"{self.dim}f", *vec)
        self._conn.execute(
            "INSERT OR REPLACE INTO emb (key, vec) VALUES (?, ?)", (key, blob)
        )
        self._conn.commit()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float] | None] = [None] * len(texts)
        missing_idx: list[int] = []
        missing_texts: list[str] = []

        for i, text in enumerate(texts):
            vec = self._load(self._key("doc", text))
            if vec is not None:
                result[i] = vec
            else:
                missing_idx.append(i)
                missing_texts.append(text)

        if missing_texts:
            new_vecs = await self._inner.embed_documents(missing_texts)
            for i, vec in zip(missing_idx, new_vecs):
                self._store(self._key("doc", texts[i]), vec)
                result[i] = vec

        return result  # type: ignore[return-value]

    async def embed_query(self, text: str) -> list[float]:
        key = self._key("query", text)
        cached = self._load(key)
        if cached is not None:
            return cached
        vec = await self._inner.embed_query(text)
        self._store(key, vec)
        return vec


# ─────────────────────────────────────────────────────────────────
# get_embedder()  —  fábrica pública
# ─────────────────────────────────────────────────────────────────

_embedder_singleton: Embedder | None = None
_embedder_lock = asyncio.Lock()


def get_embedder(*, use_cache: bool = True) -> Embedder:
    """Devuelve el Embedder configurado en EMBED_PROVIDER.

    En tests usa EMBED_PROVIDER=fake para evitar red.
    Llama solo una vez por proceso; reutiliza el singleton.
    """
    global _embedder_singleton  # noqa: PLW0603

    if _embedder_singleton is not None:
        return _embedder_singleton

    provider = settings.EMBED_PROVIDER.lower()

    if provider == "fake":
        inner: Embedder = FakeEmbedder(dim=settings.EMBED_DIM)
    elif provider == "none":
        inner = NoneEmbedder()
    elif provider == "gemini":
        inner = GeminiEmbedder()
    elif provider == "fastembed":
        # Importación perezosa: evita cargar el modelo en tests
        from fastembed import TextEmbedding  # noqa: PLC0415

        class FastEmbedEmbedder(Embedder):  # noqa: PLW0621
            name = "fastembed"

            def __init__(self) -> None:
                self.dim = settings.EMBED_DIM
                self._model = TextEmbedding(model_name=settings.EMBED_MODEL)

            async def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [list(v) for v in self._model.embed(texts)]

            async def embed_query(self, text: str) -> list[float]:
                return list(next(self._model.query_embed(text)))

        inner = FastEmbedEmbedder()
    else:
        raise ValueError(f"EMBED_PROVIDER desconocido: {provider!r}")

    if use_cache and provider not in ("fake", "none"):
        embedder: Embedder = CachedEmbedder(inner)
    else:
        embedder = inner

    _embedder_singleton = embedder
    return embedder


def reset_embedder() -> None:
    """Reinicia el singleton (usado en tests)."""
    global _embedder_singleton  # noqa: PLW0603
    _embedder_singleton = None
