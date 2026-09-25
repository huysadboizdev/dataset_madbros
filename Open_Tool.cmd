@echo off
rem Mo PDF Cleaner Tool (backend + trinh duyet). Duong dan co dau/khoang trang van OK.
setlocal
set PYTHONIOENCODING=utf-8
set "PY="
if exist "%~dp0data\python_path.txt" set /p PY=<"%~dp0data\python_path.txt"
if not defined PY set "PY=D:\OCR_Local\.venv313\Scripts\python.exe"
if not exist "%PY%" (
  echo [LOI] Khong tim thay Python: "%PY%"
  echo Chay setup.cmd truoc, hoac sua duong dan trong data\python_path.txt.
  pause
  exit /b 1
)
"%PY%" "%~dp0scripts\launch.py"
pause
