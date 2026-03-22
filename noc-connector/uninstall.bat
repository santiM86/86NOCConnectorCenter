@echo off
title 86NocConnector - Disinstallazione
echo ============================================================
echo   86NocConnector - Disinstallazione
echo ============================================================
echo.

set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python\python.exe"

:: Stop service
echo [1/4] Arresto servizio...
sc stop 86NocConnector >nul 2>&1
sc delete 86NocConnector >nul 2>&1

:: Kill tray app
echo [2/4] Chiusura applicazione tray...
taskkill /f /im python.exe /fi "WINDOWTITLE eq 86NocConnector*" >nul 2>&1

:: Remove firewall rules
echo [3/4] Rimozione regole firewall...
netsh advfirewall firewall delete rule name="86NocConnector SNMP" >nul 2>&1
netsh advfirewall firewall delete rule name="86NocConnector Syslog" >nul 2>&1

:: Remove startup entry
echo [4/4] Rimozione avvio automatico...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "86NocConnector" /f >nul 2>&1

echo.
echo ============================================================
echo   86NocConnector disinstallato con successo!
echo   Puoi eliminare questa cartella manualmente.
echo ============================================================
echo.
pause
