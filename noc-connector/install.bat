@echo off
REM =====================================================
REM   86NocConnector v3.0.0 - Installazione Rapida
REM   86BIT srl - ARGUS Center
REM =====================================================
echo.
echo   86NocConnector v3.0.0
echo   Installazione in corso...
echo.

REM Controlla se eseguito come Amministratore
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRORE] Esegui come Amministratore!
    echo Clicca col tasto destro e scegli "Esegui come amministratore"
    pause
    exit /b 1
)

REM Crea cartella di installazione
set INSTALL_DIR=C:\86NocConnector
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%INSTALL_DIR%\src" mkdir "%INSTALL_DIR%\src"
if not exist "%INSTALL_DIR%\logs" mkdir "%INSTALL_DIR%\logs"

REM Copia file
echo Copia file...
copy /Y "src\connector.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "src\snmp_poller.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "src\backup_monitor.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "src\diagnostica.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "src\service_wrapper.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "src\updater.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "src\tray_app.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "src\installer_gui.ps1" "%INSTALL_DIR%\src\" >nul
copy /Y "version.json" "%INSTALL_DIR%\" >nul
if exist "src\86bit_logo.jpg" copy /Y "src\86bit_logo.jpg" "%INSTALL_DIR%\src\" >nul

REM Controlla se config esiste gia
if not exist "%INSTALL_DIR%\config.json" (
    echo.
    echo =============================================
    echo  PRIMA INSTALLAZIONE - Configurazione
    echo =============================================
    echo.
    set /p NOC_URL="URL ARGUS Center (es: https://argus.86bit.it): "
    set /p API_KEY="API Key del cliente: "
    echo.
    echo Creazione config.json...
    (
        echo {
        echo   "noc_center_url": "%NOC_URL%",
        echo   "api_key": "%API_KEY%",
        echo   "snmp_trap_port": 162,
        echo   "syslog_port": 514,
        echo   "poll_interval_seconds": 60,
        echo   "heartbeat_interval_seconds": 60
        echo }
    ) > "%INSTALL_DIR%\config.json"
    echo Config creato: %INSTALL_DIR%\config.json
) else (
    echo Config esistente trovato, non sovrascritto.
)

REM Crea Scheduled Task (SYSTEM, avvio automatico)
echo.
echo Creazione servizio Windows (Scheduled Task)...
schtasks /Create /TN "86NocConnector" /TR "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%INSTALL_DIR%\src\connector.ps1\"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F >nul 2>&1

if %errorLevel% equ 0 (
    echo [OK] Scheduled Task creato con successo
) else (
    echo [WARN] Errore creazione task, potrebbe gia' esistere
)

REM Avvia il connettore
echo.
echo Avvio connettore...
schtasks /Run /TN "86NocConnector" >nul 2>&1

echo.
echo =============================================
echo   INSTALLAZIONE COMPLETATA!
echo =============================================
echo.
echo   Cartella: %INSTALL_DIR%
echo   Log:      %INSTALL_DIR%\logs\
echo   Config:   %INSTALL_DIR%\config.json
echo.
echo   Il connettore e' in esecuzione come servizio SYSTEM.
echo   Si avvia automaticamente al boot del PC.
echo.
pause
