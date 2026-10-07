@echo off
setlocal
cd /d "%~dp0"

rem Check that the packages are installed without importing Qt (importing Qt can fail for
rem environment reasons that reinstalling dependencies cannot fix).
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in ('PySide6','requests')) else 1)" >nul 2>nul
if not errorlevel 1 goto run

:setup
call setup.bat
if errorlevel 1 exit /b 1

:run
rem Import the whole app once with a console attached, so a broken environment prints a reason
rem instead of vanishing silently inside pythonw.exe.
".venv\Scripts\python.exe" -W ignore -c "import mathsnip" 2>"%~dp0startup-error.log"
if errorlevel 1 goto failed
del "%~dp0startup-error.log" >nul 2>nul

start "" ".venv\Scripts\pythonw.exe" "%~dp0mathsnip.py"
exit /b 0

:failed
echo.
echo MathSnip could not start. The reason is printed below.
echo ---------------------------------------------------------------
type "%~dp0startup-error.log" 2>nul
echo ---------------------------------------------------------------
echo Troubleshooting: delete the .venv folder and run setup.bat again.
pause
exit /b 1
