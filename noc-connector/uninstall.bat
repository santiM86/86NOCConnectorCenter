@echo off
title 86NocConnector - Disinstallazione
echo ============================================================
echo   86NocConnector - Disinstallazione
echo ============================================================
echo.

echo [1/7] Arresto Servizio Windows e processi...
if exist "%~dp0nssm.exe" (
    "%~dp0nssm.exe" stop 86NocConnectorService >nul 2>&1
    "%~dp0nssm.exe" remove 86NocConnectorService confirm >nul 2>&1
    echo   Servizio NSSM rimosso.
)
schtasks /end /tn "86NocConnectorService" >nul 2>&1
schtasks /delete /tn "86NocConnectorService" /f >nul 2>&1
echo   Scheduled Task rimosso.
taskkill /f /fi "WINDOWTITLE eq 86NocConnector*" >nul 2>&1
powershell -Command "Get-Process powershell | Where-Object {$_.MainWindowTitle -like '*86Noc*' -or $_.CommandLine -like '*tray_app*' -or $_.CommandLine -like '*connector*'} | Stop-Process -Force" 2>nul

echo [2/7] Rimozione regole firewall...
netsh advfirewall firewall delete rule name="86NocConnector SNMP" >nul 2>&1
netsh advfirewall firewall delete rule name="86NocConnector Syslog" >nul 2>&1

echo [3/7] Rimozione avvio automatico (registro, se presente)...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "86NocConnector" /f >nul 2>&1

echo [4/7] Rimozione collegamento Menu Start...
set "STARTMENU=%ProgramData%\Microsoft\Windows\Start Menu\Programs\86BIT Connector"
if exist "%STARTMENU%" (
    rmdir /s /q "%STARTMENU%"
    echo   Menu Start (86BIT Connector) rimosso.
)
set "STARTMENU_OLD=%ProgramData%\Microsoft\Windows\Start Menu\Programs\86NocConnector"
if exist "%STARTMENU_OLD%" (
    rmdir /s /q "%STARTMENU_OLD%"
    echo   Menu Start (vecchio) rimosso.
)

echo [5/7] Rimozione da Programmi e Funzionalita'...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector" /f >nul 2>&1

echo [6/7] Rimozione status file...
if exist "%ProgramData%\86NocConnector\status.json" (
    del /q "%ProgramData%\86NocConnector\status.json" >nul 2>&1
)

echo [7/7] Rimozione configurazione...
if exist "%ProgramData%\86NocConnector" (
    rmdir /s /q "%ProgramData%\86NocConnector"
    echo   Configurazione rimossa.
)

echo.
echo ============================================================
echo   86NocConnector disinstallato con successo!
echo   Puoi eliminare questa cartella manualmente.
echo ============================================================
echo.
pause
