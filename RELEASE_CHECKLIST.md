Release checklist for v1.0

1. Source / Git
   [ ] git status が clean
   [ ] main.py の APP_VERSION がリリース予定版と一致している
   [ ] 先頭コメントのバージョンも APP_VERSION と一致している
   [ ] 不要な試行コードが残っていない
   [ ] DEBUG = False になっている

2. Environment
   [ ] .venv を有効化している
   [ ] python -m pip show flet flet-cli flet-desktop flet-web が 0.28.3
   [ ] python main.py で起動できる
   [ ] requirements.txt が作成済み
   [ ] .venv/ は .gitignore に入っている

3. Files / Assets
   [ ] assets/app_icon.ico が存在する
   [ ] APP_ICON_FILE = "assets/app_icon.ico" になっている
   [ ] config.json は配布物に含めるか方針確認
   [ ] preview_cache/ は配布物に含めない
   [ ] build/ dist/ *.spec はGit管理外

4. Basic UI
   [ ] ウィンドウタイトルにバージョンが表示される
   [ ] ダークモード固定で表示される
   [ ] アプリアイコンが表示される
   [ ] 設定保存ボタンが検索モード行の右側にある
   [ ] 終了ボタンでアプリが閉じる
   [ ] 上部固定エリアの余白が問題ない

5. Excel extraction
   [ ] Excelファイルを選択できる
   [ ] シート選択プレースホルダが表示される
   [ ] シート選択後に抽出できる
   [ ] 品番/PG名列が正しく表示される
   [ ] 品名の2段表示が崩れていない
   [ ] 出力不可行が正しく空欄化される
   [ ] 数量0が不可になる
   [ ] 数量セル色あり が不可になる
   [ ] PG名のみ行の前行補完が効いている

6. PDF candidate search
   [ ] PDF検索先フォルダを選択できる
   [ ] PDF一覧取得中の進捗が出る
   [ ] PDF検索用データ作成中の表示が出る
   [ ] PDF候補抽出中の進捗が出る
   [ ] 候補0件は未検出になる
   [ ] 候補1件は自動採用になる
   [ ] 候補複数は選択ボタンが出る
   [ ] 候補選択ダイアログが小さいウィンドウでも横スクロールで対応できる
   [ ] 候補選択でプレビューが表示される
   [ ] 採用しないを選べる

7. Preview
   [ ] 広い画面では出力PDF欄ホバーで右側プレビューが出る
   [ ] 狭い画面ではプレビューボタンが出る
   [ ] プレビューボタンからPDFプレビューが開く
   [ ] A3横図面が見やすいサイズで表示される
   [ ] プレビュー不可PDFでもアプリが落ちない

8. Output / Merge
   [ ] PDF候補検索後、出力対象チェックが適切にONになる
   [ ] 全選択/全解除で出力件数バッジが更新される
   [ ] 個別チェック変更で出力件数バッジが更新される
   [ ] 採用PDF重複の2件目以降が出力OFFになる
   [ ] PDF結合が成功する
   [ ] 出力PDF名が選択Excel名ベースになる
   [ ] 出力先フォルダにPDFが作成される

9. PyInstaller
   [ ] .venv を有効化した状態でビルドする
   [ ] PyInstaller コマンドに --icon を指定する
   [ ] PyInstaller コマンドに --add-data "assets/app_icon.ico;assets" を指定する
   [ ] dist/main.exe が作成される
   [ ] EXE単体で起動できる
   [ ] EXEでもアイコンが表示される
   [ ] EXEでもPDFプレビューが動く
   [ ] EXEでもPDF結合が動く

10. On-site verification
   [ ] NAS上のPDFフォルダで候補検索できる
   [ ] PDF約3万件で検索時間が許容範囲
   [ ] 実際の構成部品表Excelで抽出できる
   [ ] 実際の出力先にPDFを作成できる
   [ ] 別PCでEXE起動できる
   [ ] 必要な設定をconfig.jsonに保存できる
   [ ] 現地で追加修正が必要な点をメモする

Post-v1.0 tasks
   [ ] Flet version up
   [ ] DataTable2でタイトル行固定
   [ ] ドラッグ＆ドロップ実装
   [ ] PDF出力ファイルのエクスプローラー表示を再検討
   [ ] 他ユーザーが開いているExcelの読み取り対応
   [ ] 通常検索モード実装

Decided not to implement
   [x] 候補インライン表示