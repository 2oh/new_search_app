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