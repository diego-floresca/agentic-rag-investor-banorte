"""E1 catalog.py — DocumentInfo por PDF desde el contenido, nunca el nombre."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from app.contracts import DocumentInfo


# ── Utilidades de slug ────────────────────────────────────────────

def _slug(name: str) -> str:
    """Convierte un nombre de archivo a un slug limpio."""
    name = Path(name).stem
    name = "".join(
        c for c in unicodedata.normalize("NFD", name.lower())
        if unicodedata.category(c) != "Mn"
    )
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


# ── Detección de idioma ───────────────────────────────────────────

_ES_CHARS = set("áéíóúñ¿¡")
_EN_WORDS = frozenset({"the", "and", "or", "of", "in", "to", "is", "are", "was", "were"})


def _detect_lang(text: str) -> str:
    text_lower = text.lower()
    es_count = sum(1 for c in text if c in _ES_CHARS)
    en_count = sum(1 for w in _EN_WORDS if w in text_lower.split())
    if es_count > 5:
        return "es"
    if en_count > 3:
        return "en"
    return "es-en"


# ── Detección de periodo ──────────────────────────────────────────

_PERIOD_Q_RE = re.compile(r"\b([1-4])[TtQq](\d{2})\b")
_PERIOD_S_RE = re.compile(r"\b([12])[Ss](\d{2})\b")
_PERIOD_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _normalize_period(match_obj: re.Match, kind: str) -> str:
    """Normaliza un match de periodo al formato NT26."""
    if kind == "quarter":
        n = match_obj.group(1)
        yy = match_obj.group(2)
        return f"{n}T{yy}"
    if kind == "semester":
        n = match_obj.group(1)
        yy = match_obj.group(2)
        return f"{n}S{yy}"
    return match_obj.group(1)  # year


def _detect_period(text: str) -> str | None:
    """Devuelve el periodo más frecuente encontrado en el texto."""
    found: list[str] = []

    for m in _PERIOD_Q_RE.finditer(text):
        found.append(_normalize_period(m, "quarter"))

    for m in _PERIOD_S_RE.finditer(text):
        found.append(_normalize_period(m, "semester"))

    # Solo cuenta años si no hay trimestres/semestres
    year_found: list[str] = []
    for m in _PERIOD_YEAR_RE.finditer(text):
        year_found.append(m.group(1))

    if found:
        counter = Counter(found)
        return counter.most_common(1)[0][0]

    if year_found:
        counter = Counter(year_found)
        return counter.most_common(1)[0][0]

    return None


def _period_to_year_quarter(period: str) -> tuple[int, int | None]:
    """Extrae año y trimestre de un periodo normalizado."""
    # Trimestre: NT26 → año 2026, trimestre N
    m = re.match(r"^([1-4])T(\d{2})$", period)
    if m:
        return 2000 + int(m.group(2)), int(m.group(1))

    # Semestre: NS26 → año 2026, sin trimestre
    m = re.match(r"^([12])S(\d{2})$", period)
    if m:
        return 2000 + int(m.group(2)), None

    # Año: 2025 → año 2025
    m = re.match(r"^(20\d{2})$", period)
    if m:
        return int(m.group(1)), None

    # Fallback
    return 2000, None


# ── Detección de tipo de fuente ───────────────────────────────────

def _detect_source_kind(text: str) -> str:
    text_lower = text.lower()

    if any(k in text_lower for k in ("transcript", "conference call", "llamada", "analyst")):
        return "transcripcion"
    if any(k in text_lower for k in ("presentation", "presentación", "slide")):
        return "presentacion"
    if any(k in text_lower for k in ("estado financiero", "balance", "estado de resultados")):
        return "estado_financiero"
    if any(k in text_lower for k in ("anual", "annual", "informe anual")):
        return "anual"
    if any(k in text_lower for k in ("riesgo", "risk", "factores de riesgo")):
        return "riesgos"
    return "reporte"


# ── LLM fallback ─────────────────────────────────────────────────

def _catalog_via_llm(sample_text: str, doc_id: str, filename: str, n_pages: int) -> DocumentInfo:
    """Usa LLM para catalogar cuando no se puede determinar con heurísticas."""
    from app.config import settings

    if settings.LLM_PROVIDER == "fake" or settings.EMBED_PROVIDER == "fake":
        # Modo test: devolver defaults
        return DocumentInfo(
            doc_id=doc_id,
            title=filename,
            source_kind="reporte",
            report_period="2T26",
            year=2026,
            quarter=2,
            lang="es",
            pages=n_pages,
            filename=filename,
        )

    from google import genai
    from google.genai import types as gtypes

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    prompt = (
        "Analiza el siguiente texto de un documento financiero y extrae:\n"
        "1. El periodo del reporte (formato: NT26 para trimestres, AAAA para años)\n"
        "2. El tipo de documento (reporte, presentacion, transcripcion, estado_financiero, anual, riesgos)\n"
        "3. El idioma principal (es, en, es-en)\n"
        "4. El título del documento (primera línea relevante)\n\n"
        f"Texto:\n{sample_text[:2000]}\n\n"
        "Responde SOLO con JSON: "
        '{"period": "...", "source_kind": "...", "lang": "...", "title": "..."}'
    )

    try:
        response = client.models.generate_content(
            model=settings.LLM_MODEL,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)
        period = data.get("period", "2T26")
        year, quarter = _period_to_year_quarter(period)
        return DocumentInfo(
            doc_id=doc_id,
            title=data.get("title", filename),
            source_kind=data.get("source_kind", "reporte"),
            report_period=period,
            year=year,
            quarter=quarter,
            lang=data.get("lang", "es"),
            pages=n_pages,
            filename=filename,
        )
    except Exception:
        return DocumentInfo(
            doc_id=doc_id,
            title=filename,
            source_kind="reporte",
            report_period="2T26",
            year=2026,
            quarter=2,
            lang="es",
            pages=n_pages,
            filename=filename,
        )


# ── catalog_pdf ───────────────────────────────────────────────────

def catalog_pdf(path: Path, sha12: str) -> DocumentInfo:
    """Cataloga un PDF a partir de su contenido. Nunca usa el nombre del archivo como datos."""
    import pymupdf  # type: ignore[import]

    doc = pymupdf.open(str(path))
    n_pages = doc.page_count
    doc_id = _slug(path.stem)

    # Leer primera página y 5 páginas distribuidas uniformemente
    sample_indices = [0]
    if n_pages > 1:
        step = max(1, (n_pages - 1) // 5)
        sample_indices += list(range(step, n_pages, step))[:5]

    texts: list[str] = []
    for i in sample_indices:
        if i < n_pages:
            texts.append(doc[i].get_text("text"))

    doc.close()

    first_page_text = texts[0] if texts else ""
    sample_text = "\n".join(texts)

    # Extraer título: primera línea no vacía de la primera página
    title = path.name
    for line in first_page_text.splitlines():
        line = line.strip()
        if line:
            title = line
            break

    lang = _detect_lang(sample_text)
    period = _detect_period(sample_text)
    source_kind = _detect_source_kind(sample_text)

    # Decidir si se necesita el LLM
    needs_llm = period is None

    if needs_llm:
        return _catalog_via_llm(sample_text, doc_id, path.name, n_pages)

    year, quarter = _period_to_year_quarter(period)  # type: ignore[arg-type]

    return DocumentInfo(
        doc_id=doc_id,
        title=title,
        source_kind=source_kind,  # type: ignore[arg-type]
        report_period=period,  # type: ignore[arg-type]
        year=year,
        quarter=quarter,
        lang=lang,
        pages=n_pages,
        filename=path.name,
    )


def catalog_all(data_dir: Path | str, work_dir: Path | str) -> list[DocumentInfo]:
    """Cataloga todos los PDFs en data_dir, usando caché por sha12."""
    data_dir = Path(data_dir)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = work_dir / "catalog.json"
    existing: dict[str, dict] = {}  # doc_id → serialized DocumentInfo

    if catalog_path.exists():
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        for entry in raw:
            existing[entry.get("doc_id", "")] = entry

    pdf_paths = sorted(data_dir.glob("*.pdf"))
    results: list[DocumentInfo] = []

    for pdf_path in pdf_paths:
        sha12 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:12]
        doc_id = _slug(pdf_path.stem)

        # Verificar caché por sha12
        cached = existing.get(doc_id)
        if cached and cached.get("_sha12") == sha12:
            results.append(DocumentInfo.model_validate(cached))
            continue

        print(f"[catalog] Catalogando {pdf_path.name} ...")
        doc_info = catalog_pdf(pdf_path, sha12)
        serialized = doc_info.model_dump()
        serialized["_sha12"] = sha12
        existing[doc_id] = serialized
        results.append(doc_info)

    # Guardar catalog.json
    catalog_path.write_text(
        json.dumps(list(existing.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return results
