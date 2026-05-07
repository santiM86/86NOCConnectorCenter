@echo off
SET "URL=https://snmp-hub-noc.preview.emergentagent.com/downloads/argus-fix.ps1"
SET "DST=%TEMP%\argus-fix.ps1"

echo Scaricando lo script di fix...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%URL%', '%DST%')"

if not exist "%DST%" (
    echo ERRORE: download fallito.
    pause
    exit /b 1
)

echo Lancio fix con privilegi admin...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%DST%' -Verb RunAs"

exit /b 0
