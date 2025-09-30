import flet as ft
import pandas as pd
import os
from PyPDF2 import PdfMerger

PDF_FOLDER = "C:/pdf_folder"  # PDFが入っているフォルダ

def main(page: ft.Page):
    page.title = "Excel→PDF結合アプリ"

    result_list = ft.Column(scroll="auto", expand=True)
    selected_pdfs = []

    def pick_excel_result(e: ft.FilePickerResultEvent):
        if e.files:
            file_path = e.files[0].path
            df = pd.read_excel(file_path)

            # A列から検索文字列を取得（最小限なので固定）
            search_words = df.iloc[:, 0].dropna().astype(str).tolist()

            result_list.controls.clear()
            selected_pdfs.clear()

            for word in search_words:
                candidates = [
                    f for f in os.listdir(PDF_FOLDER)
                    if word in f and f.lower().endswith(".pdf")
                ]
                if not candidates:
                    result_list.controls.append(ft.Text(f"{word}: 該当なし"))
                else:
                    for pdf in candidates:
                        pdf_path = os.path.join(PDF_FOLDER, pdf)

                        # チェックボックス（初期ON）
                        cb = ft.Checkbox(label=pdf, value=True)

                        def on_change(ev, fname=pdf_path):
                            if ev.control.value:
                                if fname not in selected_pdfs:
                                    selected_pdfs.append(fname)
                            else:
                                if fname in selected_pdfs:
                                    selected_pdfs.remove(fname)

                        cb.on_change = on_change
                        selected_pdfs.append(pdf_path)  # 初期ONなので追加

                        result_list.controls.append(cb)

            page.update()

    def merge_pdfs(e):
        if not selected_pdfs:
            page.snack_bar = ft.SnackBar(ft.Text("PDFが選択されていません"))
            page.snack_bar.open = True
            page.update()
            return

        merger = PdfMerger()
        for pdf in selected_pdfs:
            merger.append(pdf)

        output_path = os.path.join(PDF_FOLDER, "merged.pdf")
        merger.write(output_path)
        merger.close()

        page.snack_bar = ft.SnackBar(ft.Text(f"出力しました: {output_path}"))
        page.snack_bar.open = True
        page.update()

    file_picker = ft.FilePicker(on_result=pick_excel_result)
    page.overlay.append(file_picker)

    page.add(
        ft.Row([
            ft.ElevatedButton("Excelを選択", on_click=lambda _: file_picker.pick_files()),
            ft.ElevatedButton("選択PDFを結合", on_click=merge_pdfs)
        ]),
        result_list
    )

ft.app(target=main)
