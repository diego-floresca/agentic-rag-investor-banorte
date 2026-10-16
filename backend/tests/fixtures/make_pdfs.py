"""
Genera los 2 PDFs sintéticos de fixtures según SPEC §Fixtures.

PDF 1 (una_columna.pdf)  — empresa ficticia:
  - Tabla con encabezado de periodos de dos niveles
  - Subtítulos internos (ej. "Créditos Comerciales")
  - Marca "(1)" en un valor
  - Párrafo que cruza de página
  - Tabla de solo texto (sin cifras)

PDF 2 (balance_dos_columnas.pdf)  — empresa ficticia:
  - Dos columnas tipo balance general
  - Subtotal en la línea del último hijo

Ejecutar: uv run python backend/tests/fixtures/make_pdfs.py
Los PDFs se guardan en el mismo directorio que este script.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

HERE = Path(__file__).parent
W, H = letter


# ─────────────────────────────────────────────────────────────────
# PDF 1: una columna con tablas y párrafo que cruza de página
# ─────────────────────────────────────────────────────────────────

def make_pdf_una_columna(path: Path) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    elements = []

    # Título
    elements.append(Paragraph("Empresa Ficticia S.A. — Reporte 2T26", styles["Title"]))
    elements.append(Spacer(1, 0.5 * cm))

    # ── Tabla principal con periodos de dos niveles y subtítulos ──
    # Encabezado nivel 1: periodos
    # Encabezado nivel 2: columnas por periodo
    header_row0 = ["", "1T26", "", "2T26", "", "Var."]
    header_row1 = ["Concepto", "Monto", "Mix%", "Monto", "Mix%", "Vs 1T26"]

    data: list[list[str]] = [header_row0, header_row1]

    # Subtítulo interno: Créditos Comerciales
    data.append(["Créditos Comerciales", "", "", "", "", ""])
    data.append(["  Empresas", "310,000", "43%", "320,000", "44%", "3%"])
    data.append(["  Pymes", "145,000", "20%", "148,000", "21%", "2%"])
    data.append(["  Gobierno", "255,000", "36%", "247,000 (1)", "34%", "(3%)"])
    # Subtotal
    data.append(["Créditos Comerciales (subtotal)", "710,000", "100%", "715,000", "100%", "1%"])

    # Subtítulo interno: Créditos Consumo
    data.append(["Créditos Consumo", "", "", "", "", ""])
    data.append(["  Hipotecario", "180,000", "56%", "185,000", "57%", "3%"])
    data.append(["  Nómina", "140,000", "44%", "142,000", "43%", "1%"])
    data.append(["Créditos Consumo (subtotal)", "320,000", "100%", "327,000", "100%", "2%"])

    # Total
    data.append(["TOTAL CARTERA", "1,030,000", "", "1,042,000", "", "1%"])

    col_widths = [7 * cm, 2.5 * cm, 1.5 * cm, 2.5 * cm, 1.5 * cm, 2 * cm]

    tbl = Table(data, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#D0E4F7")),
        ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 2), (0, 2), "Helvetica-Bold"),   # subtítulo 1
        ("FONTNAME", (0, 7), (0, 7), "Helvetica-Bold"),   # subtítulo 2
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),  # total
        ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#E8F0E8")),  # subtotal 1
        ("BACKGROUND", (0, 10), (-1, 10), colors.HexColor("#E8F0E8")),  # subtotal 2
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 0.5 * cm))

    # ── Nota al pie ──────────────────────────────────────────────
    elements.append(Paragraph(
        "(1) Incluye cartera reestructurada por Ps 12,500 millones.",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 0.5 * cm))

    # ── Tabla de solo texto (sin cifras) ─────────────────────────
    elements.append(Paragraph("Factores de riesgo", styles["Heading2"]))
    text_data = [
        ["Factor", "Descripción"],
        ["Riesgo de crédito", "Posibilidad de incumplimiento de contrapartes"],
        ["Riesgo de mercado", "Variaciones en tasas de interés y tipo de cambio"],
        ["Riesgo operativo", "Fallas en procesos internos, personas o sistemas"],
        ["Riesgo de liquidez", "Incapacidad de cumplir obligaciones a corto plazo"],
    ]
    text_tbl = Table(text_data, colWidths=[5 * cm, 12 * cm])
    text_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D0E4F7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(text_tbl)
    elements.append(Spacer(1, 0.5 * cm))

    # ── Párrafo largo que cruza de página ─────────────────────────
    elements.append(Paragraph("Perspectivas y contexto macroeconómico", styles["Heading2"]))
    long_text = (
        "La empresa ficticia mantiene una posición sólida en el mercado nacional. "
        "Durante el segundo trimestre de 2026, la cartera total creció un 1.2% respecto "
        "al trimestre anterior, impulsada principalmente por el segmento hipotecario y el "
        "crecimiento en préstamos a empresas medianas. "
        * 12  # repetir para asegurar que cruza de página
    )
    elements.append(Paragraph(long_text, styles["Normal"]))

    doc.build(elements)


# ─────────────────────────────────────────────────────────────────
# PDF 2: balance a dos columnas con subtotales
# ─────────────────────────────────────────────────────────────────

def make_pdf_balance(path: Path) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(
        "Empresa Ficticia S.A. — Balance General 2T26 (millones de pesos)",
        styles["Title"],
    ))
    elements.append(Spacer(1, 0.5 * cm))

    # Balance a dos columnas: Activo | Pasivo y Capital
    activos = [
        ("ACTIVO", "", True),
        ("Activo circulante", "", True),
        ("  Efectivo y equivalentes", "85,200", False),
        ("  Inversiones temporales", "42,100", False),
        ("  Cartera de crédito neta", "715,000", False),
        ("Activo circulante (subtotal)", "842,300", True),
        ("Activo no circulante", "", True),
        ("  Propiedades y equipo", "12,400", False),
        ("  Activos intangibles", "3,800", False),
        ("  Otros activos", "5,600", False),
        ("Activo no circulante (subtotal)", "21,800", True),
        ("TOTAL ACTIVO", "864,100", True),
    ]

    pasivos = [
        ("PASIVO Y CAPITAL", "", True),
        ("Pasivo circulante", "", True),
        ("  Depósitos a la vista", "380,000", False),
        ("  Depósitos a plazo", "220,000", False),
        ("  Préstamos bancarios CP", "45,000", False),
        ("Pasivo circulante (subtotal)", "645,000", True),
        ("Pasivo no circulante", "", True),
        ("  Deuda a largo plazo", "85,000", False),
        ("  Obligaciones laborales", "8,500", False),
        ("Pasivo no circulante (subtotal)", "93,500", True),
        ("Capital contable", "125,600", True),
        ("TOTAL PASIVO Y CAPITAL", "864,100", True),
    ]

    # Construir tabla de dos columnas lado a lado
    rows: list[list[str]] = [["Concepto", "Monto", "Concepto", "Monto"]]
    for (a_label, a_val, a_bold), (p_label, p_val, p_bold) in zip(activos, pasivos):
        rows.append([a_label, a_val, p_label, p_val])

    col_widths = [6 * cm, 2.5 * cm, 6 * cm, 2.5 * cm]
    tbl = Table(rows, colWidths=col_widths)

    # Estilos base
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D0E4F7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]

    # Negritas para filas con subtotales y cabeceras de sección
    bold_rows_activo = {i + 1 for i, (_, _, is_bold) in enumerate(activos) if is_bold}
    bold_rows_pasivo = {i + 1 for i, (_, _, is_bold) in enumerate(pasivos) if is_bold}
    bold_rows = bold_rows_activo & bold_rows_pasivo | bold_rows_activo | bold_rows_pasivo

    for row_idx in bold_rows:
        if row_idx < len(rows):
            style_cmds.append(("FONTNAME", (0, row_idx), (1, row_idx), "Helvetica-Bold"))
            style_cmds.append(("FONTNAME", (2, row_idx), (3, row_idx), "Helvetica-Bold"))
            # Fondo suave en subtotales
            _, a_val, a_bold = activos[row_idx - 1] if row_idx - 1 < len(activos) else ("", "", False)
            if "subtotal" in activos[row_idx - 1][0].lower() if row_idx - 1 < len(activos) else False:
                style_cmds.append(("BACKGROUND", (0, row_idx), (1, row_idx), colors.HexColor("#E8F0E8")))
            if "subtotal" in pasivos[row_idx - 1][0].lower() if row_idx - 1 < len(pasivos) else False:
                style_cmds.append(("BACKGROUND", (2, row_idx), (3, row_idx), colors.HexColor("#E8F0E8")))

    tbl.setStyle(TableStyle(style_cmds))
    elements.append(tbl)

    doc.build(elements)


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    output_dir = HERE / "pdfs"
    output_dir.mkdir(exist_ok=True)

    p1 = output_dir / "una_columna.pdf"
    p2 = output_dir / "balance_dos_columnas.pdf"

    make_pdf_una_columna(p1)
    print(f"Generado: {p1}")

    make_pdf_balance(p2)
    print(f"Generado: {p2}")
