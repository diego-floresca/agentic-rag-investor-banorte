"""E0 probe.py — Análisis de corpus. Escribe WORK_DIR/probe.json y proyección L1."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path


def _slug(name: str) -> str:
    """Convierte un nombre de archivo a un slug limpio."""
    # Eliminar extensión si la tiene
    name = Path(name).stem
    # Eliminar acentos
    name = "".join(
        c for c in unicodedata.normalize("NFD", name.lower())
        if unicodedata.category(c) != "Mn"
    )
    # Reemplazar caracteres no alfanuméricos con "_"
    name = re.sub(r"[^a-z0-9]+", "_", name)
    # Eliminar guiones bajos al inicio/final y colapsar múltiples
    name = name.strip("_")
    return name


def _classify_page(page) -> str:  # type: ignore[no-untyped-def]
    """Clasifica una página de PyMuPDF según su contenido."""
    text = page.get_text("text")
    n_chars = len(text.replace(" ", "").replace("\n", ""))
    n_draws = len(page.get_drawings())

    images = page.get_image_info()
    n_imgs = len(images)

    # Área de imágenes vs área total de la página
    page_area = page.rect.width * page.rect.height
    img_area = sum(
        abs((img.get("bbox", [0, 0, 0, 0])[2] - img.get("bbox", [0, 0, 0, 0])[0]) *
            (img.get("bbox", [0, 0, 0, 0])[3] - img.get("bbox", [0, 0, 0, 0])[1]))
        for img in images
    )
    img_ratio = img_area / max(page_area, 1)

    n_alpha = sum(1 for c in text if c.isalpha())
    n_digits = sum(1 for c in text if c.isdigit())

    # Clasificación según SPEC
    if n_chars < 50 and img_ratio > 0.60:
        return "scanned"
    if (n_draws + n_imgs) > 30 and n_chars < 300:
        return "visual"
    if (
        n_chars > 0
        and (float(n_digits) / max(n_alpha + n_digits, 1) > 0.25)
        and (n_draws + n_imgs) > 10
    ):
        return "mixed"
    return "text"


def probe_corpus(data_dir: Path | str, work_dir: Path | str) -> dict:
    """Analiza todos los PDFs en data_dir y escribe probe.json en work_dir."""
    import pymupdf  # type: ignore[import]

    data_dir = Path(data_dir)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(data_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"[probe] No se encontraron PDFs en {data_dir}")
        return {"documents": [], "total_pages": 0}

    documents = []
    total_pages = 0

    for pdf_path in pdf_paths:
        sha12 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:12]
        doc_id = _slug(pdf_path.stem)

        doc = pymupdf.open(str(pdf_path))
        n_pages = doc.page_count
        total_pages += n_pages

        page_kinds: dict[str, int] = {}
        for i in range(n_pages):
            page = doc[i]
            kind = _classify_page(page)
            page_kinds[kind] = page_kinds.get(kind, 0) + 1

        doc.close()

        documents.append({
            "doc_id": doc_id,
            "filename": pdf_path.name,
            "sha12": sha12,
            "pages": n_pages,
            "page_kinds": page_kinds,
        })

    # Proyección de tiempo para L1
    time_per_page_L1_s = 0.05  # 50ms/page medido
    projected_seconds = total_pages * time_per_page_L1_s

    print(
        f"[probe] {len(documents)} PDFs · {total_pages} páginas totales · "
        f"proyección L1: {projected_seconds:.1f}s "
        f"({total_pages} págs × {time_per_page_L1_s*1000:.0f}ms)"
    )

    if projected_seconds > 300:
        print(
            f"[probe] ADVERTENCIA: proyección L1 ({projected_seconds:.1f}s) "
            f"supera el límite de 300s. Abortando.",
            file=sys.stderr,
        )
        sys.exit(2)

    probe_data = {
        "documents": documents,
        "total_pages": total_pages,
        "projected_l1_s": projected_seconds,
    }

    probe_path = work_dir / "probe.json"
    probe_path.write_text(
        json.dumps(probe_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[probe] Escrito: {probe_path}")

    return probe_data


def main() -> None:
    """Punto de entrada: python -m app.ingest.probe"""
    from app.config import settings

    result = probe_corpus(settings.DATA_DIR, settings.WORK_DIR)
    print(f"[probe] Documentos: {len(result['documents'])}, Páginas: {result['total_pages']}")


if __name__ == "__main__":
    main()
