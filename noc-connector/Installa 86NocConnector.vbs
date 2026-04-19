' ============================================================
' 86NocConnector - Wizard di Installazione
' ============================================================
' Questo file lancia il wizard di installazione grafico.
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

' Lancia il wizard PowerShell (self-elevating se serve admin)
CreateObject("WScript.Shell").Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1File & """", 0, False
