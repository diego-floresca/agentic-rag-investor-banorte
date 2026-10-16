"""
Publica un índice v1 con los chunks de chunks.jsonl usando EMBED_PROVIDER=fake.

Uso: uv run python backend/tests/fixtures/make_index.py [--index-dir PATH]
También importable como módulo desde conftest.py (fixture_index).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).parent
CHUNKS_PATH = HERE / "chunks.jsonl"


def publish_index(index_dir: Path) -> str:
    """Publica v1 con los chunks de fixtures; devuelve la versión publicada."""
    # Evitar importar Qdrant si no se necesita (tests fake no lo usan)
    # IndexStore en modo fake omite la escritura en Qdrant.
    os.environ.setdefault("EMBED_PROVIDER", "fake")
    os.environ.setdefault("LLM_PROVIDER", "fake")
    os.environ.setdefault("RUNNER_MODE", "fake")

    # Importación diferida para que los overrides de env vars estén activos
    from app.indexstore import IndexStore  # noqa: PLC0415
    from app.contracts import DocumentInfo, PageContent, Chunk  # noqa: PLC0415

    store = IndexStore(index_dir=index_dir)
    version = store.new_version()

    # Leer chunks del fixture
    chunks: list[Chunk] = []
    doc_ids: set[str] = set()
    with CHUNKS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            chunks.append(Chunk.model_validate(raw))
            doc_ids.add(raw["doc_id"])

    # Construir DocumentInfo ficticios a partir de los chunks
    documents = [
        DocumentInfo(
            doc_id=doc_id,
            title=f"Documento Ficticio {doc_id}",
            source_kind="reporte",
            report_period="2T26",
            year=2026,
            quarter=2,
            lang="es",
            pages=5,
            filename=f"{doc_id}.pdf",
        )
        for doc_id in sorted(doc_ids)
    ]

    # Construir pages.jsonl a partir de los chunks (una entrada por (doc_id, page))
    pages_dict: dict[tuple[str, int], list[str]] = {}
    for chunk in chunks:
        key = (chunk.doc_id, chunk.page)
        pages_dict.setdefault(key, []).append(chunk.chunk_id)

    pages = [
        PageContent(
            doc_id=doc_id,
            page=page,
            text=f"[Texto crudo página {page} de {doc_id}]",
            chunk_ids=cids,
        )
        for (doc_id, page), cids in sorted(pages_dict.items())
    ]

    meta = {
        "chunks": len(chunks),
        "documents": len(documents),
        "embed_provider": "fake",
        "version": version,
    }

    store.publish(version, meta, documents, pages)
    return version


if __name__ == "__main__":
    import argparse
    import tempfile

    parser = argparse.ArgumentParser()
    parser.add_argument("--index-dir", type=Path, default=None)
    args = parser.parse_args()

    idx_dir = args.index_dir or Path(tempfile.mkdtemp(prefix="test_index_"))
    v = publish_index(idx_dir)
    print(f"Publicado {v} en {idx_dir}")
