# PDF索引の設定と運用（第1段階）

通常モード・構成部品表モードとも、端末内の同じPDF索引を参照します。PDF本文は索引化しません。
構成部品表の読込・抽出、検索キー生成、候補照合・選択・出力ルールは従来どおりです。

## 更新用端末

1. `pdf_index_config.example.json`を`pdf_index_config.json`として別途コピーし、実パスを設定します。
2. `root`は共通PDF親フォルダ、`database`は更新用端末のローカルDBファイル、`publish`はPDF索引公開先、`logs`はログ先です。
3. 相対パスは設定JSONのある場所が基準です。JSONのバックスラッシュは二重に記述します。
4. Pythonでの確認は次のコマンドです。

```powershell
& 'C:\dev\new_search_app\Scripts\python.exe' pdf_index_batch.py --config pdf_index_config.json
```

更新用EXEを作成する場合：

```powershell
& 'C:\dev\new_search_app_build_v112\Scripts\python.exe' tools/build_pdf_index_exe.py
```

タスクスケジューラはプログラムに`pdf_index_update.exe`の絶対パス、引数に`--config "設定JSONの絶対パス"`を指定します。
業務時間外に、共有先を読み書きできるアカウントで実行します。初回は手動実行して終了コード0とログを確認してください。
Python・Excel・SQLiteの別途インストールは更新用EXEの実行には不要です。

毎回PDFの一覧と更新日時・サイズを調べ、完全な新世代を作成します。本文は読みません。
アクセス失敗・走査途中のエラー・PDFが0件の場合は公開を中止します。
既存の公開版は維持し、終了コード1とログで通知します。

公開先は`pdf-latest.json`と世代別の`pdf-catalog-*.sqlite`を持ちます。
Cの`latest.json`とは別の名前ですが、運用上も専用の公開フォルダを推奨します。
古い公開世代は自動削除しません。容量を確認し、利用者の判断で後日整理します。

## 利用端末

両モード共通の「PDF索引 公開フォルダ」に公開先を設定し、「最新データ取得」を実行します。
起動時にも最新版を確認します。PDF検索先は取得DBから表示し、編集しません。
既存`pdf_folder`設定は旧版へ戻す際に備えて保持しますが、今回の両モードの検索先には使いません。

取得DBは`%LOCALAPPDATA%\DrawingPdfSearch\pdf_catalog.sqlite`に保存します。
公開先設定はAの既存`config.json`に`pdf_index_publish`として保存します。
PDF本体はコピーせず、開く・プレビュー・出力時に共有先の実ファイルを使います。

検索結果・更新日時・並び順は日次索引時点の情報です。更新後の移動等は次回更新まで反映されません。
検索結果があっても共有先へ接続できなければPDFは開けません。
取得失敗時は前回のDBで検索でき、初回未取得時は検索できない旨を案内します。
新しいDBを取得したときは通常モードの旧検索結果を空にします。ストックは維持します。
構成部品表モードでは抽出結果・候補選択を維持します。新しい索引を反映するには、再度PDF候補抽出を実行してください。

## 検証

```powershell
& 'C:\dev\new_search_app\Scripts\python.exe' -m unittest discover -s tests -p test_pdf_catalog.py -v
& 'C:\dev\new_search_app\Scripts\python.exe' tools/test_normal_mode.py .
& 'C:\dev\new_search_app\Scripts\python.exe' tools/test_ui_state.py .
```

テストは一時データを使います。現地の初回公開、日次実行、速度計測は別途確認が必要です。
クライアントEXEの作成手順は既存のBUILD_EXE.mdを参照してください。
