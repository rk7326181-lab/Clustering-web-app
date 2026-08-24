<#
.SYNOPSIS
  Start Clustering-web-app (Geo Intelligence Portal) as a background process,
  bound to 0.0.0.0 so it's reachable over the Tailscale private network.

.DESCRIPTION
  - Uses .\venv\Scripts\python.exe if present, else falls back to `python`
    on PATH.
  - Refuses to start a second copy if one is already running (tracked via
    deploy\run\app.pid).
  - Logs stdout/stderr to deploy\logs\.
  See ..\DEPLOYMENT.md for the full runbook.
#>
param(
    [int]$Port = 8501,
    [string]$BindAddress = "0.0.0.0"
)
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$RunDir = Join-Path $PSScriptRoot "run"
$LogDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null
$PidFile = Join-Path $RunDir "app.pid"

if (Test-Path $PidFile) {
    $existingPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Host "Already running (PID $existingPid) on port $Port." -ForegroundColor Yellow
        Write-Host "Use Restart-App.bat to restart, or Stop-App.bat first." -ForegroundColor Yellow
        exit 0
    }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

$venvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $LogDir "app_$timestamp.log"
$errFile = Join-Path $LogDir "app_$timestamp.err.log"

Write-Host "Starting Clustering-web-app on $($BindAddress):$Port using $python ..." -ForegroundColor Cyan

$proc = Start-Process -FilePath $python `
    -ArgumentList @(
        "-m", "streamlit", "run", "app.py",
        "--server.address=$BindAddress",
        "--server.port=$Port",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ) `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
    Write-Host "Process exited immediately - check the log for errors:" -ForegroundColor Red
    Write-Host "  $errFile" -ForegroundColor Red
    Get-Content $errFile -Tail 20 -ErrorAction SilentlyContinue
    exit 1
}

$proc.Id | Out-File -FilePath $PidFile -Encoding ascii
Write-Host "Started. PID=$($proc.Id)" -ForegroundColor Green
Write-Host "  Local:     http://localhost:$Port"
Write-Host "  Tailscale: http://<this-machine-tailscale-name-or-ip>:$Port"
Write-Host "  Log:       $logFile"
