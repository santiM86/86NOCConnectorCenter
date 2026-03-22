@echo off
title 86NocConnector - Installazione
start "" /min powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0src\installer_gui.ps1"
exit
