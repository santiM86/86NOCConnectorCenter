@echo off
title 86NocConnector - Installazione
echo ============================================================
echo   86NocConnector - Installazione
echo ============================================================
echo.

set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python\python.exe"

:: Check Python embedded
if not exist "%PYTHON_EXE%" (
    echo Python embedded non trovato. Eseguo setup.bat...
    call "%BASE_DIR%setup.bat"
)

:: Launch installer GUI
"%PYTHON_EXE%" "%BASE_DIR%src\installer_gui.py"
