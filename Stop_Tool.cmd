@echo off
rem Dong DUNG backend + worker cua PDF Cleaner Tool (khong taskkill moi python.exe).
setlocal
set PYTHONIOENCODING=utf-8
set "PY="
if exist "%~dp0data\python_path.txt" set /p PY=<"%~dp0data\python_path.txt"
if not defined PY set "PY=D:\OCR_Local\.venv313\Scripts\python.exe"
"%PY%" "%~dp0scripts\stop.py"
pause
