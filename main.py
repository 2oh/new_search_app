# ======================================================
#  Excel–PDF結合アプリ (v0.9.8)
# ======================================================

import flet as ft
import pandas as pd
import os
import json
import re
from pathlib import Path
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

def normalize_filename_match(text: str) -> str:
    """PDFファイル名検索用の軽い正規化"""
    if text is None:
        return ""

    s = str(text).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def collect_pdf_files(root_folder: str) -> list[Path]:
    """指定フォルダ配下のPDFを再帰的に集める"""
    if not root_folder or not os.path.isdir(root_folder):
        return []

    root = Path(root_folder)
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]


def find_pdf_candidates_by_filename(search_text: str, pdf_files: list[Path]) -> list[str]:
    """検索文字列を使ってPDFファイル名を部分一致検索する"""
    needle = normalize_filename_match(search_text)

    if not needle:
        return []

    hits = []

    for pdf_path in pdf_files:
        stem_norm = normalize_filename_match(pdf_path.stem)
        name_norm = normalize_filename_match(pdf_path.name)

        if needle in stem_norm or needle in name_norm:
            hits.append(str(pdf_path))

    return hits

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
            # ✅ 数量欄が完全に空（NaN / 空白）の行だけ除外する
            if pd.isna(x):
                return False
            s = str(x).strip()
            if s == "":
                return False
            # 0 かどうかはここでは判定しない（表示はする）
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
    page.title = "Excel–PDF結合アプリ"
    page.scroll = "adaptive"

    sheet_dropdown = None

    # DataTable状態管理用
    current_df = pd.DataFrame()
    search_text_fields = {}
    output_checkboxes = {}

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

        page.open(ft.SnackBar(ft.Text("設定を保存しました。")))
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
            # ✅ 構成部品表モードでは target_col_field を表示しない
            mode_row.controls = [
                mode_dropdown
            ]
            set_excel_ui_enabled(True)
        else:
            manual_field = ft.TextField(
                label="検索文字列（手動入力）",
                width=450
            )
            mode_row.controls = [
                mode_dropdown,
                manual_field
            ]
            set_excel_ui_enabled(False)

        page.update()

    mode_row = ft.Row(
        [mode_dropdown],
        alignment="spaceBetween"
    )
    mode_dropdown.on_change = lambda e: update_mode_fields()

    # ---- Excel選択 ----
    selected_excel_path = ""
    sheet_dropdown = ft.Dropdown(label="シート選択", width=300)
    message = ft.Text("")
    mode_notice = ft.Text("")
    table = ft.DataTable(columns=[ft.DataColumn(ft.Text("項目"))], rows=[])
    table_header = ft.Row([], alignment="center")

    def format_quantity_for_display(v) -> str:
        if pd.isna(v):
            return ""
        s = str(v).strip()
        if s == "" or s.lower() in ("nan", "none"):
            return ""

        # "1.0" のような整数の小数表現だけ "1" に戻す
        try:
            x = float(s.replace(",", ""))
            if x.is_integer():
                return str(int(x))
        except ValueError:
            pass

        return s

    def render_table_from_df(df: pd.DataFrame):
        nonlocal current_df

        current_df = df.copy()

        search_text_fields.clear()
        output_checkboxes.clear()

        hidden_columns = {"候補PDFパス一覧"}
        display_columns = [c for c in df.columns if c not in hidden_columns]

        table.columns = [ft.DataColumn(ft.Text(c)) for c in display_columns]
        table.rows = []

        for idx, row in df.iterrows():
            cells = []

            for c in display_columns:
                v = row.get(c, "")
                if c == "数量":
                    display_value = format_quantity_for_display(v)
                elif c in ("先頭候補PDF", "採用PDFパス"):
                    display_value = os.path.basename(str(v)) if str(v).strip() else ""
                else:
                    if pd.isna(v) or str(v).strip().lower() in ("nan", "none"):
                        display_value = ""
                    else:
                        display_value = str(v)

                if c == "出力対象":
                    checkbox = ft.Checkbox(value=bool(v))
                    output_checkboxes[idx] = checkbox
                    cells.append(ft.DataCell(checkbox))

                elif c == "検索用文字列":
                    text_field = ft.TextField(
                        value=display_value,
                        dense=True,
                        text_size=14,
                        color=ft.Colors.BLACK,
                        content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
                        border=ft.InputBorder.NONE,
                        bgcolor=ft.Colors.TRANSPARENT,
                    )
                    search_text_fields[idx] = text_field

                    cells.append(
                        ft.DataCell(
                            ft.Container(
                                width=100,
                                padding=2,
                                bgcolor=ft.Colors.YELLOW_100,
                                border_radius=6,
                                content=text_field,
                            )
                        )
                    )

                else:
                    cells.append(ft.DataCell(ft.Text(display_value)))

            table.rows.append(ft.DataRow(cells=cells))

    # 🔽 抽出結果エリアの初期化関数を追加 🔽
    def reset_extract_view():
        nonlocal current_df

        current_df = pd.DataFrame()
        search_text_fields.clear()
        output_checkboxes.clear()

        table.rows = []
        table.columns = [ft.DataColumn(ft.Text("項目"))]
        table_header.controls = []
        message.value = ""
        page.update()

    def on_sheet_change(e):
        # シート変更時に抽出結果を初期化
        reset_extract_view()

    sheet_dropdown.on_change = on_sheet_change

    file_picker = ft.FilePicker(on_result=lambda e: pick_excel_result(e))
    page.overlay.append(file_picker)

    def pick_excel_click(e):
        file_picker.pick_files(allowed_extensions=["xlsx", "xls"])

    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal selected_excel_path  # sheet_dropdown は作り直さないので nonlocal 不要でもOK

        if not e.files:
            return

        # ★ 抽出エリアを初期化
        reset_extract_view()

        selected_excel_path = e.files[0].path
        excel_folder_field.value = os.path.abspath(selected_excel_path)
        page.update()

        try:
            xls = pd.ExcelFile(selected_excel_path)
            sheet_names = xls.sheet_names

            # ✅ Dropdownを作り直さず、options/valueだけ更新する
            sheet_dropdown.options = [
                ft.dropdown.Option("（シートを選択してください）"),
                *[ft.dropdown.Option(name) for name in sheet_names]
            ]
            sheet_dropdown.value = "（シートを選択してください）"
            sheet_dropdown.on_change = on_sheet_change  # 念のため（維持）
            sheet_dropdown.update()

            page.snack_bar = ft.SnackBar(ft.Text("シートを選択してください。"))
            page.snack_bar.open = True
            page.update()

        except PermissionError:
            page.dialog = ft.AlertDialog(
                title=ft.Text("ファイル使用中"),
                content=ft.Text("Excelファイルを閉じてください。")
            )
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
        # 1) Excel 未選択
        if not selected_excel_path:
            message.value = "Excelファイルを選択してください。"
            page.update()
            return

        # 2) シート未選択（プレースホルダ含む）
        sheet_val = sheet_dropdown.value
        if (not sheet_val) or (sheet_val == "（シートを選択してください）"):
            message.value = "シートを選択してください。"
            page.update()
            return

        # 3) モードチェック
        if mode_dropdown.value != "構成部品表":
            message.value = "通常モードは未実装です。"
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

            # --- 品番 or PG名 のどちらか優先で生成（元値を保持）
            df["元検索文字列"] = df.apply(
                lambda row: create_search_keyword(row.get("品番")) or create_search_keyword(row.get("PG名")),
                axis=1
            )

            # --- 実際に検索に使う文字列（初期値は元検索文字列と同じ）
            df["検索用文字列"] = df["元検索文字列"]

            qty_colors = []
            if "数量" in detected_columns:
                qty_colors = get_quantity_colors(
                    selected_excel_path,
                    sheet_dropdown.value,
                    header_row_index,
                    detected_columns["数量"]
                )

                # ✅ df.index（元の行位置）で色リストを引く → フィルタ後でもズレない
                def color_by_df_index(i: int) -> str:
                    return qty_colors[i] if 0 <= i < len(qty_colors) else ""

                df["数量セル色"] = [color_by_df_index(i) for i in df.index]
            else:
                df["数量セル色"] = ""

            # 数量ゼロ判定（0, "0", "0.0", " 0 " などを想定）
            def is_zero_quantity(v):
                if pd.isna(v):
                    return False
                s = str(v).strip()
                if s == "":
                    return False
                try:
                    return float(s.replace(",", "")) == 0.0
                except ValueError:
                    return False

            # 出力対象判定：色付き or 数量ゼロ → False
            def decide_output_target(row):
                colored = bool(row.get("数量セル色"))
                zero_qty = False
                if "数量" in df.columns:
                    zero_qty = is_zero_quantity(row.get("数量"))
                return not (colored or zero_qty)

            df["出力対象"] = df.apply(decide_output_target, axis=1)

            # PDF候補情報の初期列
            df["候補PDF数"] = 0
            df["先頭候補PDF"] = ""
            df["候補PDFパス一覧"] = [[] for _ in range(len(df))]
            df["採用PDFパス"] = ""

            if df.empty:
                message.value = "抽出結果がありません。"
                table.rows = []
                table_header.controls = []
            else:
                message.value = f"{len(df)}件のデータを抽出しました。"

                select_all_btn = ft.ElevatedButton("全選択", on_click=lambda e: toggle_all(True))
                deselect_all_btn = ft.ElevatedButton("全解除", on_click=lambda e: toggle_all(False))
                # export_btn = ft.ElevatedButton("PDF出力実行（プレースホルダ）", on_click=on_pdf_export)
                export_btn = ft.ElevatedButton("PDF候補抽出", on_click=on_pdf_export)
                table_header.controls = [select_all_btn, deselect_all_btn, export_btn]

                render_table_from_df(df)


            page.update()
        except Exception as ex:
            message.value = f"エラー: {ex}"
            page.update()

    def toggle_all(value: bool):
        for checkbox in output_checkboxes.values():
            checkbox.value = value
        page.update()

    def get_cell_value(control):
        if isinstance(control, ft.Text):
            return control.value
        if isinstance(control, ft.TextField):
            return control.value
        if isinstance(control, ft.Checkbox):
            return control.value
        if isinstance(control, ft.Container):
            return get_cell_value(control.content)
        return None

    def get_export_ready_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        実際にPDF出力に回せる行だけを抽出する。

        条件:
        - 出力対象 が True
        - 採用PDFパス が空でない
        """
        if df is None or df.empty:
            return pd.DataFrame()

        if "出力対象" not in df.columns or "採用PDFパス" not in df.columns:
            return pd.DataFrame()

        output_target = df["出力対象"].fillna(False).astype(bool)
        adopted_pdf_exists = df["採用PDFパス"].fillna("").astype(str).str.strip().ne("")

        return df[output_target & adopted_pdf_exists].copy()

    def on_pdf_export(e):
        nonlocal current_df

        if current_df is None or current_df.empty:
            message.value = "抽出結果がありません。"
            page.open(ft.SnackBar(ft.Text("抽出結果がありません。")))
            page.update()
            return

        pdf_root = search_folder_field.value.strip()

        if not pdf_root or not os.path.isdir(pdf_root):
            message.value = "検索先フォルダが正しくありません。"
            page.open(ft.SnackBar(ft.Text("検索先フォルダが正しくありません。")))
            page.update()
            return

        # DataTable上の最新の検索用文字列・出力対象チェックを current_df に反映
        for idx, text_field in search_text_fields.items():
            if idx in current_df.index:
                current_df.at[idx, "検索用文字列"] = (text_field.value or "").strip()

        for idx, checkbox in output_checkboxes.items():
            if idx in current_df.index:
                current_df.at[idx, "出力対象"] = bool(checkbox.value)

        pdf_files = collect_pdf_files(pdf_root)

        if not pdf_files:
            message.value = "検索先フォルダ配下にPDFが見つかりませんでした。"
            page.open(ft.SnackBar(ft.Text("検索先フォルダ配下にPDFが見つかりませんでした。")))
            page.update()
            return

        # 各行ごとにPDF候補を抽出
        for idx, row in current_df.iterrows():
            search_text = row.get("検索用文字列", "")
            candidates = find_pdf_candidates_by_filename(search_text, pdf_files)

            current_df.at[idx, "候補PDF数"] = len(candidates)
            current_df.at[idx, "先頭候補PDF"] = candidates[0] if candidates else ""
            current_df.at[idx, "候補PDFパス一覧"] = candidates

            # 候補が1件だけなら自動採用。0件・複数件は未確定扱い。
            if len(candidates) == 1:
                current_df.at[idx, "採用PDFパス"] = candidates[0]
            else:
                current_df.at[idx, "採用PDFパス"] = ""

        # 更新後のDataFrameで表を再描画
        render_table_from_df(current_df)

        matched_count = int((current_df["候補PDF数"].fillna(0) > 0).sum())
        selected_count = int(current_df["出力対象"].fillna(False).sum())
        adopted_count = int(current_df["採用PDFパス"].fillna("").astype(str).str.strip().ne("").sum())

        export_ready_df = get_export_ready_df(current_df)
        export_ready_count = len(export_ready_df)

        print("===== PDF候補抽出結果 =====")
        for idx, row in current_df.iterrows():
            print(
                f"[{idx}] "
                f"出力対象={row.get('出力対象', False)}, "
                f"検索用文字列={row.get('検索用文字列', '')!r}, "
                f"候補PDF数={row.get('候補PDF数', 0)}, "
                f"先頭候補PDF={row.get('先頭候補PDF', '')!r}, "
                f"採用PDFパス={row.get('採用PDFパス', '')!r}"
            )

        print("===== 出力可能行 =====")
        if export_ready_df.empty:
            print("出力可能な行はありません。")
        else:
            for idx, row in export_ready_df.iterrows():
                print(
                    f"[{idx}] "
                    f"検索用文字列={row.get('検索用文字列', '')!r}, "
                    f"採用PDFパス={row.get('採用PDFパス', '')!r}"
                )

        result_message = (
            f"PDF候補抽出完了: "
            f"一致あり {matched_count}件 / "
            f"採用 {adopted_count}件 / "
            f"出力対象 {selected_count}件 / "
            f"出力可能 {export_ready_count}件"
        )

        message.value = result_message

        page.open(
            ft.SnackBar(
                ft.Text(result_message)
            )
        )

        page.update()

    pick_excel_btn = ft.ElevatedButton("Excelを選択", on_click=pick_excel_click)
    extract_btn = ft.ElevatedButton("抽出実行", on_click=on_extract_click)

    def set_excel_ui_enabled(enabled: bool):
        excel_folder_field.disabled = not enabled
        pick_excel_btn.disabled = not enabled
        sheet_dropdown.disabled = not enabled
        sheet_dropdown.opacity = 1.0 if enabled else 0.5
        extract_btn.disabled = not enabled

        if not enabled:
            # ✅ 通常モードへ切替 → シート選択をプレースホルダに戻す
            sheet_dropdown.value = "（シートを選択してください）"
            reset_extract_view()
            mode_notice.value = "通常モードでは構成部品表選択は無効です。"
        else:
            mode_notice.value = ""

        # 保険（効かない環境があるので）
        sheet_dropdown.update()
        page.update()

    # ---- レイアウト ----
    excel_folder_field = ft.TextField(label="選択中のExcelファイル", expand=True)
    save_button = ft.ElevatedButton("設定を保存", on_click=save_config)

    layout = ft.Column([
        ft.Row(
            [
                ft.Text("⚙️ 設定", size=20, weight="bold"),
                save_button,
            ],
            alignment="spaceBetween",
            vertical_alignment="center",
        ),
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
        ft.Text("🔍 構成部品表選択", size=20, weight="bold"),
        mode_notice,
        ft.Row([excel_folder_field, pick_excel_btn], alignment="center"),
        ft.Row([sheet_dropdown, extract_btn], alignment="center"),
        ft.Divider(),
        table_header,
        message,
        table
    ], expand=True, scroll="auto")

    page.add(layout)
    update_mode_fields()


if __name__ == "__main__":
    ft.app(target=main)