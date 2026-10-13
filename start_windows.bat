@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.13 -c "import sys" >nul 2>nul
  if errorlevel 1 (
    py -3.12 -m venv .venv
  ) else (
    py -3.13 -m venv .venv
  )
  if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info[:2] in [(3,12),(3,13)], 'Python 3.12 or 3.13 is required'"
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.lock
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 goto :error
echo Browser: http://127.0.0.1:8000
".venv\Scripts\python.exe" -m app.launcher
if errorlevel 1 goto :error
exit /b 0
:error
echo Startup failed. Install Python 3.12 or 3.13 and check the error above.
pause
exit /b 1
