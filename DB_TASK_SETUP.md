# Windows 11：自端末でのDB更新タスク（テスト運用）

自端末で共有フォルダにアクセスするため、今回は「PC起動時」ではなく、本人の**サインイン時から少し遅らせて実行**する構成を使います。サインイン前でも動かす常設PCの設定とは分けます。
この資料は登録手順です。タスクは自動登録していません。

## 先に手動確認

PDF：更新EXE・`daily_pdf_index.cmd`・`manual_pdf_index.cmd`・`pdf_index_config.json` を同じフォルダへ置きます。
構成部品表：Cの更新EXE・`daily.cmd`・`manual_batch.cmd`・`batch_config.json` を同じフォルダへ置きます。
各手動CMDで終了コード0と公開manifestの更新を確認します。各JSONのpublishは共通配信先、作業databaseは別々にします。
共有先にはドライブ文字より `\\サーバー\共有\...` のUNCパスを使います。

## 1．PDF索引更新

スタートメニューから「タスク スケジューラ」を開き、「タスクの作成」。

**全般**

- 名前：PDF索引更新（テスト）
- 自分のWindowsアカウントを指定
- 「ユーザーがログオンしているときのみ実行する」
- 「最上位の特権で実行する」は通常不要

**トリガー**

- タスクの開始：ログオン時
- 特定のユーザー：自分
- 遅延時間：登録画面では仮の値を選択し、登録後に下記「任意の遅延を設定する」で3分等へ変更
- 有効：ON

**操作**

- プログラム／スクリプト：`C:\Windows\System32\cmd.exe`
- 引数の追加：`/d /c ""C:\実際のPDFバッチフォルダ\daily_pdf_index.cmd""`
- 開始：`C:\実際のPDFバッチフォルダ`（引用符なし）

上のパスを実際の配置に置き換えます。pause付きのmanualではなくdailyを登録します。

**条件・設定**

- ノートPCでバッテリー時も試すなら「AC電源使用時のみ開始」をOFF
- 必要なら「ネットワーク接続が使用可能な場合のみ開始」をON
- 「タスクを要求時に実行する」をON
- 「既に実行中の場合」：新しいインスタンスを開始しない
- 失敗時の再試行：10分後、3回など。実際の通信待ち時間に合わせる
- 長時間処理の強制停止は、初回の実測時間より短く設定しない

## 2．構成部品表DB更新

同様に「構成部品表DB更新（テスト）」を作ります。
登録後、下記の手順でトリガーの遅延を10分程度にずらし、次の操作を設定します。

- プログラム：`C:\Windows\System32\cmd.exe`
- 引数：`/d /c ""C:\実際の構成部品表バッチフォルダ\daily.cmd""`
- 開始：`C:\実際の構成部品表バッチフォルダ`

遅延をずらしても実行が重なる可能性はあります。両DBは独立更新なので世代を合わせる必要はありませんが、NAS負荷が高い場合は遅延を延ばします。

## 3．登録後の確認

タスクを右クリックして「実行」。終了まで待ち、次を確認します。

1. 前回の実行結果が `0x0`（処理中の `0x41301` は完了ではありません）
2. 各バッチのログに正常終了が記録されている
3. 共通配信先の `pdf-latest.json` と `latest.json` の更新日時が新しい
4. アプリで「最新データ取得」後、2つのDB更新日時が新しい

最後にサインアウト→サインインして遅延実行を確認します。
ログオン時トリガーはサインインするたびに動きます。毎晩決まった時間の実行ではなく、電源OFF中は実行されません。
常時起動PCへ移す時は、実行用アカウントとNAS権限を確認して「毎日」の時刻指定へ変更します。

## 任意の遅延を設定する（3分／10分など）

プルダウンに3分等がなくても、Windowsの遅延値には `PT3M` のように任意の分数を設定できます。
同梱の `tools/set_task_delay.ps1` を使います。これは実行中のタスクを起動するコマンドではありません。
対象は、この手順で作った「ユーザーがログオンしているときのみ実行する」タスクです。別の実行アカウント形式では変更せず停止します。

正本フォルダでPowerShellを開き、実際のタスク名で、まず変更予定を表示します。

```powershell
& .\tools\set_task_delay.ps1 -TaskName 'PDF索引更新（テスト）' -Minutes 3
```

`Number / Type / Delay` を確認します。ログオン時はLogonTrigger、PC起動時はBootTriggerです。
対象トリガーが2番なら `-TriggerNumber 2` を付けます。別フォルダに登録した場合は `-TaskPath '\そのフォルダ\'` も指定します。
対象が正しいことを確認して、同じコマンドに `-Apply` を付けます。

```powershell
& .\tools\set_task_delay.ps1 -TaskName 'PDF索引更新（テスト）' -Minutes 3 -Apply
& .\tools\set_task_delay.ps1 -TaskName '構成部品表DB更新（テスト）' -Minutes 10 -Apply
```

変更前のXMLを `work/task-backups/task-....xml` へ保存し、対象トリガーのDelayだけを変更します。
`Verified: PT3M` 等が出ることを確認してください。上の数値は例で、`-Minutes 5` などにもできます。
プルダウンの粗い候補を選び直すと、その値に戻るためご注意ください。
アシスタントによる確認はXML編集のオフラインテストまでです。実タスクの変更はこの手順を実行した端末で行います。

戻すには、表示されたバックアップXMLと、同じTaskName／TaskPathを指定します。

```powershell
$taskBackupXml = Get-Content -LiteralPath '実際のバックアップXMLのパス' -Raw
Register-ScheduledTask -TaskName 'PDF索引更新（テスト）' -TaskPath '\' -Xml $taskBackupXml -Force
```

公式仕様：
[ログオン時のDelay](https://learn.microsoft.com/en-us/windows/win32/taskschd/logontrigger-delay)、
[XMLによるタスク登録](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)。
