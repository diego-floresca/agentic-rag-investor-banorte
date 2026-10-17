"""E2 bands.py — Bandas repetidas (header/footer) y section titles."""
from __future__ import annotations

import re
import statistics
from collections import Counter


def _norm_key(text: str) -> str:
    """Clave de normalización para comparar bandas entre páginas."""
    return re.sub(r"\d+", "#", text.lower().strip())


def detect_bands(doc) -> dict:  # type: ignore[no-untyped-def]
    """
    Detecta bandas repetidas (header/footer) y encabezados por página.

    Returns:
        {page_num (0-indexed): {
            band_top: str|None,
            band_bottom: str|None,
            band_section: str|None,
            headings: list[str]
        }}
    """
    n_pages = doc.page_count
    if n_pages == 0:
        return {}

    # Recolectar bloques de cabecera y pie por página
    top_texts: list[list[str]] = []   # top_texts[i] = lista de textos de bloques en la zona top de la página i
    bottom_texts: list[list[str]] = []

    for i in range(n_pages):
        page = doc[i]
        h = page.rect.height
        top_limit = h * 0.12
        bottom_limit = h * 0.88

        blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,block_type)
        page_top: list[str] = []
        page_bottom: list[str] = []

        for block in blocks:
            if block[6] != 0:  # skip non-text blocks
                continue
            y0 = block[1]
            y1 = block[3]
            text = block[4].strip()
            if not text:
                continue

            if y1 <= top_limit:
                page_top.append(text)
            elif y0 >= bottom_limit:
                page_bottom.append(text)

        top_texts.append(page_top)
        bottom_texts.append(page_bottom)

    # Determinar qué textos (normalizados) aparecen en >50% de páginas
    threshold = n_pages * 0.5

    top_counter: Counter[str] = Counter()
    bottom_counter: Counter[str] = Counter()

    for page_tops in top_texts:
        seen_keys: set[str] = set()
        for t in page_tops:
            key = _norm_key(t)
            if key not in seen_keys:
                top_counter[key] += 1
                seen_keys.add(key)

    for page_bottoms in bottom_texts:
        seen_keys = set()
        for t in page_bottoms:
            key = _norm_key(t)
            if key not in seen_keys:
                bottom_counter[key] += 1
                seen_keys.add(key)

    common_tops = {k for k, c in top_counter.items() if c > threshold}
    common_bottoms = {k for k, c in bottom_counter.items() if c > threshold}

    # Construir resultado por página
    result: dict[int, dict] = {}

    for i in range(n_pages):
        page = doc[i]

        # --- Tamaños de fuente para detectar encabezados ---
        rawdict = page.get_text("rawdict")
        all_sizes: list[float] = []
        for block in rawdict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0.0)
                    if size > 0:
                        all_sizes.append(size)

        median_size = statistics.median(all_sizes) if all_sizes else 0.0
        heading_threshold = median_size * 1.3

        # Recopilar encabezados: spans cuyo tamaño > threshold
        headings: list[tuple[float, str]] = []  # (y, text)
        for block in rawdict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0.0)
                    if size > heading_threshold:
                        text = span.get("text", "").strip()
                        if text:
                            y = span.get("origin", (0, 0))[1]
                            headings.append((y, text))

        # Ordenar encabezados top-to-bottom y agrupar por proximidad
        headings.sort(key=lambda x: x[0])
        heading_texts = [h[1] for h in headings]

        # band_top: primer bloque del top que sea "común"
        band_top: str | None = None
        for t in top_texts[i]:
            if _norm_key(t) in common_tops:
                band_top = t
                break

        # band_bottom: primer bloque del bottom que sea "común"
        band_bottom: str | None = None
        for t in bottom_texts[i]:
            if _norm_key(t) in common_bottoms:
                band_bottom = t
                break

        # band_section: texto del bloque top que NO sea la banda repetida
        # Buscar en rawdict bloques con color de fondo diferente (simulado via background)
        band_section: str | None = None
        h = page.rect.height
        top_limit = h * 0.12

        # Buscar primer bloque en la zona top que no sea la banda común
        for t in top_texts[i]:
            key = _norm_key(t)
            if key not in common_tops and len(t.strip()) > 3:
                band_section = t.strip()
                break

        result[i] = {
            "band_top": band_top,
            "band_bottom": band_bottom,
            "band_section": band_section,
            "headings": heading_texts,
        }

    return result
