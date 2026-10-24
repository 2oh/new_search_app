# 開発環境と単体EXE作成

リポジトリnew_search_appをVS Codeで開いて実行します。

```powershell
C:\dev\new_search_app\Scripts\Activate.ps1
```

初回の環境準備、または依存設定を更新したとき：

```powershell
python -m pip install -r requirements-build.txt
python -m pip check
```

2026-10-13の0.28.3からの移行時は、旧flet-cli/flet-webをアンインストール済みです。
新しい構成ではpython main.pyで起動し、PyInstallerでEXEを作成します。

ソースから起動：

```powershell
python main.py
```

Git反映後に単体EXEを作成：

```powershell
python tools/build_exe.py
```

main.pyのAPP_VERSIONを読み、dist/図面PDF検索結合ツール (v1.1.0).exeの形式で作成します。
版番号変更時にビルドコマンドを変更する必要はありません。
tools/build_exe.pyはFlet 1.0.1用です。Fletの版を変更する際にはビルド手順も検証してください。
初回は公式Fletクライアントをダウンロードする場合があるため、ネット接続が必要です。

EXEだけを配布できます。_internalを持ち込む必要はありません。
隣の.build.jsonはソース・EXEのハッシュと環境記録で、現地への持ち込みは不要です。
config.jsonとプレビューキャッシュは使用時にEXEの隣へ生成されます。
既存の旧版用.specは使いません。ビルドは既存の.envやconfigを変更しません。

tools/fixturesには架空の小規模ExcelとPDFのみを含めています。
内蔵--self-testは実画面を出さず処理を検査するための開発用機能で、現地操作の代わりではありません。


## v1.1.2のビルド検証

開発環境 `C:\dev\new_search_app` はそのまま残し、ビルド検証には
`C:\dev\new_search_app_build_v112` を新規作成して
`requirements-build.txt` の依存パッケージを導入しました。

```powershell
& "C:\dev\new_search_app_build_v112\Scripts\Activate.ps1"
python -c "import sys; print(sys.executable)"
python -m pip check
python tools/build_exe.py
```

既存環境のflet-cliのPyInstallerフックと、本スクリプトの明示的な同梱が
重なるとFletクライアントが二重に入ります。ビルド用環境にパッケージを
追加する場合は、サイズと同梱内容を再確認してください。
環境を切り替えた場合の比較ビルドでは、別の出力先を使用してください。

`.build.json` にEXEサイズと全インストール済みパッケージ一覧も保存します。
既存の `packages` は主要パッケージの抜粋、`all_packages` は環境全体です。
単体EXEの実画面確認は、内蔵self-testとは別に行います。
