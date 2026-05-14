@echo off
SET "URL=https://device-monitor-94.preview.emergentagent.com/downloads/argus-firewall-test.ps1"
SET "DST=%TEMP%\argus-firewall-test.ps1"

echo Scarico script Firewall-Test...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%URL%', '%DST%')"

if not exist "%DST%" (
    echo ERRORE download.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -ArgumentList '-NoProfile','-NoExit','-ExecutionPolicy','Bypass','-File','%DST%' -Verb RunAs"

exit /b 0
