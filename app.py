# このモジュールは、filepicker関連で大幅変更する前のもの
# この状態はapp.pyとしての最終系で、正常動作はしていない。
# この大幅変更時に、モジュール名称をappからmainに変更



import flet as ft
import pandas as pd
import os
import json
from PyPDF2 import PdfMerger

APP_NAME = "MyPdfApp"
CONFIG_DIR = os.path.join(os.getenv("APPDATA"), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

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
    print("Page platform:", page.platform)
    print("Page web:", page.web)


    page.title = "Excel→PDF結合アプリ"
    page.scroll = "auto"
    page.horizontal_alignment = "center"

    config = load_config()

    result_list = ft.Column(scroll="auto", expand=True)
    selected_pdfs = []
    excel_df = None

    # -----------------------------
    # UI: 検索モード
    # -----------------------------
    search_mode_dropdown = ft.Dropdown(
        label="検索モード",
        options=[ft.dropdown.Option("通常")],
        value=config["search_mode"],
        width=150
    )

    # -----------------------------
    # UI: 検索先／出力先フィールド
    # -----------------------------
    search_folder_field = ft.TextField(
        label="検索先フォルダ",
        value=config["search_folder"],
        width=400,
        read_only=True
    )

    output_folder_field = ft.TextField(
        label="出力先フォルダ",
        value=config["output_folder"],
        width=400,
        read_only=True
    )

    column_dropdown = ft.Dropdown(label="検索対象列", options=[], width=200)

    # -----------------------------
    # FilePicker（フォルダ・ファイル）
    # -----------------------------
    folder_picker_search = ft.FilePicker()
    folder_picker_output = ft.FilePicker()

    # -----------------------------
    # コールバック（フォルダ選択）
    # -----------------------------
    def pick_search_folder(e: ft.FilePickerResultEvent):
        if e.path:
            search_folder_field.value = e.path
            config["search_folder"] = e.path
            save_config(config)
            page.update()

    def pick_output_folder(e: ft.FilePickerResultEvent):
        if e.path:
            output_folder_field.value = e.path
            config["output_folder"] = e.path
            save_config(config)
            page.update()

    # -----------------------------
    # ボタン
    # -----------------------------
    # ✅ 新仕様対応：on_result に代入してから get_directory_path()
    folder_picker_search.on_result = pick_search_folder
    folder_picker_output.on_result = pick_output_folder

    pick_search_btn = ft.ElevatedButton(
        "検索先を選択",
        on_click=lambda _: folder_picker_search.get_directory_path()
    )
    pick_output_btn = ft.ElevatedButton(
        "出力先を選択",
        on_click=lambda _: folder_picker_output.get_directory_path()
    )

    # -----------------------------
    # Excelファイル選択
    # -----------------------------
    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal excel_df
        if e.files:
            file_path = e.files[0].path
            excel_df = pd.read_excel(file_path)
            column_names = [str(c) for c in excel_df.columns]
            column_dropdown.options = [ft.dropdown.Option(c) for c in column_names]
            column_dropdown.value = column_names[0]
            page.update()

    # -----------------------------
    # PDF検索
    # -----------------------------
    def search_pdfs(e):
        nonlocal selected_pdfs
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

    # -----------------------------
    # PDF結合
    # -----------------------------
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

    # -----------------------------
    # 設定保存
    # -----------------------------
    def save_settings(e):
        config["search_folder"] = search_folder_field.value
        config["output_folder"] = output_folder_field.value
        config["search_mode"] = search_mode_dropdown.value
        save_config(config)
        page.snack_bar = ft.SnackBar(ft.Text("設定を保存しました"))
        page.snack_bar.open = True
        page.update()

    # -----------------------------
    # レイアウト
    # -----------------------------
    file_picker = ft.FilePicker(on_result=pick_excel_result)
    page.overlay.extend([folder_picker_search, folder_picker_output, file_picker])

    layout = ft.Column(
        [
            ft.Row(
                [
                    ft.ElevatedButton("Excelを選択", on_click=lambda _: (
                                      print(f"initial_directory: '{search_folder_field.value}'"),
                                      file_picker.pick_files(
                                        allowed_extensions=["xlsx"],
                                        initial_directory=search_folder_field.value  # ✅ 検索先を初期フォルダにする！
                                    ))
                    ),
                    column_dropdown,
                    search_mode_dropdown,
                    ft.ElevatedButton("検索実行", on_click=search_pdfs),
                    ft.ElevatedButton("PDF結合", on_click=merge_pdfs),
                    ft.ElevatedButton("設定保存", on_click=save_settings),
                ],
                alignment="center",
            ),
            ft.Container(height=10),
            ft.Row([search_folder_field, pick_search_btn], alignment="center"),
            ft.Row([output_folder_field, pick_output_btn], alignment="center"),
            ft.Divider(),
            result_list,
        ],
        expand=True,
        alignment="start",
        horizontal_alignment="center",
    )

    page.add(layout)

ft.app(target=main)
