@echo off
rem Cai dat / kiem tra moi truong PDF Cleaner Tool.
rem Khong hardcode mot venv: thu PDFCLEANER_PY -> venv 3.13 quen -> py -3.13.
rem Moi ung vien PHAI duoc KIEM LA INTERPRETER THAT (phienv 3.13, 64-bit, co paddleocr)
rem bang scripts\check_interpreter.py — khong chi kiem 'file ton tai'.
setlocal EnableDelayedExpansion
set PYTHONIOENCODING=utf-8
set "ROOT=%~dp0"
set "CHECK=%ROOT%scripts\check_interpreter.py"
set "PY="

rem --- Ung vien 1: PDFCLEANER_PY (do nguoi dung chi). Nghi ngp la interpreter san co ---
if defined PDFCLEANER_PY (
  call :try "%PDFCLEANER_PY%"
)

rem --- Ung vien 2: venv PaddleOCR 3.13 mac dinh may nay (duong dan co dau/khoang OK) ---
if not defined PY call :try "D:\OCR_Local\.venv313\Scripts\python.exe"

rem --- Ung vien 3: bat ky Python 3.13 he thong -> tao venv DU AN va cai theo lock ---
if not defined PY (
  echo [THONG BAO] Khong co interpreter PaddleOCR 3.13 hop le. Tao venv rieng trong du an...
  py -3.13 -c "print(1)" >nul 2>nul
  if errorlevel 1 (
    echo [LOI] May khong co Python 3.13 ^(py -3.13^). Cai hoac dat PDFCLEANER_PY tro toi interpreter 3.13 64-bit.
    pause
    exit /b 1
  )
  py -3.13 -m venv "%ROOT%.venv" || goto :fail
  set "PY=%ROOT%.venv\Scripts\python.exe"
  rem KIEM venv vua tao la interpreter that, 3.13, 64-bit
  "!PY!" "%CHECK%" "!PY!" --no-paddle || (echo [LOI] venv khong hop le.& goto :fail)
  echo [LUU Y] Venv moi se tai toan bo paddle ^+ dependencies ^(internet, ~1.5 GB^).
)

echo Dung interpreter: %PY%
if not exist "%ROOT%data" mkdir "%ROOT%data"
echo %PY%> "%ROOT%data\python_path.txt"

echo == Cai backend ^(idempotent, theo lock^) ==
"%PY%" -m pip install -r "%ROOT%requirements.lock.txt" || goto :fail
echo == Kiem tra moi truong ==
"%PY%" "%ROOT%scripts\check_environment.py"
echo == Kiem tra interpreter (lan cuoi, sau khi cai) ==
"%PY%" "%CHECK%" "%PY%"

where npm.cmd >nul 2>nul || where npm >nul 2>nul
if errorlevel 1 (
  echo [THONG BAO] Chua cai Node - bo qua build frontend. Cai Node roi chay lai setup.cmd neu can UI.
  goto :done
)
pushd "%ROOT%frontend"
if exist package-lock.json (
  echo == Cai frontend bang npm ci ^(tai lap chinh xac tu lockfile^) ==
  call npm.cmd ci --no-audit --no-fund || call npm.cmd install --no-audit --no-fund
) else (
  echo == Khong co package-lock.json -> npm install ==
  call npm.cmd install --no-audit --no-fund
)
call npm.cmd run build
popd

:done
if not exist "%ROOT%config.json" copy "%ROOT%config.example.json" "%ROOT%config.json" >nul
echo == Xong. Mo tool bang Open_Tool.cmd ==
pause
exit /b 0

rem ---------------------------------------------------------------------------
rem :try <python> : chap nhan <python> NEU no la interpreter 3.13/64-bit/paddle.
rem ---------------------------------------------------------------------------
:try
set "CAND=%~1"
if not defined CAND exit /b 1
if not exist "%CAND%" exit /b 1
"%CAND%" "%CHECK%" "%CAND%" >nul 2>nul
if errorlevel 1 exit /b 1
set "PY=%CAND%"
exit /b 0

:fail
echo [LOI] Cai backend that bai.
pause
exit /b 1
