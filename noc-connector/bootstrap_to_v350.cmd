@echo off
REM ============================================================================
REM 86NocConnector - Bootstrap v3.5.0 Microsoft-native auto-update
REM ============================================================================
REM
REM Questo script va lanciato UNA SOLA VOLTA come amministratore sui server
REM che hanno versioni v3.4.x-v3.4.9 del connector per migrare al nuovo
REM sistema di auto-update basato su Windows Task Scheduler (pattern Microsoft).
REM
REM Da v3.5.0 in poi tutti gli aggiornamenti sono automatici senza piu' PS blocking
REM ne' esclusioni Defender.
REM
REM COME USARLO:
REM   1. Scarica 86NocConnector_v3.5.0.zip (solo prg, non l'installer) dal NOC
REM   2. Estrai in C:\Temp\86Noc_v350\
REM   3. Tasto destro su questo file -> "Esegui come amministratore"
REM   4. Attendi 30-60 secondi
REM
REM COSA FA:
REM   1. Ferma servizio 86NocConnectorService
REM   2. Copia tutti i file da C:\Temp\86Noc_v350\prg\* a C:\Program Files\86NocConnector\
REM   3. Crea Scheduled Task \86BIT\ArgusConnectorUpdater
REM   4. Riavvia il servizio
REM   5. Da ora in poi gli update sono automatici (ogni 5 min)
REM ============================================================================

setlocal EnableExtensions

echo.
echo ==========================================================================
echo   86NocConnector - Bootstrap v3.5.0 Microsoft-native auto-update
echo ==========================================================================
echo.

REM Verifica admin
net session >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Questo script richiede privilegi amministratore.
    echo Tasto destro -^> "Esegui come amministratore"
    echo.
    pause
    exit /b 1
)

set "INSTALL_DIR=C:\Program Files\86NocConnector"
set "EXTRACT_DIR=%~dp0"
if "%EXTRACT_DIR:~-1%"=="\" set "EXTRACT_DIR=%EXTRACT_DIR:~0,-1%"

echo InstallDir:  %INSTALL_DIR%
echo ExtractDir:  %EXTRACT_DIR%
echo.

if not exist "%EXTRACT_DIR%\prg" (
    echo ERRORE: Cartella "prg" non trovata in %EXTRACT_DIR%
    echo Estrai il ZIP v3.5.0 prima di lanciare questo script.
    echo.
    pause
    exit /b 2
)

if not exist "%INSTALL_DIR%" (
    echo ERRORE: %INSTALL_DIR% non esiste. Connector non installato.
    echo Per una nuova installazione usa 86NocConnector_v3.5.0_install.zip
    echo.
    pause
    exit /b 3
)

REM === STEP 1: STOP servizio ===
echo [1/5] Stop servizio 86NocConnectorService...
net stop 86NocConnectorService >nul 2>&1
sc.exe stop 86NocConnectorService >nul 2>&1
timeout /t 5 /nobreak >nul 2>&1

REM === STEP 2: RIMUOVI vecchi scheduled task obsoleti ===
echo [2/5] Rimozione vecchi scheduled task...
schtasks.exe /Delete /TN "\86BIT\ArgusConnectorUpdater" /F >nul 2>&1
schtasks.exe /Delete /TN "\86NocConnector\UpdateChecker" /F >nul 2>&1
schtasks.exe /Delete /TN "86NocConnector" /F >nul 2>&1

REM === STEP 3: COPIA file nuovi ===
echo [3/5] Copia file da %EXTRACT_DIR%\prg\* a %INSTALL_DIR%\...
REM Backup src/ corrente
if exist "%INSTALL_DIR%\_backup_pre_v350" rmdir /S /Q "%INSTALL_DIR%\_backup_pre_v350" 2>nul
mkdir "%INSTALL_DIR%\_backup_pre_v350" 2>nul
xcopy "%INSTALL_DIR%\src" "%INSTALL_DIR%\_backup_pre_v350\src\" /E /I /Y /Q >nul 2>&1
if exist "%INSTALL_DIR%\version.json" copy /Y "%INSTALL_DIR%\version.json" "%INSTALL_DIR%\_backup_pre_v350\version.json" >nul 2>&1

REM Rimuovi vecchi file update (updater.ps1, updater.cmd non piu' necessari in v3.5.0)
del /F /Q "%INSTALL_DIR%\src\updater.ps1" >nul 2>&1
del /F /Q "%INSTALL_DIR%\src\updater.cmd" >nul 2>&1

REM Copia file nuovi
xcopy "%EXTRACT_DIR%\prg\*" "%INSTALL_DIR%\" /E /I /Y /Q >nul 2>&1
if errorlevel 1 (
    echo      ERRORE xcopy. Rollback...
    xcopy "%INSTALL_DIR%\_backup_pre_v350\src\*" "%INSTALL_DIR%\src\" /E /I /Y /Q >nul 2>&1
    net start 86NocConnectorService >nul 2>&1
    pause
    exit /b 4
)

REM === STEP 4: CREA Scheduled Task ===
echo [4/5] Creazione Scheduled Task \86BIT\ArgusConnectorUpdater...
set "UPDATE_SCRIPT=%INSTALL_DIR%\src\update_check.ps1"
if not exist "%UPDATE_SCRIPT%" (
    echo      ERRORE: update_check.ps1 non trovato in %UPDATE_SCRIPT%
    echo      Verifica che il ZIP v3.5.0 sia corretto.
    pause
    exit /b 5
)
set "TASK_ACTION=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%UPDATE_SCRIPT%\" -InstallDir \"%INSTALL_DIR%\""
schtasks.exe /Create /TN "\86BIT\ArgusConnectorUpdater" /SC MINUTE /MO 5 /TR "%TASK_ACTION%" /RU "SYSTEM" /RL HIGHEST /F >nul 2>&1
if errorlevel 1 (
    echo      ERRORE creazione scheduled task
    pause
    exit /b 6
)
echo      OK - task creato

REM === STEP 5: START servizio ===
echo [5/5] Start servizio 86NocConnectorService...
net start 86NocConnectorService >nul 2>&1
timeout /t 3 /nobreak >nul 2>&1

sc.exe query 86NocConnectorService | find "RUNNING" >nul 2>&1
if errorlevel 1 (
    echo      ATTENZIONE: servizio non ancora RUNNING, controlla Event Viewer
) else (
    echo      OK servizio RUNNING
)

echo.
echo ==========================================================================
echo   BOOTSTRAP v3.5.0 COMPLETATO
echo ==========================================================================
echo.
echo   Installato:
echo   - File aggiornati in %INSTALL_DIR%
echo   - Scheduled Task "\86BIT\ArgusConnectorUpdater" (trigger: ogni 5 min)
echo   - Backup v3.4.x in %INSTALL_DIR%\_backup_pre_v350\
echo.
echo   Da ora in poi tutti gli aggiornamenti sono AUTOMATICI
echo   tramite Windows Task Scheduler. Nessun intervento manuale richiesto.
echo.
echo   Puoi testare manualmente il task con:
echo      schtasks /Run /TN "\86BIT\ArgusConnectorUpdater"
echo.
echo   Log update:  %%ProgramData%%\86NocConnector\update.log
echo.
pause
exit /b 0
