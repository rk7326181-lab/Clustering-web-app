@echo off
REM Double-click to start Clustering-web-app (Geo Intelligence Portal).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
