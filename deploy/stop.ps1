<#
.SYNOPSIS
  Stop the running Clustering-web-app instance started by start.ps1.
#>
$ErrorActionPreference = "SilentlyContinue"
$PidFile = Join-Path $PSScriptRoot "run\app.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "Not running (no deploy\run\app.pid found)." -ForegroundColor Yellow
    exit 0
}

$procId = Get-Content $PidFile
if ($procId -and (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $procId -Force
    Write-Host "Stopped (PID $procId)." -ForegroundColor Green
} else {
    Write-Host "Process $procId was not running (already stopped)." -ForegroundColor Yellow
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
