@echo off
REM =====================================================
REM   86BIT ARGUS Center Connector - Disinstallazione
REM   Rimozione COMPLETA senza lasciare tracce
REM =====================================================
echo.
echo   86BIT ARGUS Center Connector
echo   Disinstallazione in corso...
echo.

REM Controlla Amministratore
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRORE] Esegui come Amministratore!
    pause
    exit /b 1
)

echo === STEP 1: Arresto servizi ===

REM Ferma il servizio NSSM
echo Arresto servizio NSSM...
nssm.exe stop 86NocConnectorService >nul 2>&1
if exist "C:\86NocConnector\nssm.exe" (
    "C:\86NocConnector\nssm.exe" stop 86NocConnectorService >nul 2>&1
    "C:\86NocConnector\nssm.exe" remove 86NocConnectorService confirm >nul 2>&1
)
nssm.exe remove 86NocConnectorService confirm >nul 2>&1

REM Ferma Scheduled Task se esiste
schtasks /End /TN "86NocConnector" >nul 2>&1
schtasks /Delete /TN "86NocConnector" /F >nul 2>&1
REM Rimuovi Scheduled Task v3.5.0+ Microsoft-native auto-update
schtasks /End /TN "\86BIT\ArgusConnectorUpdater" >nul 2>&1
schtasks /Delete /TN "\86BIT\ArgusConnectorUpdater" /F >nul 2>&1
REM Rimuovi anche il folder task parent se vuoto
schtasks /Delete /TN "\86BIT" /F >nul 2>&1

REM Termina processi PowerShell del connettore
echo Terminazione processi connettore...
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%connector.ps1%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /PID %%i /F >nul 2>&1
)
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%tray_app.ps1%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /PID %%i /F >nul 2>&1
)
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%snmp_poller.ps1%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /PID %%i /F >nul 2>&1
)
echo [OK] Servizi e processi fermati

echo === STEP 2: Rimozione dal Menu Start ===
REM Rimuovi cartella Menu Start (tutti i nomi possibili)
if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs\86BIT ArgusCenter" (
    rmdir /s /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\86BIT ArgusCenter" >nul 2>&1
    echo [OK] Cartella Menu Start "86BIT ArgusCenter" rimossa
)
if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs\86BIT Connector" (
    rmdir /s /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\86BIT Connector" >nul 2>&1
    echo [OK] Cartella Menu Start "86BIT Connector" rimossa
)
if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs\86NocConnector" (
    rmdir /s /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\86NocConnector" >nul 2>&1
    echo [OK] Cartella Menu Start "86NocConnector" rimossa
)

echo === STEP 3: Rimozione dal Registro (Programmi e Funzionalita) ===
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86BIT_ArgusCenter_Connector" /f /reg:64 >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86BIT_ArgusCenter_Connector" /f /reg:32 >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector" /f /reg:64 >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector" /f /reg:32 >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run\86NocConnector" /f >nul 2>&1
echo [OK] Chiavi di registro rimosse

echo === STEP 4: Rimozione file e cartelle ===

REM Rimuovi dati ProgramData
if exist "%ProgramData%\86NocConnector" (
    rmdir /s /q "%ProgramData%\86NocConnector" >nul 2>&1
    echo [OK] Dati ProgramData rimossi
)

REM Rimuovi cartella installazione C:\86NocConnector (se diversa da quella corrente)
set CURRENT_DIR=%~dp0
set INSTALL_DIR=C:\86NocConnector

REM Se eseguito dalla cartella di installazione, non eliminarla ora
echo [OK] File di programma rimossi

echo === STEP 5: Rimozione servizio Windows ===
sc delete 86NocConnectorService >nul 2>&1
echo [OK] Servizio Windows rimosso

echo.
echo =============================================
echo   DISINSTALLAZIONE COMPLETATA!
echo =============================================
echo.
echo   Rimosso:
echo   - Servizio Windows (NSSM)
echo   - Scheduled Task
echo   - Menu Start (86BIT ArgusCenter)
echo   - Programmi e Funzionalita (registro)
echo   - Processi in esecuzione
echo   - Dati in ProgramData
echo.
echo   La cartella "%INSTALL_DIR%" puo' essere
echo   eliminata manualmente se non serve piu'.
echo.

REM Pulizia cartella di installazione (ritardata per permettere al bat di finire)
echo Pulizia finale cartella installazione...
if "%CURRENT_DIR:~0,-1%"=="%INSTALL_DIR%" (
    REM Siamo dentro la cartella di installazione, usa pulizia ritardata
    start /b cmd /c "timeout /t 3 /nobreak >nul & rmdir /s /q "%INSTALL_DIR%" 2>nul"
    echo [OK] Pulizia cartella programmata (3 secondi)
) else (
    if exist "%INSTALL_DIR%" (
        rmdir /s /q "%INSTALL_DIR%" >nul 2>&1
        echo [OK] Cartella installazione rimossa
    )
)

echo.
pause
