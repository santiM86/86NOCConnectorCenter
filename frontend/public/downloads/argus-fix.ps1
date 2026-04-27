# =============================================================================
# ARGUS Fix - sblocca connector v3.5.23 in 4 step automatici
# =============================================================================
# Doppio click. Risolve:
#   1. Quoting NSSM AppParameters (elimina ciclo Paused/Resumed)
#   2. Rilevamento Task Scheduler duplicati (riporta in chiaro)
#   3. Test API Key e prompt per nuova chiave
#   4. Restart pulito
# =============================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = "ARGUS Connector — Fix v1"

function H($t)  { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t) { Write-Host "  [OK] $t" -ForegroundColor Green }
function Wn($t) { Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Er($t) { Write-Host "  [ERR] $t" -ForegroundColor Red }
function Inf($t){ Write-Host "  $t" }

$nssm = "C:\Program Files\86NocConnector\nssm.exe"
$svcN = "86NocConnectorService"
$cfgPath = "C:\ProgramData\86NocConnector\config.json"
$installDir = "C:\Program Files\86NocConnector"
$psFile = "$installDir\src\connector.ps1"

H "STEP 1: STOP servizio + watchdog (per evitare riavvio durante fix)"
& schtasks.exe /End /TN "\86BIT\86NocConnector_Watchdog" 2>$null | Out-Null
Inf "Watchdog fermato"
Stop-Service $svcN -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$svc = Get-Service $svcN -ErrorAction SilentlyContinue
if ($svc) { Inf "Servizio: $($svc.Status)" } else { Wn "Servizio non trovato" }

H "STEP 2: FIX quoting NSSM AppParameters"
$newParams = "-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$psFile`""
$oldParams = & $nssm get $svcN AppParameters 2>$null
Inf "OLD: $oldParams"
Inf "NEW: $newParams"
& $nssm set $svcN AppParameters $newParams 2>&1 | Out-Null
& $nssm set $svcN AppDirectory "`"$installDir\src`"" 2>&1 | Out-Null
$check = & $nssm get $svcN AppParameters 2>$null
if ($check -like "*`"$psFile`"*") { Ok "Quoting NSSM corretto" } else { Er "Fix NSSM fallito: $check" }

H "STEP 3: RILEVA Task Scheduler che lanciano connector.ps1"
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.Actions.Execute -like "*powershell*" -and ($_.Actions.Arguments -like "*connector.ps1*" -or $_.Actions.Arguments -like "*86NocConnector*")
}
if ($tasks) {
    foreach ($t in $tasks) {
        Wn "Task: $($t.TaskPath)$($t.TaskName)"
        Inf "    Last run:  $((Get-ScheduledTaskInfo -TaskPath $t.TaskPath -TaskName $t.TaskName).LastRunTime)"
        Inf "    Next run:  $((Get-ScheduledTaskInfo -TaskPath $t.TaskPath -TaskName $t.TaskName).NextRunTime)"
        Inf "    State:     $($t.State)"
    }
    Wn "QUESTI task duplicano il servizio. Vuoi DISABILITARLI? Lascia attivo solo il servizio NSSM (raccomandato)."
    $r = Read-Host "Disabilitare i task duplicati? [s/N]"
    if ($r -match '^[sS]') {
        foreach ($t in $tasks) {
            try {
                Disable-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName -ErrorAction Stop | Out-Null
                Ok "Disabled: $($t.TaskPath)$($t.TaskName)"
            } catch { Er "Disable fallito $($t.TaskName): $($_.Exception.Message)" }
        }
    }
} else {
    Inf "Nessun task scheduler trovato che lancia il connector."
}

H "STEP 4: TEST API KEY corrente verso il Center"
if (-not (Test-Path $cfgPath)) {
    Er "config.json non trovato in $cfgPath"
    Read-Host "Premi INVIO per uscire"; exit 1
}
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$url = $cfg.noc_center_url
$cid = $cfg.client_id
$ak  = $cfg.api_key
Inf "Center:    $url"
Inf "Client ID: $cid"
Inf "API Key:   $($ak.Substring(0,8))...$($ak.Substring($ak.Length-4))"

# Endpoint v3.5.8 attualmente attivo sul tuo IIS prod
$body = @{ client_id = $cid; status = "running"; devices = @() } | ConvertTo-Json -Compress
try {
    $r = Invoke-WebRequest -Uri "$url/api/connector/device-report" -Method Post -Body $body `
         -ContentType "application/json" -Headers @{ "X-API-Key" = $ak } -TimeoutSec 10 -UseBasicParsing
    Ok "API Key VALIDA - HTTP $($r.StatusCode)"
    Inf "Body: $($r.Content)"
    $apiOk = $true
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    if ($code -eq 401) {
        Er "HTTP 401 - API Key NON valida. DEVI rigenerare la chiave dal Center."
    } else {
        Wn "HTTP $code - $($_.Exception.Message)"
    }
    $apiOk = $false
}

if (-not $apiOk) {
    Write-Host ""
    Write-Host "AZIONE RICHIESTA:" -ForegroundColor Yellow
    Write-Host "  1. Apri sul tuo Center: $url" -ForegroundColor Yellow
    Write-Host "  2. Login admin > Clienti > seleziona il cliente di GALVANSRV > Rigenera API Key" -ForegroundColor Yellow
    Write-Host "  3. Copia la NUOVA chiave (formato: noc_xxxxxxxxxxxxxxxxxxxxxx)" -ForegroundColor Yellow
    Write-Host ""
    $newKey = Read-Host "Incolla qui la NUOVA API Key (o INVIO per saltare)"
    if ($newKey -match '^noc_[a-f0-9]{32}$') {
        # Test la nuova chiave
        try {
            $r = Invoke-WebRequest -Uri "$url/api/connector/device-report" -Method Post -Body $body `
                 -ContentType "application/json" -Headers @{ "X-API-Key" = $newKey } -TimeoutSec 10 -UseBasicParsing
            Ok "Nuova API Key VALIDATA - HTTP $($r.StatusCode)"
            $cfg.api_key = $newKey
            $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $cfgPath -Encoding UTF8
            Ok "config.json aggiornato"
        } catch {
            Er "Anche la nuova chiave fallisce: $($_.Exception.Message)"
        }
    } elseif ($newKey -ne "") {
        Wn "Formato chiave non valido (atteso: noc_<32 hex>). Modifica manualmente $cfgPath"
    }
}

H "STEP 5: RIAVVIO PULITO"
Start-Service $svcN -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
$svc = Get-Service $svcN -ErrorAction SilentlyContinue
if ($svc.Status -eq 'Running') {
    Ok "Servizio: Running"
} elseif ($svc.Status -eq 'Paused') {
    Er "Servizio: ANCORA Paused. Esamina service_stderr.log per dettagli aggiornati"
} else {
    Wn "Servizio: $($svc.Status)"
}

# Riabilita watchdog
& schtasks.exe /Run /TN "\86BIT\86NocConnector_Watchdog" 2>$null | Out-Null

H "STATO FINALE — controlla il log applicativo"
Write-Host ""
Inf "Tail connector.log (entro 30 secondi dovresti vedere ciclo SNMP + heartbeat OK):"
Write-Host ""
$logFile = "C:\ProgramData\86NocConnector\logs\connector.log"
$startSize = (Get-Item $logFile -ErrorAction SilentlyContinue).Length
Start-Sleep -Seconds 25
Get-Content $logFile -Tail 25 | ForEach-Object {
    if ($_ -match "401|ERROR|FAIL") { Write-Host "  $_" -ForegroundColor Red }
    elseif ($_ -match "WARN") { Write-Host "  $_" -ForegroundColor Yellow }
    elseif ($_ -match "OK|inviato|ricevuti") { Write-Host "  $_" -ForegroundColor Green }
    else { Write-Host "  $_" }
}

Write-Host ""
Read-Host "Premi INVIO per chiudere"
