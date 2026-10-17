"""CLI: make ingest [TIER=1|2] y make index-status"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from app.config import settings
from app.contracts import DocumentInfo


def _process_document(args: tuple) -> dict:
    """
    Procesa un documento completo (bandas, regiones, extracción, bloques, records, chunks).
    Función standalone para ProcessPoolExecutor.
    """
    import pymupdf  # type: ignore[import]

    (
        pdf_path_str,
        doc_id,
        sha12,
        doc_info_dict,
        work_dir_str,
        page_kinds_dict,
        entities_dict,
    ) = args

    pdf_path = Path(pdf_path_str)
    work_dir = Path(work_dir_str)
    chunks_dir = work_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    doc_info = DocumentInfo.model_validate(doc_info_dict)

    # E2: bandas
    from app.ingest.bands import detect_bands
    doc = pymupdf.open(str(pdf_path))
    page_bands = detect_bands(doc)

    # E3: regiones por página
    from app.ingest.regions import detect_regions
    page_regions: dict = {}
    for i in range(doc.page_count):
        page = doc[i]
        regions = detect_regions(page)
        page_regions[i] = regions

    doc.close()

    # E4: extracción (con caché por sha12)
    from app.ingest.extract import extract_document_parallel
    parsed_pages = extract_document_parallel(
        pdf_path=pdf_path,
        doc_id=doc_id,
        sha12=sha12,
        page_bands=page_bands,
        page_regions=page_regions,
        work_dir=work_dir,
        page_kinds=page_kinds_dict,
    )

    # Actualizar kind desde probe en parsed_pages
    for pp in parsed_pages:
        page_idx = pp["page"] - 1  # 0-indexed
        pp["kind"] = page_kinds_dict.get(page_idx, "text")

    # E5+E6+E7: bloques, records, chunks
    from app.ingest.blocks import parse_blocks
    from app.ingest.chunk import chunk_document

    all_chunks = chunk_document(
        parsed_pages=parsed_pages,
        doc_info=doc_info,
        entities=entities_dict,
    )

    # Guardar chunks en work_dir/chunks/{sha12}.jsonl
    chunk_file = chunks_dir / f"{sha12}.jsonl"
    with chunk_file.open("w", encoding="utf-8") as fh:
        for chunk in all_chunks:
            fh.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")

    # Estadísticas
    n_table = sum(1 for c in all_chunks if c.content_type == "table")
    n_prose = sum(1 for c in all_chunks if c.content_type == "prose")
    n_header_ok = sum(1 for c in all_chunks if c.content_type == "table" and c.header_ok)

    return {
        "doc_id": doc_id,
        "sha12": sha12,
        "n_pages": len(parsed_pages),
        "n_chunks": len(all_chunks),
        "n_table": n_table,
        "n_prose": n_prose,
        "n_header_ok": n_header_ok,
        "n_header_bad": n_table - n_header_ok,
    }


def main() -> None:
    """Punto de entrada principal del pipeline de ingesta."""
    parser = argparse.ArgumentParser(description="Pipeline de ingesta T1")
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2], help="Nivel de extracción")
    parser.add_argument("--status", action="store_true", help="Mostrar estado del índice")
    args = parser.parse_args()

    if args.status:
        from app.indexstore import IndexStore
        store = IndexStore()
        status = store.status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return

    data_dir = settings.DATA_DIR
    work_dir = settings.WORK_DIR
    work_dir.mkdir(parents=True, exist_ok=True)

    t_total_start = time.time()

    print(f"[ingest] Tier={args.tier} | DATA_DIR={data_dir} | WORK_DIR={work_dir}")

    # ── E0: probe ─────────────────────────────────────────────────
    t0 = time.time()
    from app.ingest.probe import probe_corpus
    probe_data = probe_corpus(data_dir, work_dir)
    t_probe = time.time() - t0
    print(f"[E0 probe] {t_probe:.1f}s")

    if not probe_data.get("documents"):
        print("[ingest] No se encontraron PDFs. Abortando.")
        sys.exit(0)

    # Mapa: doc_id → info de probe
    probe_by_id = {d["doc_id"]: d for d in probe_data["documents"]}
    probe_by_filename = {d["filename"]: d for d in probe_data["documents"]}

    # ── E1: catálogo ──────────────────────────────────────────────
    t0 = time.time()
    from app.ingest.catalog import catalog_all
    doc_info_list = catalog_all(data_dir, work_dir)
    t_catalog = time.time() - t0
    print(f"[E1 catalog] {len(doc_info_list)} docs · {t_catalog:.1f}s")

    # Mapa: doc_id → DocumentInfo
    doc_info_by_id = {d.doc_id: d for d in doc_info_list}

    # ── Cargar entidades ──────────────────────────────────────────
    from app.ingest.chunk import load_or_generate_entities_yaml
    entities_path = work_dir / "entities.yaml"
    entities: dict = {}
    if entities_path.exists():
        import yaml
        with entities_path.open(encoding="utf-8") as f:
            entities = yaml.safe_load(f) or {}
    else:
        entities = load_or_generate_entities_yaml(work_dir, [])

    # ── E2-E7: procesar documentos en paralelo ────────────────────
    pdf_paths = sorted(data_dir.glob("*.pdf"))
    total_docs = len(pdf_paths)
    t0 = time.time()

    import hashlib

    # Preparar args para cada documento
    doc_args: list[tuple] = []
    skip_count = 0
    chunks_dir = work_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = work_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_paths:
        sha12 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:12]
        doc_id = probe_by_filename.get(pdf_path.name, {}).get("doc_id", pdf_path.stem)

        # Verificar caché: si chunks/{sha12}.jsonl existe → skip
        chunk_file = chunks_dir / f"{sha12}.jsonl"
        pages_file = pages_dir / f"{sha12}.jsonl"

        if chunk_file.exists() and pages_file.exists():
            skip_count += 1
            continue

        doc_info = doc_info_by_id.get(doc_id)
        if not doc_info:
            print(f"[ingest] ADVERTENCIA: sin DocumentInfo para {pdf_path.name} (doc_id={doc_id})")
            continue

        probe_entry = probe_by_filename.get(pdf_path.name, {})
        page_kinds_map: dict[int, str] = {}
        if probe_entry:
            # Reconstruir mapa de page_kinds desde page_kinds: {kind: count}
            # No tenemos mapa inverso exacto, usar "text" por defecto
            # Para el mapa preciso necesitaríamos el probe detallado
            import pymupdf
            doc_tmp = pymupdf.open(str(pdf_path))
            for i in range(doc_tmp.page_count):
                page_kinds_map[i] = "text"
            doc_tmp.close()

        doc_args.append((
            str(pdf_path),
            doc_id,
            sha12,
            doc_info.model_dump(),
            str(work_dir),
            page_kinds_map,
            entities,
        ))

    if skip_count > 0:
        print(f"[ingest] {skip_count}/{total_docs} documentos omitidos (caché hit)")

    results: list[dict] = []
    n_to_process = len(doc_args)

    if n_to_process == 0:
        print("[ingest] Todos los documentos ya están procesados.")
    else:
        max_workers = min(4, n_to_process)
        done_count = 0
        t_start_docs = time.time()

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process_document, a): a for a in doc_args}
            for future in as_completed(futures):
                done_count += 1
                elapsed = time.time() - t_start_docs
                eta = elapsed / done_count * (n_to_process - done_count) if done_count > 0 else 0
                print(
                    f"[E4 extract] {done_count}/{n_to_process} docs · "
                    f"{elapsed:.0f}s · ETA {eta:.0f}s"
                )
                try:
                    r = future.result()
                    results.append(r)
                except Exception as e:
                    print(f"[ingest] ERROR procesando documento: {e}", file=sys.stderr)

    t_docs = time.time() - t0
    print(f"[E2-E7] {n_to_process} documentos procesados · {t_docs:.1f}s")

    # ── E8+E9: construir índice ────────────────────────────────────
    t0 = time.time()
    from app.ingest.build import build_index

    version = build_index(
        chunks_dir=chunks_dir,
        doc_info_list=doc_info_list,
        pages_dir=pages_dir,
        work_dir=work_dir,
    )
    t_build = time.time() - t0
    print(f"[E8+E9 build] versión {version} · {t_build:.1f}s")

    # ── Resumen final ─────────────────────────────────────────────
    t_total = time.time() - t_total_start

    total_pages = sum(r.get("n_pages", 0) for r in results)
    total_chunks = sum(r.get("n_chunks", 0) for r in results)
    total_tables = sum(r.get("n_table", 0) for r in results)
    total_prose = sum(r.get("n_prose", 0) for r in results)
    total_header_ok = sum(r.get("n_header_ok", 0) for r in results)
    total_header_bad = sum(r.get("n_header_bad", 0) for r in results)

    # Contar chunks y páginas del caché también
    if skip_count > 0:
        for cfile in chunks_dir.glob("*.jsonl"):
            if not any(r.get("sha12") in str(cfile) for r in results):
                with cfile.open(encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            d = json.loads(line)
                            total_chunks += 1
                            if d.get("content_type") == "table":
                                total_tables += 1
                                if d.get("header_ok"):
                                    total_header_ok += 1
                                else:
                                    total_header_bad += 1
                            elif d.get("content_type") == "prose":
                                total_prose += 1

    print("\n" + "=" * 60)
    print(f"RESUMEN INGESTA")
    print(f"  Documentos: {total_docs} ({skip_count} desde caché)")
    print(f"  Páginas procesadas: {total_pages}")
    print(f"  Chunks totales: {total_chunks} (tablas: {total_tables}, prosa: {total_prose})")
    print(f"  Tablas header OK: {total_header_ok}, header KO: {total_header_bad}")
    print(f"  Tiempos: probe={t_probe:.1f}s, catalog={t_catalog:.1f}s, docs={t_docs:.1f}s, build={t_build:.1f}s")
    print(f"  Total: {t_total:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
