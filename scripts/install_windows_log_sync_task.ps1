param(
  [string]$TaskName = "ApiRelayRankCodexLogSync",
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "python",
  [string]$UploadTarget = $env:CODEX_LOG_UPLOAD_TARGET,
  [string]$SshIdentity = $env:CODEX_LOG_SSH_IDENTITY
)

$ErrorActionPreference = "Stop"

if (-not $UploadTarget) {
  throw "UploadTarget is required, for example user@example.com:/srv/api-relay-rank/log-inbox"
}

$runner = Join-Path $ProjectRoot "scripts\run_codex_log_sync.ps1"
$argumentParts = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$runner`"",
  "-ProjectRoot", "`"$ProjectRoot`"",
  "-Python", "`"$Python`"",
  "-UploadTarget", "`"$UploadTarget`""
)
if ($SshIdentity) {
  $argumentParts += @("-SshIdentity", "`"$SshIdentity`"")
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($argumentParts -join " ")
$trigger = New-ScheduledTaskTrigger -Daily -At "23:59:59"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Export sanitized Codex Manager logs and upload them to api-relay-rank." -Force | Out-Null

Write-Output "Scheduled task '$TaskName' installed for 23:59:59 daily."
