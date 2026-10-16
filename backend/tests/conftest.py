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
    """Publica v1 con chunks de fixtures en un directorio temporal.

    Devuelve (IndexStore, tmp_dir).
    """
    from app.indexstore import IndexStore
    from tests.fixtures.make_index import publish_index

    with tempfile.TemporaryDirectory(prefix="test_index_") as tmp:
        index_dir = Path(tmp)
        version = publish_index(index_dir)
        store = IndexStore(index_dir=index_dir)
        yield store, index_dir, version


@pytest.fixture(autouse=True)
def reset_embedder_singleton():
    """Limpia el singleton de embedder entre tests."""
    from app.retrieval.embeddings import reset_embedder

    reset_embedder()
    yield
    reset_embedder()
