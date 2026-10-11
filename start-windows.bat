@echo off
setlocal
title FluxClip Studio - setup
REM FluxClip Studio - one-click start for Windows
REM Needs: Python 3.10+, Node.js 20+, FFmpeg
cd /d "%~dp0"

echo.
echo  ===== FluxClip Studio =====
echo.

echo [1/5] Checking required programs...
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  ERROR: Python is not installed.
  echo  Install it from https://www.python.org/downloads/
  echo  IMPORTANT: tick "Add python.exe to PATH" on the first install screen.
  goto :fail
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo  ERROR: Python 3.10 or newer is needed. You have:
  python --version
  goto :fail
)
where node >nul 2>nul
if errorlevel 1 (
  echo  ERROR: Node.js is not installed. Get the LTS version from https://nodejs.org
  goto :fail
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo  ERROR: FFmpeg is not installed.
  echo  Open PowerShell and run:   winget install ffmpeg
  echo  Then CLOSE this window and double-click start-windows.bat again.
  goto :fail
)
echo     OK - Python, Node.js and FFmpeg found.

echo [2/5] Python packages (first time: 3-10 minutes)...
if not exist .venv\Scripts\fluxclip.exe (
  if not exist .venv python -m venv .venv
  if errorlevel 1 goto :fail
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -e ".[all]"
  if errorlevel 1 (
    echo  ERROR: Python package install failed - see the messages above.
    goto :fail
  )
)
echo     OK

echo [3/5] Web app packages (first time: 1-3 minutes)...
if not exist web\node_modules (
  pushd web
  call npm install --no-audit --no-fund
  if errorlevel 1 ( popd & echo  ERROR: npm install failed. & goto :fail )
  popd
)
echo     OK

echo [4/5] Building the web app...
if not exist web\.next\BUILD_ID (
  pushd web
  call npm run build
  if errorlevel 1 ( popd & echo  ERROR: web build failed. & goto :fail )
  popd
)
echo     OK

echo [5/5] Starting FluxClip Studio...
start "FluxClip API (keep open)" cmd /k "cd /d "%~dp0" && .venv\Scripts\fluxclip.exe studio --host 127.0.0.1 --port 8000"
start "FluxClip Web (keep open)" cmd /k "cd /d "%~dp0web" && npm start"

echo     Waiting for it to come up...
set /a tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://localhost:3000/api/health -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 goto :ready
if %tries% GEQ 60 (
  echo  ERROR: FluxClip did not start within 2 minutes.
  echo  Look at the two other black windows for the error message.
  goto :fail
)
timeout /t 2 >nul
goto :wait

:ready
echo.
echo  FluxClip Studio is running:  http://localhost:3000
echo  Keep the two "FluxClip" windows open while you use it. Close them to stop.
start http://localhost:3000
echo.
pause
exit /b 0

:fail
echo.
echo  Setup stopped. Fix the error above, then double-click start-windows.bat again.
echo.
pause
exit /b 1
