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
    raw = list(struct.unpack_from(f"{dim}f", bytes(buf[:needed])))
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
    """Embedder con Gemini API.  T1 implementa el cuerpo."""

    name = "gemini"
    dim: int

    def __init__(self, model: str = settings.EMBED_MODEL, dim: int = settings.EMBED_DIM) -> None:
        self.dim = dim
        self._model = model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("T1")

    async def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError("T1")


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
        raise NotImplementedError("T1")  # T1 implementa FastEmbedEmbedder
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
