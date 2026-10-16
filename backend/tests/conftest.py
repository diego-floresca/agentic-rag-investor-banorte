"""
conftest.py — fixtures compartidas para todos los tests.

Modos fake por defecto (sin red, sin GPU):
  EMBED_PROVIDER=fake, LLM_PROVIDER=fake, RUNNER_MODE=fake
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Forzar modos fake ANTES de cualquier importación de módulos de la app
os.environ.setdefault("EMBED_PROVIDER", "fake")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("RUNNER_MODE", "fake")


@pytest.fixture(scope="session")
def fixture_index():
    """Publica v1 + crea Qdrant con embeddings fake en un directorio temporal.

    Devuelve (IndexStore, index_dir, version).
    También inyecta el store en app.retrieval.core para los tests de retrieval.
    """
    from app.indexstore import IndexStore
    from tests.fixtures.make_index import publish_index, create_qdrant_index

    with tempfile.TemporaryDirectory(prefix="test_index_") as tmp:
        index_dir = Path(tmp)
        version = publish_index(index_dir)
        create_qdrant_index(index_dir, version)

        store = IndexStore(index_dir=index_dir)

        # Inyectar en core.py para que los tests de retrieval usen esta instancia
        import app.retrieval.core as core_mod
        core_mod.set_store(store)

        yield store, index_dir, version

        # Limpiar la inyección al terminar la sesión
        core_mod.set_store(None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def reset_embedder_singleton():
    """Limpia el singleton de embedder entre tests."""
    from app.retrieval.embeddings import reset_embedder

    reset_embedder()
    yield
    reset_embedder()
