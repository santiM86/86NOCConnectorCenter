@echo off
REM ============================================================================
REM   ARGUS Connector - Installer (doppio click per partire)
REM   86BIT srl
REM ============================================================================
REM   Questo batch lancia automaticamente il wizard PowerShell di installazione
REM   con auto-elevazione UAC.
REM ============================================================================

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-ArgusConnector.ps1"
