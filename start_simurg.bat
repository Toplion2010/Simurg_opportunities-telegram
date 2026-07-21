@echo off
cd /d "%~dp0"

tasklist /FI "IMAGENAME eq python.exe" /FO CSV | findstr /I "python.exe" >nul
if not errorlevel 1 (
    echo Simurg is already running.
    exit /b 0
)
tasklist /FI "IMAGENAME eq pythonw.exe" /FO CSV | findstr /I "pythonw.exe" >nul
if not errorlevel 1 (
    echo Simurg is already running as a background task ^(pythonw.exe^).
    exit /b 0
)

if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install -e .
simurg
