import flet as ft
import pandas as pd
import json
import os

CONFIG_FILE = "config.json"

def main(page: ft.Page):
    page.title = "PDF検索＆結合ツール"
    page.scroll = "adaptive"

    # -------------------------------
    # 設定の読み込みと保存
    # -------------------------------
    def load_config():
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"search_folder": "", "output_folder": "", "search_mode": "通常"}

    def save_config(cfg):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    config = load_config()

    # -------------------------------
    # UIコンポーネント
    # -------------------------------
    search_folder_field = ft.TextField(
        label="検索先フォルダ",
        value=config.get("search_folder", ""),
        expand=True
    )
    output_folder_field = ft.TextField(
        label="出力先フォルダ",
        value=config.get("output_folder", ""),
        expand=True
    )

    search_mode_dropdown = ft.Dropdown(
        label="検索モード",
        options=[ft.dropdown.Option("通常")],
        value=config.get("search_mode", "通常"),
        expand=False
    )

    column_dropdown = ft.Dropdown(label="検索対象列")
    result_list = ft.Column(scroll="auto", expand=True)

    # -------------------------------
    # Excel読込処理
    # -------------------------------
    excel_df = None

    def pick_excel_result(e: ft.FilePickerResultEvent):
        nonlocal excel_df
        if e.files:
            file_path = e.files[0].path
            excel_df = pd.read_excel(file_path)
            column_names = [str(c) for c in excel_df.columns]
            column_dropdown.options = [ft.dropdown.Option(c) for c in column_names]
            if column_names:
                column_dropdown.value = column_names[0]
            page.update()

    # -------------------------------
    # FilePicker（統合版）
    # -------------------------------
    file_picker = ft.FilePicker(on_result=None)
    page.overlay.append(file_picker)
    current_mode = {"type": None}

    def on_filepicker_result(e: ft.FilePickerResultEvent):
        nonlocal excel_df
        if e.path or e.files:
            if current_mode["type"] == "search":
                search_folder_field.value = e.path
                config["search_folder"] = e.path
                save_config(config)
            elif current_mode["type"] == "output":
                output_folder_field.value = e.path
                config["output_folder"] = e.path
                save_config(config)
            elif current_mode["type"] == "excel":
                # Excelファイルの選択結果
                pick_excel_result(e)

        page.update()

    file_picker.on_result = on_filepicker_result

    # -------------------------------
    # 各ボタン
    # -------------------------------
    pick_search_btn = ft.ElevatedButton(
        "検索先を選択",
        on_click=lambda _: (
            current_mode.update({"type": "search"}),
            file_picker.get_directory_path(
                initial_directory=search_folder_field.value
            )
        )
    )

    pick_output_btn = ft.ElevatedButton(
        "出力先を選択",
        on_click=lambda _: (
            current_mode.update({"type": "output"}),
            file_picker.get_directory_path(
                initial_directory=output_folder_field.value
            )
        )
    )

    excel_button = ft.ElevatedButton(
        "Excelを選択",
        on_click=lambda _: (
            current_mode.update({"type": "excel"}),
            file_picker.pick_files(
                allowed_extensions=["xlsx"],
                initial_directory=search_folder_field.value
            )
        )
    )

    save_button = ft.ElevatedButton(
        "設定を保存",
        on_click=lambda _: save_config({
            "search_folder": search_folder_field.value,
            "output_folder": output_folder_field.value,
            "search_mode": search_mode_dropdown.value
        })
    )

    # -------------------------------
    # レイアウト構成
    # -------------------------------
    page.add(
        ft.Row([excel_button, column_dropdown, search_mode_dropdown, save_button]),
        ft.Row([search_folder_field, pick_search_btn]),
        ft.Row([output_folder_field, pick_output_btn]),
        result_list
    )

ft.app(target=main)
