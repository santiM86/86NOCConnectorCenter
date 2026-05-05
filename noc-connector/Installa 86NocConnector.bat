@echo off
REM ============================================================
REM  86NocConnector - Wizard di Installazione (BAT launcher)
REM ============================================================
REM  Alternativa a "Installa 86NocConnector.vbs" per evitare
REM  blocchi Mark-of-the-Web (MOTW) di SmartScreen su Windows 11.
REM
REM  USO: doppio-click. Auto-elevation con UAC.
REM  REQ: PowerShell 5.1+ (incluso in Windows 10/11).
REM ============================================================

setlocal
set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%prg\src\installer_gui.ps1"

if not exist "%PS1%" (
    echo.
    echo  [ERRORE] File del wizard non trovato:
    echo  %PS1%
    echo.
    echo  Assicurati di aver estratto TUTTI i file dallo zip
    echo  mantenendo la struttura delle cartelle.
    echo.
    pause
    exit /b 1
)

REM Auto-elevation: se non e' admin, rilancia se stesso elevato
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM Lancia il wizard con bypass execution policy
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%PS1%"
