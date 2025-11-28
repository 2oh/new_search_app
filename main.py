# ======================================================
#  Excel–PDF結合アプリ（フェーズ2.8.1 base）
#  Excel–PDF結合アプリ（フェーズ2.9.0.1）
#  Excel–PDF結合アプリ（フェーズ2.9.0.2）
#  Excel–PDF結合アプリ（フェーズ2.9.0.3）
#  Excel–PDF結合アプリ（フェーズ2.9.0.4）
# ======================================================

import flet as ft
import pandas as pd
import os
import json
import re
from openpyxl import load_workbook

CONFIG_FILE = "config.json"


# ========= 共通ユーティリティ =========
def normalize(text: str) -> str:
    if text is None:
        return ""
    s = str(text).strip().lower()
    s = s.translate(str.maketrans(
        "０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
        "0123456789abcdefghijklmnopqrstuvwxyz"
    ))
    s = re.sub(r"[／/⁄・\.\s　\-＿_]", "", s)
    return s


# ========= Excel列検出 =========
def detect_columns(file_path: str, sheet_name: str, header_row_index: int, target_columns=None):
    if target_columns is None:
        target_columns = ["品番", "PG名", "品名", "数量"]

    df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row_index)

    print(f"\n[DEBUG] ===== detect_columns start =====")
    print(f"[DEBUG] header_row_index = {header_row_index}")
    print(f"[DEBUG] df.columns = {list(df.columns)}")

    detected = {}
    normalized_cols = [normalize(c) for c in df.columns]
    print(f"[DEBUG] normalized_cols = {normalized_cols}")

    for target in target_columns:
        norm_target = normalize(target)
        print(f"[DEBUG] Searching for '{target}' (normalized='{norm_target}')")
        for i, col in enumerate(normalized_cols):
            if norm_target in col or col in norm_target:
                print(f"[DEBUG]  -> matched '{df.columns[i]}' (normalized='{col}')")
                detected[target] = i
                break
            if norm_target.startswith("pg") and ("pg" in col or "ｐｇ" in col):
                print(f"[DEBUG]  -> matched (special rule) '{df.columns[i]}' (normalized='{col}')")
                detected[target] = i
                break
    print(f"[DEBUG] detect_columns detected={detected}")
    print(f"[DEBUG] ===== detect_columns end =====\n")

    return detected


# ========= 数量セルの背景色を取得 =========
def get_quantity_colors(file_path: str, sheet_name: str, header_row_index: int, quantity_col_index: int):
    """
    数量セルに「何らかの色が付いているかどうか」を判定して返す。
    - パターンなし or 塗りなし → ""（無色扱い）
    - 何らかの色（RGB / indexed / theme） → 何かしらの文字列（非空）
    """
    wb = load_workbook(file_path, data_only=True)
    ws = wb[sheet_name]
    colors = []

    for row_idx in range(header_row_index + 2, ws.max_row + 1):
        cell = ws.cell(row=row_idx, column=quantity_col_index + 1)  # openpyxlは1始まり
        fill = cell.fill

        if not fill:
            colors.append("")
            continue

        pattern = getattr(fill, "patternType", None)
        # パターンが none / 未設定なら「塗りなし」とみなす
        if pattern in (None, "none"):
            colors.append("")
            continue

        fg = fill.fgColor
        if fg is None:
            colors.append("")
            continue

        colored = False
        marker = ""

        # 1) RGB 色
        if fg.type == "rgb":
            # 完全な白 or 透明っぽい値は「塗りなし」とみなす
            if fg.rgb not in (None, "00000000", "FFFFFFFF"):
                colored = True
                marker = fg.rgb

        # 2) インデックス色（パレット）
        elif fg.type == "indexed":
            # 0, 64 は「塗りなし」的な扱いが多いので除外
            if fg.index not in (0, 64):
                colored = True
                marker = f"indexed:{fg.index}"

        # 3) テーマ色
        elif fg.type == "theme":
            # テーマ色で塗りがある場合は、とりあえず「色あり」とみなす
            colored = True
            marker = f"theme:{fg.theme}"

        # その他タイプは一応「色なし」として扱う
        if colored:
            colors.append(marker)
        else:
            colors.append("")

    return colors


# ========= Excel抽出処理 =========
def extract_data_from_excel(file_path: str, sheet_name: str, detected_columns: dict, header_row_index: int):
    df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row_index)

    col_items = []
    for key in ["品番", "PG名", "品名", "数量"]:
        if key in detected_columns:
            col_name = df.columns[detected_columns[key]]
            col_items.append(col_name)

    sub_df = df[col_items].copy() if col_items else pd.DataFrame()

    # --- 品名列が結合されている場合への対応 ---
    cols = list(df.columns)

    def find_name_block_indices(cols):
        for i, c in enumerate(cols):
            if "品名" in str(c):
                j = i + 1
                block = [i]
                while j < len(cols):
                    cj = str(cols[j])
                    if cj.startswith("Unnamed") or cj.strip() == "" or cj.lower() in ("none", "nan"):
                        block.append(j)
                        j += 1
                    else:
                        break
                return block
        return []

    name_idx = find_name_block_indices(cols)
    if name_idx:
        name_df = df.iloc[:, name_idx].astype(str)
        sub_df["品名"] = (
            name_df.apply(lambda row: " ".join(v.strip() for v in row if v.strip() and v.lower() != "nan"), axis=1)
            .str.strip()
        )
    else:
        name_like_cols = [c for c in df.columns if "品名" in str(c)]
        if len(name_like_cols) == 1:
            sub_df["品名"] = df[name_like_cols[0]].astype(str).fillna("").str.strip()

    # --- 数量フィルタ ---
    quantity_col = next((c for c in df.columns if "数量" in str(c)), None)
    if quantity_col:
        def keep_row(x):
            if pd.isna(x):
                return False
            s = str(x).strip()
            if s == "":
                return False
            try:
                return float(s.replace(",", "")) != 0.0
            except ValueError:
                return True
        sub_df = sub_df[df[quantity_col].apply(keep_row)]

    # ✅ 検出された列に基づいて、列名を統一（英字ブレ対応）
    rename_map = {}
    if "品番" in detected_columns:
        rename_map[df.columns[detected_columns["品番"]]] = "品番"
    if "PG名" in detected_columns:
        rename_map[df.columns[detected_columns["PG名"]]] = "PG名"
    if "品名" in detected_columns:
        rename_map[df.columns[detected_columns["品名"]]] = "品名"
    if "数量" in detected_columns:
        rename_map[df.columns[detected_columns["数量"]]] = "数量"

    sub_df.rename(columns=rename_map, inplace=True)

    # ✅ 品名列が複数（例：'品名', 'Unnamed:3'）ある場合は結合して1列に統一
    name_like_cols = [c for c in sub_df.columns if "品名" in str(c) or "Unnamed" in str(c)]
    if len(name_like_cols) > 1:
        sub_df["品名"] = sub_df[name_like_cols].astype(str).apply(
            lambda row: " ".join(v.strip() for v in row if v.strip() and v.lower() != "nan"),
            axis=1
        )
        sub_df.drop(columns=[c for c in name_like_cols if c != "品名"], inplace=True)

    # ✅ 対象列のみを保持（項番・備考など除外）
    keep_cols = [c for c in ["品番", "PG名", "品名", "数量"] if c in sub_df.columns]
    sub_df = sub_df[keep_cols]

    return sub_df



# ========= メイン =========
def main(page: ft.Page):
    page.title = "Excel–PDF結合アプリ（フェーズ2.8.0）"
    page.scroll = "adaptive"

    try:
        page.window_maximized = True
    except Exception:
        pass
    
    # ---- 設定ファイル処理 ----
    def load_config():
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "excel_folder": "",
            "pdf_folder": "",
            "output_folder": "",
            "search_mode": "構成部品表",
            "target_columns": ["品番", "PG名"],
        }

    def save_config(e=None):
        config.update({
            "excel_folder": excel_folder_field.value,
            "pdf_folder": search_folder_field.value,
            "output_folder": output_folder_field.value,
            "search_mode": mode_dropdown.value,
            "target_columns": [x.strip() for x in target_col_field.value.split(",") if x.strip()],
        })
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        page.snack_bar = ft.SnackBar(ft.Text("設定を保存しました。"))
        page.snack_bar.open = True
        page.update()

    config = load_config()

    # ---- UI構成 ----
    search_folder_field = ft.TextField(label="検索先フォルダ", value=config.get("pdf_folder", ""), expand=True)
    output_folder_field = ft.TextField(label="出力先フォルダ", value=config.get("output_folder", ""), expand=True)
    target_col_field = ft.TextField(
        label="抽出対象列（カンマ区切り）",
        value=", ".join(config.get("target_columns", [])),
        width=450  # ← expand=False & 半分幅
    )
    mode_dropdown = ft.Dropdown(
        label="検索モード",
        options=[ft.dropdown.Option("構成部品表"), ft.dropdown.Option("通常")],
        value=config.get("search_mode", "構成部品表"),
        width=150
    )

    # ---- フォルダ選択ダイアログ ----
    folder_picker_search = ft.FilePicker(on_result=lambda e: pick_search_result(e))
    folder_picker_output = ft.FilePicker(on_result=lambda e: pick_output_result(e))
    page.overlay.extend([folder_picker_search, folder_picker_output])

    def pick_search_folder(e):
        start_path = search_folder_field.value.strip()  # ← テキストボックスから取得
        if not os.path.isdir(start_path):
            start_path = os.getcwd()
        folder_picker_search.get_directory_path(initial_directory=start_path)

    def pick_output_folder(e):
        start_path = output_folder_field.value.strip()  # ← テキストボックスから取得
        if not os.path.isdir(start_path):
            start_path = os.getcwd()
        folder_picker_output.get_directory_path(initial_directory=start_path)

    def pick_search_result(e: ft.FilePickerResultEvent):
        if e.path:
            search_folder_field.value = e.path
            page.update()

    def pick_output_result(e: ft.FilePickerResultEvent):
        if e.path:
            output_folder_field.value = e.path
            page.update()

    # ---- 検索モード行 ----
    def update_mode_fields():
        if mode_dropdown.value == "構成部品表":
            # expandではなく固定幅にする
            target_col_field.expand = False
            target_col_field.width = 450  # ← 半分くらいの幅に調整（必要に応じて増減OK）
            mode_row.controls = [
                mode_dropdown,
                target_col_field,
                ft.ElevatedButton("設定を保存", on_click=save_config)
            ]
        else:
            manual_field = ft.TextField(
                label="検索文字列（手動入力）",
                width=450  # ← 同じ幅で統一
            )
            mode_row.controls = [
                mode_dropdown,
                manual_field,
                ft.ElevatedButton("設定を保存", on_click=save_config)
            ]
        page.update()

    mode_row = ft.Row(
        [mode_dropdown, target_col_field, ft.ElevatedButton("設定を保存", on_click=save_config)],
        alignment="spaceBetween"
    )
    mode_dropdown.on_change = lambda e: update_mode_fields()

    # ---- Excel選択 ----
    selected_excel_path = ""
    sheet_dropdown = ft.Dropdown(label="シート選択", width=300)
    message = ft.Text("")
    table = ft.DataTable(columns=[ft.DataColumn(ft.Text("項目"))], rows=[])
    table_header = ft.Row([], alignment="center")

    # 🔽🔽 ここを追加 🔽🔽
    def on_sheet_change(e):
        # シート変更時に抽出結果を初期化
        table.rows = []
        table.columns = [ft.DataColumn(ft.Text("項目"))]
        table_header.controls = []
        message.value = ""
        page.update()

    sheet_dropdown.on_change = on_sheet_change
    # 🔼🔼 ここまで追加 🔼🔼

    file_picker = ft.FilePicker(on_result=lambda e: pick_excel_result(e))
    page.overlay.append(file_picker)

    def pick_excel_click(e):
        file_picker.pick_files(allowed_extensions=["xlsx", "xls"])

    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal selected_excel_path
        if not e.files:
            return
        selected_excel_path = e.files[0].path
        excel_folder_field.value = os.path.abspath(selected_excel_path)
        page.update()
        try:
            xls = pd.ExcelFile(selected_excel_path)
            sheet_dropdown.options = [ft.dropdown.Option(name) for name in xls.sheet_names]
            sheet_dropdown.value = None
            page.snack_bar = ft.SnackBar(ft.Text("シートを選択してください。"))
            page.snack_bar.open = True
            page.update()
        except PermissionError:
            page.dialog = ft.AlertDialog(title=ft.Text("ファイル使用中"), content=ft.Text("Excelファイルを閉じてください。"))
            page.dialog.open = True
            page.update()

    # ---- ヘッダ検出 ----
    def get_merged_cells_info(excel_path, sheet_name):
        wb = load_workbook(excel_path, data_only=True)
        ws = wb[sheet_name]
        return ws.merged_cells.ranges

    def detect_header_row(df, merged_cells_info):
        merged_a_rows = set()
        for crange in merged_cells_info:
            if crange.min_col == 1:
                for r in range(crange.min_row - 1, crange.max_row):
                    merged_a_rows.add(r)
        for i, row in df.iterrows():
            a_val = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
            filled = sum(1 for v in row if not pd.isna(v) and str(v).strip() != "")
            if i in merged_a_rows or not a_val:
                continue
            if filled >= 1:
                return i
        return 0

    # ---- 抽出処理 ----
    def on_extract_click(e):
        if not selected_excel_path or not sheet_dropdown.value:
            message.value = "Excelファイルとシートを選択してください。"
            page.update()
            return
        try:
            df_raw = pd.read_excel(selected_excel_path, sheet_name=sheet_dropdown.value, header=None)
            merged_info = get_merged_cells_info(selected_excel_path, sheet_dropdown.value)
            header_row_index = detect_header_row(df_raw, merged_info)
            detected_columns = detect_columns(selected_excel_path, sheet_dropdown.value, header_row_index)
            df = extract_data_from_excel(selected_excel_path, sheet_dropdown.value, detected_columns, header_row_index)

            def create_search_keyword(text):
                if pd.isna(text):
                    return ""
                s = str(text).strip()
                if len(s) >= 2 and s[0].upper() in ["I", "U", "H", "F"] and s[1].isdigit():
                    s = s[1:]
                for pat in ["R/L", "L/R", "A/B"]:
                    idx = s.find(pat)
                    if idx != -1:
                        s = s[:idx]
                idx_slash = s.find("/")
                if idx_slash != -1:
                    s = s[:idx_slash]
                return s.strip()

            # --- 品番 or PG名 のどちらか優先で生成（ラベル固定）
            df["検索用文字列"] = df.apply(
                lambda row: create_search_keyword(row.get("品番")) or create_search_keyword(row.get("PG名")),
                axis=1
            )

            qty_colors = []
            if "数量" in detected_columns:
                qty_colors = get_quantity_colors(selected_excel_path, sheet_dropdown.value, header_row_index, detected_columns["数量"])
                df["数量セル色"] = qty_colors[: len(df)]
            else:
                df["数量セル色"] = ""

            df["出力対象"] = df["数量セル色"].apply(lambda x: False if x else True)

            if df.empty:
                message.value = "抽出結果がありません。"
                table.rows = []
                table_header.controls = []
            else:
                message.value = f"{len(df)}件のデータを抽出しました。"

                select_all_btn = ft.ElevatedButton("全選択", on_click=lambda e: toggle_all(True))
                deselect_all_btn = ft.ElevatedButton("全解除", on_click=lambda e: toggle_all(False))
                export_btn = ft.ElevatedButton("PDF出力実行（プレースホルダ）", on_click=on_pdf_export)
                table_header.controls = [select_all_btn, deselect_all_btn, export_btn]

                table.columns = [ft.DataColumn(ft.Text(c)) for c in df.columns]
                table.rows = []

                for _, row in df.iterrows():
                    cells = []
                    for c, v in row.items():
                        if pd.isna(v) or str(v).strip().lower() in ("nan", "none"):
                            display_value = ""
                        else:
                            display_value = str(v)

                        if c == "出力対象":
                            cells.append(ft.DataCell(ft.Checkbox(value=bool(v))))
                        elif c == "検索用文字列":
                            # 編集なしの通常テキスト表示に変更
                            cells.append(ft.DataCell(ft.Text(display_value)))
                        else:
                            cells.append(ft.DataCell(ft.Text(display_value)))
                    table.rows.append(ft.DataRow(cells=cells))


            page.update()
        except Exception as ex:
            message.value = f"エラー: {ex}"
            page.update()

    def toggle_all(value: bool):
        for r in table.rows:
            for c in r.cells:
                if isinstance(c.content, ft.Checkbox):
                    c.content.value = value
        page.update()

    def on_pdf_export(e):
        selected_rows = []
        for r in table.rows:
            last_cell = r.cells[-1].content
            if isinstance(last_cell, ft.Checkbox) and last_cell.value:
                row_values = [c.content.value if isinstance(c.content, ft.Text) else c.content.value for c in r.cells]
                selected_rows.append(row_values)
        print("出力対象行:", selected_rows)
        page.snack_bar = ft.SnackBar(ft.Text(f"{len(selected_rows)} 件を出力対象として選択しました（ダミー出力）。"))
        page.snack_bar.open = True
        page.update()

    # ---- レイアウト ----
    excel_folder_field = ft.TextField(label="選択中のExcelファイル", expand=True)
    layout = ft.Column([
        ft.Text("⚙️ 設定", size=20, weight="bold"),
        ft.Row([
            search_folder_field,
            ft.ElevatedButton("フォルダを選択", on_click=pick_search_folder)
        ]),
        ft.Row([
            output_folder_field,
            ft.ElevatedButton("フォルダを選択", on_click=pick_output_folder)
        ]),
        mode_row,
        ft.Divider(),
        ft.Text("🔍 Excel検索モード", size=20, weight="bold"),
        ft.Row([excel_folder_field, ft.ElevatedButton("Excelを選択", on_click=pick_excel_click)], alignment="center"),
        ft.Row([sheet_dropdown, ft.ElevatedButton("抽出実行", on_click=on_extract_click)], alignment="center"),
        ft.Divider(),
        table_header,
        message,
        table
    ], expand=True, scroll="auto")

    page.add(layout)
    update_mode_fields()


ft.app(target=main)
