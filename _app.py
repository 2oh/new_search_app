import flet as ft
import pandas as pd
import os
from PyPDF2 import PdfMerger

PDF_FOLDER = "C:/pdf_folder"  # PDFが入っているフォルダ

def main(page: ft.Page):
    page.title = "Excel→PDF結合アプリ"

    result_list = ft.Column(scroll="auto", expand=True)
    selected_pdfs = []
    excel_df = None  # Excelデータを保持
    column_dropdown = ft.Dropdown(label="検索対象列", options=[], width=200)

    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal excel_df
        if e.files:
            file_path = e.files[0].path
            excel_df = pd.read_excel(file_path)

            # 列名を取得（Unnamed: 0 みたいな名前になる場合もあるので文字列化）
            column_names = [str(c) for c in excel_df.columns]

            column_dropdown.options = [ft.dropdown.Option(c) for c in column_names]
            column_dropdown.value = column_names[0]  # デフォルトで1列目
            page.update()

    def search_pdfs(e):
        if excel_df is None or not column_dropdown.value:
            page.snack_bar = ft.SnackBar(ft.Text("Excelと列を選択してください"))
            page.snack_bar.open = True
            page.update()
            return

        # 選択された列の文字列をリスト化
        search_words = excel_df[column_dropdown.value].dropna().astype(str).tolist()

        result_list.controls.clear()
        selected_pdfs.clear()
        seen = set()  # 重複PDF防止用

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

                    if pdf_path in seen:
                        continue  # 重複スキップ
                    seen.add(pdf_path)

                    cb = ft.Checkbox(label=pdf, value=True)

                    def on_change(ev, fname=pdf_path):
                        if ev.control.value:
                            if fname not in selected_pdfs:
                                selected_pdfs.append(fname)
                        else:
                            if fname in selected_pdfs:
                                selected_pdfs.remove(fname)

                    cb.on_change = lambda ev, fname=pdf_path: on_change(ev, fname)
                    selected_pdfs.append(pdf_path)

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
            column_dropdown,
            ft.ElevatedButton("検索実行", on_click=search_pdfs),
            ft.ElevatedButton("選択PDFを結合", on_click=merge_pdfs)
        ]),
        result_list
    )

ft.app(target=main)
