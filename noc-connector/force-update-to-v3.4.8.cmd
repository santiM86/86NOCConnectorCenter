@echo off
REM ============================================================================
REM 86NocConnector - Force Update to v3.4.8 (ASR-safe bootstrap)
REM ============================================================================
REM QUANDO USARLO:
REM   Se il connector client rimane bloccato a v3.4.5/v3.4.6/v3.4.7 perche'
REM   Windows Defender ASR uccide il PowerShell updater.
REM   Dopo UNA esecuzione di questo script, tutti gli aggiornamenti futuri
REM   saranno automatici grazie al nuovo updater.cmd ASR-safe di v3.4.8+.
REM
REM COME USARLO:
REM   1. Scarica 86NocConnector_v3.4.8.zip da:
REM      https://<your-argus-domain>/downloads/86NocConnector_v3.4.8.zip
REM   2. Estrai in C:\Temp\86Noc_Update\
REM   3. Tasto destro su questo file -> "Esegui come amministratore"
REM   4. Attendi circa 30-60 secondi
REM
REM COSA FA:
REM   - Ferma il servizio 86NocConnectorService
REM   - Copia i nuovi file da C:\Temp\86Noc_Update\prg\* a C:\Program Files\86NocConnector\
REM   - Riavvia il servizio
REM   - Non richiede esclusioni Defender (usa solo cmd.exe + xcopy nativi)
REM ============================================================================

setlocal EnableExtensions

echo.
echo ==========================================================================
echo   86NocConnector - Force Update Bootstrap to v3.4.8
echo ==========================================================================
echo.

REM Verify admin
net session >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Questo script richiede privilegi amministratore.
    echo Tasto destro sul file e scegli "Esegui come amministratore"
    echo.
    pause
    exit /b 1
)

set "INSTALL_DIR=C:\Program Files\86NocConnector"
set "EXTRACT_DIR=%~dp0"

REM Remove trailing backslash from EXTRACT_DIR
if "%EXTRACT_DIR:~-1%"=="\" set "EXTRACT_DIR=%EXTRACT_DIR:~0,-1%"

echo InstallDir:  %INSTALL_DIR%
echo ExtractDir:  %EXTRACT_DIR%
echo.

if not exist "%EXTRACT_DIR%\prg" (
    echo ERRORE: Cartella "prg" non trovata in %EXTRACT_DIR%
    echo Assicurati di aver estratto il ZIP correttamente prima di lanciare questo script.
    echo.
    pause
    exit /b 2
)

if not exist "%INSTALL_DIR%" (
    echo ERRORE: %INSTALL_DIR% non esiste. Il connector non risulta installato.
    echo Usa invece l'installer completo: 86NocConnector_v3.4.8_install.zip
    echo.
    pause
    exit /b 3
)

REM === STOP SERVIZIO ===
echo [1/4] Stop servizio 86NocConnectorService...
net stop 86NocConnectorService >nul 2>&1
if errorlevel 1 (
    sc.exe stop 86NocConnectorService >nul 2>&1
)

REM Attendi fino a 20 secondi
set /a count=0
:wait_stopped
sc.exe query 86NocConnectorService 2>nul | find "STOPPED" >nul 2>&1
if %errorlevel% equ 0 goto :stopped
set /a count+=1
if %count% geq 20 (
    echo      ATTENZIONE: servizio ancora attivo dopo 20s, continuo comunque
    goto :stopped
)
timeout /t 1 /nobreak >nul 2>&1
goto :wait_stopped

:stopped
echo      Servizio fermato

REM === BACKUP ===
echo [2/4] Backup src/ precedente in %INSTALL_DIR%\_backup_pre_v348\...
if exist "%INSTALL_DIR%\_backup_pre_v348" rmdir /S /Q "%INSTALL_DIR%\_backup_pre_v348" 2>nul
mkdir "%INSTALL_DIR%\_backup_pre_v348" 2>nul
xcopy "%INSTALL_DIR%\src" "%INSTALL_DIR%\_backup_pre_v348\src\" /E /I /Y /Q >nul 2>&1
if exist "%INSTALL_DIR%\version.json" copy /Y "%INSTALL_DIR%\version.json" "%INSTALL_DIR%\_backup_pre_v348\version.json" >nul 2>&1
echo      Backup completato

REM === COPIA FILE NUOVI ===
echo [3/4] Copia file nuovi da %EXTRACT_DIR%\prg\*
xcopy "%EXTRACT_DIR%\prg\*" "%INSTALL_DIR%\" /E /I /Y /Q >nul 2>&1
if errorlevel 1 (
    echo      ERRORE: xcopy fallito! Ripristino backup...
    xcopy "%INSTALL_DIR%\_backup_pre_v348\src\*" "%INSTALL_DIR%\src\" /E /I /Y /Q >nul 2>&1
    net start 86NocConnectorService >nul 2>&1
    echo      Rollback completato. Controlla i permessi di %INSTALL_DIR%
    pause
    exit /b 4
)
echo      File copiati

REM === START SERVIZIO ===
echo [4/4] Start servizio 86NocConnectorService...
net start 86NocConnectorService >nul 2>&1
if errorlevel 1 (
    sc.exe start 86NocConnectorService >nul 2>&1
)

set /a count=0
:wait_running
sc.exe query 86NocConnectorService 2>nul | find "RUNNING" >nul 2>&1
if %errorlevel% equ 0 goto :running
set /a count+=1
if %count% geq 30 (
    echo      ERRORE: servizio non in RUNNING dopo 30s
    echo      Controlla Eventi di Windows per errori del servizio
    pause
    exit /b 5
)
timeout /t 1 /nobreak >nul 2>&1
goto :wait_running

:running
echo      Servizio RUNNING
echo.
echo ==========================================================================
echo   AGGIORNAMENTO COMPLETATO - Connector ora e' a v3.4.8
echo   Dai prossimi aggiornamenti automatici (viaa ARGUS NOC)
echo   verra' usato il nuovo updater.cmd ASR-safe.
echo ==========================================================================
echo.
pause
exit /b 0
