"""E5 blocks.py — Detecta bloques tabla/prosa en texto -layout."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TableBlock:
    title: str = ""
    units: str = ""
    header_lines: list[str] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class ProseBlock:
    paragraphs: list[str] = field(default_factory=list)


# ── Patrones ────────────────────────────────────────────────────

NUMERIC_RE = re.compile(r"[\(\d][\d,\.]*[\d\)%]?|\d+%?|\(\d[\d,\.]*\)")
PERIOD_RE = re.compile(r"\b[1-4][TtQqSs]\d{2}\b|\b20\d{2}\b")
HEADER_KEYWORDS = re.compile(
    r"\bVar\b|\bVs\b|%|\bmillones\b|\bmiles\b|\bmillion\b|\bpesos\b|\bMXN\b|\bUSD\b",
    re.I,
)
UNITS_RE = re.compile(
    r"(?:millones|miles)\s+de\s+(?:pesos|dolares|USD|MXN)|"
    r"(?:millones|miles)\s+MXN|"
    r"MXN\s+(?:millones|miles)|"
    r"(?:en\s+)?(?:millones|miles)",
    re.I,
)


def _has_label_and_numbers(line: str) -> bool:
    """Detecta si la línea tiene una parte etiqueta y números en columnas > 30% del ancho."""
    if not line.strip():
        return False

    line_len = len(line)
    if line_len == 0:
        return False

    col_threshold = max(int(line_len * 0.30), 10)

    # Parte derecha (a partir del 30% de la longitud)
    right_part = line[col_threshold:]
    nums = NUMERIC_RE.findall(right_part)

    if not nums:
        return False

    # Parte izquierda debe tener algo alfanumérico
    left_part = line[:col_threshold]
    has_alpha = any(c.isalpha() for c in left_part)

    # También aceptar si la etiqueta está en la parte derecha pero precedida por espacios
    if not has_alpha:
        # Buscar si hay algún token alfabético en toda la línea a la izquierda de los números
        stripped = line.lstrip()
        alpha_part = re.match(r"^[A-Za-záéíóúñÁÉÍÓÚÑ\s\(\)\.,:&/]+", stripped)
        if alpha_part and alpha_part.group(0).strip():
            has_alpha = True

    return has_alpha


def _is_header_line(line: str) -> bool:
    """Una línea es header si contiene tokens de periodo o keywords de header."""
    if not line.strip():
        return False
    # No es header si es prosa larga sin tokens de periodo
    if len(line.strip()) > 60 and not PERIOD_RE.search(line):
        return False
    return bool(PERIOD_RE.search(line) or HEADER_KEYWORDS.search(line))


def _is_subtitle_only(line: str) -> bool:
    """Línea que termina en ':' o es ALL CAPS sin números."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.endswith(":"):
        return True
    # ALL CAPS sin tokens numéricos
    nums = NUMERIC_RE.findall(stripped)
    if not nums and stripped == stripped.upper() and any(c.isalpha() for c in stripped):
        return True
    return False


def parse_blocks(layout_text: str) -> list[TableBlock | ProseBlock]:
    """
    Parsea texto pdftotext -layout en bloques tabla/prosa.

    Algoritmo:
    1. Identificar "table runs" (3+ líneas numéricas consecutivas)
    2. Para cada run: extraer headers, título y construir TableBlock
    3. Lo demás: ProseBlock
    """
    lines = layout_text.splitlines()
    n = len(lines)

    if n == 0:
        return []

    # Marcar cada línea
    is_numeric = [_has_label_and_numbers(l) for l in lines]
    is_header = [_is_header_line(l) for l in lines]
    is_subtitle = [_is_subtitle_only(l) for l in lines]
    is_blank = [not l.strip() for l in lines]

    # Detectar table runs: 3+ líneas numéricas (tolerando hasta 2 blanks/subtítulos sin números consecutivos)
    in_table_range: list[bool] = [False] * n

    i = 0
    while i < n:
        if is_numeric[i]:
            # Iniciar posible run
            run_start = i
            run_lines = [i]
            j = i + 1
            consecutive_non_numeric = 0

            while j < n:
                if is_numeric[j]:
                    run_lines.append(j)
                    consecutive_non_numeric = 0
                elif is_blank[j] or is_subtitle[j]:
                    consecutive_non_numeric += 1
                    if consecutive_non_numeric > 2:
                        break
                else:
                    break
                j += 1

            if len(run_lines) >= 3:
                # Marcar toda la zona como tabla (incluyendo blanks/subtítulos intercalados)
                for k in range(run_start, j):
                    in_table_range[k] = True
            i = j
        else:
            i += 1

    # Construir bloques
    blocks: list[TableBlock | ProseBlock] = []

    i = 0
    while i < n:
        if in_table_range[i]:
            # Encontrar el rango completo de la tabla
            table_start = i
            while i < n and in_table_range[i]:
                i += 1
            table_end = i  # exclusive

            table_lines = lines[table_start:table_end]

            # Buscar headers hacia arriba desde table_start (hasta 4 líneas)
            header_line_indices: list[int] = []
            search_start = table_start
            for k in range(max(0, table_start - 4), table_start):
                if is_header[k]:
                    header_line_indices.append(k)
                    search_start = min(search_start, k)

            # Buscar título: primera línea no vacía, no header, por encima de los headers
            title = ""
            units = ""
            title_search_start = max(0, search_start - 4)
            for k in range(title_search_start, search_start):
                l = lines[k].strip()
                if not l:
                    continue
                if is_header[k]:
                    continue
                # Buscar unidades
                if UNITS_RE.search(l):
                    units = l
                    continue
                # El primer no-vacío, no-header = título
                if not title:
                    title = l

            header_lines_text = [lines[k] for k in header_line_indices]

            # Las rows son las líneas numéricas (y subtítulos) dentro del rango de tabla
            rows = table_lines

            raw_text = "\n".join(lines[min(search_start, table_start):table_end])

            block = TableBlock(
                title=title,
                units=units,
                header_lines=header_lines_text,
                rows=rows,
                raw_text=raw_text,
            )
            blocks.append(block)

        else:
            # Prosa: recolectar líneas no-tabla consecutivas
            prose_start = i
            while i < n and not in_table_range[i]:
                i += 1
            prose_lines = lines[prose_start:i]

            # Dividir en párrafos por líneas en blanco
            paragraphs: list[str] = []
            current_para_lines: list[str] = []

            for k, line in enumerate(prose_lines):
                if not line.strip():
                    if current_para_lines:
                        # Intentar unir líneas que se "envuelven"
                        para = _join_wrapped_lines(current_para_lines)
                        if para.strip():
                            paragraphs.append(para)
                        current_para_lines = []
                else:
                    current_para_lines.append(line.rstrip())

            if current_para_lines:
                para = _join_wrapped_lines(current_para_lines)
                if para.strip():
                    paragraphs.append(para)

            if paragraphs:
                blocks.append(ProseBlock(paragraphs=paragraphs))

    return blocks


def _join_wrapped_lines(lines: list[str]) -> str:
    """Une líneas envueltas: si la línea no termina en '.' y la siguiente empieza en minúscula."""
    if not lines:
        return ""

    result = lines[0].rstrip()
    for i in range(1, len(lines)):
        line = lines[i].rstrip()
        if not line:
            continue
        prev = result.rstrip()
        # Si la línea anterior no termina en '.' y la actual empieza en minúscula → unir
        next_stripped = line.lstrip()
        if (
            prev
            and not prev.endswith(".")
            and next_stripped
            and next_stripped[0].islower()
        ):
            result = prev + " " + next_stripped
        else:
            result = prev + "\n" + line

    return result
