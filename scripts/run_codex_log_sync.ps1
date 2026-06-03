param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$Python = "python",
  [string]$UploadTarget = $env:CODEX_LOG_UPLOAD_TARGET,
  [string]$SshIdentity = $env:CODEX_LOG_SSH_IDENTITY
)

$ErrorActionPreference = "Stop"

$logDir = Join-Path $ProjectRoot ".local-artifacts\codex-log-sync"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "sync-$stamp.log"

$args = @(
  (Join-Path $ProjectRoot "scripts\export_codex_logs.py"),
  "--output-dir",
  (Join-Path $ProjectRoot ".local-artifacts\codex-log-batches")
)

if ($UploadTarget) {
  $args += @("--upload-target", $UploadTarget)
}
if ($SshIdentity) {
  $args += @("--ssh-identity", $SshIdentity)
}

Push-Location $ProjectRoot
try {
  & $Python @args *>&1 | Tee-Object -FilePath $logPath
  if ($LASTEXITCODE -ne 0) {
    throw "Codex log sync failed with exit code $LASTEXITCODE"
  }
}
finally {
  Pop-Location
}
