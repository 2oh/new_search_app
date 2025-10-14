import flet as ft
import pandas as pd
import os
import json
import re

CONFIG_FILE = "config.json"


def main(page: ft.Page):
    page.title = "PDF検索ツール - Excel検索モード Step 2.1"
    page.scroll = "adaptive"

    # ------------------------------
    # 設定ファイルの読み込み
    # ------------------------------
    def load_config():
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"excel_folder": "", "pdf_folder": "", "output_folder": "", "search_mode": "Excel"}

    def save_config():
        config.update({
            "excel_folder": excel_folder_field.value,
            "pdf_folder": search_folder_field.value,
            "output_folder": output_folder_field.value,
            "search_mode": mode_dropdown.value,
        })
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    config = load_config()

    # ------------------------------
    # UI要素定義
    # ------------------------------
    excel_folder_field = ft.TextField(label="Excelフォルダ", value=config.get("excel_folder", ""), expand=True)
    search_folder_field = ft.TextField(label="検索先フォルダ（PDF）", value=config.get("pdf_folder", ""), expand=True)
    output_folder_field = ft.TextField(label="出力先フォルダ", value=config.get("output_folder", ""), expand=True)
    mode_dropdown = ft.Dropdown(
        label="検索モード",
        options=[ft.dropdown.Option("Excel"), ft.dropdown.Option("通常")],
        value=config.get("search_mode", "Excel"),
    )

    selected_excel_path = ""
    sheet_dropdown = ft.Dropdown(label="シート選択", width=300)
    column_dropdown = ft.Dropdown(label="列選択（タイトル行に基づく）", width=400)
    extracted_keywords = ft.ListView(expand=True, spacing=5)

    # ------------------------------
    # Excelファイル選択
    # ------------------------------
    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal selected_excel_path
        if not e.files:
            return
        selected_excel_path = e.files[0].path
        excel_folder_field.value = os.path.dirname(selected_excel_path)
        page.update()

        try:
            xls = pd.ExcelFile(selected_excel_path)
            sheet_dropdown.options = [ft.dropdown.Option(name) for name in xls.sheet_names]
            sheet_dropdown.value = xls.sheet_names[0]
            page.snack_bar = ft.SnackBar(ft.Text(f"{len(xls.sheet_names)} シートを読み込みました。"))
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.dialog = ft.AlertDialog(title=ft.Text("Excel読込エラー"), content=ft.Text(str(ex)))
            page.dialog.open = True
            page.update()

    def detect_header_row(df):
        """タイトル行を自動検出：A列に値があり、結合でない行を探す"""
        for i, row in df.iterrows():
            val = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
            if val:
                return i
        return 0  # 見つからない場合は0行目

    def on_sheet_selected(e):
        """選択されたシートの列を取得（タイトル行自動検出）"""
        if not selected_excel_path:
            return
        try:
            df = pd.read_excel(selected_excel_path, sheet_name=sheet_dropdown.value, header=None)
            header_row = detect_header_row(df)
            headers = df.iloc[header_row].tolist()
            df = df.iloc[header_row + 1:]
            column_dropdown.options = [ft.dropdown.Option(str(h)) for h in headers if str(h).strip() != ""]

            column_dropdown.value = headers[0] if headers else None
            page.snack_bar = ft.SnackBar(ft.Text(f"タイトル行 {header_row + 1} 行目を検出しました"))
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.dialog = ft.AlertDialog(title=ft.Text("シート読込エラー"), content=ft.Text(str(ex)))
            page.dialog.open = True
            page.update()

    def on_column_selected(e):
        """列選択→文字列抽出"""
        if not selected_excel_path or not column_dropdown.value:
            return
        try:
            df = pd.read_excel(selected_excel_path, sheet_name=sheet_dropdown.value)
            col = column_dropdown.value
            keywords = []

            for val in df[col].dropna():
                s = str(val).strip()
                if not s:
                    continue
                if re.match(r"^[IUHF]", s) and len(s) > 1 and s[1].isdigit():
                    s = s[1:]
                keywords.append(s)

            extracted_keywords.controls.clear()
            for kw in keywords:
                extracted_keywords.controls.append(ft.Text(kw))
            page.snack_bar = ft.SnackBar(ft.Text(f"{len(keywords)} 件のキーワードを抽出しました"))
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.dialog = ft.AlertDialog(title=ft.Text("列読込エラー"), content=ft.Text(str(ex)))
            page.dialog.open = True
            page.update()

    # ------------------------------
    # FilePicker登録
    # ------------------------------
    file_picker = ft.FilePicker(on_result=pick_excel_result)
    page.overlay.append(file_picker)

    def pick_excel_click(e):
        file_picker.pick_files(allowed_extensions=["xlsx", "xls"])

    # ------------------------------
    # レイアウト
    # ------------------------------
    layout = ft.Column([
        ft.Text("🔍 Excel検索モード (Step 2.1)", size=20, weight=ft.FontWeight.BOLD),
        ft.Row([excel_folder_field, ft.ElevatedButton("Excelを選択", on_click=pick_excel_click)], alignment="center"),
        ft.Row([sheet_dropdown, ft.ElevatedButton("シート読み込み", on_click=on_sheet_selected)], alignment="center"),
        ft.Row([column_dropdown, ft.ElevatedButton("列を読み込む", on_click=on_column_selected)], alignment="center"),
        ft.Divider(),
        ft.Text("📄 抽出された検索文字列:"),
        extracted_keywords
    ], expand=True, scroll="auto")

    page.add(layout)


ft.app(target=main)
