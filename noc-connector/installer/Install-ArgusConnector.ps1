# ============================================================================
# ARGUS Connector - Bootstrap Installer (self-elevating, single file)
# ============================================================================
# Doppio click su questo file (oppure tasto destro -> Esegui con PowerShell)
# e parte automaticamente:
#   1. Auto-elevazione UAC
#   2. Download dell'ultima versione del connector dal Center
#   3. Estrazione in cartella temporanea
#   4. Lancio del wizard GUI di installazione (installer_gui.ps1)
#
# Nessuna configurazione necessaria, nessuno ZIP da gestire manualmente.
# ============================================================================

$ErrorActionPreference = "Stop"

# URL del Center da cui scaricare il connector. Modificabile prima della distribuzione.
# Default: il preview environment dell'agent. Per produzione cambialo in https://argus.86bit.it
$CenterUrl = "https://noc-monitor-hub.preview.emergentagent.com"

# ================================================================
# AUTO-ELEVATION (UAC)
# ================================================================
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    try {
        Write-Host "[INFO] Elevazione richiesta. Accetta il prompt UAC..." -ForegroundColor Yellow
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
        $psi.Verb = "runas"
        [System.Diagnostics.Process]::Start($psi) | Out-Null
        exit 0
    } catch {
        Write-Host "[ERRORE] Devi accettare il prompt UAC per installare." -ForegroundColor Red
        Read-Host "Premi INVIO per chiudere"
        exit 1
    }
}

# ================================================================
# UI banner
# ================================================================
Clear-Host
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "    ARGUS Connector - Bootstrap Installer" -ForegroundColor Cyan
Write-Host "    86BIT srl" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Center URL: $CenterUrl" -ForegroundColor Gray
Write-Host ""

# ================================================================
# TLS 1.2 + Download
# ================================================================
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$tmpDir = Join-Path $env:TEMP "argus_bootstrap_$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
$zipPath = Join-Path $tmpDir "connector.zip"

Write-Host "[1/4] Download connector dal Center..." -ForegroundColor White
try {
    $url = "$CenterUrl/api/connector/public-download/latest"
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -TimeoutSec 120
    $size = (Get-Item $zipPath).Length
    Write-Host "      OK: $([math]::Round($size/1KB, 1)) KB scaricati" -ForegroundColor Green
} catch {
    Write-Host "      ERRORE download: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "      Verifica connessione internet e che il Center sia raggiungibile."
    Read-Host "      Premi INVIO per chiudere"
    exit 1
}

# ================================================================
# Extract
# ================================================================
Write-Host ""
Write-Host "[2/4] Estrazione archivio..." -ForegroundColor White
try {
    Expand-Archive -Path $zipPath -DestinationPath $tmpDir -Force
    $wizardPath = Join-Path $tmpDir "prg\src\installer_gui.ps1"
    if (-not (Test-Path $wizardPath)) {
        throw "Wizard non trovato nello ZIP"
    }
    Write-Host "      OK: file estratti in $tmpDir" -ForegroundColor Green
} catch {
    Write-Host "      ERRORE estrazione: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "      Premi INVIO per chiudere"
    exit 1
}

# ================================================================
# Versione info
# ================================================================
$versionInfo = "?"
try {
    $vj = Get-Content (Join-Path $tmpDir "prg\version.json") -Raw | ConvertFrom-Json
    $versionInfo = $vj.version
} catch {}

Write-Host ""
Write-Host "[3/4] Versione rilevata: v$versionInfo" -ForegroundColor White
Write-Host ""

# ================================================================
# Lancia il wizard GUI
# ================================================================
Write-Host "[4/4] Avvio Wizard installazione..." -ForegroundColor White
Write-Host "      Si aprira' una finestra grafica per la configurazione." -ForegroundColor Gray
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wizardPath
} catch {
    Write-Host "[ERRORE] Impossibile avviare il wizard: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Premi INVIO per chiudere"
    exit 1
}

# ================================================================
# Cleanup
# ================================================================
try {
    Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
} catch {}

Write-Host ""
Write-Host "  Installazione completata. Controlla lo stato sul Center." -ForegroundColor Green
Write-Host ""
