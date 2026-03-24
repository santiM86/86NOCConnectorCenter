@echo off
REM Kill existing 86NocConnector processes before starting fresh
for /f "tokens=2" %%a in ('tasklist /fi "WINDOWTITLE eq 86NocConnector*" /fo list ^| findstr PID') do taskkill /PID %%a /F >nul 2>&1
powershell -ExecutionPolicy Bypass -Command "Get-Process -Name powershell -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match '86Noc' -or ($_.CommandLine -and $_.CommandLine -match 'tray_app|connector') } | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
start "" powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0src\tray_app.ps1"
