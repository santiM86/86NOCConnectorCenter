@echo off
REM Lanciatore con doppio click - apre lo script PS1 con bypass policy
SET "URL=https://snmp-hub-noc.preview.emergentagent.com/downloads/argus-diag.ps1"
SET "DST=%TEMP%\argus-diag.ps1"

echo Scaricando lo script di diagnostica...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%URL%', '%DST%')"

if not exist "%DST%" (
    echo ERRORE: download fallito.
    pause
    exit /b 1
)

echo Lancio diagnostica con privilegi admin...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%DST%' -Verb RunAs"

exit /b 0
