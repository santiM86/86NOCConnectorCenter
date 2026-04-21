<#
.SYNOPSIS
    86NocConnector Updater - Gestisce il flusso completo di aggiornamento
.DESCRIPTION
    1. Spegne tutti i processi 86NocConnector (tray + connector)
    2. Copia i nuovi file
    3. Riavvia l'applicazione aggiornata
    Viene lanciato come processo indipendente dal connector.
#>
param(
    [Parameter(Mandatory=$true)][string]$ExtractPath,
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [string]$ApiUrl = "",
    [string]$ApiKey = ""
)

function Write-UpdateLog($msg) {
    $logDir = Join-Path $env:ProgramData "86NocConnector"
    if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
    $logFile = Join-Path $logDir "updater.log"
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content $logFile "[$ts] $msg"
}

function Send-Progress($progress, $status, $message) {
    if (-not $ApiUrl -or -not $ApiKey) { return }
    try {
        $headers = @{ "X-API-Key" = $ApiKey; "Content-Type" = "application/json" }
        $body = @{ progress = $progress; status = $status; message = $message } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri "$ApiUrl/api/connector/update-progress" -Method Post -Headers $headers -Body $body -TimeoutSec 5 -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}

Write-UpdateLog "=== INIZIO AGGIORNAMENTO ==="
Write-UpdateLog "ExtractPath: $ExtractPath"
Write-UpdateLog "InstallDir: $InstallDir"
Write-UpdateLog "PID updater: $PID"
# Diagnostic: chi e' il mio parent?
try {
    $myProc = Get-CimInstance Win32_Process -Filter "ProcessId = $PID"
    $parentPid = $myProc.ParentProcessId
    $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId = $parentPid" -ErrorAction SilentlyContinue
    Write-UpdateLog "Parent PID: $parentPid ($($parentProc.Name) - $($parentProc.CommandLine))"
} catch {}
Send-Progress 50 "stopping" "Arresto servizio Windows..."

# ===== STEP 1a: Stop Windows Service (se presente) =====
# Evita race condition: NSSM riavvierebbe connector.ps1 vecchio in RAM mentre updater copia i file.
# Il servizio reale installato da installa_servizio.bat si chiama "86NocConnectorService".
# Controlliamo entrambi i nomi per retrocompatibilità con installazioni custom.
$possibleServiceNames = @("86NocConnectorService", "86NocConnector")
$serviceName = $null
$svcWasRunning = $false

foreach ($name in $possibleServiceNames) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($svc) {
        $serviceName = $name
        $svcWasRunning = ($svc.Status -eq "Running")
        Write-UpdateLog "Trovato servizio: $name (Status: $($svc.Status))"
        break
    }
}

if ($serviceName) {
    try {
        Write-UpdateLog "Stop servizio Windows '$serviceName'..."
        Stop-Service -Name $serviceName -Force -ErrorAction Stop
        # Wait up to 15s for full stop (NSSM ha throttle di 30s, ma il process muore prima)
        $svc = Get-Service -Name $serviceName
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 1
            $svc.Refresh()
            if ($svc.Status -eq "Stopped") { break }
        }
        Write-UpdateLog "Servizio fermato (Status finale: $($svc.Status)) dopo $i secondi"
        if ($svc.Status -ne "Stopped") {
            Write-UpdateLog "ATTENZIONE: servizio non in stato Stopped, provo con sc.exe"
            & sc.exe stop $serviceName | Out-Null
            Start-Sleep -Seconds 3
        }
    } catch {
        Write-UpdateLog "ATTENZIONE: Stop-Service fallito: $($_.Exception.Message) — provo con sc.exe"
        & sc.exe stop $serviceName 2>&1 | Out-String | ForEach-Object { Write-UpdateLog "  sc.exe: $_" }
        Start-Sleep -Seconds 5
    }
} else {
    Write-UpdateLog "Nessun servizio Windows trovato — modalità standalone"
}

# ===== STEP 1b: Kill ALL 86NocConnector processes (belt + suspenders) =====
Write-UpdateLog "STEP 1b: Arresto processi residui..."
$currentPid = $PID

# Kill by command line match
Get-Process -Name powershell, pwsh -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Id -ne $currentPid) {
        try {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmdLine -match "tray_app\.ps1|connector\.ps1|86NocConnector") {
                Write-UpdateLog "  Killing PID $($_.Id): $cmdLine"
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
        } catch {}
    }
}

# Wait for processes to fully terminate
Write-UpdateLog "Attesa chiusura processi..."
Start-Sleep -Seconds 4

# Refresh Windows tray to clear ghost icons
Write-UpdateLog "Pulizia icone fantasma dalla tray..."
try {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class TrayClean {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string w);
    [DllImport("user32.dll")] public static extern IntPtr FindWindowEx(IntPtr p, IntPtr a, string c, string w);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    public static void Clean() {
        var t = FindWindow("Shell_TrayWnd", null);
        var n = FindWindowEx(t, IntPtr.Zero, "TrayNotifyWnd", null);
        var p = FindWindowEx(n, IntPtr.Zero, "SysPager", null);
        var b = FindWindowEx(p, IntPtr.Zero, "ToolbarWindow32", null);
        if (b == IntPtr.Zero) b = FindWindowEx(n, IntPtr.Zero, "ToolbarWindow32", null);
        if (b != IntPtr.Zero) { RECT r; GetClientRect(b, out r);
            for (int x=0;x<r.R;x+=10) for (int y=0;y<r.B;y+=10)
                SendMessage(b, 0x0200, IntPtr.Zero, (IntPtr)((y<<16)|x));
        }
    }
}
"@
    [TrayClean]::Clean()
    Write-UpdateLog "Icone fantasma rimosse"
} catch {
    Write-UpdateLog "Nota: pulizia tray non riuscita (non critico)"
}

Send-Progress 60 "installing" "Installazione file aggiornati..."

# ===== STEP 2: Copy new files =====
Write-UpdateLog "STEP 2: Copia nuovi file..."

$srcDir = Join-Path $ExtractPath "src"
$extractedRoot = $ExtractPath

# Handle both flat and nested ZIP
if (-not (Test-Path $srcDir)) {
    $subDir = Get-ChildItem $ExtractPath -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($subDir) {
        $extractedRoot = $subDir.FullName
        $srcDir = Join-Path $extractedRoot "src"
    }
}

if (-not (Test-Path $srcDir)) {
    Write-UpdateLog "ERRORE: cartella src non trovata in $ExtractPath"
    Send-Progress 0 "error" "Errore: cartella src non trovata"
    exit 1
}

$installSrc = Join-Path $InstallDir "src"

# Backup
$backupDir = Join-Path $env:TEMP "86NocConnector_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
try {
    Copy-Item $installSrc $backupDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-UpdateLog "  Backup creato: $backupDir"
} catch {}

Send-Progress 70 "installing" "Copia file src..."

# Copy src files
Get-ChildItem $srcDir -File | ForEach-Object {
    $dest = Join-Path $installSrc $_.Name
    Copy-Item $_.FullName $dest -Force
    Write-UpdateLog "  Aggiornato: src\$($_.Name)"
}

Send-Progress 80 "installing" "Copia file radice..."

# Copy root files (version.json, bat, etc)
Get-ChildItem $extractedRoot -File | ForEach-Object {
    $dest = Join-Path $InstallDir $_.Name
    Copy-Item $_.FullName $dest -Force
    Write-UpdateLog "  Aggiornato: $($_.Name)"
}

Send-Progress 90 "finalizing" "Pulizia e riavvio..."

# ===== STEP 3: Cleanup temp files =====
Write-UpdateLog "STEP 3: Pulizia..."
$parentZip = Join-Path $env:TEMP "86NocConnector_update.zip"
Remove-Item $parentZip -Force -ErrorAction SilentlyContinue
Remove-Item $ExtractPath -Recurse -Force -ErrorAction SilentlyContinue

# ===== STEP 4: Restart application (chain of fallbacks) =====
Write-UpdateLog "STEP 4: Riavvio applicazione..."
Send-Progress 95 "restarting" "Riavvio 86NocConnector..."

$restartOk = $false

# Path 1 (preferito): Start-Service (richiede servizio installato)
if ($serviceName) {
    try {
        Write-UpdateLog "Tentativo 1: Start-Service $serviceName..."
        Start-Service -Name $serviceName -ErrorAction Stop
        Start-Sleep -Seconds 3
        $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq "Running") {
            Write-UpdateLog "OK: servizio Windows avviato correttamente"
            $restartOk = $true
        } else {
            Write-UpdateLog "Servizio non Running (Status: $($svc.Status))"
        }
    } catch {
        Write-UpdateLog "Tentativo 1 fallito: $($_.Exception.Message)"
    }
}

# Path 2: sc.exe start (bypassa problemi permessi di Start-Service in alcuni contesti)
if (-not $restartOk -and $serviceName) {
    try {
        Write-UpdateLog "Tentativo 2: sc.exe start $serviceName..."
        & sc.exe start $serviceName 2>&1 | Out-String | ForEach-Object { Write-UpdateLog "  sc.exe: $_" }
        Start-Sleep -Seconds 5
        $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq "Running") {
            Write-UpdateLog "OK: servizio avviato via sc.exe"
            $restartOk = $true
        }
    } catch {
        Write-UpdateLog "Tentativo 2 fallito: $($_.Exception.Message)"
    }
}

# Path 3: fallback BAT (standalone o se i servizi non funzionano)
if (-not $restartOk) {
    $batPath = Join-Path $InstallDir "86NocConnector.bat"
    if (Test-Path $batPath) {
        try {
            Write-UpdateLog "Tentativo 3: Launch via BAT $batPath"
            Start-Process "cmd.exe" -ArgumentList "/c `"$batPath`"" -WindowStyle Hidden -ErrorAction Stop
            Start-Sleep -Seconds 3
            Write-UpdateLog "BAT lanciato"
            $restartOk = $true
        } catch {
            Write-UpdateLog "Tentativo 3 fallito: $($_.Exception.Message)"
        }
    } else {
        Write-UpdateLog "BAT non trovato: $batPath"
    }
}

# Path 4 (ultima spiaggia): direct PowerShell launch
if (-not $restartOk) {
    $newConnector = Join-Path $InstallDir "src\connector.ps1"
    if (Test-Path $newConnector) {
        try {
            Write-UpdateLog "Tentativo 4: Launch diretto PowerShell $newConnector"
            Start-Process "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$newConnector`"" -WindowStyle Hidden
            Start-Sleep -Seconds 3
            $restartOk = $true
            Write-UpdateLog "Connector lanciato direttamente"
        } catch {
            Write-UpdateLog "Tentativo 4 fallito: $($_.Exception.Message)"
        }
    }
}

# Path 5 (garanzia finale): se abbiamo un servizio NSSM con AppExit=Restart e abbiamo fatto Stop,
# forziamo un riavvio del servizio anche se tutto il resto è fallito.
# NSSM con AppExit=Restart RIAVVIA automaticamente se il processo muore; ma Stop-Service dice "stay stopped".
# Se siamo arrivati qui senza successo, il servizio NSSM è in stato Stopped e non riparte da solo.
# Ultimo tentativo: net start (più robusto di Start-Service in alcuni edge case).
if (-not $restartOk -and $serviceName) {
    try {
        Write-UpdateLog "Tentativo 5: net start $serviceName"
        & net.exe start $serviceName 2>&1 | Out-String | ForEach-Object { Write-UpdateLog "  net: $_" }
        Start-Sleep -Seconds 3
        $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq "Running") {
            Write-UpdateLog "OK: servizio avviato via net.exe"
            $restartOk = $true
        }
    } catch {}
}

Start-Sleep -Seconds 3
if ($restartOk) {
    Send-Progress 100 "completed" "Aggiornamento completato!"
    Write-UpdateLog "=== AGGIORNAMENTO COMPLETATO ==="
} else {
    Send-Progress 0 "error" "Aggiornamento installato ma restart fallito — richiede intervento manuale"
    Write-UpdateLog "=== ERRORE: tutti i tentativi di restart sono falliti ==="
    Write-UpdateLog "I nuovi file sono stati copiati correttamente. Avviare il servizio manualmente."
    Write-UpdateLog "Comando: Start-Service 86NocConnectorService"
}

# Cleanup: self-delete staged updater copy + remove schtasks task if present
try {
    $taskName = [Environment]::GetEnvironmentVariable("ARGUS_UPDATE_TASK", "Machine")
    if ($taskName) {
        Write-UpdateLog "Cleanup task scheduler: $taskName"
        & schtasks.exe /Delete /TN $taskName /F 2>&1 | Out-Null
        [Environment]::SetEnvironmentVariable("ARGUS_UPDATE_TASK", $null, "Machine")
    }
} catch {}
# Self-delete staged updater (in TEMP)
try {
    if ($MyInvocation.MyCommand.Path -and $MyInvocation.MyCommand.Path -like "*\Temp\*") {
        $selfPath = $MyInvocation.MyCommand.Path
        # Schedule deletion via cmd so we can exit cleanly
        Start-Process "cmd.exe" -ArgumentList "/c timeout /t 5 /nobreak > nul & del /F /Q `"$selfPath`" > nul 2>&1" -WindowStyle Hidden
    }
} catch {}

# ===== STEP 5: Restart TRAY in user interactive session =====
# Il service gira come LocalSystem e non puo' lanciare processi GUI nella sessione utente.
# Usiamo schtasks /Create con /RU "INTERACTIVE" + trigger ONCE quasi-immediato.
Write-UpdateLog "STEP 5: Tentativo restart tray_app in sessione utente..."
$trayScript = Join-Path $InstallDir "src\tray_app.ps1"
if (Test-Path $trayScript) {
    try {
        $taskName = "86NocConnector_TrayRestart_$(Get-Random)"
        $runTime = (Get-Date).AddSeconds(10).ToString("HH:mm")
        # Crea task "una tantum" che gira come utente interattivo loggato
        & schtasks.exe /Create /TN $taskName /SC ONCE /ST $runTime `
            /TR "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$trayScript`"" `
            /RU "INTERACTIVE" /F 2>&1 | Out-String | ForEach-Object { Write-UpdateLog "  schtasks: $_" }
        # Esegui subito
        & schtasks.exe /Run /TN $taskName 2>&1 | Out-String | ForEach-Object { Write-UpdateLog "  schtasks run: $_" }
        Start-Sleep -Seconds 5
        # Cleanup: rimuovi task subito dopo il lancio
        & schtasks.exe /Delete /TN $taskName /F 2>&1 | Out-Null
        Write-UpdateLog "Tray restart richiesto"
    } catch {
        Write-UpdateLog "Tray restart fallito (non critico): $($_.Exception.Message)"
    }
}
