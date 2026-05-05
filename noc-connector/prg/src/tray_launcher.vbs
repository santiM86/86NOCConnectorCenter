' =============================================================================
' tray_launcher.vbs - ARGUS Connector Tray App Launcher (hidden)
' =============================================================================
' Avvia tray_app.ps1 in modalita' completamente nascosta, SENZA finestra
' PowerShell visibile in taskbar. Il processo PowerShell diventa detached:
' chiudendo la taskbar o facendo logout non kilta il connector.
'
' Questo VBS e' quello che deve essere lanciato dal menu Start / Autostart,
' NON powershell.exe direttamente.
' =============================================================================

Option Explicit

Dim objFS, objShell, scriptDir, psScript, cmd
Set objFS = CreateObject("Scripting.FileSystemObject")
Set objShell = CreateObject("WScript.Shell")

' Directory dello script (cartella src/ del connector)
scriptDir = objFS.GetParentFolderName(WScript.ScriptFullName)
psScript = objFS.BuildPath(scriptDir, "tray_app.ps1")

If Not objFS.FileExists(psScript) Then
    MsgBox "tray_app.ps1 non trovato in " & scriptDir, 16, "ARGUS Connector"
    WScript.Quit 1
End If

' Costruisci comando PowerShell con tutti i flag per massima invisibilita':
'   -NoProfile           : non caricare $PROFILE
'   -NoLogo              : no banner
'   -NonInteractive      : no prompt
'   -ExecutionPolicy Bypass : non richiedere conferma script non firmati
'   -WindowStyle Hidden  : nessuna finestra console
'   -File ...            : esegue lo script
cmd = "powershell.exe -NoProfile -NoLogo -NonInteractive " & _
      "-ExecutionPolicy Bypass -WindowStyle Hidden " & _
      "-File """ & psScript & """"

' objShell.Run(cmd, windowStyle, waitForReturn)
'   windowStyle = 0 : finestra nascosta
'   waitForReturn = False : non aspettare (detached)
objShell.Run cmd, 0, False
