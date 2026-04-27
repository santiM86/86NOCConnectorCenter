# =============================================================================
# ARGUS Logs - estrai gli ultimi log per diagnosi crash
# =============================================================================
# Doppio click. Salva i log filtrati in C:\Temp\argus-logs-<timestamp>.txt
# =============================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$ErrorActionPreference = 'Continue'
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$out = "C:\Temp\argus-logs-$ts.txt"
if (-not (Test-Path "C:\Temp")) { New-Item -ItemType Directory -Path "C:\Temp" -Force | Out-Null }

function Section($title) {
    $line = "=" * 78
    Add-Content -Path $out -Value ""
    Add-Content -Path $out -Value $line
    Add-Content -Path $out -Value " $title"
    Add-Content -Path $out -Value $line
    Write-Host "`n$line" -ForegroundColor Cyan
    Write-Host " $title" -ForegroundColor Cyan
}
function Log($msg) { Add-Content -Path $out -Value $msg; Write-Host $msg }

"ARGUS Logs - $ts" | Set-Content -Path $out -Encoding UTF8

# =====================================================================
Section "1. ULTIME 150 RIGHE connector.log (log applicativo)"
# =====================================================================
$f1 = "C:\ProgramData\86NocConnector\logs\connector.log"
if (Test-Path $f1) {
    Get-Content $f1 -Tail 150 -Encoding UTF8 | ForEach-Object { Log $_ }
} else { Log "  FILE NON TROVATO: $f1" }

# =====================================================================
Section "2. ULTIME 80 RIGHE service_stderr.log (errori PowerShell)"
# =====================================================================
$f2 = "C:\ProgramData\86NocConnector\logs\service_stderr.log"
if (Test-Path $f2) {
    Get-Content $f2 -Tail 80 -Encoding UTF8 | ForEach-Object { Log $_ }
} else { Log "  FILE NON TROVATO: $f2" }

# =====================================================================
Section "3. ULTIME 80 RIGHE service_stdout.log"
# =====================================================================
$f3 = "C:\ProgramData\86NocConnector\logs\service_stdout.log"
if (Test-Path $f3) {
    Get-Content $f3 -Tail 80 -Encoding UTF8 | ForEach-Object { Log $_ }
} else { Log "  FILE NON TROVATO: $f3" }

# =====================================================================
Section "4. ULTIME 30 RIGHE update.log + watchdog.log"
# =====================================================================
$f4 = "C:\ProgramData\86NocConnector\update.log"
if (Test-Path $f4) {
    Log "--- update.log ---"
    Get-Content $f4 -Tail 30 -Encoding UTF8 | ForEach-Object { Log $_ }
} else { Log "  update.log non trovato" }

$f5 = "C:\ProgramData\86NocConnector\watchdog.log"
if (Test-Path $f5) {
    Log ""
    Log "--- watchdog.log ---"
    Get-Content $f5 -Tail 30 -Encoding UTF8 | ForEach-Object { Log $_ }
} else { Log "  watchdog.log non trovato" }

# =====================================================================
Section "5. EVENTI WINDOWS DEFENDER ULTIMA ORA"
# =====================================================================
# Cerca interferenze AV/Defender che potrebbero killare PowerShell
$cutoff = (Get-Date).AddHours(-1)
try {
    $defEvents = Get-WinEvent -LogName "Microsoft-Windows-Windows Defender/Operational" -MaxEvents 200 -ErrorAction SilentlyContinue |
        Where-Object { $_.TimeCreated -gt $cutoff -and $_.Id -in 1006,1007,1008,1009,1116,1117,1121,1122,5007,5010,5012 }
    foreach ($e in $defEvents) {
        Log ("  [{0}] [Id={1}] {2}" -f $e.TimeCreated, $e.Id, ($e.Message -replace "`r?`n", " | ").Substring(0, [Math]::Min(180, $e.Message.Length)))
    }
    if (-not $defEvents) { Log "  Nessun evento Defender critico nell'ultima ora (good)" }
} catch { Log "  Errore lettura eventi Defender: $($_.Exception.Message)" }

# =====================================================================
Section "6. EVENTI POWERSHELL ENGINE ULTIMA ORA (crash, eccezioni)"
# =====================================================================
try {
    $psEvents = Get-WinEvent -LogName "Windows PowerShell" -MaxEvents 100 -ErrorAction SilentlyContinue |
        Where-Object { $_.TimeCreated -gt $cutoff -and $_.LevelDisplayName -in 'Errore','Avviso' }
    foreach ($e in $psEvents | Select -First 10) {
        Log ("  [{0}] [{1}] {2}" -f $e.TimeCreated, $e.LevelDisplayName, ($e.Message -replace "`r?`n", " | ").Substring(0, [Math]::Min(180, $e.Message.Length)))
    }
    if (-not $psEvents) { Log "  Nessun evento PS critico nell'ultima ora" }
} catch { Log "  Errore: $($_.Exception.Message)" }

# =====================================================================
Section "7. CONFIG ASR (Attack Surface Reduction)"
# =====================================================================
try {
    $asr = Get-MpPreference -ErrorAction SilentlyContinue
    Log "  AttackSurfaceReductionRules_Ids:"
    if ($asr.AttackSurfaceReductionRules_Ids) {
        for ($i=0; $i -lt $asr.AttackSurfaceReductionRules_Ids.Count; $i++) {
            $rid = $asr.AttackSurfaceReductionRules_Ids[$i]
            $rac = if ($i -lt $asr.AttackSurfaceReductionRules_Actions.Count) { $asr.AttackSurfaceReductionRules_Actions[$i] } else { "?" }
            Log "    $rid -> $rac"
        }
    } else {
        Log "    (nessuna regola ASR attiva)"
    }
    Log "  TamperProtectionSource: $($asr.TamperProtectionSource)"
    Log "  RealTimeScanDirection:  $($asr.RealTimeScanDirection)"
    Log "  ExclusionPath count:    $($asr.ExclusionPath.Count)"
    if ($asr.ExclusionPath) {
        $asr.ExclusionPath | Where-Object { $_ -like "*86NocConnector*" -or $_ -like "*ARGUS*" } | ForEach-Object { Log "    INCLUDED: $_" }
    }
} catch { Log "  Get-MpPreference errore: $($_.Exception.Message)" }

Section "FINE"
Log ""
Log "Report: $out"
Write-Host ""
Write-Host "  >>> Apertura cartella..." -ForegroundColor Yellow
Start-Process explorer.exe -ArgumentList "/select,`"$out`""
Read-Host "`nPremi INVIO per chiudere"
