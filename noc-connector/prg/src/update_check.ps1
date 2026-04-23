# ============================================================================
# 86NocConnector Update Checker — v3.5.0 Microsoft-native pattern
# ============================================================================
# Eseguito da Windows Task Scheduler ogni 5 minuti come NT AUTHORITY\SYSTEM.
# Task: \86BIT\ArgusConnectorUpdater
#
# Logica:
#   1. Legge config del connector (API URL + API Key)
#   2. GET /api/connector/update-check
#   3. Se update_available && latest_version != current → applica update
#   4. Report progress al NOC via /api/connector/update-progress
#   5. Logga tutto in ProgramData\86NocConnector\update.log
#
# Perche' Microsoft-pulito:
#   - Eseguito da Task Scheduler (host firstparty Microsoft)
#   - Invoke-WebRequest, Expand-Archive, Stop/Start-Service sono tutti
#     cmdlet Microsoft built-in, mai bloccati da ASR/WDAC/SmartScreen
#   - Nessun child-process da PowerShell del connector principale
#   - Unica fonte della verita': un solo log, un solo file, una sola logica
# ============================================================================

[CmdletBinding()]
param(
    [string]$InstallDir = "C:\Program Files\86NocConnector",
    [string]$ServiceName = "86NocConnectorService"
)

$ErrorActionPreference = "Stop"

# TLS 1.2 (Windows Server 2016+ richiede override esplicito)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ==================== LOGGING ====================
$LogDir = Join-Path $env:ProgramData "86NocConnector"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir "update.log"

function Write-UpdateLog {
    param([string]$Message, [string]$Level = "INFO")
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$Level] $Message"
    try {
        Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
    Write-Host $line
}

# Rotation: se log > 2 MB, mantieni solo le ultime 5000 righe
try {
    if (Test-Path $LogFile) {
        $sz = (Get-Item $LogFile).Length
        if ($sz -gt 2MB) {
            $lines = Get-Content $LogFile -Tail 5000
            Set-Content -Path $LogFile -Value $lines -Encoding UTF8
        }
    }
} catch {}

Write-UpdateLog "=========================================="
Write-UpdateLog "UpdateChecker start (pattern Task Scheduler v3.5.0+)"
Write-UpdateLog "InstallDir: $InstallDir"

# ==================== LOCK FILE (safety net contro concorrenza) ====================
# Anche con MultipleInstancesPolicy=IgnoreNew, lock esplicito su file system
# garantisce che solo UNA istanza alla volta puo' fare update.
$LockFile = Join-Path $LogDir "update_check.lock"
$LockAge = 1200   # lock stale se piu' vecchio di 20 min (oltre il nostro timeout di 15 min)

if (Test-Path $LockFile) {
    try {
        $lockInfo = Get-Item $LockFile
        $ageSec = (Get-Date).Subtract($lockInfo.LastWriteTime).TotalSeconds
        if ($ageSec -lt $LockAge) {
            $lockPid = Get-Content $LockFile -ErrorAction SilentlyContinue
            Write-UpdateLog "Lock attivo (PID=$lockPid, eta=$([int]$ageSec)s). Skip run (un altro updater e' in corso)." "INFO"
            exit 0
        } else {
            Write-UpdateLog "Lock stale ($([int]$ageSec)s > $LockAge). Rimozione e continuo..." "WARN"
            Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}

# Acquire lock
try {
    Set-Content -Path $LockFile -Value $PID -ErrorAction Stop
} catch {
    Write-UpdateLog "Impossibile creare lock file: $($_.Exception.Message)" "WARN"
}

# Release lock on exit (ogni exit path)
$ReleaseLock = {
    try { Remove-Item $LockFile -Force -ErrorAction SilentlyContinue } catch {}
}
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action $ReleaseLock | Out-Null

# ==================== SELF-HARDEN TASK (prima volta post-bootstrap) ====================
# Il bootstrap_to_v350.cmd crea il task con schtasks /Create semplice.
# Qui verifichiamo e ottimizziamo le opzioni del task se non gia' settate.
# Costo: 1 chiamata schtasks /Query ogni 5 min, irrilevante.
try {
    $taskXml = & schtasks.exe /Query /TN "\86BIT\ArgusConnectorUpdater" /XML 2>$null
    if ($taskXml -and ($taskXml -join "") -notmatch "MultipleInstancesPolicy") {
        Write-UpdateLog "Self-harden task settings (MultipleInstancesPolicy + Priority + ExecutionTimeLimit)..."
        $xml = [xml]($taskXml -join "`n")
        $ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
        $ns.AddNamespace("t", "http://schemas.microsoft.com/windows/2004/02/mit/task")
        $settings = $xml.SelectSingleNode("//t:Settings", $ns)
        if ($settings) {
            function Add-IfMissing($parent, $name, $value, $xmlDoc, $nsMgr) {
                if (-not $parent.SelectSingleNode("t:$name", $nsMgr)) {
                    $el = $xmlDoc.CreateElement($name, "http://schemas.microsoft.com/windows/2004/02/mit/task")
                    $el.InnerText = $value
                    $parent.AppendChild($el) | Out-Null
                }
            }
            Add-IfMissing $settings "MultipleInstancesPolicy" "IgnoreNew" $xml $ns
            Add-IfMissing $settings "Priority" "7" $xml $ns
            Add-IfMissing $settings "ExecutionTimeLimit" "PT15M" $xml $ns
            Add-IfMissing $settings "StartWhenAvailable" "true" $xml $ns
            $tmpXml = Join-Path $env:TEMP "_selfharden.xml"
            $xml.Save($tmpXml)
            & schtasks.exe /Delete /TN "\86BIT\ArgusConnectorUpdater" /F 2>$null | Out-Null
            & schtasks.exe /Create /TN "\86BIT\ArgusConnectorUpdater" /XML $tmpXml /RU "SYSTEM" /RL HIGHEST /F 2>&1 | Out-Null
            Remove-Item $tmpXml -Force -ErrorAction SilentlyContinue
            Write-UpdateLog "Task self-harden completato"
        }
    }
} catch {
    Write-UpdateLog "Self-harden fallito (non critico): $($_.Exception.Message)" "DEBUG"
}

# ==================== READ CONFIG ====================
$configPath = Join-Path $InstallDir "config.json"
if (-not (Test-Path $configPath)) {
    Write-UpdateLog "Config non trovata in $configPath" "ERROR"
    exit 1
}

try {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
} catch {
    Write-UpdateLog "Errore parsing config.json: $($_.Exception.Message)" "ERROR"
    exit 2
}

$apiUrl = $config.noc_center_url
$apiKey = $config.api_key
if (-not $apiUrl -or -not $apiKey) {
    Write-UpdateLog "Config incompleta: noc_center_url o api_key mancanti" "ERROR"
    exit 3
}

# Read current version
$versionJsonPath = Join-Path $InstallDir "version.json"
$currentVersion = "unknown"
if (Test-Path $versionJsonPath) {
    try {
        $vj = Get-Content $versionJsonPath -Raw | ConvertFrom-Json
        $currentVersion = $vj.version
    } catch {}
}
Write-UpdateLog "Versione corrente: $currentVersion"

# ==================== HELPER: Progress report ====================
function Send-Progress {
    param([int]$Progress, [string]$Status, [string]$Message)
    try {
        $body = @{ progress = $Progress; status = $Status; message = $Message } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method POST `
            -Uri "$apiUrl/api/connector/update-progress" `
            -Headers @{ "X-API-Key" = $apiKey; "Content-Type" = "application/json" } `
            -Body $body -TimeoutSec 10 -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}

# ==================== STEP 1: Check for update ====================
try {
    $checkResponse = Invoke-RestMethod -Method GET `
        -Uri "$apiUrl/api/connector/update-check" `
        -Headers @{ "X-API-Key" = $apiKey } `
        -TimeoutSec 15
} catch {
    Write-UpdateLog "Errore chiamata /update-check: $($_.Exception.Message)" "WARN"
    exit 0   # exit 0 perche' e' normale se offline, non segnaliamo errore
}

if (-not $checkResponse.update_available) {
    Write-UpdateLog "Nessun aggiornamento disponibile (server: v$($checkResponse.latest_version))"
    exit 0
}

$newVersion = $checkResponse.latest_version
$newFilename = $checkResponse.filename
$newFileSize = $checkResponse.file_size

if ($newVersion -eq $currentVersion) {
    Write-UpdateLog "Gia' aggiornato a v$currentVersion"
    exit 0
}

Write-UpdateLog "Aggiornamento disponibile: v$currentVersion -> v$newVersion (file: $newFilename, size: $newFileSize bytes)" "INFO"
Send-Progress 10 "starting" "Preparazione aggiornamento v$newVersion"

# ==================== STEP 2: Download ZIP ====================
$tempDir = Join-Path $env:TEMP "ArgusConnectorUpdate_$newVersion"
if (Test-Path $tempDir) {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

$zipPath = Join-Path $tempDir $newFilename

try {
    Write-UpdateLog "Download ZIP da $apiUrl/api/connector/download/$newFilename..."
    Send-Progress 25 "downloading" "Download in corso"
    Invoke-WebRequest -Uri "$apiUrl/api/connector/download/$newFilename" `
        -Headers @{ "X-API-Key" = $apiKey } `
        -OutFile $zipPath -TimeoutSec 180 -UseBasicParsing
    
    if (-not (Test-Path $zipPath)) {
        throw "File ZIP non trovato dopo download"
    }
    $actualSize = (Get-Item $zipPath).Length
    Write-UpdateLog "Download completato: $actualSize bytes"
    if ($newFileSize -gt 0 -and $actualSize -ne $newFileSize) {
        Write-UpdateLog "ATTENZIONE: size atteso $newFileSize, ricevuto $actualSize" "WARN"
    }
} catch {
    Write-UpdateLog "Errore download: $($_.Exception.Message)" "ERROR"
    Send-Progress 0 "error" "Download fallito: $($_.Exception.Message)"
    exit 10
}

# ==================== STEP 3: Extract ZIP ====================
$extractDir = Join-Path $tempDir "extracted"
try {
    Write-UpdateLog "Estrazione ZIP in $extractDir..."
    Send-Progress 50 "extracting" "Estrazione archivio"
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
    
    # Expected structure: extracted/prg/src, extracted/prg/version.json, ecc.
    $srcPath = Join-Path $extractDir "prg"
    if (-not (Test-Path $srcPath)) {
        throw "Struttura ZIP non valida: manca cartella prg/"
    }
    Write-UpdateLog "Estrazione completata"
} catch {
    Write-UpdateLog "Errore estrazione: $($_.Exception.Message)" "ERROR"
    Send-Progress 0 "error" "Estrazione fallita: $($_.Exception.Message)"
    exit 11
}

# ==================== STEP 4: Backup src/ corrente ====================
$backupDir = Join-Path $InstallDir "_backup"
try {
    if (Test-Path $backupDir) {
        Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    if (Test-Path "$InstallDir\src") {
        Copy-Item "$InstallDir\src" -Destination "$backupDir\src" -Recurse -Force
    }
    if (Test-Path "$InstallDir\version.json") {
        Copy-Item "$InstallDir\version.json" -Destination "$backupDir\version.json" -Force
    }
    Write-UpdateLog "Backup completato in $backupDir"
} catch {
    Write-UpdateLog "Backup fallito: $($_.Exception.Message)" "WARN"
    # Continuiamo comunque, il backup e' un nice-to-have
}

# ==================== STEP 5: Stop service ====================
Send-Progress 65 "installing" "Stop del servizio"
try {
    Write-UpdateLog "Stop servizio $ServiceName..."
    $svc = Get-Service $ServiceName -ErrorAction Stop
    if ($svc.Status -eq "Running") {
        Stop-Service $ServiceName -Force -ErrorAction Stop
        $svc.WaitForStatus("Stopped", (New-TimeSpan -Seconds 30))
    }
    Write-UpdateLog "Servizio fermato"
} catch {
    Write-UpdateLog "Errore stop servizio: $($_.Exception.Message)" "WARN"
    # Fallback: sc.exe + net stop
    & sc.exe stop $ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 5
    & net stop $ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 5
}

# ==================== STEP 6: Copia file nuovi ====================
Send-Progress 80 "installing" "Copia file nuovi"
try {
    Write-UpdateLog "Copia $srcPath\* in $InstallDir\ ..."
    # Copia ricorsiva, sovrascrittura forzata
    Get-ChildItem -Path $srcPath -Recurse | ForEach-Object {
        $relPath = $_.FullName.Substring($srcPath.Length).TrimStart('\')
        $destPath = Join-Path $InstallDir $relPath
        if ($_.PSIsContainer) {
            if (-not (Test-Path $destPath)) {
                New-Item -ItemType Directory -Path $destPath -Force | Out-Null
            }
        } else {
            $destDir = Split-Path $destPath -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            Copy-Item -Path $_.FullName -Destination $destPath -Force
        }
    }
    Write-UpdateLog "File copiati con successo"
} catch {
    Write-UpdateLog "Errore copia file: $($_.Exception.Message)" "ERROR"
    Send-Progress 0 "error" "Copia fallita: $($_.Exception.Message). Rollback in corso..."
    # Rollback: ripristina backup
    try {
        if (Test-Path "$backupDir\src") {
            if (Test-Path "$InstallDir\src") { Remove-Item "$InstallDir\src" -Recurse -Force }
            Copy-Item "$backupDir\src" -Destination "$InstallDir\src" -Recurse -Force
        }
        Write-UpdateLog "Rollback backup OK"
    } catch {
        Write-UpdateLog "Rollback fallito: $($_.Exception.Message)" "ERROR"
    }
    # Riavvia il servizio anche se rollback, cosi' non resta fermo
    try { Start-Service $ServiceName } catch {}
    exit 12
}

# ==================== STEP 7: Start service ====================
Send-Progress 90 "installing" "Avvio servizio"
try {
    Write-UpdateLog "Start servizio $ServiceName..."
    Start-Service $ServiceName -ErrorAction Stop
    $svc = Get-Service $ServiceName
    $svc.WaitForStatus("Running", (New-TimeSpan -Seconds 30))
    Write-UpdateLog "Servizio avviato"
} catch {
    Write-UpdateLog "Errore start servizio: $($_.Exception.Message)" "ERROR"
    # Fallback sc.exe
    & sc.exe start $ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 5
    $svc = Get-Service $ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        Write-UpdateLog "Servizio avviato via sc.exe fallback"
    } else {
        Send-Progress 0 "error" "Servizio non parte: $($_.Exception.Message)"
        exit 13
    }
}

# ==================== STEP 8: Cleanup ====================
try {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-UpdateLog "Cleanup temp directory OK"
} catch {}

# ==================== SUCCESS ====================
Write-UpdateLog "AGGIORNAMENTO COMPLETATO: v$currentVersion -> v$newVersion" "INFO"
Send-Progress 100 "success" "Aggiornato a v$newVersion"
exit 0
