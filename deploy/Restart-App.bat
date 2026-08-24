@echo off
REM Double-click to restart Clustering-web-app.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1" %*
pause
