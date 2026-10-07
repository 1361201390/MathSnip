@echo off
setlocal
cd /d "%~dp0"
call setup.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
set QT_QPA_PLATFORM=offscreen
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto failed
set QT_QPA_PLATFORM=
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --name MathSnip --icon assets\mathsnip.ico mathsnip.py
if errorlevel 1 goto failed
echo Build complete: dist\MathSnip.exe
echo Double-click the EXE to start. Python is not required for the EXE.
pause
exit /b 0
:failed
echo Build failed. See the messages above.
pause
exit /b 1
