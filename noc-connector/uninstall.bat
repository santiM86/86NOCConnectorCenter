@echo off
title 86NocConnector - Disinstallazione
echo ============================================================
echo   86NocConnector - Disinstallazione
echo ============================================================
echo.

echo [1/4] Arresto processi...
taskkill /f /fi "WINDOWTITLE eq 86NocConnector*" >nul 2>&1
powershell -Command "Get-Process powershell | Where-Object {$_.MainWindowTitle -like '*86Noc*' -or $_.CommandLine -like '*tray_app*' -or $_.CommandLine -like '*connector*'} | Stop-Process -Force" 2>nul

echo [2/4] Rimozione regole firewall...
netsh advfirewall firewall delete rule name="86NocConnector SNMP" >nul 2>&1
netsh advfirewall firewall delete rule name="86NocConnector Syslog" >nul 2>&1

echo [3/5] Rimozione avvio automatico...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "86NocConnector" /f >nul 2>&1

echo [4/5] Rimozione da Programmi e Funzionalita'...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector" /f >nul 2>&1

echo [5/5] Rimozione configurazione...
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
