"""E4 extract.py — Extrae texto por región con pdftotext -layout."""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def extract_page_regions(
    pdf_path: Path,
    page_num: int,  # 1-indexed
    regions: list[tuple[float, float]],  # (x0, x1) in pts
    page_height: float,
    page_width: float,
) -> list[str]:
    """
    Extrae texto de cada región de la página usando pdftotext -layout.

    Returns list of text strings, one per region.
    """
    results: list[str] = []

    for x0, x1 in regions:
        w = x1 - x0
        if w <= 0:
            results.append("")
            continue

        cmd = [
            "pdftotext",
            "-layout",
            "-f", str(page_num),
            "-l", str(page_num),
            "-x", str(int(x0)),
            "-y", "0",
            "-W", str(max(1, int(w))),
            "-H", str(int(page_height) + 1),
            str(pdf_path),
            "-",
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            results.append(proc.stdout)
        except subprocess.TimeoutExpired:
            results.append("")
        except FileNotFoundError:
            # pdftotext no disponible
            results.append("")

    return results


def _process_single_page(args: tuple) -> dict:
    """Procesa una sola página. Función standalone para ProcessPoolExecutor."""
    (
        pdf_path_str,
        doc_id,
        page_num,
        page_width,
        page_height,
        page_kind,
        regions,
        band_section,
        headings,
    ) = args

    pdf_path = Path(pdf_path_str)

    region_tuples = [(r[0], r[1]) for r in regions]
    region_texts = extract_page_regions(
        pdf_path, page_num, region_tuples, page_height, page_width
    )

    raw_text = "\n---\n".join(region_texts)
    chars = len(raw_text.replace(" ", "").replace("\n", ""))

    return {
        "doc_id": doc_id,
        "page": page_num,
        "width": page_width,
        "height": page_height,
        "kind": page_kind,
        "regions": [[r[0], r[1]] for r in region_tuples],
        "band_section": band_section,
        "headings": headings if headings else [],
        "chars": chars,
        "raw_text": raw_text,
    }


def extract_document(
    pdf_path: Path,
    doc_id: str,
    sha12: str,
    page_bands: dict,   # from bands.py: {page_num: {...}}
    page_regions: dict,  # {page_num: list[tuple[float,float]]}
    work_dir: Path,
) -> list[dict]:
    """
    Extrae texto de todas las páginas de un documento.

    Retorna lista de ParsedPage dicts.
    Usa caché: si work_dir/pages/{sha12}.jsonl existe, lo salta.
    """
    import pymupdf  # type: ignore[import]

    pages_dir = work_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    output_path = pages_dir / f"{sha12}.jsonl"

    # Caché: si ya existe, skip
    if output_path.exists():
        results: list[dict] = []
        with output_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
        return results

    doc = pymupdf.open(str(pdf_path))
    n_pages = doc.page_count

    # Preparar args para cada página
    page_args: list[tuple] = []
    for i in range(n_pages):
        page = doc[i]
        page_num = i + 1  # 1-indexed
        page_width = page.rect.width
        page_height = page.rect.height

        bands = page_bands.get(i, {})
        band_section = bands.get("band_section")
        headings = bands.get("headings", [])

        regions = page_regions.get(i, [(0.0, page_width)])

        page_args.append((
            str(pdf_path),
            doc_id,
            page_num,
            page_width,
            page_height,
            "text",  # kind placeholder — será sobreescrito desde probe
            list(regions),
            band_section,
            headings,
        ))

    doc.close()

    # Procesar páginas (secuencial por documento para simplicidad y corrección)
    # La paralelización por documento ocurre en run.py con ProcessPoolExecutor
    page_results: list[dict] = []
    for args in page_args:
        result = _process_single_page(args)
        page_results.append(result)

    # Guardar en caché
    with output_path.open("w", encoding="utf-8") as fh:
        for pr in page_results:
            fh.write(json.dumps(pr, ensure_ascii=False) + "\n")

    return page_results


def extract_document_parallel(
    pdf_path: Path,
    doc_id: str,
    sha12: str,
    page_bands: dict,
    page_regions: dict,
    work_dir: Path,
    page_kinds: dict | None = None,  # {page_num_0idx: kind}
) -> list[dict]:
    """
    Versión paralela de extract_document usando ProcessPoolExecutor.

    page_kinds: mapa de índice de página (0-indexed) → kind de probe.
    """
    import pymupdf  # type: ignore[import]

    pages_dir = work_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    output_path = pages_dir / f"{sha12}.jsonl"

    # Caché
    if output_path.exists():
        results: list[dict] = []
        with output_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
        return results

    doc = pymupdf.open(str(pdf_path))
    n_pages = doc.page_count

    page_args: list[tuple] = []
    for i in range(n_pages):
        page = doc[i]
        page_num = i + 1
        page_width = page.rect.width
        page_height = page.rect.height

        bands = page_bands.get(i, {})
        band_section = bands.get("band_section")
        headings = bands.get("headings", [])

        regions = page_regions.get(i, [(0.0, page_width)])
        kind = (page_kinds or {}).get(i, "text")

        page_args.append((
            str(pdf_path),
            doc_id,
            page_num,
            page_width,
            page_height,
            kind,
            list(regions),
            band_section,
            headings,
        ))

    doc.close()

    max_workers = min(os.cpu_count() or 4, n_pages, 4)
    page_results: list[dict | None] = [None] * n_pages

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_single_page, args): i for i, args in enumerate(page_args)}
        for future in as_completed(futures):
            idx = futures[future]
            page_results[idx] = future.result()

    final_results = [r for r in page_results if r is not None]

    # Guardar en caché
    with output_path.open("w", encoding="utf-8") as fh:
        for pr in final_results:
            fh.write(json.dumps(pr, ensure_ascii=False) + "\n")

    return final_results
