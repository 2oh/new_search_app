# Preview by default. Only -Apply updates an existing interactive-user task.
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName,
    [string]$TaskPath = '\',
    [ValidateRange(1, 999)][int]$TriggerNumber = 1,
    [ValidateRange(0, 1440)][int]$Minutes = 3,
    [string]$BackupDirectory = (Join-Path $PSScriptRoot '..\work\task-backups'),
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'

function Edit-TaskDelayXml {
    param([string]$Definition, [int]$Index, [int]$DelayMinutes)
    if ($DelayMinutes -lt 0 -or $DelayMinutes -gt 1440) { throw 'Invalid delay.' }
    [xml]$document = $Definition
    $namespace = New-Object System.Xml.XmlNamespaceManager($document.NameTable)
    $namespace.AddNamespace('t', $document.DocumentElement.NamespaceURI)
    $triggers = @($document.SelectNodes('/t:Task/t:Triggers/*', $namespace))
    if ($Index -lt 1 -or $Index -gt $triggers.Count) { throw 'Trigger number does not exist.' }
    $trigger = $triggers[$Index - 1]
    if ($trigger.LocalName -notin @('LogonTrigger', 'BootTrigger')) { throw 'Select a logon or boot trigger.' }
    $delay = $trigger.SelectSingleNode('t:Delay', $namespace)
    if ($null -eq $delay) {
        $delay = $document.CreateElement('Delay', $document.DocumentElement.NamespaceURI)
        [void]$trigger.AppendChild($delay)
    }
    $delay.InnerText = 'PT' + $DelayMinutes + 'M'
    return $document.OuterXml
}

# Dot-sourcing with no task name only loads the XML helper for offline testing.
if (-not $TaskName) { return }
$matches = @(Get-ScheduledTask -TaskPath $TaskPath | Where-Object { $_.TaskName -ceq $TaskName })
if ($matches.Count -ne 1) { throw 'Exactly one existing task must match the name and path.' }
$definition = Export-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
[xml]$document = $definition
$namespace = New-Object System.Xml.XmlNamespaceManager($document.NameTable)
$namespace.AddNamespace('t', $document.DocumentElement.NamespaceURI)
$principal = $document.SelectSingleNode('/t:Task/t:Principals/t:Principal/t:LogonType', $namespace)
if ($null -eq $principal -or $principal.InnerText -ne 'InteractiveToken') {
    throw 'This procedure supports only tasks configured to run while the user is logged on. No changes made.'
}
$triggers = @($document.SelectNodes('/t:Task/t:Triggers/*', $namespace))
for ($index = 0; $index -lt $triggers.Count; $index++) {
    $currentDelay = $triggers[$index].SelectSingleNode('t:Delay', $namespace)
    [pscustomobject]@{ Number = $index + 1; Type = $triggers[$index].LocalName; Delay = if ($currentDelay) { $currentDelay.InnerText } else { 'PT0M' } }
}
$updated = Edit-TaskDelayXml -Definition $definition -Index $TriggerNumber -DelayMinutes $Minutes
Write-Host ('Task: ' + $TaskPath + $TaskName + '; trigger ' + $TriggerNumber + '; new delay PT' + $Minutes + 'M')
if (-not $Apply) { Write-Host 'Preview only. Add -Apply to save this change.'; return }
if ($PSCmdlet.ShouldProcess(($TaskPath + $TaskName), 'Update trigger delay')) {
    [void](New-Item -ItemType Directory -Path $BackupDirectory -Force)
    $backup = Join-Path $BackupDirectory ('task-' + [guid]::NewGuid().ToString('N') + '.xml')
    [System.IO.File]::WriteAllText($backup, $definition, [System.Text.Encoding]::Unicode)
    Write-Host ('Backup: ' + $backup)
    Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Xml $updated -Force | Out-Null
    [xml]$verified = Export-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    $namespace2 = New-Object System.Xml.XmlNamespaceManager($verified.NameTable)
    $namespace2.AddNamespace('t', $verified.DocumentElement.NamespaceURI)
    $actual = $verified.SelectNodes('/t:Task/t:Triggers/*', $namespace2)[$TriggerNumber-1].SelectSingleNode('t:Delay', $namespace2)
    if ($null -eq $actual -or [System.Xml.XmlConvert]::ToTimeSpan($actual.InnerText).TotalMinutes -ne $Minutes) {
        throw ('Verification failed. Restore from ' + $backup)
    }
    Write-Host ('Verified: ' + $actual.InnerText)
}
