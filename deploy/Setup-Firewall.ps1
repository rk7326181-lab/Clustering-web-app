<#
.SYNOPSIS
  Restrict inbound access to Clustering-web-app's port to the Tailscale
  network only (plus localhost). Run ONCE as Administrator, after Tailscale
  is installed and running.

.DESCRIPTION
  Adds a Windows Firewall inbound ALLOW rule scoped to the Tailscale CGNAT
  range (100.64.0.0/10) and localhost, for TCP port 8501. Because Windows
  Firewall's default inbound policy is "Block" for anything not explicitly
  allowed, and this script does NOT add a broad allow rule, devices on your
  regular LAN/Wi-Fi (not on the tailnet) cannot reach the app even though it
  listens on 0.0.0.0. Combine this with Tailscale ACLs (in the Tailscale
  admin console) to control which specific tailnet devices/users may connect.
#>
param(
    [int]$Port = 8501,
    [string]$RuleName = "Clustering-web-app (Tailscale only, $Port)"
)

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please re-run this script as Administrator (right-click PowerShell -> Run as administrator)." -ForegroundColor Red
    exit 1
}

$defaultAction = (Get-NetFirewallProfile -Profile Domain,Private,Public | Select-Object -ExpandProperty DefaultInboundAction)
if ($defaultAction -contains "Allow") {
    Write-Host "WARNING: one of your firewall profiles has DefaultInboundAction = Allow." -ForegroundColor Yellow
    Write-Host "This script relies on the default being Block so only the rule below can let traffic in." -ForegroundColor Yellow
    Write-Host "Current defaults: $($defaultAction -join ', ')" -ForegroundColor Yellow
}

Remove-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue

New-NetFirewallRule -DisplayName $RuleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress "100.64.0.0/10","127.0.0.1" `
    -Action Allow `
    -Profile Any | Out-Null

Write-Host "Firewall rule '$RuleName' created:" -ForegroundColor Green
Write-Host "  Port $Port is reachable ONLY from Tailscale peers (100.64.0.0/10) and localhost."
Write-Host "  Devices on your regular LAN/Wi-Fi cannot reach it."
Write-Host ""
Write-Host "Also set up Tailscale ACLs in https://login.tailscale.com/admin/acls to control" -ForegroundColor Cyan
Write-Host "which specific tailnet devices/users may reach this machine. See DEPLOYMENT.md." -ForegroundColor Cyan
