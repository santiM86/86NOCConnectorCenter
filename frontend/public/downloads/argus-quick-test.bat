@echo off
SET "URL=https://noc-monitor-hub.preview.emergentagent.com/downloads/argus-quick-test.ps1"
SET "DST=%TEMP%\argus-quick-test.ps1"

echo Scarico script Quick-Test...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%URL%', '%DST%')"

if not exist "%DST%" (
    echo ERRORE: download fallito.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%DST%' -Verb RunAs"

exit /b 0
