@echo off
REM Double-click to stop Clustering-web-app.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
pause
