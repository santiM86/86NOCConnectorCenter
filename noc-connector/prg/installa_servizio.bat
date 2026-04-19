@echo off
:: =============================================================
:: 86NocConnector - Installa come Servizio Windows
:: Esegui come Amministratore
:: =============================================================
echo.
echo ============================================================
echo   86NocConnector - Installazione Servizio Windows
echo ============================================================
echo.

:: Percorso corrente
set "BASE=%~dp0"
set "NSSM=%BASE%nssm.exe"
set "SCRIPT=%BASE%src\connector.ps1"
set "SVC=86NocConnectorService"

:: Verifica NSSM
if not exist "%NSSM%" (
    echo ERRORE: nssm.exe non trovato in %NSSM%
    echo Scarica il pacchetto completo.
    pause
    exit /b 1
)

:: Verifica connector.ps1
if not exist "%SCRIPT%" (
    echo ERRORE: connector.ps1 non trovato in %SCRIPT%
    pause
    exit /b 1
)

echo [1/4] Rimozione servizio precedente (se esiste)...
"%NSSM%" stop %SVC% >nul 2>&1
"%NSSM%" remove %SVC% confirm >nul 2>&1
schtasks /end /tn "%SVC%" >nul 2>&1
schtasks /delete /tn "%SVC%" /f >nul 2>&1
echo   OK

echo [2/4] Registrazione servizio Windows...
"%NSSM%" install %SVC% powershell.exe "-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File \"%SCRIPT%\""
"%NSSM%" set %SVC% AppDirectory "%BASE%src"
"%NSSM%" set %SVC% DisplayName "86NocConnector Service"
"%NSSM%" set %SVC% Description "86NocConnector - Raccolta SNMP/Syslog per NOC Center. Gira come servizio Windows indipendente dalla sessione utente."
"%NSSM%" set %SVC% Start SERVICE_AUTO_START
"%NSSM%" set %SVC% ObjectName LocalSystem
"%NSSM%" set %SVC% AppStdout "%ProgramData%\86NocConnector\logs\service_stdout.log"
"%NSSM%" set %SVC% AppStderr "%ProgramData%\86NocConnector\logs\service_stderr.log"
"%NSSM%" set %SVC% AppRotateFiles 1
"%NSSM%" set %SVC% AppRotateBytes 5242880
"%NSSM%" set %SVC% AppRestartDelay 30000
"%NSSM%" set %SVC% AppThrottle 30000
"%NSSM%" set %SVC% AppExit Default Restart
echo   Servizio registrato!

echo [3/4] Avvio servizio...
"%NSSM%" start %SVC%
timeout /t 5 /nobreak >nul

echo [4/4] Verifica...
"%NSSM%" status %SVC%
echo.

echo ============================================================
echo   FATTO! Il connettore ora gira come Servizio Windows.
echo.
echo   - Sopravvive alla disconnessione RDP
echo   - Si riavvia automaticamente se crasha
echo   - Si avvia all'accensione del server
echo   - Gestibile da: services.msc (nome: 86NocConnector Service)
echo ============================================================
echo.
pause
