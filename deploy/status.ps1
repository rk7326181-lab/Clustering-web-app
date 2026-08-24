<#
.SYNOPSIS
  Check whether Clustering-web-app is running, and show its Tailscale URL.
#>
$ErrorActionPreference = "SilentlyContinue"
$PidFile = Join-Path $PSScriptRoot "run\app.pid"
$Port = 8501

if ((Test-Path $PidFile)) {
    $procId = Get-Content $PidFile
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p) {
        $uptime = (Get-Date) - $p.StartTime
        Write-Host "RUNNING - PID $procId, up for $([int]$uptime.TotalMinutes) min" -ForegroundColor Green
    } else {
        Write-Host "NOT RUNNING (stale PID file - process $procId no longer exists)" -ForegroundColor Yellow
    }
} else {
    Write-Host "NOT RUNNING (no PID file)" -ForegroundColor Yellow
}

Write-Host "  Local:     http://localhost:$Port"
$ts = tailscale ip -4 2>$null
if ($ts) {
    Write-Host "  Tailscale: http://$($ts):$Port" -ForegroundColor Cyan
} else {
    Write-Host "  Tailscale: run 'tailscale ip -4' to get this machine's address, or use its MagicDNS name."
}
