@echo off
REM ============================================================================
REM 86NocConnector Updater — CMD-based (ASR-safe)
REM ============================================================================
REM Sostituisce updater.ps1 per evitare che Defender ASR uccida PowerShell.
REM Usa SOLO comandi nativi Windows: net stop/start, xcopy, del, rmdir.
REM
REM PARAMETRI (piazzati come variabili d'ambiente dal caller):
REM   ARGUS_EXTRACT_PATH    — Path dove il ZIP e' stato estratto (es: %TEMP%\86NocConnector_update)
REM   ARGUS_INSTALL_DIR     — Path installazione (es: C:\Program Files\86NocConnector)
REM   ARGUS_API_URL         — URL backend ARGUS (opzionale, per progress report)
REM   ARGUS_API_KEY         — API key connector (opzionale, per progress report)
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

set "LOG_DIR=%ProgramData%\86NocConnector"
set "LOG_FILE=%LOG_DIR%\updater_cmd.log"
set "FLAG_FILE=%LOG_DIR%\updater_started.flag"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul

REM === Breadcrumb immediato (se ASR killa, almeno sappiamo che e' partito)
echo started PID=%^PID% > "%FLAG_FILE%" 2>nul

call :log "==============================================="
call :log "INIZIO AGGIORNAMENTO (cmd-based updater)"
call :log "ExtractPath: %ARGUS_EXTRACT_PATH%"
call :log "InstallDir:  %ARGUS_INSTALL_DIR%"
call :log "==============================================="

if not defined ARGUS_EXTRACT_PATH (
    call :log "ERROR: ARGUS_EXTRACT_PATH non definito"
    exit /b 1
)
if not defined ARGUS_INSTALL_DIR (
    call :log "ERROR: ARGUS_INSTALL_DIR non definito"
    exit /b 1
)
if not exist "%ARGUS_EXTRACT_PATH%\prg" (
    call :log "ERROR: Cartella estratta non valida (%ARGUS_EXTRACT_PATH%\prg non esiste)"
    exit /b 1
)

REM === STOP SERVIZIO ============================================================
call :log "Stop servizio 86NocConnectorService..."
net stop 86NocConnectorService >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log "net stop fallito, provo sc.exe stop..."
    sc.exe stop 86NocConnectorService >>"%LOG_FILE%" 2>&1
)

REM Attendi fino a 20s per vedere lo stato stopped
set /a count=0
:wait_stopped
sc.exe query 86NocConnectorService | find "STOPPED" >nul 2>&1
if !errorlevel! equ 0 goto :stopped
set /a count+=1
if !count! geq 20 (
    call :log "ATTENZIONE: servizio non fermo dopo 20s, continuo comunque"
    goto :stopped
)
ping -n 2 127.0.0.1 >nul
goto :wait_stopped

:stopped
call :log "Servizio fermato (o timeout)"

REM === BACKUP SRC CORRENTE ======================================================
set "BACKUP_DIR=%ARGUS_INSTALL_DIR%\_backup_prev"
if exist "%BACKUP_DIR%" rmdir /S /Q "%BACKUP_DIR%" 2>nul
mkdir "%BACKUP_DIR%" 2>nul
call :log "Backup src/ in %BACKUP_DIR%\src\..."
xcopy "%ARGUS_INSTALL_DIR%\src" "%BACKUP_DIR%\src\" /E /I /Y /Q >>"%LOG_FILE%" 2>&1
if exist "%ARGUS_INSTALL_DIR%\version.json" (
    copy /Y "%ARGUS_INSTALL_DIR%\version.json" "%BACKUP_DIR%\version.json" >>"%LOG_FILE%" 2>&1
)

REM === COPIA NUOVI FILE =========================================================
call :log "Copia nuovi file da %ARGUS_EXTRACT_PATH%\prg\..."
xcopy "%ARGUS_EXTRACT_PATH%\prg\*" "%ARGUS_INSTALL_DIR%\" /E /I /Y /Q >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log "ERROR: xcopy fallito. Ripristino backup..."
    xcopy "%BACKUP_DIR%\src\*" "%ARGUS_INSTALL_DIR%\src\" /E /I /Y /Q >>"%LOG_FILE%" 2>&1
    call :start_service
    exit /b 2
)
call :log "File copiati con successo"

REM === START SERVIZIO ===========================================================
:start_service
call :log "Start servizio 86NocConnectorService..."
net start 86NocConnectorService >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log "net start fallito, provo sc.exe start..."
    sc.exe start 86NocConnectorService >>"%LOG_FILE%" 2>&1
)

REM Attendi fino a 30s per vedere lo stato running
set /a count=0
:wait_running
sc.exe query 86NocConnectorService | find "RUNNING" >nul 2>&1
if !errorlevel! equ 0 goto :running
set /a count+=1
if !count! geq 30 (
    call :log "ERROR: servizio non in RUNNING dopo 30s"
    exit /b 3
)
ping -n 2 127.0.0.1 >nul
goto :wait_running

:running
call :log "Servizio RUNNING"

REM === CLEANUP ==================================================================
call :log "Cleanup directory temp/staging..."
if exist "%ARGUS_EXTRACT_PATH%" rmdir /S /Q "%ARGUS_EXTRACT_PATH%" 2>nul
if exist "%ARGUS_INSTALL_DIR%\_update_staging" rmdir /S /Q "%ARGUS_INSTALL_DIR%\_update_staging" 2>nul

call :log "=== AGGIORNAMENTO COMPLETATO CON SUCCESSO ==="
exit /b 0

REM === FUNZIONI ================================================================
:log
set "TS=%date% %time%"
echo [%TS%] %~1 >> "%LOG_FILE%" 2>nul
echo [%TS%] %~1
goto :eof
