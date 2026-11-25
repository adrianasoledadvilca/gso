"""Exportación de listados a Excel (.xlsx)."""
import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

AZUL = "14324B"
NARANJA = "F08C41"


def exportar_xlsx(titulo, columnas, filas, organismo=""):
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31].replace("/", "-")
    n = len(columnas)
    fino = Side(style="thin", color="B4BEC8")
    borde = Border(left=fino, right=fino, top=fino, bottom=fino)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    ws.cell(1, 1, organismo or "Gestión de Stock Odontológico").font = Font(bold=True, size=13, color=AZUL)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n)
    ws.cell(2, 1, titulo).font = Font(bold=True, size=11)
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=n)
    ws.cell(3, 1, f"Generado: {datetime.now():%d/%m/%Y %H:%M}").font = Font(size=9, color="666666")

    for c, nombre in enumerate(columnas, 1):
        celda = ws.cell(5, c, nombre)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor=NARANJA)
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = borde

    for r, fila in enumerate(filas, 6):
        for c, valor in enumerate(fila, 1):
            celda = ws.cell(r, c, valor)
            celda.border = borde
            nombre = columnas[c - 1].lower()
            if isinstance(valor, float) or any(k in nombre for k in ("precio", "valor", "subtotal", "$", "unitario")):
                if isinstance(valor, (int, float)):
                    celda.number_format = '"$" #,##0.00'
            if str(fila[0]).upper() == "TOTAL" or (len(fila) > 4 and str(fila[4]).upper() == "TOTAL"):
                celda.font = Font(bold=True)

    for c, nombre in enumerate(columnas, 1):
        largo = max([len(str(nombre))] + [len(str(f[c - 1])) for f in filas if c - 1 < len(f)] or [10])
        ws.column_dimensions[get_column_letter(c)].width = min(max(largo + 3, 10), 60)
    ws.freeze_panes = "A6"
    ws.page_setup.orientation = "landscape" if n > 6 else "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
