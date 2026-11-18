"""Create a new workbook from selected part stock; no source workbook is opened."""
import os
from pathlib import Path
import uuid

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


def export_parts(items, destination):
    selected = [item for item in items if item['selected']]
    if not selected:
        raise ValueError('出力する部品を選択してください')
    destination = Path(destination)
    temporary = destination.with_name(f'.parts-{uuid.uuid4().hex}.xlsx')
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '部品一覧'
    sheet.append(['代表品名', '品番／PG', '材料', 'PDFリンク', '使用製品ID'])
    sheet.freeze_panes = 'A2'
    sheet.sheet_view.zoomScale = 85
    for cell in sheet[1]:
        cell.font = Font(name='Yu Gothic', bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='234B69')
    sheet.row_dimensions[1].height = 28
    for column, width in zip('ABCDE', (32, 25, 24, 65, 35)):
        sheet.column_dimensions[column].width = width
    try:
        for group in selected:
            ids = sorted({o['product_id'] for o in group['occurrences'] if o['product_id']})
            for offset, pdf in enumerate(group['pdfs'] or [None]):
                values = [group['name'], group['identifier'], group['material'],
                          Path(pdf).name if pdf else group['pdf_status'], ', '.join(ids)]
                if offset:
                    values[0] = values[1] = values[2] = values[4] = ''
                if any(len(str(value)) > 32767 for value in values):
                    raise ValueError('1セルの文字数がExcelの上限を超えています。出力部品を分けてください')
                sheet.append(values)
                for cell in sheet[sheet.max_row]:
                    if len(str(cell.value or '')) > 32767:
                        raise ValueError('1セルの文字数がExcelの上限を超えています。出力部品を分けてください')
                    cell.data_type = 's'
                    cell.font = Font(name='Yu Gothic', size=11)
                    cell.alignment = Alignment(vertical='top', wrap_text=True)
                    if offset == 0:
                        cell.border = Border(top=Side(style='thin', color='879BAA'))
                if pdf:
                    cell = sheet.cell(sheet.max_row, 4)
                    cell.hyperlink = Path(pdf).as_uri()
                    cell.font = Font(name='Yu Gothic', size=11, color='0563C1', underline='single')
                sheet.row_dimensions[sheet.max_row].height = max(32, 15 * (1 + max(len(str(v)) // 30 for v in values)))
        sheet.print_title_rows = '1:1'
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = 'landscape'
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        workbook.save(temporary)
        os.replace(temporary, destination)
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)
    return destination
