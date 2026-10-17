"""E3 regions.py — Canales verticales por página."""
from __future__ import annotations

from collections import Counter, defaultdict


def detect_regions(page) -> list[tuple[float, float]]:  # type: ignore[no-untyped-def]
    """
    Detecta canales verticales y devuelve lista de (x0, x1) regiones.

    Algoritmo:
    1. Agrupa todos los caracteres por línea (y-bucket de 6pt).
    2. Para cada línea con texto en zona central (20%-80%):
       - Encuentra la brecha más amplia entre caracteres consecutivos.
    3. Vota por la posición de brecha más consistente (moda de x_gap).
    4. Valida: brecha ≥ 8pt, texto alfabético a ambos lados, ≥3 líneas.
    5. Las líneas de ancho completo (títulos) se omiten del votación.
    """
    page_x0 = page.rect.x0
    page_x1 = page.rect.x1
    page_width = page_x1 - page_x0

    if page_width <= 0:
        return [(page_x0, page_x1)]

    zone_lo = page_x0 + page_width * 0.20
    zone_hi = page_x0 + page_width * 0.80

    # ── 1. Recolectar caracteres agrupados por y-bucket ───────────────────
    Y_BIN = 6.0
    lines: dict[int, list[float]] = defaultdict(list)

    for block in page.get_text("rawdict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    if c and c.strip():
                        x = ch["origin"][0]
                        y = ch["origin"][1]
                        y_bucket = int(y / Y_BIN)
                        lines[y_bucket].append(x)

    if not lines:
        return [(page_x0, page_x1)]

    # ── 2. Por cada línea, recolectar TODOS los gaps ≥ MIN_GAP en zona central ─
    MIN_GAP = 20.0
    VOTE_BIN = 15.0
    gap_votes: list[float] = []  # todas las brechas candidatas (centro x)

    for y_bucket, xs in lines.items():
        xs_sorted = sorted(set(round(x, 1) for x in xs))
        if len(xs_sorted) < 4:
            continue

        # Solo líneas con chars en ambos lados de la zona central
        has_left  = any(x < zone_lo for x in xs_sorted)
        has_right = any(x > zone_hi for x in xs_sorted)
        if not (has_left and has_right):
            continue

        # Recolectar TODOS los gaps en la zona central
        for i in range(len(xs_sorted) - 1):
            g = xs_sorted[i + 1] - xs_sorted[i]
            cx = (xs_sorted[i] + xs_sorted[i + 1]) / 2
            if g >= MIN_GAP and zone_lo <= cx <= zone_hi:
                gap_votes.append(cx)

    if not gap_votes:
        return [(page_x0, page_x1)]

    # ── 3. Votar: encontrar el bin con más votos ──────────────────────────
    vote_hist: Counter[int] = Counter(int(v / VOTE_BIN) for v in gap_votes)
    # Ordenar: primero por frecuencia, luego por bin más central (menos extremo)
    page_center_bin = int((page_x0 + page_x1) / 2 / VOTE_BIN)
    best_vote_bin = max(
        vote_hist,
        key=lambda b: (vote_hist[b], -abs(b - page_center_bin))
    )
    min_votes_required = max(2, len(lines) // 4)  # al menos 25% de las líneas
    if vote_hist[best_vote_bin] < min_votes_required:
        return [(page_x0, page_x1)]

    split_candidates = [v for v in gap_votes if int(v / VOTE_BIN) == best_vote_bin]
    split_x = sum(split_candidates) / len(split_candidates)

    # ── 4. Validar ────────────────────────────────────────────────────────
    full_width_threshold = page_width * 0.5
    alpha_left = 0
    alpha_right = 0
    lines_left: set[int] = set()
    lines_right: set[int] = set()

    for block in page.get_text("rawdict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            ys = [sp["bbox"][1] for sp in line.get("spans", []) if sp.get("bbox")]
            y_bucket = int((sum(ys) / len(ys)) / 4) if ys else 0

            for span in line.get("spans", []):
                text = span.get("text", "") or "".join(
                    ch.get("c", "") for ch in span.get("chars", [])
                )
                if not text.strip():
                    continue
                bbox = span.get("bbox", [0, 0, 0, 0])
                is_fullwidth = (bbox[2] - bbox[0]) >= full_width_threshold
                if is_fullwidth:
                    continue

                span_cx = (bbox[0] + bbox[2]) / 2
                if span_cx < split_x:
                    if any(c.isalpha() for c in text):
                        alpha_left += 1
                    lines_left.add(y_bucket)
                else:
                    if any(c.isalpha() for c in text):
                        alpha_right += 1
                    lines_right.add(y_bucket)

    if alpha_left < 2 or alpha_right < 2:
        return [(page_x0, page_x1)]
    if len(lines_left) < 3 or len(lines_right) < 3:
        return [(page_x0, page_x1)]

    # ── 5. Construir regiones ─────────────────────────────────────────────
    regions: list[tuple[float, float]] = [
        (page_x0, split_x), (split_x, page_x1)
    ]
    regions = [(x0, x1) for x0, x1 in regions if (x1 - x0) >= 30.0]
    if len(regions) < 2:
        return [(page_x0, page_x1)]

    return regions
