@echo off
rem Geo Intelligence Portal - DESKTOP MODE
rem Go Live can then upload to Saruman (office network / VPN only) and push polygons
rem to Google My Maps through a robot Chrome window. See modules\desktop.py.
cd /d "%~dp0.."
set GEO_PORTAL_DESKTOP=1
set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"
"%PY%" -c "import playwright" 2>nul || "%PY%" -m pip install -q -r requirements-desktop.txt
echo.
echo  Desktop mode starting at http://localhost:8501  (close this window to stop)
echo.
"%PY%" -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless false
