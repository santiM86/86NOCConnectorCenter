@echo off
SET "URL=https://noc-monitor-hub.preview.emergentagent.com/downloads/argus-regen-key.ps1"
SET "DST=%TEMP%\argus-regen-key.ps1"

echo Scaricando lo script di rigenerazione API Key...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%URL%', '%DST%')"

if not exist "%DST%" (
    echo ERRORE: download fallito.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%DST%' -Verb RunAs"

exit /b 0
