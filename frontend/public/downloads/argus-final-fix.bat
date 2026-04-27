@echo off
SET "URL=https://noc-monitor-hub.preview.emergentagent.com/downloads/argus-final-fix.ps1"
SET "DST=%TEMP%\argus-final-fix.ps1"

echo Scarico script Final-Fix...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%URL%', '%DST%')"

if not exist "%DST%" (
    echo ERRORE download.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -ArgumentList '-NoProfile','-NoExit','-ExecutionPolicy','Bypass','-File','%DST%' -Verb RunAs"

exit /b 0
