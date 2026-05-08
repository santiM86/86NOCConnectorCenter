' 86NocAgent - Wizard launcher (no PowerShell console)
' Lancia installer_gui.ps1 con esecuzione policy bypass + finestra nascosta.
' L'auto-elevation UAC e' gestita dallo script PowerShell stesso.
Dim shell, scriptDir, ps1Path
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
ps1Path = scriptDir & "\installer_gui.ps1"
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """", 0, False
