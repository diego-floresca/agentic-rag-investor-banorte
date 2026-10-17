"""E7 chunk.py — Genera Chunk objects desde bloques y registros."""
from __future__ import annotations

import re
import yaml
from pathlib import Path
from typing import Any

from app.contracts import Chunk, DocumentInfo
from app.ingest.blocks import TableBlock, ProseBlock, parse_blocks
from app.ingest.records import parse_records


# ── Entidades ────────────────────────────────────────────────────

def load_or_generate_entities_yaml(work_dir: Path, observed_headings: list[str]) -> dict:
    """
    Carga entities.yaml desde work_dir, o lo genera desde los headings observados.

    Returns: dict mapping keyword → entity name
    """
    entities_path = work_dir / "entities.yaml"

    if entities_path.exists():
        with entities_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data

    # Generar desde headings observados
    # Agrupar headings únicos y crear un mapa simple
    entity_map: dict[str, str] = {}

    # Valores por defecto: cualquier heading → "grupo"
    for heading in observed_headings:
        if heading and len(heading) > 2:
            key = heading.lower().strip()
            entity_map[key] = "grupo"

    # Guardar para que Diego pueda revisarlo
    print(f"[chunk] Generando entities.yaml con {len(entity_map)} entradas")
    print(f"[chunk] Por favor revisa: {entities_path}")
    for k, v in list(entity_map.items())[:10]:
        print(f"  {k!r} → {v!r}")

    with entities_path.open("w", encoding="utf-8") as f:
        yaml.dump(entity_map, f, allow_unicode=True, default_flow_style=False)

    return entity_map


def _resolve_entity(section_path: list[str], entities: dict) -> str:
    """Busca la entidad correspondiente al section_path."""
    for part in section_path:
        part_lower = part.lower()
        for keyword, entity in entities.items():
            if keyword in part_lower:
                return entity
    return "grupo"


def _build_embed_text(
    title: str,
    report_period: str,
    section_path: list[str],
    entity: str,
    units: str,
    text: str,
) -> str:
    """Construye el texto de embedding según SPEC."""
    path_str = " › ".join(section_path) if section_path else ""
    prefix = f"[{title} · {report_period} · {path_str} · {entity}"
    if units:
        prefix += f" · {units}"
    prefix += "]"
    return f"{prefix}\n{text}"


def _count_tokens(text: str) -> int:
    """Estimación de tokens: len(text) // 4."""
    return len(text) // 4


def _build_section_path(
    band_section: str | None,
    headings: list[str],
    title: str = "",
) -> list[str]:
    """Construye el section_path desde band_section, headings y título de tabla."""
    path: list[str] = []
    if band_section and band_section.strip():
        path.append(band_section.strip())
    for h in headings:
        if h and h.strip() and h.strip() not in path:
            path.append(h.strip())
    if title and title.strip() and title.strip() not in path:
        path.append(title.strip())
    return path


def chunk_page(
    page_data: dict,
    doc_info: DocumentInfo,
    blocks: list[Any],
    chunk_counter: dict,
    entities: dict | None = None,
    prev_page_last_para: dict | None = None,  # {doc_id: str}
) -> list[Chunk]:
    """
    Genera chunks para una página a partir de sus bloques parseados.

    chunk_counter: dict mutable para llevar el conteo por página {doc_id: {page: n}}
    prev_page_last_para: último párrafo sin terminar de la página anterior
    """
    if entities is None:
        entities = {}

    doc_id = page_data["doc_id"]
    page_num = page_data["page"]
    band_section = page_data.get("band_section")
    headings = page_data.get("headings", [])

    chunks: list[Chunk] = []

    # Contador de chunks por doc_id
    if doc_id not in chunk_counter:
        chunk_counter[doc_id] = 0

    def next_chunk_id() -> str:
        chunk_counter[doc_id] += 1
        return f"{doc_id}:p{page_num}:c{chunk_counter[doc_id]}"

    for block in blocks:
        if isinstance(block, ProseBlock):
            # Prose: agrupar párrafos hasta ~450 tokens
            current_paras: list[str] = []
            current_tokens = 0

            for para in block.paragraphs:
                para_tokens = _count_tokens(para)

                if current_tokens + para_tokens > 450 and current_paras:
                    # Emitir chunk actual
                    text = "\n\n".join(current_paras)
                    section_path = _build_section_path(band_section, headings)
                    entity = _resolve_entity(section_path, entities)
                    embed_text = _build_embed_text(
                        doc_info.title,
                        doc_info.report_period,
                        section_path,
                        entity,
                        "",
                        text,
                    )
                    chunk = Chunk(
                        chunk_id=next_chunk_id(),
                        doc_id=doc_id,
                        title=doc_info.title,
                        source_kind=doc_info.source_kind,
                        report_period=doc_info.report_period,
                        year=doc_info.year,
                        quarter=doc_info.quarter,
                        lang=doc_info.lang,
                        page=page_num,
                        pages=[page_num],
                        section_path=section_path,
                        entity=entity,
                        content_type="prose",
                        text=text,
                        embed_text=embed_text,
                        tokens=_count_tokens(text),
                    )
                    chunks.append(chunk)
                    current_paras = [para]
                    current_tokens = para_tokens
                else:
                    current_paras.append(para)
                    current_tokens += para_tokens

            # Emitir el último chunk de prosa
            if current_paras:
                text = "\n\n".join(current_paras)
                section_path = _build_section_path(band_section, headings)
                entity = _resolve_entity(section_path, entities)
                embed_text = _build_embed_text(
                    doc_info.title,
                    doc_info.report_period,
                    section_path,
                    entity,
                    "",
                    text,
                )
                chunk = Chunk(
                    chunk_id=next_chunk_id(),
                    doc_id=doc_id,
                    title=doc_info.title,
                    source_kind=doc_info.source_kind,
                    report_period=doc_info.report_period,
                    year=doc_info.year,
                    quarter=doc_info.quarter,
                    lang=doc_info.lang,
                    page=page_num,
                    pages=[page_num],
                    section_path=section_path,
                    entity=entity,
                    content_type="prose",
                    text=text,
                    embed_text=embed_text,
                    tokens=_count_tokens(text),
                )
                chunks.append(chunk)

        elif isinstance(block, TableBlock):
            # Table: emitir context line + records en grupos de ~350 tokens
            record_lines, header_ok = parse_records(block)

            if not record_lines:
                continue

            section_path = _build_section_path(band_section, headings, block.title)
            entity = _resolve_entity(section_path, entities)

            # Context line: "título · unidades · headers"
            header_str = " | ".join(h.strip() for h in block.header_lines if h.strip())
            context_parts = []
            if block.title:
                context_parts.append(block.title)
            if block.units:
                context_parts.append(block.units)
            if header_str:
                context_parts.append(header_str)
            context_line = " · ".join(context_parts)

            # table_id: único por tabla (doc_id:page:título_limpio)
            title_slug = re.sub(r"[^a-z0-9]+", "_", block.title.lower()).strip("_") if block.title else "table"
            table_id = f"{doc_id}:p{page_num}:{title_slug}"

            # Agrupar records en chunks de ~350 tokens
            current_records: list[str] = []
            current_tokens = _count_tokens(context_line)

            for rec_line in record_lines:
                rec_tokens = _count_tokens(rec_line)

                if current_tokens + rec_tokens > 350 and current_records:
                    # Emitir chunk
                    text = context_line + "\n" + "\n".join(current_records)
                    embed_text = _build_embed_text(
                        doc_info.title,
                        doc_info.report_period,
                        section_path,
                        entity,
                        block.units,
                        text,
                    )
                    chunk = Chunk(
                        chunk_id=next_chunk_id(),
                        doc_id=doc_id,
                        title=doc_info.title,
                        source_kind=doc_info.source_kind,
                        report_period=doc_info.report_period,
                        year=doc_info.year,
                        quarter=doc_info.quarter,
                        lang=doc_info.lang,
                        page=page_num,
                        pages=[page_num],
                        section_path=section_path,
                        entity=entity,
                        content_type="table",
                        table_id=table_id,
                        units=block.units or None,
                        header=block.header_lines,
                        header_ok=header_ok,
                        text=text,
                        embed_text=embed_text,
                        tokens=_count_tokens(text),
                    )
                    chunks.append(chunk)
                    current_records = [rec_line]
                    current_tokens = _count_tokens(context_line) + rec_tokens
                else:
                    current_records.append(rec_line)
                    current_tokens += rec_tokens

            # Emitir el último chunk de tabla
            if current_records:
                text = context_line + "\n" + "\n".join(current_records)
                embed_text = _build_embed_text(
                    doc_info.title,
                    doc_info.report_period,
                    section_path,
                    entity,
                    block.units,
                    text,
                )
                chunk = Chunk(
                    chunk_id=next_chunk_id(),
                    doc_id=doc_id,
                    title=doc_info.title,
                    source_kind=doc_info.source_kind,
                    report_period=doc_info.report_period,
                    year=doc_info.year,
                    quarter=doc_info.quarter,
                    lang=doc_info.lang,
                    page=page_num,
                    pages=[page_num],
                    section_path=section_path,
                    entity=entity,
                    content_type="table",
                    table_id=table_id,
                    units=block.units or None,
                    header=block.header_lines,
                    header_ok=header_ok,
                    text=text,
                    embed_text=embed_text,
                    tokens=_count_tokens(text),
                )
                chunks.append(chunk)

    return chunks


def chunk_document(
    parsed_pages: list[dict],
    doc_info: DocumentInfo,
    entities: dict | None = None,
) -> list[Chunk]:
    """
    Genera todos los chunks para un documento.

    Maneja la unión de párrafos que cruzan páginas.
    """
    if entities is None:
        entities = {}

    all_chunks: list[Chunk] = []
    chunk_counter: dict = {}

    # Último párrafo incompleto de la página anterior
    last_para: str | None = None
    last_para_page: int | None = None
    last_para_chunk_idx: int | None = None  # índice en all_chunks del chunk que contiene el párrafo

    for page_data in parsed_pages:
        raw_text = page_data.get("raw_text", "")
        if not raw_text.strip():
            continue

        # Parsear bloques del raw_text
        blocks = parse_blocks(raw_text)

        # Intentar unir párrafo de página anterior con el primero de esta página
        if last_para is not None and blocks and isinstance(blocks[0], ProseBlock):
            first_paras = blocks[0].paragraphs
            if first_paras:
                first_para = first_paras[0].lstrip()
                # Unir si: último párrafo no termina en '.' y este empieza en minúscula
                if (
                    last_para
                    and not last_para.rstrip().endswith(".")
                    and first_para
                    and first_para[0].islower()
                ):
                    # Modificar el primer párrafo de este bloque
                    joined = last_para.rstrip() + " " + first_para
                    blocks[0].paragraphs[0] = joined

                    # Actualizar el chunk anterior que tenía el párrafo incompleto
                    if last_para_chunk_idx is not None and last_para_chunk_idx < len(all_chunks):
                        old_chunk = all_chunks[last_para_chunk_idx]
                        # Reemplazar el texto del chunk anterior (quitar last_para)
                        old_text = old_chunk.text
                        if last_para in old_text:
                            new_text = old_text.replace(last_para, "").strip()
                            if new_text:
                                # Actualizar el chunk anterior
                                new_embed = _build_embed_text(
                                    old_chunk.title,
                                    old_chunk.report_period,
                                    old_chunk.section_path,
                                    old_chunk.entity,
                                    old_chunk.units or "",
                                    new_text,
                                )
                                all_chunks[last_para_chunk_idx] = old_chunk.model_copy(update={
                                    "text": new_text,
                                    "embed_text": new_embed,
                                    "tokens": _count_tokens(new_text),
                                })
                            else:
                                # Eliminar el chunk vacío
                                all_chunks.pop(last_para_chunk_idx)

        page_chunks = chunk_page(
            page_data,
            doc_info,
            blocks,
            chunk_counter,
            entities=entities,
        )

        # Rastrear el último párrafo para posible unión en la siguiente página
        last_para = None
        last_para_page = None
        last_para_chunk_idx = None

        for i, chunk in enumerate(page_chunks):
            if chunk.content_type == "prose":
                # El último chunk de prosa de esta página
                last_para = chunk.text.split("\n\n")[-1] if chunk.text else None
                last_para_page = page_data["page"]
                last_para_chunk_idx = len(all_chunks) + i

        all_chunks.extend(page_chunks)

    return all_chunks
