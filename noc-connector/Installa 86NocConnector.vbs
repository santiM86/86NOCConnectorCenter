' ============================================================
' 86NocConnector - Wizard di Installazione
' ============================================================
' Questo file lancia il wizard di installazione grafico con
' ELEVATION AMMINISTRATIVA OBBLIGATORIA (UAC prompt).
'
' Tutti gli altri file del connettore sono nella sottocartella "prg\".
' NON SPOSTARE ne' RINOMINARE questo file.
' ============================================================

Set fso = CreateObject("Scripting.FileSystemObject")
myDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1File = myDir & "\prg\src\installer_gui.ps1"

If Not fso.FileExists(ps1File) Then
    MsgBox "File del wizard non trovato:" & vbCrLf & vbCrLf & ps1File & vbCrLf & vbCrLf & _
           "Assicurati di aver estratto TUTTI i file dallo zip mantenendo la struttura delle cartelle.", _
           vbCritical, "86NocConnector - Errore"
    WScript.Quit 1
End If

' ================================================================
' ELEVATION VIA SHELLEXECUTE "runas" (UAC prompt obbligatorio)
' ================================================================
' Necessario per:
'   - Copia file in C:\Program Files\86NocConnector (richiede admin)
'   - Creazione shortcut in C:\ProgramData\Microsoft\...\Start Menu (admin)
'   - schtasks /Create /RU SYSTEM (admin)
'   - reg add HKLM\Software\... (admin)
'   - Registrazione servizio NSSM (admin)
'
' Se l'utente non accetta UAC il setup termina senza partire.
' ================================================================

' Argomenti passati a PowerShell
psArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1File & """"

' ShellExecute con verb "runas" forza UAC elevation prompt
' ShellExecute(lpFile, lpParameters, lpDirectory, lpVerb, nShow)
Set shellApp = CreateObject("Shell.Application")
shellApp.ShellExecute "powershell.exe", psArgs, myDir, "runas", 0
