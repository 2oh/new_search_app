import flet as ft
import pandas as pd
import os
import json
import re
from openpyxl import load_workbook

CONFIG_FILE = "config.json"


def main(page: ft.Page):
    page.title = "PDF検索ツール - Excel検索モード Step 2.2（項目名行検出対応）"
    page.scroll = "adaptive"

    # ------------------------------
    # 設定ファイル
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
    # UI 要素
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
    column_dropdown = ft.Dropdown(label="列選択（項目名行に基づく）", width=400)
    extracted_keywords = ft.ListView(expand=True, spacing=5)

    # ------------------------------
    # Excel ヘルパー関数
    # ------------------------------
    def get_merged_cells_info(excel_path, sheet_name):
        """openpyxl で結合セル情報を取得"""
        wb = load_workbook(excel_path, data_only=True)
        ws = wb[sheet_name]
        return ws.merged_cells.ranges

    def detect_header_row(df, merged_cells_info):
        """
        項目名行を自動検出：
        ・A列に値があり
        ・結合セルを含まず
        ・少なくとも 2 列以上に値がある行
        """
        merged_rows = set()
        for crange in merged_cells_info:
            for r in range(crange.min_row - 1, crange.max_row):
                merged_rows.add(r)

        for i, row in df.iterrows():
            if i in merged_rows:
                continue
            a_val = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
            if not a_val:
                continue
            filled = sum(1 for v in row if not pd.isna(v) and str(v).strip() != "")
            if filled >= 2:
                return i
        return 0

    # ------------------------------
    # イベント処理
    # ------------------------------
    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal selected_excel_path, sheet_dropdown, column_dropdown

        if not e.files:
            return

        selected_excel_path = e.files[0].path
        excel_folder_field.value = os.path.dirname(selected_excel_path)

        # ✅ Excel選択時：シート・列選択のコントロールを完全再生成
        sheet_dropdown = ft.Dropdown(
            label="シート選択",
            width=300,
            on_change=on_sheet_selected,  # ✅ ユーザー選択時に自動読み込み
        )
        column_dropdown = ft.Dropdown(label="列選択（項目名行に基づく）", width=400)
        extracted_keywords.controls.clear()

        # 再生成してUIに再配置
        layout.controls[2] = ft.Row(
            [sheet_dropdown],  # ✅ シート読み込みボタン削除
            alignment="center",
        )
        layout.controls[3] = ft.Row(
            [column_dropdown, ft.ElevatedButton("列を読み込む", on_click=on_column_selected)],
            alignment="center",
        )

        page.update()

        # ✅ Excelのシート一覧を取得（初期値はNone、ユーザー選択を待つ）
        try:
            xls = pd.ExcelFile(selected_excel_path)
            sheet_dropdown.options = [ft.dropdown.Option(name) for name in xls.sheet_names]
            sheet_dropdown.value = None  # ✅ 自動選択しない
            page.snack_bar = ft.SnackBar(ft.Text(f"{len(xls.sheet_names)} シートを読み込みました（選択してください）"))
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.dialog = ft.AlertDialog(title=ft.Text("Excel読込エラー"), content=ft.Text(str(ex)))
            page.dialog.open = True
            page.update()


    def on_sheet_selected(e):
        """シート選択時：列Dropdownを再生成"""
        nonlocal column_dropdown

        # ✅ 列Dropdownを完全に再生成してUIに反映
        column_dropdown = ft.Dropdown(label="列選択（項目名行に基づく）", width=400)
        extracted_keywords.controls.clear()
        layout.controls[3] = ft.Row(
            [column_dropdown, ft.ElevatedButton("列を読み込む", on_click=on_column_selected)],
            alignment="center",
        )
        page.update()

        if not selected_excel_path or not sheet_dropdown.value:
            return

        try:
            df = pd.read_excel(selected_excel_path, sheet_name=sheet_dropdown.value, header=None)
            merged_info = get_merged_cells_info(selected_excel_path, sheet_dropdown.value)
            header_row = detect_header_row(df, merged_info)
            headers = df.iloc[header_row].tolist()
            df = df.iloc[header_row + 1:]
            column_dropdown.options = [ft.dropdown.Option(str(h)) for h in headers if str(h).strip() != ""]
            column_dropdown.value = headers[0] if headers else None

            page.snack_bar = ft.SnackBar(ft.Text(f"項目名行 {header_row + 1} 行目を検出しました"))
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.dialog = ft.AlertDialog(title=ft.Text("シート読込エラー"), content=ft.Text(str(ex)))
            page.dialog.open = True
            page.update()


    def on_column_selected(e):
        """列選択 → 文字列抽出"""
        if not selected_excel_path or not column_dropdown.value:
            return
        try:
            # Step 1: まず header_row を再検出（検出ロジックを再利用）
            df_raw = pd.read_excel(selected_excel_path, sheet_name=sheet_dropdown.value, header=None)
            merged_info = get_merged_cells_info(selected_excel_path, sheet_dropdown.value)
            header_row = detect_header_row(df_raw, merged_info)

            # Step 2: 正しい項目名行を header として再読み込み
            df = pd.read_excel(
                selected_excel_path,
                sheet_name=sheet_dropdown.value,
                header=header_row
            )

            # Step 3: 列名を正規化
            df.columns = [str(c).strip().replace("\n", "").replace("\r", "") for c in df.columns]
            selected_col = str(column_dropdown.value).strip().replace("\n", "").replace("\r", "")

            print("▼ 実際の列名一覧:", df.columns.tolist())
            print("▼ 選択中の列名:", selected_col)

            # Step 4: 列一致チェック
            matching_cols = [c for c in df.columns if c == selected_col]
            if not matching_cols:
                raise ValueError(f"列 '{selected_col}' が見つかりません。")

            col = matching_cols[0]
            print("▼ 一致した列:", col)

            # Step 5: 検索文字列抽出
            keywords = []
            for val in df[col].dropna():
                s = str(val).strip()
                if not s:
                    continue
                if re.match(r"^[IUHF]", s) and len(s) > 1 and s[1].isdigit():
                    s = s[1:]
                keywords.append(s)

            # Step 6: 表示更新
            extracted_keywords.controls.clear()
            for kw in keywords:
                extracted_keywords.controls.append(ft.Text(kw))
            page.snack_bar = ft.SnackBar(ft.Text(f"{len(keywords)} 件の検索文字列を抽出しました"))
            page.snack_bar.open = True
            page.update()

        except Exception as ex:
            page.dialog = ft.AlertDialog(title=ft.Text("列読込エラー"), content=ft.Text(str(ex)))
            page.dialog.open = True
            page.update()


    # ------------------------------
    # FilePicker
    # ------------------------------
    file_picker = ft.FilePicker(on_result=pick_excel_result)
    page.overlay.append(file_picker)

    def pick_excel_click(e):
        file_picker.pick_files(allowed_extensions=["xlsx", "xls"])

    # ------------------------------
    # レイアウト
    # ------------------------------
    layout = ft.Column([
        ft.Text("🔍 Excel検索モード", size=20, weight=ft.FontWeight.BOLD),
        ft.Row([excel_folder_field, ft.ElevatedButton("Excelを選択", on_click=pick_excel_click)], alignment="center"),
        ft.Row([sheet_dropdown], alignment="center"),  # ✅ ボタン削除済
        ft.Row([column_dropdown, ft.ElevatedButton("列を読み込む", on_click=on_column_selected)], alignment="center"),
        ft.Divider(),
        ft.Text("📄 抽出された検索文字列:"),
        extracted_keywords
    ], expand=True, scroll="auto")

    page.add(layout)


ft.app(target=main)
