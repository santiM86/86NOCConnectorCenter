# =============================================================================
# ARGUS Final-Fix - sblocca il connector e diagnostica il backend prod
# =============================================================================
# Eseguito DOPO firewall-test che ha confermato connettivita OK.
# Cosa fa:
#   1. Fix quoting NSSM AppParameters (sblocca lo stato Paused)
#   2. Disabilita Task Scheduler legacy duplicati
#   3. Restart pulito
#   4. Test heartbeat al prod argus.86bit.it con la API Key attuale
#   5. Test schema device-report per capire se il backend prod e' compatibile
#   6. Tail log applicativo 30 secondi
#   7. Diagnosi finale + next step preciso
# =============================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

if (-not (Test-Path "C:\Temp")) { New-Item -ItemType Directory -Path "C:\Temp" -Force | Out-Null }
$tFile = "C:\Temp\argus-final-fix-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
try { Start-Transcript -Path $tFile -Force | Out-Null } catch {}

$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = "ARGUS Final-Fix"

trap {
    Write-Host ""
    Write-Host "ERRORE: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Posizione: $($_.InvocationInfo.PositionMessage)" -ForegroundColor Yellow
    Write-Host "Log: $tFile" -ForegroundColor Cyan
    Read-Host "INVIO per chiudere"
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Pass($t)    { Write-Host "  [OK] $t" -ForegroundColor Green }
function Warn2($t)   { Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Fail($t)    { Write-Host "  [ERR] $t" -ForegroundColor Red }

Section "ARGUS Final-Fix - sblocco connector e diagnosi backend prod"

# =========================================================
Section "1. Stop servizio + watchdog"
# =========================================================
& schtasks.exe /End /TN "\86BIT\86NocConnector_Watchdog" 2>$null | Out-Null
Pass "Watchdog fermato (per evitare resume durante fix)"
Stop-Service 86NocConnectorService -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# =========================================================
Section "2. Fix quoting NSSM AppParameters"
# =========================================================
$nssm = "C:\Program Files\86NocConnector\nssm.exe"
$psFile = "C:\Program Files\86NocConnector\src\connector.ps1"
$installDir = "C:\Program Files\86NocConnector"

if (-not (Test-Path $nssm)) { Fail "nssm.exe non trovato"; Read-Host "INVIO"; exit 1 }
if (-not (Test-Path $psFile)) { Fail "connector.ps1 non trovato"; Read-Host "INVIO"; exit 1 }

$oldParams = & $nssm get 86NocConnectorService AppParameters 2>$null
Write-Host "  OLD AppParameters: $oldParams"
$newParams = "-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$psFile`""
& $nssm set 86NocConnectorService AppParameters $newParams 2>&1 | Out-Null
& $nssm set 86NocConnectorService AppDirectory "`"$installDir\src`"" 2>&1 | Out-Null
$check = & $nssm get 86NocConnectorService AppParameters 2>$null
Write-Host "  NEW AppParameters: $check"
if ($check -like "*`"$psFile`"*") { Pass "Quoting NSSM corretto" } else { Fail "Quoting fallito" }

# =========================================================
Section "3. Disabilita task scheduler duplicati"
# =========================================================
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.Actions -and $_.Actions.Execute -like "*powershell*" -and (
        $_.Actions.Arguments -like "*connector.ps1*" -or
        $_.Actions.Arguments -like "*86NocConnector*"
    ) -and $_.TaskName -notlike "*Updater*" -and $_.TaskName -notlike "*Watchdog*"
}
if ($tasks) {
    foreach ($t in $tasks) {
        try {
            Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName -ErrorAction Stop | Out-Null
            Pass "Disabilitato task duplicato: $($t.TaskPath)$($t.TaskName)"
        } catch { Warn2 "Disable fallito $($t.TaskName): $($_.Exception.Message)" }
    }
} else {
    Pass "Nessun task duplicato (solo Updater/Watchdog presenti, OK)"
}

# =========================================================
Section "4. Restart servizio"
# =========================================================
try {
    Start-Service 86NocConnectorService -ErrorAction Stop
    Start-Sleep -Seconds 8
    $svc = Get-Service 86NocConnectorService
    if ($svc.Status -eq 'Running') {
        Pass "Servizio: Running (era Paused per quoting bug)"
    } elseif ($svc.Status -eq 'Paused') {
        Fail "Servizio: ANCORA Paused. Il quoting fix non e' bastato."
    } else {
        Warn2 "Servizio: $($svc.Status)"
    }
} catch {
    Fail "Start fallito: $($_.Exception.Message)"
}

# =========================================================
Section "5. Test heartbeat manuale al PROD argus.86bit.it"
# =========================================================
$cfgPath = "C:\ProgramData\86NocConnector\config.json"
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$url = $cfg.noc_center_url
$cid = $cfg.client_id
$ak = $cfg.api_key

Write-Host "  Center: $url"
Write-Host "  Client: $cid"
Write-Host "  APIKey: $($ak.Substring(0,8))...$($ak.Substring($ak.Length-4))"

# Test 1: device-report
$body1 = @{ client_id = $cid; status = "running"; devices = @() } | ConvertTo-Json -Compress
Write-Host ""
Write-Host "  [TEST 1] POST /api/connector/device-report:" -ForegroundColor Gray
try {
    $r1 = Invoke-WebRequest -Uri "$url/api/connector/device-report" -Method Post -Body $body1 `
          -ContentType "application/json" -Headers @{ "X-API-Key" = $ak } -TimeoutSec 10 -UseBasicParsing
    Pass "HTTP $($r1.StatusCode) - $($r1.Content.Substring(0, [Math]::Min(80, $r1.Content.Length)))"
    $apiOk = $true
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    $respBody = ""
    try { $respBody = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch {}
    Fail "HTTP $code - $($_.Exception.Message)"
    if ($respBody) { Write-Host "    Response: $respBody" -ForegroundColor DarkGray }
    $apiOk = $false
    $apiCode = $code
}

# Test 2: heartbeat (schema nuovo v3.5+)
$body2 = @{
    client_id = $cid
    connector_version = "3.5.23"
    hostname = $env:COMPUTERNAME
    status = "running"
} | ConvertTo-Json -Compress
Write-Host ""
Write-Host "  [TEST 2] POST /api/connector/heartbeat (schema v3.5+):" -ForegroundColor Gray
try {
    $r2 = Invoke-WebRequest -Uri "$url/api/connector/heartbeat" -Method Post -Body $body2 `
          -ContentType "application/json" -Headers @{ "X-API-Key" = $ak } -TimeoutSec 10 -UseBasicParsing
    Pass "HTTP $($r2.StatusCode)"
    $hbOk = $true
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    $respBody = ""
    try { $respBody = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch {}
    Fail "HTTP $code - $($_.Exception.Message)"
    if ($respBody) { Write-Host "    Response: $respBody" -ForegroundColor DarkGray }
    $hbOk = $false
    $hbCode = $code
}

# =========================================================
Section "6. Tail log applicativo 30 secondi"
# =========================================================
$logFile = "C:\ProgramData\86NocConnector\logs\connector.log"
if (Test-Path $logFile) {
    $startSize = (Get-Item $logFile).Length
    Start-Sleep -Seconds 25
    $newLines = Get-Content $logFile -Tail 20
    foreach ($ln in $newLines) {
        if ($ln -match "401|ERROR|FAIL") { Write-Host "  $ln" -ForegroundColor Red }
        elseif ($ln -match "WARN") { Write-Host "  $ln" -ForegroundColor Yellow }
        elseif ($ln -match "200|inviato|metric") { Write-Host "  $ln" -ForegroundColor Green }
        else { Write-Host "  $ln" -ForegroundColor Gray }
    }
} else { Warn2 "Log connector.log non trovato" }

# =========================================================
Section "DIAGNOSI FINALE + NEXT STEP"
# =========================================================
Write-Host ""

if ($apiOk -and $hbOk) {
    Write-Host "  IL CONNECTOR PUO' COMUNICARE COL CENTER PROD" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Vai su https://argus.86bit.it" -ForegroundColor Yellow
    Write-Host "  Pagina /connectors -> dovresti vedere GALVANSRV con stato 'connesso'"
    Write-Host "  Pagina cliente -> i 4 device polled"
} elseif ($apiOk -and -not $hbOk) {
    Write-Host "  device-report OK ma /heartbeat schema NUOVO rifiutato (HTTP $hbCode)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Significa: il backend prod accetta dati nel formato vecchio v3.5.8" -ForegroundColor White
    Write-Host "  ma rifiuta lo schema /heartbeat che il connector v3.5.23 vuole inviare."
    Write-Host ""
    Write-Host "  -> SOLUZIONE: deploy del backend Python aggiornato su IIS" -ForegroundColor Yellow
    Write-Host "  -> Pacchetto: https://device-monitor-94.preview.emergentagent.com/downloads/argus-backend-deploy.zip"
} elseif (-not $apiOk -and $apiCode -eq 401) {
    Write-Host "  API KEY NON VALIDA sul prod (HTTP 401)" -ForegroundColor Red
    Write-Host ""
    Write-Host "  La chiave $($ak.Substring(0,8))...$($ak.Substring($ak.Length-4)) NON e' accettata da $url" -ForegroundColor Yellow
    Write-Host "  -> Login admin sul Center prod e rigenera la API Key per il cliente Galvan"
    Write-Host "  -> Poi modifica $cfgPath e sostituisci campo 'api_key'"
    Write-Host "  -> Restart-Service 86NocConnectorService"
} elseif ($apiCode -eq 502 -or $apiCode -eq 503 -or $apiCode -eq 504) {
    Write-Host "  Backend prod IIS INSTABILE (HTTP $apiCode)" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Il backend Python su IIS sta dando errori 5xx. Verifica:" -ForegroundColor Yellow
    Write-Host "    - App Pool IIS: Started?"
    Write-Host "    - Worker Python: in restart loop?"
    Write-Host "    - Memoria/CPU del server: limite raggiunto?"
} else {
    Write-Host "  Stato anomalo (api_code=$apiCode hb_code=$hbCode)" -ForegroundColor Yellow
    Write-Host "  Manda log: $tFile" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "  Log completo: $tFile" -ForegroundColor Gray
try { Stop-Transcript | Out-Null } catch {}
Read-Host "INVIO per chiudere"
