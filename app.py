import flet as ft
import pandas as pd
import os
import json
from PyPDF2 import PdfMerger

APP_NAME = "MyPdfApp"
CONFIG_DIR = os.path.join(os.getenv("APPDATA"), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# デフォルト設定
default_config = {
    "search_folder": "C:/pdf_folder",
    "output_folder": "C:/pdf_output",
    "search_mode": "通常"
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_config.copy()

def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def main(page: ft.Page):
    page.title = "Excel→PDF結合アプリ"

    # 設定読み込み
    config = load_config()

    result_list = ft.Column(scroll="auto", expand=True)
    selected_pdfs = []
    excel_df = None

    # UI: 検索モード
    search_mode_dropdown = ft.Dropdown(
        label="検索モード",
        options=[ft.dropdown.Option("通常")],
        value=config["search_mode"],
        width=150
    )

    # UI: 検索先フォルダ
    search_folder_field = ft.TextField(
        label="検索先フォルダ",
        value=config["search_folder"],
        width=400
    )

    # UI: 出力先フォルダ
    output_folder_field = ft.TextField(
        label="出力先フォルダ",
        value=config["output_folder"],
        width=400
    )

    # Excel列選択
    column_dropdown = ft.Dropdown(label="検索対象列", options=[], width=200)

    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal excel_df
        if e.files:
            file_path = e.files[0].path
            excel_df = pd.read_excel(file_path)
            column_names = [str(c) for c in excel_df.columns]
            column_dropdown.options = [ft.dropdown.Option(c) for c in column_names]
            column_dropdown.value = column_names[0]
            page.update()

    def search_pdfs(e):
        if excel_df is None or not column_dropdown.value:
            page.snack_bar = ft.SnackBar(ft.Text("Excelと列を選択してください"))
            page.snack_bar.open = True
            page.update()
            return

        search_folder = search_folder_field.value
        if not os.path.exists(search_folder):
            page.snack_bar = ft.SnackBar(ft.Text("検索先フォルダが存在しません"))
            page.snack_bar.open = True
            page.update()
            return

        search_words = excel_df[column_dropdown.value].dropna().astype(str).tolist()

        result_list.controls.clear()
        selected_pdfs.clear()
        seen = set()

        for word in search_words:
            candidates = [
                f for f in os.listdir(search_folder)
                if word in f and f.lower().endswith(".pdf")
            ]
            if not candidates:
                result_list.controls.append(ft.Text(f"{word}: 該当なし"))
            else:
                for pdf in candidates:
                    pdf_path = os.path.join(search_folder, pdf)

                    if pdf_path in seen:
                        continue
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

        output_folder = output_folder_field.value
        os.makedirs(output_folder, exist_ok=True)

        merger = PdfMerger()
        for pdf in selected_pdfs:
            merger.append(pdf)

        output_path = os.path.join(output_folder, "merged.pdf")
        merger.write(output_path)
        merger.close()

        page.snack_bar = ft.SnackBar(ft.Text(f"出力しました: {output_path}"))
        page.snack_bar.open = True
        page.update()

    def save_settings(e):
        config["search_folder"] = search_folder_field.value
        config["output_folder"] = output_folder_field.value
        config["search_mode"] = search_mode_dropdown.value
        save_config(config)
        page.snack_bar = ft.SnackBar(ft.Text("設定を保存しました"))
        page.snack_bar.open = True
        page.update()

    file_picker = ft.FilePicker(on_result=pick_excel_result)
    page.overlay.append(file_picker)

    page.add(
        ft.Row([
            ft.ElevatedButton("Excelを選択", on_click=lambda _: file_picker.pick_files()),
            column_dropdown,
            search_mode_dropdown,
            ft.ElevatedButton("検索実行", on_click=search_pdfs),
            ft.ElevatedButton("PDF結合", on_click=merge_pdfs),
            ft.ElevatedButton("設定保存", on_click=save_settings),
        ]),
        search_folder_field,
        output_folder_field,
        result_list
    )

ft.app(target=main)
