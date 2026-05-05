@echo off
REM =============================================================================
REM 86NocConnector.bat - Launcher ARGUS Connector (v3.7.6+)
REM Usa wscript + tray_launcher.vbs per avviare il tray app SENZA finestra
REM PowerShell visibile (niente DOS box che flashano al boot / apertura shortcut)
REM =============================================================================
start "" wscript.exe "%~dp0src\tray_launcher.vbs"
