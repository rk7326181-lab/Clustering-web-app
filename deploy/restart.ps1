<#
.SYNOPSIS
  Restart Clustering-web-app (stop, wait, start).
#>
param(
    [int]$Port = 8501,
    [string]$BindAddress = "0.0.0.0"
)
& "$PSScriptRoot\stop.ps1"
Start-Sleep -Seconds 2
& "$PSScriptRoot\start.ps1" -Port $Port -BindAddress $BindAddress
