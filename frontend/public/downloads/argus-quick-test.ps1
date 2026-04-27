# =============================================================================
# ARGUS Quick-Test — Punta il connector al Center preview per validare end-to-end
# =============================================================================
# Cosa fa:
#   1. Backup del config.json attuale (che punta al tuo prod argus.86bit.it)
#   2. Sostituisce noc_center_url + api_key + client_id con quelli del preview
#   3. Restart servizio
#   4. Verifica heartbeat - vedi i dati arrivare in 60 secondi
#
# Per tornare al prod:
#   doppio click su argus-quick-restore.ps1
#   (o ripristina manualmente config.json.bak che lo script crea)
# =============================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

# Logging persistente — anche se lo script va in errore tutto e' in C:\Temp\argus-quick-test.log
if (-not (Test-Path "C:\Temp")) { New-Item -ItemType Directory -Path "C:\Temp" -Force | Out-Null }
$transcriptFile = "C:\Temp\argus-quick-test-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
try { Start-Transcript -Path $transcriptFile -Force | Out-Null } catch {}

$ErrorActionPreference = 'Continue'  # NON Stop: lasciamo continuare e gestiamo errori manualmente
$Host.UI.RawUI.WindowTitle = "ARGUS Quick-Test (Center preview)"

# Catch-all globale: qualsiasi errore non-handled viene mostrato senza far chiudere la finestra
trap {
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Red
    Write-Host " ERRORE NON GESTITO - lo script si e' interrotto" -ForegroundColor Red
    Write-Host "==========================================================" -ForegroundColor Red
    Write-Host "  Errore:    $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  Tipo:      $($_.Exception.GetType().FullName)" -ForegroundColor Yellow
    Write-Host "  Posizione: $($_.InvocationInfo.PositionMessage)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Log completo salvato in: $transcriptFile" -ForegroundColor Cyan
    Write-Host "  MANDA QUEL FILE all'agente per analisi." -ForegroundColor Cyan
    Write-Host ""
    Read-Host "INVIO per chiudere"
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

# ====== TARGET PREVIEW ======
$PREVIEW_URL = "https://noc-monitor-hub.preview.emergentagent.com"
$PREVIEW_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
$PREVIEW_API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"

function H($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t){ Write-Host "  [OK] $t" -ForegroundColor Green }
function Wn($t){ Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Er($t){ Write-Host "  [ERR] $t" -ForegroundColor Red }

H "ARGUS Quick-Test"
Write-Host "  Cosa faccio: puntare temporaneamente il connector al Center preview Kubernetes"
Write-Host "  per validare che TUTTO funziona end-to-end."
Write-Host ""
Write-Host "  Target preview: $PREVIEW_URL" -ForegroundColor Yellow
Write-Host "  Client ID:      $PREVIEW_CLIENT_ID" -ForegroundColor Yellow
Write-Host ""
$conf = Read-Host "Procedo? [S/n]"
if ($conf -match '^[nN]') { exit 0 }

# ====== 1. BACKUP CONFIG ======
H "1. Backup config attuale"
$cfgPath = "C:\ProgramData\86NocConnector\config.json"
if (-not (Test-Path $cfgPath)) {
    Er "config.json non trovato: $cfgPath"
    Read-Host "INVIO per uscire"; exit 1
}
$bk = "$cfgPath.PROD-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item $cfgPath $bk
Ok "Backup salvato: $bk"

# Il backup viene anche memorizzato in posizione fissa per facilitare il restore
$fixedBk = "C:\ProgramData\86NocConnector\config.PROD-original.json"
if (-not (Test-Path $fixedBk)) {
    Copy-Item $cfgPath $fixedBk
    Ok "Backup PERMANENTE in: $fixedBk (per restore futuro)"
}

# ====== 2. RISCRITTURA CONFIG ======
H "2. Riconfigurazione su Center preview"
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
Write-Host "  PRIMA:"
Write-Host "    URL:    $($cfg.noc_center_url)"
Write-Host "    Client: $($cfg.client_id)"
Write-Host "    APIKey: $($cfg.api_key.Substring(0,8))...$($cfg.api_key.Substring($cfg.api_key.Length-4))"

$cfg.noc_center_url = $PREVIEW_URL
$cfg.client_id = $PREVIEW_CLIENT_ID
$cfg.api_key = $PREVIEW_API_KEY
$cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $cfgPath -Encoding UTF8

Write-Host "  DOPO:"
Write-Host "    URL:    $($cfg.noc_center_url)" -ForegroundColor Green
Write-Host "    Client: $($cfg.client_id)" -ForegroundColor Green
Write-Host "    APIKey: $($cfg.api_key.Substring(0,8))...$($cfg.api_key.Substring($cfg.api_key.Length-4))" -ForegroundColor Green
Ok "Config aggiornato"

# ====== 3. TEST PRELIMINARE HEARTBEAT ======
H "3. Test pre-volo: heartbeat verso il Center preview"
$body = @{ client_id = $PREVIEW_CLIENT_ID; status = "running"; devices = @() } | ConvertTo-Json -Compress
try {
    $r = Invoke-WebRequest -Uri "$PREVIEW_URL/api/connector/device-report" -Method Post `
         -Body $body -ContentType "application/json" `
         -Headers @{ "X-API-Key" = $PREVIEW_API_KEY } -TimeoutSec 10 -UseBasicParsing
    Ok "Center preview risponde: HTTP $($r.StatusCode)"
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    Er "Test pre-volo FALLITO: HTTP $code"
    Wn "$($_.Exception.Message)"
    Wn "Procedo comunque col restart per vedere se il connector reale funziona"
}

# ====== 4. RESTART SERVIZIO ======
H "4. Restart servizio"
try {
    Stop-Service 86NocConnectorService -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-Service 86NocConnectorService -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 6
    $svc = Get-Service 86NocConnectorService -ErrorAction SilentlyContinue
    if ($svc.Status -eq 'Running') {
        Ok "Servizio: Running"
    } else {
        Wn "Servizio: $($svc.Status)"
    }
} catch { Er "Restart fallito: $($_.Exception.Message)" }

# ====== 5. ATTESA + TAIL LOG ======
H "5. Attesa heartbeat (60 secondi)..."
Write-Host "  Tail log in tempo reale - dovresti vedere POST 200 senza piu' 401:"
Write-Host ""
$logFile = "C:\ProgramData\86NocConnector\logs\connector.log"
$startSize = (Get-Item $logFile -ErrorAction SilentlyContinue).Length
$elapsed = 0
$success = $false
while ($elapsed -lt 60 -and -not $success) {
    Start-Sleep -Seconds 5
    $elapsed += 5
    $now = Get-Item $logFile -ErrorAction SilentlyContinue
    if ($now -and $now.Length -gt $startSize) {
        $newLines = Get-Content $logFile -Tail 20
        foreach ($ln in $newLines) {
            if ($ln -match "401|ERROR|FAIL") { Write-Host "  $ln" -ForegroundColor Red }
            elseif ($ln -match "WARN") { Write-Host "  $ln" -ForegroundColor Yellow }
            elseif ($ln -match "200|inviato|metric|ricevut") {
                Write-Host "  $ln" -ForegroundColor Green
                if ($ln -match "200|inviato") { $success = $true }
            }
            else { Write-Host "  $ln" -ForegroundColor Gray }
        }
        $startSize = $now.Length
    }
    Write-Host "  ... [$elapsed/60s] in attesa di heartbeat valido ..." -ForegroundColor DarkGray
}

# ====== 6. RESULT FINALE ======
H "RISULTATO FINALE"
if ($success) {
    Write-Host ""
    Write-Host "   IL CONNECTOR SI E' AGGANCIATO AL CENTER PREVIEW!" -ForegroundColor Green
    Write-Host ""
    Write-Host "   Vai su:  $PREVIEW_URL" -ForegroundColor Yellow
    Write-Host "   Login:   admin@86bit.it / password" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Dovresti vedere il connector ATTIVO nella pagina /connectors" -ForegroundColor White
    Write-Host "   e i 4 device polled nella pagina del cliente '86BIT_Office'" -ForegroundColor White
    Write-Host ""
    Write-Host "   Per tornare al tuo Center prod (argus.86bit.it):" -ForegroundColor Cyan
    Write-Host "   Esegui: Copy-Item '$fixedBk' '$cfgPath' -Force ; Restart-Service 86NocConnectorService" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "   Heartbeat ancora NON visto in 60 secondi." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Se vedi 401 nei log: l'API Key del Center preview e' stata cambiata." -ForegroundColor Yellow
    Write-Host "   Se vedi connection refused: problema di firewall outbound HTTPS" -ForegroundColor Yellow
    Write-Host "   Manda l'output di:" -ForegroundColor Yellow
    Write-Host "     Get-Content $logFile -Tail 40" -ForegroundColor White
}

Write-Host ""
try { Stop-Transcript | Out-Null } catch {}
Read-Host "INVIO per chiudere"
