$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'set_task_delay.ps1')
$sample = '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Triggers><LogonTrigger><Enabled>true</Enabled><Delay>PT1M</Delay></LogonTrigger><BootTrigger><Enabled>false</Enabled></BootTrigger></Triggers><Actions><Exec><Command>C:\batch\daily.cmd</Command></Exec></Actions></Task>'
[xml]$changed = Edit-TaskDelayXml $sample 1 3
if ($changed.Task.Triggers.LogonTrigger.Delay -ne 'PT3M') { throw 'Three-minute delay was not set.' }
if ($changed.Task.Triggers.BootTrigger.Enabled -ne 'false') { throw 'Other trigger changed.' }
if ($changed.Task.Actions.Exec.Command -ne 'C:\batch\daily.cmd') { throw 'Action changed.' }
[xml]$changed2 = Edit-TaskDelayXml $sample 2 10
if ($changed2.Task.Triggers.BootTrigger.Delay -ne 'PT10M') { throw 'Missing Delay was not created.' }
try { Edit-TaskDelayXml $sample 3 10; throw 'Accepted invalid index.' } catch { if ($_.Exception.Message -eq 'Accepted invalid index.') { throw } }
Write-Output 'PASS: delay XML edit, other trigger/action preservation, invalid trigger guard. No tasks registered.'
