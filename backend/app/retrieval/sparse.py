# Creado en P0. Dueño: T1. No lo borres.
"""
BM25 sparse vectorizer según SPEC §BM25.

Reglas de tokenización:
- Minúsculas, sin acentos, sin stemming
- Stop words en español e inglés
- Cifras: quitar separador de miles  ("1,273,193" → "1273193")
- Periodos como un solo término      ("2T26" → "2t26", "2Q26" → "2q26")
- Índices: crc32(token) & 0x7FFFFFFF
- Peso documento: 1 + ln(tf)
- Peso consulta: 1.0
"""
from __future__ import annotations

import math
import re
import unicodedata
import zlib
from collections import Counter

# ── Stop words mínimas ES + EN ────────────────────────────────────
_STOP_WORDS: frozenset[str] = frozenset(
    """
    a al de del en el la los las un una unos unas y o e u pero sino
    por para con sin sobre entre bajo tras según durante como cuando
    donde si no ni más menos también tampoco aunque porque pues
    que quien quienes cual cuales este esta estos estas ese esa esos esas
    aquel aquella aquellos aquellas lo le les me te se nos
    the a an and or but in on at to for of with by from as is was
    are were be been being have has had do does did will would shall
    should may might must can could it its this that these those
    i we you he she they them us him her our my your his their its
    """.split()
)

# ── Normalización ────────────────────────────────────────────────

def _remove_accents(text: str) -> str:
    """Elimina diacríticos (ñ → n, á → a, etc.)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


# Cifra con separador de miles: "1,273,193" o "1.273.193"
_RE_THOUSANDS = re.compile(r"(\d{1,3})((?:[,.])\d{3})+")

# Periodo tipo "2T26", "3Q24", etc.
_RE_PERIOD = re.compile(r"\b([1-4][tTqQ]\d{2})\b")


def _normalize_number(token: str) -> str:
    """Elimina separadores de miles de una cadena numérica."""
    return re.sub(r"[,.]", "", token)


def tokenize(text: str) -> list[str]:
    """Devuelve lista de tokens normalizados según SPEC §BM25."""
    # Normalizar periodos antes de convertir a minúsculas
    # p. ej. "2T26" → "2t26" (se preserva como término compuesto)
    text = _RE_PERIOD.sub(lambda m: m.group(1).lower(), text)

    # Eliminar separadores de miles: "1,273,193" → "1273193"
    text = _RE_THOUSANDS.sub(lambda m: _normalize_number(m.group(0)), text)

    text = text.lower()
    text = _remove_accents(text)

    # Separar por cualquier carácter que no sea alfanumérico
    tokens = re.split(r"[^a-z0-9]+", text)

    result: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        if tok in _STOP_WORDS:
            continue
        result.append(tok)
    return result


# ── Pesos ────────────────────────────────────────────────────────

def term_index(token: str) -> int:
    """Índice disperso determinista: crc32(token) & 0x7FFFFFFF."""
    return zlib.crc32(token.encode()) & 0x7FFFFFFF


def document_vector(text: str) -> dict[int, float]:
    """Vectoriza un documento: índice → 1 + ln(tf)."""
    counts = Counter(tokenize(text))
    return {term_index(tok): 1.0 + math.log(tf) for tok, tf in counts.items()}


def query_vector(text: str) -> dict[int, float]:
    """Vectoriza una consulta: índice → 1.0."""
    return {term_index(tok): 1.0 for tok in tokenize(text)}
