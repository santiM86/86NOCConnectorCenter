@echo off
REM ============================================================
REM 86NocAgent v4 - Wizard installazione (avvio nascosto)
REM ============================================================
REM Lancia il wizard PowerShell senza mostrare ne' la console
REM nera del .bat (chiusa subito) ne' la finestra blu di PS
REM (lanciata in -WindowStyle Hidden). Il wizard grafico viene
REM mostrato solo dopo la conferma UAC.
REM
REM Tasto destro -> "Esegui come amministratore" oppure semplice
REM doppio-click (la auto-elevazione e' integrata nello script).
REM ============================================================
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0installer_gui.ps1"
exit /b
