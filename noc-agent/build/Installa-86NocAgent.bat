@echo off
REM ============================================================
REM 86NocAgent v4 - Wizard di installazione
REM ------------------------------------------------------------
REM Lancia il wizard PowerShell (auto-elevation UAC integrata).
REM
REM Per evitare anche il singolo click su UAC: tasto destro su
REM questo file -> "Esegui come amministratore".
REM ============================================================
setlocal
title 86NocAgent v4 - Wizard installazione

echo.
echo  +------------------------------------------------------+
echo  ^|        86NocAgent v4 - Wizard installazione          ^|
echo  ^|        86bit S.r.l. - www.86bit.it                   ^|
echo  +------------------------------------------------------+
echo.
echo  Avvio del wizard grafico in corso...
echo  Se Windows mostra il prompt UAC, accetta per concedere
echo  i privilegi di amministratore.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer_gui.ps1"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo  Il wizard ha terminato con codice %RC%.
    echo  Controlla eventuali messaggi di errore qui sopra.
    echo.
    pause
)
endlocal
exit /b %RC%
