@echo off
REM ============================================================
REM  Probe Into It - one-time setup for Windows
REM  Needs: Python 3.11 or 3.12 (python.org, tick "Add to PATH")
REM         Claude Code (https://claude.ai/code) logged in with your subscription
REM ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause & exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
choice /M "Download local AI image generation (stable-diffusion.cpp Vulkan + FLUX.1-schnell, ~17 GB) for shots with no real footage"
if errorlevel 2 (
  python -m ytfactory setup
) else (
  python -m ytfactory setup --images
)

echo.
echo Real stock footage is the main source of visuals. Get two free keys (no credit card):
echo   Pexels:  https://www.pexels.com/api/
echo   Pixabay: https://pixabay.com/api/docs/
python -m ytfactory keys

python -m ytfactory branding
python -m ytfactory check
echo.
echo Done! Double-click start.bat to open the studio.
pause
