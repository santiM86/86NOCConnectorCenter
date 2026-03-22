@echo off
start "" powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0src\tray_app.ps1"
