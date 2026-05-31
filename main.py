# ======================================================
#  Excel–PDF結合アプリ (v0.9.36)
# ======================================================

import flet as ft
import pandas as pd
import os
import json
import re
from pathlib import Path
from openpyxl import load_workbook

CONFIG_FILE = "config.json"
PREVIEW_CACHE_DIR = "preview_cache"


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

def merge_pdfs(pdf_paths: list[str], output_path: str) -> str:
    """
    複数のPDFを1つに結合して保存する。

    Parameters
    ----------
    pdf_paths:
        結合するPDFファイルのパス一覧。
        この順番で結合される。

    output_path:
        出力PDFの保存先パス。

    Returns
    -------
    str
        作成されたPDFファイルのパス。

    Raises
    ------
    ValueError:
        pdf_paths が空、または output_path が空の場合。

    FileNotFoundError:
        入力PDFが存在しない場合。
    """
    if not pdf_paths:
        raise ValueError("結合対象のPDFがありません。")

    if not output_path or not str(output_path).strip():
        raise ValueError("出力先PDFパスが指定されていません。")

    # pypdf が未インストールの場合でも、アプリ起動時には落ちないように関数内でimportする
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as ex:
        raise ImportError(
            "pypdf がインストールされていません。'pip install pypdf' を実行してください。"
        ) from ex

    writer = PdfWriter()

    for pdf_path in pdf_paths:
        path = Path(pdf_path)

        if not path.is_file():
            raise FileNotFoundError(f"PDFファイルが見つかりません: {pdf_path}")

        reader = PdfReader(str(path))

        # パスワードなしで開ける暗号化PDFなら試す
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError(f"暗号化されたPDFを開けません: {pdf_path}")

        for page in reader.pages:
            writer.add_page(page)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "wb") as f:
        writer.write(f)

    return str(output)

def clear_preview_cache(cache_dir: str = PREVIEW_CACHE_DIR):
    """
    PDFプレビューキャッシュを全削除する。
    アプリ起動時に呼び出し、preview_cache が増え続けるのを防ぐ。
    """
    cache_path = Path(cache_dir)

    if not cache_path.exists():
        return

    for image_file in cache_path.glob("preview_*.png"):
        try:
            image_file.unlink()
        except Exception:
            # 削除できないファイルがあってもアプリ本体は止めない
            pass

def create_pdf_preview_image(
    pdf_path: str,
    page_number: int = 0,
    dpi: int = 120,
    cache_dir: str = PREVIEW_CACHE_DIR,
) -> str:
    """
    PDFの指定ページをPNG画像として保存し、その画像パスを返す。

    Parameters
    ----------
    pdf_path:
        プレビュー対象のPDFファイルパス。

    page_number:
        0始まりのページ番号。通常は1ページ目なので0。

    dpi:
        画像化する際の解像度。大きいほどきれいだが重くなる。

    cache_dir:
        プレビュー画像の保存先フォルダ。

    Returns
    -------
    str
        作成されたPNG画像ファイルのパス。

    Raises
    ------
    ValueError:
        pdf_path が空、またはページ番号が範囲外の場合。

    FileNotFoundError:
        PDFファイルが存在しない場合。
    """
    if not pdf_path or not str(pdf_path).strip():
        raise ValueError("PDFパスが指定されていません。")

    pdf_file = Path(str(pdf_path).strip())

    if not pdf_file.is_file():
        raise FileNotFoundError(f"PDFファイルが見つかりません: {pdf_path}")

    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError as ex:
            raise ImportError(
                "PyMuPDF がインストールされていません。"
                "'python -m pip install PyMuPDF' を実行してください。"
            ) from ex

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    # ファイルパス・更新日時・ページ番号・dpi からキャッシュ名を作る
    stat = pdf_file.stat()
    cache_key_src = f"{pdf_file.resolve()}_{stat.st_mtime_ns}_{page_number}_{dpi}"
    cache_key = str(abs(hash(cache_key_src)))
    output_image = cache_path / f"preview_{cache_key}.png"

    # すでに作成済みなら再利用
    if output_image.is_file():
        return str(output_image)

    doc = None
    try:
        doc = pymupdf.open(str(pdf_file))

        if doc.page_count == 0:
            raise ValueError(f"PDFにページがありません: {pdf_path}")

        if page_number < 0 or page_number >= doc.page_count:
            raise ValueError(
                f"ページ番号が範囲外です: {page_number + 1} / {doc.page_count}"
            )

        page = doc[page_number]
        pix = page.get_pixmap(dpi=dpi)
        pix.save(str(output_image))

        return str(output_image)

    finally:
        if doc is not None:
            doc.close()

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

    # --- 共通列への対応 ---
    # 「共通」は内部処理には使わず、検索結果テーブルに表示するだけの項目。
    # Excel上に「共通」を含む列があれば取得する。
    common_col = next((c for c in df.columns if "共通" in str(c)), None)

    if common_col:
        sub_df["共通"] = (
            df[common_col]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace({"nan": "", "None": "", "none": ""})
        )

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
    keep_cols = [c for c in ["品番", "PG名", "品名", "共通", "数量"] if c in sub_df.columns]
    sub_df = sub_df[keep_cols]

    return sub_df

# ========= メイン =========
def main(page: ft.Page):
    page.title = "Excel–PDF結合アプリ"

    # 起動時のウィンドウ表示設定
    try:
        page.window.maximized = True
        page.window.width = 1400
        page.window.height = 900
        page.window.min_width = 1200
        page.window.min_height = 700
    except Exception:
        pass

    # プレビューキャッシュを起動時に削除
    clear_preview_cache()

    sheet_dropdown = None

    # DataTable状態管理用
    current_df = pd.DataFrame()
    search_text_fields = {}
    output_checkboxes = {}

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
    sheet_dropdown = ft.Dropdown(label="シート選択", width=420)
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

    def create_preview_box(preview_image: ft.Image, height: int = 520) -> ft.Container:
        """
        PDFプレビュー画像を表示するための共通枠を作る。
        """
        return ft.Container(
            content=preview_image,
            alignment=ft.alignment.center,
            border=ft.border.all(1, ft.Colors.GREY_500),
            border_radius=8,
            padding=10,
            height=height,
            bgcolor=ft.Colors.GREY_200,
        )

    def on_preview_adopted_pdf(pdf_path: str):
        """
        採用済みPDFをプレビュー表示する。
        自動採用・手動採用どちらでも、採用PDFパスがある行から呼び出す。
        """
        if not pdf_path or not str(pdf_path).strip():
            page.open(ft.SnackBar(ft.Text("採用PDFがありません。")))
            page.update()
            return

        preview_image = ft.Image(
            src="",
            width=760,
            height=520,
            fit=ft.ImageFit.CONTAIN,
            visible=False,
        )

        preview_message = ft.Text("プレビューを読み込み中...")

        def load_preview():
            preview_image.visible = False
            preview_message.value = "プレビューを読み込んでいます..."
            page.update()

            try:
                preview_path = create_pdf_preview_image(
                    pdf_path,
                    page_number=0,
                    dpi=120,
                )
                preview_image.src = preview_path
                preview_image.visible = True
                preview_message.value = format_pdf_path_for_display(pdf_path)

            except Exception as ex:
                preview_image.src = ""
                preview_image.visible = False
                preview_message.value = (
                    "プレビューを生成できませんでした。"
                    f" PDFにアクセスできない、または形式に問題がある可能性があります。詳細: {ex}"
                )

            page.update()

        def close_dialog(e):
            render_table_from_df(current_df)
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("採用PDFプレビュー"),
            content=ft.Container(
                width=860,
                height=640,
                content=ft.Column(
                    controls=[
                        preview_message,
                        create_preview_box(preview_image, height=560),
                    ],
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton("再読み込み", on_click=lambda e: load_preview()),
                ft.TextButton("閉じる", on_click=close_dialog),
            ],
            actions_alignment="end",
        )

        page.open(dialog)
        page.update()

        load_preview()

    def on_select_pdf_candidate(row_index):
        """
        複数候補のPDFから、採用するPDFを1つ選択する。
        ラジオボタンで選択した内容を、即時に採用PDFパスへ反映する。
        """
        nonlocal current_df

        if current_df is None or current_df.empty:
            page.open(ft.SnackBar(ft.Text("抽出結果がありません。")))
            page.update()
            return

        sync_table_state_to_current_df()

        if row_index not in current_df.index:
            page.open(ft.SnackBar(ft.Text("対象行が見つかりません。")))
            page.update()
            return

        row = current_df.loc[row_index]
        candidates = row.get("候補PDFパス一覧", [])

        if not isinstance(candidates, list):
            candidates = []

        if not candidates:
            page.open(ft.SnackBar(ft.Text("候補PDFはありません。")))
            page.update()
            return

        current_adopted_pdf = str(row.get("採用PDFパス", "") or "").strip()

        preview_image = ft.Image(
            src="",
            width=520,
            height=360,
            fit=ft.ImageFit.CONTAIN,
            visible=False,
        )

        preview_message = ft.Text("左の候補PDFを選択すると、ここにプレビューを表示します。")

        def update_preview(pdf_path: str):
            if not pdf_path:
                preview_image.src = ""
                preview_image.visible = False
                preview_message.value = "左の候補PDFを選択すると、ここにプレビューを表示します。"
                page.update()
                return

            preview_image.visible = False
            preview_message.value = "プレビューを読み込んでいます..."
            page.update()

            try:
                preview_path = create_pdf_preview_image(
                    pdf_path,
                    page_number=0,
                    dpi=120,
                )
                preview_image.src = preview_path
                preview_image.visible = True
                preview_message.value = format_pdf_path_for_display(pdf_path)

            except Exception as ex:
                preview_image.src = ""
                preview_image.visible = False
                preview_message.value = (
                    "プレビューを生成できませんでした。"
                    f" PDFにアクセスできない、または形式に問題がある可能性があります。詳細: {ex}"
                )

            page.update()

        NO_ADOPTED_PDF_VALUE = "__NO_ADOPTED_PDF__"

        def apply_candidate_selection(selected_value: str):
            """
            ラジオボタンで選択された候補を、即時に採用状態へ反映する。
            """
            sync_table_state_to_current_df()

            if selected_value == NO_ADOPTED_PDF_VALUE:
                current_df.at[row_index, "採用PDFパス"] = ""
                current_df.at[row_index, "候補状態"] = "複数候補"

                preview_image.src = ""
                preview_image.visible = False
                preview_message.value = "採用しない状態です。左の候補PDFを選ぶとプレビューを表示します。"

                print("===== PDF候補 採用解除 =====")
                print(f"行index: {row_index}")
                print(f"検索文字列: {row.get('検索用文字列', '')!r}")

                page.update()
                return

            if not selected_value:
                return

            current_df.at[row_index, "採用PDFパス"] = selected_value
            current_df.at[row_index, "候補状態"] = "手動採用"

            print("===== PDF候補 即時採用 =====")
            print(f"行index: {row_index}")
            print(f"検索文字列: {row.get('検索用文字列', '')!r}")
            print(f"採用PDF: {format_pdf_path_for_display(selected_value)}")
            print(f"採用PDFフルパス: {selected_value}")

            update_preview(selected_value)

        selected_pdf = ft.RadioGroup(
            value=current_adopted_pdf if current_adopted_pdf in candidates else NO_ADOPTED_PDF_VALUE,
            on_change=lambda e: apply_candidate_selection(e.control.value),
            content=ft.Column(
                controls=[
                    *[
                        ft.Radio(
                            value=pdf_path,
                            label=format_pdf_path_for_display(pdf_path)
                        )
                        for pdf_path in candidates
                    ],
                    ft.Divider(),
                    ft.Radio(
                        value=NO_ADOPTED_PDF_VALUE,
                        label="採用しない",
                    ),
                ],
                scroll="auto",
                height=320,
            )
        )

        def close_dialog(e):
            render_table_from_df(current_df)
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("PDF候補を選択"),
            content=ft.Container(
                width=1230,
                height=520,
                content=ft.Row(
                    controls=[
                        ft.Container(
                            width=620,
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        f"検索文字列: {row.get('検索用文字列', '')}",
                                        weight="bold",
                                    ),
                                    ft.Text(f"候補数: {len(candidates)}"),
                                    ft.Text(f"現在の状態: {row.get('候補状態', '')}"),
                                    ft.Divider(),
                                    ft.Text("採用するPDFを選んでください。選択はすぐに反映されます。"),
                                    selected_pdf,
                                ],
                                tight=True,
                                scroll="auto",
                            ),
                        ),
                        ft.VerticalDivider(),
                        ft.Container(
                            width=560,
                            content=ft.Column(
                                controls=[
                                    ft.Text("プレビュー", weight="bold"),
                                    preview_message,
                                    create_preview_box(preview_image, height=390),
                                ],
                                tight=True,
                            ),
                        ),
                    ],
                    vertical_alignment="start",
                ),
            ),
            actions=[
                ft.ElevatedButton("OK", on_click=close_dialog),
            ],
            actions_alignment="end",
        )

        initial_preview_pdf = selected_pdf.value

        page.open(dialog)
        page.update()

        if initial_preview_pdf and initial_preview_pdf != NO_ADOPTED_PDF_VALUE:
            update_preview(initial_preview_pdf)

    def update_duplicate_search_text_info(df: pd.DataFrame) -> pd.DataFrame:
        """
        検索用文字列の重複状況を表示用列に反映する。

        同じ検索用文字列が複数行ある場合:
        - 1件目: 「1件目」
        - 2件目以降: 「2件目→」「3件目→」...
        
        空欄の検索用文字列は重複判定しない。
        """
        if df is None or df.empty:
            return df

        if "検索用文字列" not in df.columns:
            return df

        df = df.copy()

        search_texts = df["検索用文字列"].fillna("").astype(str).str.strip()

        # 初期値は空欄
        df["検索文字列重複"] = ""

        # 空欄は重複判定から除外
        non_empty = search_texts.ne("")

        if not non_empty.any():
            return df

        counts = search_texts[non_empty].value_counts()

        duplicate_texts = counts[counts >= 2]

        if duplicate_texts.empty:
            return df

        for search_text, count in duplicate_texts.items():
            matching_indices = df.index[non_empty & search_texts.eq(search_text)].tolist()

            for position, idx in enumerate(matching_indices, start=1):
                if position == 1:
                    df.at[idx, "検索文字列重複"] = "1件目"
                else:
                    df.at[idx, "検索文字列重複"] = f"{position}件目→"

        return df

    def apply_duplicate_output_defaults(df: pd.DataFrame) -> pd.DataFrame:
        """
        検索用文字列が重複している場合、2件目以降を初期出力対象外にする。

        - 重複なし: 既存の出力対象を維持
        - 1件目: 出力対象を維持
        - 2件目以降: 出力対象を False にする
        """
        if df is None or df.empty:
            return df

        if "検索文字列重複" not in df.columns or "出力対象" not in df.columns:
            return df

        df = df.copy()

        duplicate_info = df["検索文字列重複"].fillna("").astype(str).str.strip()

        # 「2件目→」「3件目→」など、矢印付きの行を初期OFFにする
        second_or_later = duplicate_info.str.endswith("→")

        df.loc[second_or_later, "出力対象"] = False

        return df

    def format_adopted_pdf_for_display(pdf_path: str) -> str:
        return format_pdf_path_for_display(pdf_path)

    def format_pdf_path_for_display(pdf_path: str) -> str:
        """
        PDFパスを画面表示用に整形する。
        検索先フォルダ配下のPDFであれば、検索先フォルダ以降の相対パスで表示する。
        """
        if not pdf_path or not str(pdf_path).strip():
            return ""

        path_text = str(pdf_path).strip()
        search_root = search_folder_field.value.strip()

        if not search_root:
            return path_text

        try:
            pdf_path_obj = Path(path_text)
            search_root_obj = Path(search_root)

            relative_path = pdf_path_obj.relative_to(search_root_obj)
            return str(relative_path)

        except ValueError:
            return path_text
        except Exception:
            return path_text

    def render_table_from_df(df: pd.DataFrame):
        nonlocal current_df

        current_df = df.copy()

        search_text_fields.clear()
        output_checkboxes.clear()

        hidden_columns = {
            "候補PDFパス一覧",
            "先頭候補PDF",
            "元検索文字列",
        }

        preferred_order = [
            "品番",
            "PG名",
            "品名",
            "検索用文字列",
            "共通",
            "数量",
            "数量セル色",
            "検索文字列重複",
            "出力対象",
            "候補PDF数",
            "候補状態",
            "採用PDFパス",
        ]

        display_columns = [
            c for c in preferred_order
            if c in df.columns and c not in hidden_columns
        ]

        # preferred_order に入っていない列があれば、後ろに残す
        display_columns += [
            c for c in df.columns
            if c not in display_columns and c not in hidden_columns
        ]

        # DataFrameには持たせず、画面表示専用の列として追加する
        if "採用確認" not in display_columns:
            display_columns.append("採用確認")

        if "候補確認" not in display_columns:
            display_columns.append("候補確認")

        def get_display_column_name(column_name: str) -> str:
            display_name_map = {
                "検索用文字列": "検索文字列",
                "検索文字列重複": "重複",
                "候補PDF数": "候補数",
                "数量セル色": "セル色",
                "採用PDFパス": "採用PDF",
            }
            return display_name_map.get(column_name, column_name)

        table.columns = [
            ft.DataColumn(ft.Text(get_display_column_name(c)))
            for c in display_columns
        ]
        table.rows = []

        for idx, row in df.iterrows():
            cells = []

            for c in display_columns:
                v = row.get(c, "")

                if c == "採用確認":
                    adopted_pdf_path = str(row.get("採用PDFパス", "") or "").strip()

                    if adopted_pdf_path:
                        content = ft.ElevatedButton(
                            "プレビュー",
                            on_click=lambda e, pdf_path=adopted_pdf_path: on_preview_adopted_pdf(pdf_path)
                        )
                    else:
                        content = ft.Text("")

                    cells.append(
                        ft.DataCell(
                            ft.Container(
                                content=content,
                            )
                        )
                    )

                    continue

                if c == "候補確認":
                    if row.get("候補状態") in ("複数候補", "手動採用"):
                        cells.append(
                            ft.DataCell(
                                ft.ElevatedButton(
                                    "候補確認",
                                    on_click=lambda e, row_index=idx: on_select_pdf_candidate(row_index)
                                )
                            )
                        )
                    else:
                        cells.append(ft.DataCell(ft.Text("")))

                    continue

                if c == "数量":
                    display_value = format_quantity_for_display(v)

                elif c == "数量セル色":
                    display_value = "あり" if str(v).strip() else ""

                elif c == "採用PDFパス":
                    display_value = format_adopted_pdf_for_display(v)

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
                                width=110,
                                padding=2,
                                bgcolor=ft.Colors.AMBER_50,
                                border=ft.border.all(1, ft.Colors.AMBER_100),
                                border_radius=6,
                                content=text_field,
                            )
                        )
                    )

                else:
                    cells.append(
                        ft.DataCell(
                            ft.SelectionArea(
                                content=ft.Text(display_value)
                            )
                        )
                    )

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
            df["候補状態"] = "未検索"

            # 検索用文字列の重複表示を更新
            df = update_duplicate_search_text_info(df)

            # 重複している検索用文字列の2件目以降は初期出力対象外にする
            df = apply_duplicate_output_defaults(df)

            if df.empty:
                message.value = "抽出結果がありません。"
                table.rows = []
                table_header.controls = []
            else:
                message.value = f"{len(df)}件のデータを抽出しました。"

                select_all_btn = ft.ElevatedButton("全選択", on_click=lambda e: toggle_all(True))
                deselect_all_btn = ft.ElevatedButton("全解除", on_click=lambda e: toggle_all(False))
                search_pdf_btn = ft.ElevatedButton("PDF候補抽出", on_click=on_pdf_candidate_search)
                export_pdf_btn = ft.ElevatedButton("PDF出力実行", on_click=on_pdf_export)

                table_header.controls = [
                    select_all_btn,
                    deselect_all_btn,
                    search_pdf_btn,
                    export_pdf_btn,
                ]

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

    def get_output_target_without_adopted_pdf_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        出力対象にチェックが入っているが、採用PDFパスが空の行を抽出する。
        """
        if df is None or df.empty:
            return pd.DataFrame()

        if "出力対象" not in df.columns or "採用PDFパス" not in df.columns:
            return pd.DataFrame()

        output_target = df["出力対象"].fillna(False).astype(bool)
        adopted_pdf_missing = df["採用PDFパス"].fillna("").astype(str).str.strip().eq("")

        return df[output_target & adopted_pdf_missing].copy()

    def build_output_pdf_path(output_folder: str) -> str:
        """
        出力先フォルダから、結合PDFの保存パスを作る。
        同名ファイルがある場合は _001, _002... を付ける。
        """
        if not output_folder or not output_folder.strip():
            raise ValueError("出力先フォルダが指定されていません。")

        output_dir = Path(output_folder)

        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)

        if not output_dir.is_dir():
            raise ValueError("出力先フォルダが正しくありません。")

        base_name = "merged_output"
        candidate = output_dir / f"{base_name}.pdf"

        if not candidate.exists():
            return str(candidate)

        for i in range(1, 1000):
            candidate = output_dir / f"{base_name}_{i:03d}.pdf"
            if not candidate.exists():
                return str(candidate)

        raise ValueError("出力ファイル名を作成できませんでした。")

    def sync_table_state_to_current_df():
        """
        DataTable上の最新の検索用文字列・出力対象チェックを current_df に反映する。
        """
        nonlocal current_df

        if current_df is None or current_df.empty:
            return

        for idx, text_field in search_text_fields.items():
            if idx in current_df.index:
                current_df.at[idx, "検索用文字列"] = (text_field.value or "").strip()

        for idx, checkbox in output_checkboxes.items():
            if idx in current_df.index:
                current_df.at[idx, "出力対象"] = bool(checkbox.value)

    def on_pdf_candidate_search(e):
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

        sync_table_state_to_current_df()

        current_df = update_duplicate_search_text_info(current_df)

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
            candidate_count = len(candidates)

            previous_status = str(row.get("候補状態", "") or "").strip()
            previous_adopted_pdf = str(row.get("採用PDFパス", "") or "").strip()

            current_df.at[idx, "候補PDF数"] = candidate_count
            current_df.at[idx, "先頭候補PDF"] = candidates[0] if candidates else ""
            current_df.at[idx, "候補PDFパス一覧"] = candidates

            if candidate_count == 0:
                current_df.at[idx, "採用PDFパス"] = ""
                current_df.at[idx, "候補状態"] = "未検出"

            elif candidate_count == 1:
                current_df.at[idx, "採用PDFパス"] = candidates[0]
                current_df.at[idx, "候補状態"] = "自動採用"

            else:
                # 複数候補の場合:
                # 以前に手動採用したPDFが今回の候補にも含まれていれば、その選択を保持する
                if previous_status == "手動採用" and previous_adopted_pdf in candidates:
                    current_df.at[idx, "採用PDFパス"] = previous_adopted_pdf
                    current_df.at[idx, "候補状態"] = "手動採用"
                else:
                    current_df.at[idx, "採用PDFパス"] = ""
                    current_df.at[idx, "候補状態"] = "複数候補"

        render_table_from_df(current_df)

        matched_count = int((current_df["候補PDF数"].fillna(0) > 0).sum())
        selected_count = int(current_df["出力対象"].fillna(False).sum())
        adopted_count = int(
            current_df["採用PDFパス"]
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        )
        multiple_count = int((current_df["候補PDF数"].fillna(0) >= 2).sum())
        duplicate_search_text_count = int(
            current_df["検索文字列重複"]
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        )

        export_ready_df = get_export_ready_df(current_df)
        export_ready_count = len(export_ready_df)

        print("===== PDF候補抽出結果 =====")
        for idx, row in current_df.iterrows():
            print(
                f"[{idx}] "
                f"出力対象={row.get('出力対象', False)}, "
                f"検索用文字列={row.get('検索用文字列', '')!r}, "
                f"候補PDF数={row.get('候補PDF数', 0)}, "
                f"候補状態={row.get('候補状態', '')!r}, "
                f"先頭候補PDF={row.get('先頭候補PDF', '')!r}, "
                f"採用PDFパス={row.get('採用PDFパス', '')!r}"
            )

        print("===== 複数候補行 =====")
        multiple_df = current_df[current_df["候補PDF数"].fillna(0) >= 2].copy()

        if multiple_df.empty:
            print("複数候補の行はありません。")
        else:
            for idx, row in multiple_df.iterrows():
                print(
                    f"[{idx}] "
                    f"検索用文字列={row.get('検索用文字列', '')!r}, "
                    f"候補PDF数={row.get('候補PDF数', 0)}"
                )

                candidates = row.get("候補PDFパス一覧", [])
                if not isinstance(candidates, list):
                    candidates = []

                for i, candidate_path in enumerate(candidates, start=1):
                    print(f"  {i}. {candidate_path}")


        print("===== 検索用文字列 重複行 =====")
        duplicate_df = current_df[
            current_df["検索文字列重複"]
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
        ].copy()

        if duplicate_df.empty:
            print("検索用文字列が重複している行はありません。")
        else:
            for idx, row in duplicate_df.iterrows():
                print(
                    f"[{idx}] "
                    f"検索用文字列={row.get('検索用文字列', '')!r}, "
                    f"重複={row.get('検索文字列重複', '')!r}, "
                    f"候補状態={row.get('候補状態', '')!r}, "
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
            f"複数候補 {multiple_count}件 / "
            f"検索文字列重複 {duplicate_search_text_count}件 / "
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

    def on_pdf_export(e):
        nonlocal current_df

        if current_df is None or current_df.empty:
            message.value = "抽出結果がありません。"
            page.open(ft.SnackBar(ft.Text("抽出結果がありません。")))
            page.update()
            return

        sync_table_state_to_current_df()

        current_df = update_duplicate_search_text_info(current_df)

        output_folder = output_folder_field.value.strip()

        if not output_folder:
            message.value = "出力先フォルダを指定してください。"
            page.open(ft.SnackBar(ft.Text("出力先フォルダを指定してください。")))
            page.update()
            return

        if os.path.exists(output_folder) and not os.path.isdir(output_folder):
            message.value = "出力先フォルダが正しくありません。"
            page.open(ft.SnackBar(ft.Text("出力先フォルダが正しくありません。")))
            page.update()
            return

        export_ready_df = get_export_ready_df(current_df)
        export_ready_count = len(export_ready_df)

        missing_pdf_df = get_output_target_without_adopted_pdf_df(current_df)
        missing_pdf_count = len(missing_pdf_df)

        if export_ready_df.empty:
            if missing_pdf_count > 0:
                result_message = (
                    "出力可能なPDFがありません。"
                    f"出力対象のうち {missing_pdf_count} 件は採用PDFが未確定です。"
                    "PDF候補抽出を実行するか、検索用文字列を見直してください。"
                )
            else:
                result_message = (
                    "出力可能なPDFがありません。"
                    "出力対象にチェックが入っている行、または採用PDFパスを確認してください。"
                )

            message.value = result_message
            page.open(ft.SnackBar(ft.Text(result_message)))
            page.update()
            return

        try:
            output_pdf_path = build_output_pdf_path(output_folder)

            pdf_paths = (
                export_ready_df["採用PDFパス"]
                .fillna("")
                .astype(str)
                .str.strip()
                .tolist()
            )

            pdf_paths = [p for p in pdf_paths if p]

            merge_pdfs(pdf_paths, output_pdf_path)

            result_message = (
                f"PDFを出力しました: {os.path.basename(output_pdf_path)} "
                f"（結合対象: {export_ready_count}件）"
            )

            if missing_pdf_count > 0:
                result_message += f"\n注意: 出力対象のうち {missing_pdf_count} 件は採用PDFが未確定のため除外しました。"

            print("===== PDF出力 =====")
            print(f"出力PDF: {output_pdf_path}")
            print("===== 結合対象PDF =====")
            for p in pdf_paths:
                print(p)

            if missing_pdf_count > 0:
                print("===== 出力対象だが採用PDF未確定の行 =====")
                for idx, row in missing_pdf_df.iterrows():
                    print(
                        f"[{idx}] "
                        f"検索用文字列={row.get('検索用文字列', '')!r}, "
                        f"候補PDF数={row.get('候補PDF数', 0)}, "
                        f"先頭候補PDF={row.get('先頭候補PDF', '')!r}"
                    )

        except Exception as ex:
            result_message = f"PDF出力エラー: {ex}"

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

    folder_settings_row = ft.Row(
        [
            ft.Row(
                [
                    search_folder_field,
                    ft.ElevatedButton("フォルダを選択", on_click=pick_search_folder),
                ],
                expand=True,
                spacing=6,
            ),
            ft.Row(
                [
                    output_folder_field,
                    ft.ElevatedButton("フォルダを選択", on_click=pick_output_folder),
                ],
                expand=True,
                spacing=6,
            ),
        ],
        spacing=12,
    )

    excel_control_row = ft.Row(
        [
            ft.Container(
                content=excel_folder_field,
                expand=2,
            ),
            pick_excel_btn,
            sheet_dropdown,
            extract_btn,
        ],
        alignment="center",
        vertical_alignment="center",
        spacing=10,
    )

    fixed_controls = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("⚙️ 設定", size=20, weight="bold"),
                    save_button,
                ],
                alignment="spaceBetween",
                vertical_alignment="center",
            ),
            folder_settings_row,
            mode_row,
            ft.Divider(),
            ft.Text("🔍 構成部品表選択", size=20, weight="bold"),
            mode_notice,
            excel_control_row,
            ft.Divider(),
            table_header,
            message,
        ],
        spacing=6,
    )

    result_area = ft.Container(
        content=ft.Column(
            [
                table,
            ],
            scroll="auto",
            expand=True,
        ),
        expand=True,
    )

    layout = ft.Column(
        [
            fixed_controls,
            result_area,
        ],
        expand=True,
    )

    page.add(layout)

    update_mode_fields()


if __name__ == "__main__":
    ft.app(target=main)