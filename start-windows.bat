@echo off
REM FluxClip Studio - one-click start for Windows
REM Needs: Python 3.10+, Node.js 20+, FFmpeg (winget install ffmpeg)
cd /d "%~dp0"
where python >nul 2>nul || (echo Install Python from https://python.org first & pause & exit /b 1)
where node >nul 2>nul || (echo Install Node.js from https://nodejs.org first & pause & exit /b 1)
where ffmpeg >nul 2>nul || (echo Install FFmpeg first: open PowerShell and run: winget install ffmpeg & pause & exit /b 1)
if not exist .venv (
  echo Setting up Python environment, first run takes a few minutes...
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -e ".[all]" || (pause & exit /b 1)
)
if not exist web\node_modules (
  echo Installing web app...
  pushd web & call npm install --no-audit --no-fund & popd
)
if not exist web\.next\BUILD_ID (
  pushd web & call npm run build & popd
)
start "FluxClip API" cmd /k ".venv\Scripts\fluxclip studio --port 8000"
start "FluxClip Web" cmd /k "cd web && npm start"
timeout /t 8 >nul
start http://localhost:3000
echo FluxClip Studio is running at http://localhost:3000  (close the two windows to stop)
