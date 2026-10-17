"""E6 records.py — Convierte bloques tabla a registros SPEC §Registro de tabla."""
from __future__ import annotations

import re

from app.ingest.blocks import TableBlock


# ── Patrones ────────────────────────────────────────────────────

PERIOD_RE = re.compile(r"\b[1-4][TtQqSs]\d{2}\b|\b20\d{2}\b")
HEADER_KEYWORDS = re.compile(
    r"\bVar\b|\bVs\b|%|\bmillones\b|\bmiles\b|\bmillion\b|\bpesos\b|\bMXN\b|\bUSD\b",
    re.I,
)

# Marca de nota: exactamente un dígito 1-9 entre paréntesis, sin más chars
NOTE_MARK_RE = re.compile(r"\(([1-9])\)")
# Token de valor: número negativo (≥2 dígitos o dígito+%), nunca marca de nota simple
# \([1-9]\) queda EXCLUIDO: debe tener ≥2 dígitos dentro o dígito+%
VALUE_TOKEN_RE = re.compile(r"\([\d,\.]{2,}%?\)|\(\d+%\)|\d[\d,\.]*%?")


def _is_header_line(line: str) -> bool:
    """Detecta si una línea es de header (periodos o keywords)."""
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 60 and not PERIOD_RE.search(line):
        return False
    return bool(PERIOD_RE.search(line) or HEADER_KEYWORDS.search(line))


def _find_tokens_with_positions(line: str) -> list[tuple[int, str]]:
    """
    Encuentra todos los tokens numéricos/porcentuales en la línea con su posición de inicio.
    Excluye marcas de nota simples como "(1)" no seguidas de dígito.
    """
    tokens: list[tuple[int, str]] = []
    # Primero marcar posiciones de nota (para excluirlas)
    note_positions: set[int] = set()
    for m in NOTE_MARK_RE.finditer(line):
        for pos in range(m.start(), m.end()):
            note_positions.add(pos)

    # Buscar tokens numéricos
    for m in re.finditer(r"\([\d,\.]{2,}%?\)|\(\d+%\)|\d[\d,\.]*%?", line):
        # Verificar que no esté en zona de nota
        if any(pos in note_positions for pos in range(m.start(), m.end())):
            continue
        tokens.append((m.start(), m.group(0)))

    return tokens


def _find_text_tokens_with_positions(line: str) -> list[tuple[int, int, str]]:
    """Encuentra tokens de texto (palabras) con posición start y end."""
    tokens: list[tuple[int, int, str]] = []
    for m in re.finditer(r"[A-Za-záéíóúñÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\(\)\.,&/\-]*", line):
        tokens.append((m.start(), m.end(), m.group(0)))
    return tokens


def _parse_header_columns(
    header_lines: list[str],
) -> list[tuple[str, int, int]]:
    """
    Parsea las columnas del header.

    Returns list of (col_name, start_col, end_col).
    """
    if not header_lines:
        return []

    # Filtrar líneas que realmente sean de header
    real_headers = [l for l in header_lines if _is_header_line(l)]
    if not real_headers:
        return []

    if len(real_headers) == 1:
        # Un nivel de header
        line = real_headers[0]
        cols: list[tuple[str, int, int]] = []

        # Encontrar todos los tokens en la línea de header
        for m in re.finditer(r"\S+(?:\s+\S+)*?(?=\s{2,}|\s*$)", line):
            token = m.group(0).strip()
            if token:
                cols.append((token, m.start(), m.end()))

        # Si eso no da buenos resultados, usar tokens individuales separados por espacios
        if not cols:
            for m in re.finditer(r"\S+", line):
                cols.append((m.group(0), m.start(), m.end()))

        return cols

    # Dos niveles de header: combinar superior e inferior
    upper_line = real_headers[0]
    lower_line = real_headers[-1]

    # Tokenizar línea superior
    upper_tokens: list[tuple[str, int, int]] = []
    for m in re.finditer(r"\S+(?:\s+\S+)*?(?=\s{2,}|\s*$)", upper_line):
        t = m.group(0).strip()
        if t:
            upper_tokens.append((t, m.start(), m.end()))

    if not upper_tokens:
        for m in re.finditer(r"\S+", upper_line):
            upper_tokens.append((m.group(0), m.start(), m.end()))

    # Tokenizar línea inferior
    lower_tokens: list[tuple[str, int, int]] = []
    for m in re.finditer(r"\S+(?:\s+\S+)*?(?=\s{2,}|\s*$)", lower_line):
        t = m.group(0).strip()
        if t:
            lower_tokens.append((t, m.start(), m.end()))

    if not lower_tokens:
        for m in re.finditer(r"\S+", lower_line):
            lower_tokens.append((m.group(0), m.start(), m.end()))

    # Asignar cada token inferior al token superior más cercano
    cols = []
    for lt, ls, le in lower_tokens:
        # Encontrar el token superior más cercano por posición
        best_upper = ""
        best_dist = float("inf")
        for ut, us, ue in upper_tokens:
            # Centro del token superior
            uc = (us + ue) / 2
            lc = (ls + le) / 2
            dist = abs(uc - lc)
            if dist < best_dist:
                best_dist = dist
                best_upper = ut

        if best_upper and best_upper.strip() not in ("", "Concepto", ""):
            col_name = f"{best_upper} {lt}".strip()
        else:
            col_name = lt

        cols.append((col_name, ls, le))

    return cols


def _is_subtitle_line(line: str) -> bool:
    """Línea que es subtítulo de sección (no tiene valores numéricos)."""
    stripped = line.strip()
    if not stripped:
        return False
    nums = _find_tokens_with_positions(stripped)
    if nums:
        return False
    # Es subtítulo si: termina en ':', es ALLCAPS, o es indentación 0
    if stripped.endswith(":"):
        return True
    # Texto sin números = posible subtítulo de tabla
    if any(c.isalpha() for c in stripped):
        return True
    return False


def parse_records(block: TableBlock) -> tuple[list[str], bool]:
    """
    Convierte un TableBlock en líneas de registro.

    Returns:
        (record_lines, header_ok)
        record_lines: cada elemento es "label | col: val | col: val ..."
        header_ok: True si todos los valores asignaron a columnas correctamente
    """
    header_cols = _parse_header_columns(block.header_lines)
    has_headers = len(header_cols) > 0
    header_ok = has_headers

    record_lines: list[str] = []

    # Jerarquía: pila de (indent_spaces, label)
    hierarchy_stack: list[tuple[int, str]] = []
    current_section: str = ""

    for line in block.rows:
        if not line.strip():
            continue

        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        # Líneas de nota al pie: empiezan con "(N) " y luego texto
        if re.match(r"^\(\d\)\s+[A-Za-z]", stripped):
            continue  # ignorar notas de pie en los records

        # Verificar si es una línea de subtítulo (sin números)
        value_tokens = _find_tokens_with_positions(line)

        if not value_tokens:
            # Es un subtítulo o título de sección
            # Actualizar jerarquía
            clean_label = stripped.rstrip(":")
            if clean_label:
                current_section = clean_label
                # Actualizar pila de jerarquía
                hierarchy_stack = [(indent, clean_label)]
            continue

        # Limpiar marcas de nota del texto y extraer label
        # Primero: encontrar dónde empiezan los valores (primer token numérico a la derecha del label)
        first_val_pos = value_tokens[0][0] if value_tokens else len(line)

        # Label: todo lo que está antes del primer valor numérico
        label_raw = line[:first_val_pos].rstrip()

        # Limpiar notas del label
        note_marks: list[str] = []
        for m in NOTE_MARK_RE.finditer(label_raw):
            note_marks.append(f"[nota {m.group(1)}]")
        label_clean = NOTE_MARK_RE.sub("", label_raw).strip()
        if note_marks:
            label_clean = label_clean + " " + " ".join(note_marks)
        label_clean = label_clean.strip()

        # También limpiar notas de los valores
        # "(1)" seguido de espacios y más números = nota en valor
        clean_line = line
        # Marcar y remover notas de la zona de valores
        val_note_marks: list[str] = []
        def replace_val_note(m: re.Match) -> str:
            val_note_marks.append(f"[nota {m.group(1)}]")
            return " "
        # Rehacer después de limpiar el label
        value_part = line[first_val_pos:]
        value_part_clean = NOTE_MARK_RE.sub(replace_val_note, value_part)
        if val_note_marks and label_clean:
            label_clean = label_clean + " " + " ".join(val_note_marks)

        # Re-extraer value tokens desde la parte limpia
        value_tokens_clean = _find_tokens_with_positions(value_part_clean)

        # Construir la ruta jerárquica
        # Actualizar pila según indent
        while hierarchy_stack and hierarchy_stack[-1][0] >= indent:
            hierarchy_stack.pop()

        if current_section:
            path_parts = []
            # Agregar sección actual si la hay y no está ya en la pila
            if not hierarchy_stack or hierarchy_stack[0][1] != current_section:
                path_parts.append(current_section)
            for _, parent_label in hierarchy_stack:
                path_parts.append(parent_label)
            path_parts.append(label_clean)
            path = " › ".join(p for p in path_parts if p)
        else:
            path_parts = [pl for _, pl in hierarchy_stack] + [label_clean]
            path = " › ".join(p for p in path_parts if p)

        # Actualizar pila
        hierarchy_stack.append((indent, label_clean))

        # Asignar valores a columnas
        if has_headers and value_tokens_clean:
            assignments: list[tuple[str, str]] = []
            used_cols: set[int] = set()
            mapping_ok = True

            for val_pos, val_tok in value_tokens_clean:
                # Posición real en la línea original
                real_pos = first_val_pos + val_pos

                # Buscar la columna con posición más cercana
                best_col = None
                best_dist = float("inf")
                best_col_idx = -1

                for col_idx, (col_name, col_start, col_end) in enumerate(header_cols):
                    col_center = (col_start + col_end) / 2
                    dist = abs(col_center - real_pos)
                    if dist < best_dist:
                        best_dist = dist
                        best_col = col_name
                        best_col_idx = col_idx

                if best_col is None:
                    mapping_ok = False
                    assignments.append(("", val_tok))
                else:
                    if best_col_idx in used_cols:
                        mapping_ok = False
                    used_cols.add(best_col_idx)
                    assignments.append((best_col, val_tok))

            if len(value_tokens_clean) > len(header_cols):
                mapping_ok = False
                header_ok = False

            if not mapping_ok:
                header_ok = False
                # Emitir sin columnas
                vals_str = " | ".join(v for _, v in assignments)
                record_lines.append(f"{path} | {vals_str}")
            else:
                parts = [path]
                for col_name, val in assignments:
                    if col_name:
                        parts.append(f"{col_name}: {val}")
                    else:
                        parts.append(val)
                record_lines.append(" | ".join(parts))

        elif value_tokens_clean:
            # Sin headers: emitir valores sin asignar
            vals_str = " | ".join(v for _, v in value_tokens_clean)
            record_lines.append(f"{path} | {vals_str}")
            header_ok = False

        else:
            # Línea sin valores: solo el path
            if path.strip():
                record_lines.append(path)

    return record_lines, header_ok
