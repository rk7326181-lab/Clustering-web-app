@echo off
REM Double-click to check whether Clustering-web-app is running.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0status.ps1" %*
pause
