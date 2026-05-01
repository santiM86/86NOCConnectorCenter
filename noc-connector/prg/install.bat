@echo off
REM =====================================================
REM   86NocConnector - Avvio Wizard Installazione GUI
REM   86BIT srl - ARGUS Center
REM =====================================================
echo.
echo   86NocConnector - Wizard Installazione
echo.

REM Controlla se eseguito come Amministratore
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRORE] Esegui come Amministratore!
    echo Clicca col tasto destro su install.bat e scegli "Esegui come amministratore"
    pause
    exit /b 1
)

REM Lancia il wizard GUI
set "BASE=%~dp0"
set "WIZARD=%BASE%src\installer_gui.ps1"

if not exist "%WIZARD%" (
    echo [ERRORE] Wizard non trovato: %WIZARD%
    echo Lo ZIP potrebbe essere corrotto o incompleto.
    pause
    exit /b 1
)

echo Avvio wizard...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WIZARD%"

echo.
echo Wizard chiuso.
pause
