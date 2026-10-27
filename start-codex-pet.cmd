@echo off
setlocal
cd /d "%~dp0"
set "PET_PYTHON=%~dp0.windows-runtime\python.exe"
set "PET_PYTHONW=%~dp0.windows-runtime\pythonw.exe"
if not exist "%PET_PYTHON%" (
  set "PET_PYTHON=%~dp0.venv-windows\Scripts\python.exe"
  set "PET_PYTHONW=%~dp0.venv-windows\Scripts\pythonw.exe"
)
if not exist "%PET_PYTHON%" (
  echo Please run setup-windows.cmd first, or use the portable ZIP package.
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
for %%A in (%*) do if "%%~A"=="--headless" goto console
start "" "%PET_PYTHONW%" "%~dp0codex_launcher.pyw" %*
exit /b 0
:console
"%PET_PYTHON%" "%~dp0codex_companion.py" %*
exit /b %errorlevel%
