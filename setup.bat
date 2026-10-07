@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
echo Creating a local Python environment...
py -3.12 -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" goto install
py -3 -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" goto install
python -m venv .venv
if not exist ".venv\Scripts\python.exe" goto failed
:install
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Run run.bat to start MathSnip.
exit /b 0
:failed
echo Setup failed. Install Python 3.12 64-bit, with the Python launcher enabled.
echo Check the network connection if dependency installation failed.
pause
exit /b 1
