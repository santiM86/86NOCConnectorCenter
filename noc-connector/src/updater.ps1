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
Send-Progress 50 "stopping" "Arresto processi in corso..."

# ===== STEP 1: Kill ALL 86NocConnector processes =====
Write-UpdateLog "STEP 1: Arresto processi..."
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

# ===== STEP 4: Restart application =====
Write-UpdateLog "STEP 4: Riavvio applicazione..."
Send-Progress 95 "restarting" "Riavvio 86NocConnector..."

$batPath = Join-Path $InstallDir "86NocConnector.bat"
if (Test-Path $batPath) {
    Start-Process "cmd.exe" -ArgumentList "/c `"$batPath`"" -WindowStyle Hidden
    Write-UpdateLog "Applicazione riavviata da: $batPath"
} else {
    Write-UpdateLog "ERRORE: $batPath non trovato!"
    Send-Progress 0 "error" "Errore: file BAT non trovato"
    exit 1
}

Start-Sleep -Seconds 3
Send-Progress 100 "completed" "Aggiornamento completato!"
Write-UpdateLog "=== AGGIORNAMENTO COMPLETATO ==="
