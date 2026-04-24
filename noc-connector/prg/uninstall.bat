@echo off
REM =====================================================
REM   ARGUS Connector (86NocConnector)
REM   Wrapper batch per disinstallazione PowerShell robusta
REM
REM   La vera logica risiede in uninstall.ps1 — qui gestiamo:
REM     1. Auto-elevation a Amministratore
REM     2. Copia dello script in %TEMP% prima di eseguirlo
REM        (altrimenti PowerShell con CWD=C:\Program Files\86NocConnector
REM        impedirebbe la rimozione stessa della cartella)
REM     3. Invocazione con ExecutionPolicy Bypass
REM =====================================================

setlocal

REM Rileva path dello script anche dopo elevation
set "SCRIPT_DIR=%~dp0"
set "UNINSTALL_PS1_SRC=%SCRIPT_DIR%uninstall.ps1"

if not exist "%UNINSTALL_PS1_SRC%" (
    echo.
    echo   [ERRORE] uninstall.ps1 non trovato:
    echo     %UNINSTALL_PS1_SRC%
    echo.
    echo   L'installazione potrebbe essere corrotta. Puoi eseguire la
    echo   disinstallazione manualmente scaricando il pacchetto installer
    echo   della stessa versione e usando il relativo uninstall.ps1.
    echo.
    pause
    exit /b 2
)

REM Check Amministratore — rilancia con UAC se non sufficiente
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo   Richiesti privilegi di Amministratore — elevazione in corso...
    echo.
    powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

REM Copia uninstall.ps1 in %TEMP% per evitare file-lock sulla cartella di installazione.
REM PowerShell girerà da %TEMP% quindi C:\Program Files\86NocConnector sarà
REM rimuovibile dallo script stesso senza "Accesso negato".
set "UNINSTALL_PS1_RUN=%TEMP%\argus-uninstall-runner.ps1"
copy /Y "%UNINSTALL_PS1_SRC%" "%UNINSTALL_PS1_RUN%" >nul 2>&1

if not exist "%UNINSTALL_PS1_RUN%" (
    echo   [WARN] Copia in %%TEMP%% fallita, uso direttamente la copia originale.
    set "UNINSTALL_PS1_RUN=%UNINSTALL_PS1_SRC%"
)

REM Cambia CWD in %TEMP% per lo stesso motivo (nessun handle sulla install dir)
pushd "%TEMP%" >nul 2>&1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%UNINSTALL_PS1_RUN%"
set "RC=%errorLevel%"

popd >nul 2>&1

REM Best-effort: pulizia del runner temporaneo (non critico se fallisce)
del /Q "%UNINSTALL_PS1_RUN%" 2>nul

exit /b %RC%
