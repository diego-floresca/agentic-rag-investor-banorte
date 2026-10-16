# Creado en P0. Dueño: T1. No lo borres.
"""
IndexStore — único módulo que abre Qdrant.

Estructura en INDEX_DIR:
    v1/             ← directorio con datos Qdrant (QdrantClient(path=v1/))
    v1.meta.json    ← metadatos de la versión
    v1.documents.json ← lista de DocumentInfo
    v1.pages.jsonl  ← {doc_id, page, text, chunk_ids} por línea
    CURRENT         ← contiene "v1" (escrito con os.replace para atomicidad)
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable

from app.config import settings
from app.contracts import Chunk, DocumentInfo, PageContent


# ─────────────────────────────────────────────────────────────────
# IndexReader  —  lector thread-safe que detecta cambios en CURRENT
# ─────────────────────────────────────────────────────────────────

class IndexReader:
    """Lee el índice activo. Reabre automáticamente si CURRENT cambia."""

    def __init__(self, index_dir: Path) -> None:
        self._index_dir = index_dir
        self._lock = threading.Lock()
        self._current_version: str | None = None
        self._current_stat: float | None = None
        self._client: Any = None  # QdrantClient, importado de forma perezosa

    # ── API pública ───────────────────────────────────────────────

    def get_client(self) -> Any:
        """Devuelve el QdrantClient activo, reabriendo si CURRENT cambió."""
        with self._lock:
            self._refresh_if_needed()
            return self._client

    def current_version(self) -> str:
        with self._lock:
            self._refresh_if_needed()
            return self._current_version or ""

    def documents(self) -> list[DocumentInfo]:
        """Lista de DocumentInfo de la versión activa."""
        with self._lock:
            self._refresh_if_needed()
            if not self._current_version:
                return []
            path = self._index_dir / f"{self._current_version}.documents.json"
            if not path.exists():
                return []
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [DocumentInfo.model_validate(d) for d in raw]

    def page(self, doc_id: str, page: int) -> PageContent | None:
        """Texto crudo de una página junto con sus chunk_ids."""
        with self._lock:
            self._refresh_if_needed()
            if not self._current_version:
                return None
            pages_path = self._index_dir / f"{self._current_version}.pages.jsonl"
            if not pages_path.exists():
                return None
        # La lectura secuencial ocurre fuera del lock para no bloquear otros hilos.
        with pages_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("doc_id") == doc_id and record.get("page") == page:
                    return PageContent.model_validate(record)
        return None

    # ── Privado ───────────────────────────────────────────────────

    def _refresh_if_needed(self) -> None:
        """Comprueba si CURRENT cambió (por stat) y reabre si es necesario.

        Llamar solo dentro de self._lock.
        """
        current_file = self._index_dir / "CURRENT"
        if not current_file.exists():
            return

        mtime = current_file.stat().st_mtime
        if mtime == self._current_stat and self._client is not None:
            return

        version = current_file.read_text(encoding="utf-8").strip()
        version_dir = self._index_dir / version
        if not version_dir.exists():
            return

        # Importación perezosa para evitar cargar Qdrant en tests con EMBED_PROVIDER=fake
        from qdrant_client import QdrantClient  # noqa: PLC0415

        self._client = QdrantClient(path=str(version_dir))
        self._current_version = version
        self._current_stat = mtime


# ─────────────────────────────────────────────────────────────────
# IndexStore  —  gestión de versiones
# ─────────────────────────────────────────────────────────────────

class IndexStore:
    """Gestiona versiones del índice.  Solo T1 escribe; T2/T3 solo leen."""

    COLLECTION = "ir"

    def __init__(self, index_dir: Path | None = None) -> None:
        self._index_dir = (index_dir or settings.INDEX_DIR).resolve()
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._reader: IndexReader | None = None
        self._reader_lock = threading.Lock()

    # ── Escritura ─────────────────────────────────────────────────

    def new_version(self) -> str:
        """Crea el directorio de la próxima versión y devuelve su nombre ("v1", "v2", …)."""
        existing = sorted(
            int(d.name[1:])
            for d in self._index_dir.iterdir()
            if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit()
        )
        n = (existing[-1] + 1) if existing else 1
        version = f"v{n}"
        (self._index_dir / version).mkdir(parents=True, exist_ok=True)
        return version

    def publish(
        self,
        version: str,
        meta: dict[str, Any],
        documents: list[DocumentInfo | dict[str, Any]],
        pages: Iterable[PageContent | dict[str, Any]] | None = None,
    ) -> None:
        """Escribe los archivos de la versión y actualiza CURRENT atómicamente."""
        # meta.json
        meta_path = self._index_dir / f"{version}.meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # documents.json
        docs_serialized = [
            d.model_dump() if isinstance(d, DocumentInfo) else d
            for d in documents
        ]
        doc_path = self._index_dir / f"{version}.documents.json"
        doc_path.write_text(
            json.dumps(docs_serialized, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # pages.jsonl
        if pages is not None:
            pages_path = self._index_dir / f"{version}.pages.jsonl"
            with pages_path.open("w", encoding="utf-8") as fh:
                for p in pages:
                    record = p.model_dump() if isinstance(p, PageContent) else p
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Actualizar CURRENT de forma atómica
        tmp_path = self._index_dir / "CURRENT.tmp"
        tmp_path.write_text(version, encoding="utf-8")
        os.replace(tmp_path, self._index_dir / "CURRENT")

    def write_page(
        self,
        version: str,
        page_content: PageContent | dict[str, Any],
    ) -> None:
        """Añade una línea a pages.jsonl de la versión (append).

        T1 la llama por página durante la ingesta para no acumular todo en memoria.
        """
        pages_path = self._index_dir / f"{version}.pages.jsonl"
        record = (
            page_content.model_dump()
            if isinstance(page_content, PageContent)
            else page_content
        )
        with pages_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── Lectura ───────────────────────────────────────────────────

    def current(self) -> str:
        """Nombre de la versión activa ("v1") o cadena vacía."""
        current_file = self._index_dir / "CURRENT"
        if not current_file.exists():
            return ""
        return current_file.read_text(encoding="utf-8").strip()

    def documents(self) -> list[DocumentInfo]:
        """Documentos de la versión activa."""
        return self.get_reader().documents()

    def page(self, doc_id: str, page: int) -> PageContent | None:
        """Texto crudo de una página."""
        return self.get_reader().page(doc_id, page)

    def status(self) -> dict[str, Any]:
        """Resumen del estado del índice."""
        version = self.current()
        if not version:
            return {"status": "empty", "version": None, "documents": 0}

        doc_path = self._index_dir / f"{version}.documents.json"
        n_docs = 0
        if doc_path.exists():
            n_docs = len(json.loads(doc_path.read_text(encoding="utf-8")))

        meta_path = self._index_dir / f"{version}.meta.json"
        meta: dict[str, Any] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        return {"status": "ok", "version": version, "documents": n_docs, "meta": meta}

    def get_reader(self) -> IndexReader:
        """Devuelve el IndexReader singleton (crea si no existe)."""
        with self._reader_lock:
            if self._reader is None:
                self._reader = IndexReader(self._index_dir)
            return self._reader

    def use_version(self, version: str) -> None:
        """Fuerza CURRENT a una versión existente (para make index-use)."""
        version_dir = self._index_dir / version
        if not version_dir.exists():
            raise FileNotFoundError(f"Versión '{version}' no existe en {self._index_dir}")
        tmp_path = self._index_dir / "CURRENT.tmp"
        tmp_path.write_text(version, encoding="utf-8")
        os.replace(tmp_path, self._index_dir / "CURRENT")
