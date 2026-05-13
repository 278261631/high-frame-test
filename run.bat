@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" main.py
if errorlevel 1 (
    echo.
    echo Program exited with error. Please check the message above.
    pause
)

endlocal
