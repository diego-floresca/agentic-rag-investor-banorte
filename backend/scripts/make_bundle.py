"""Empaqueta el índice activo y los PDFs del catálogo en bundle/.

Uso (desde la raíz del repo):
    cd backend && uv run python scripts/make_bundle.py

Copia:
  - INDEX_DIR/<ver>/          → bundle/index/<ver>/   (Qdrant)
  - INDEX_DIR/<ver>.meta.json → bundle/index/
  - INDEX_DIR/<ver>.documents.json → bundle/index/
  - INDEX_DIR/<ver>.pages.jsonl    → bundle/index/
  - INDEX_DIR/CURRENT         → bundle/index/CURRENT
  - DATA_DIR/<filename>       → bundle/pdfs/<filename>  (solo los del catálogo)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# El script se ejecuta desde backend/; la raíz del repo está un nivel arriba.
REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_INDEX = REPO_ROOT / "bundle" / "index"
BUNDLE_PDFS = REPO_ROOT / "bundle" / "pdfs"


def main() -> None:
    # Importaciones tardías: requieren el entorno de backend
    from app.config import settings
    from app.indexstore import IndexStore

    store = IndexStore()

    # ── Versión activa ────────────────────────────────────────────
    ver = store.current()
    if not ver:
        print(f"ERROR: no hay CURRENT en INDEX_DIR={settings.INDEX_DIR}", file=sys.stderr)
        sys.exit(1)
    print(f"  Versión activa: {ver}")

    # ── Copiar directorio Qdrant ──────────────────────────────────
    BUNDLE_INDEX.mkdir(parents=True, exist_ok=True)
    ver_src = settings.INDEX_DIR / ver
    ver_dst = BUNDLE_INDEX / ver
    if ver_dst.exists():
        shutil.rmtree(ver_dst)
    shutil.copytree(ver_src, ver_dst)
    print(f"  Índice Qdrant copiado: {ver_src} → {ver_dst}")

    # ── Copiar metadatos ─────────────────────────────────────────
    for ext in (".meta.json", ".documents.json", ".pages.jsonl"):
        src = settings.INDEX_DIR / (ver + ext)
        if src.exists():
            shutil.copy2(src, BUNDLE_INDEX / src.name)
            print(f"  Metadato copiado: {src.name}")

    (BUNDLE_INDEX / "CURRENT").write_text(ver, encoding="utf-8")
    print(f"  CURRENT → {ver}")

    # ── Copiar PDFs del catálogo ──────────────────────────────────
    BUNDLE_PDFS.mkdir(parents=True, exist_ok=True)
    docs = store.documents()
    copied = 0
    for doc in docs:
        src = settings.DATA_DIR / doc.filename
        if src.exists():
            shutil.copy2(src, BUNDLE_PDFS / doc.filename)
            copied += 1
        else:
            print(f"  ADVERTENCIA: PDF no encontrado: {src}", file=sys.stderr)
    print(f"  PDFs copiados: {copied}/{len(docs)}")

    # ── Tamaño total ─────────────────────────────────────────────
    result = subprocess.run(
        ["du", "-sh", str(REPO_ROOT / "bundle")],
        capture_output=True,
        text=True,
    )
    size = result.stdout.split()[0] if result.returncode == 0 else "?"
    print(f"  Tamaño bundle/: {size}")


if __name__ == "__main__":
    main()
