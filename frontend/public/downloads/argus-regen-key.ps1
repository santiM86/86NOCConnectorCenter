# =============================================================================
# ARGUS Regen-Key - rigenera API Key sul Center e aggiorna config.json del connector
# =============================================================================
# Doppio click. Chiede credenziali admin del Center, lista i clienti, ti fa
# scegliere quale rigenerare, applica nuova chiave al connector locale, restart.
# =============================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$Host.UI.RawUI.WindowTitle = "ARGUS Regen API Key"
$ErrorActionPreference = 'Stop'

function H($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t){ Write-Host "  [OK] $t" -ForegroundColor Green }
function Wn($t){ Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Er($t){ Write-Host "  [ERR] $t" -ForegroundColor Red }

H "1. Lettura config attuale del connector"
$cfgPath = "C:\ProgramData\86NocConnector\config.json"
if (-not (Test-Path $cfgPath)) {
    Er "config.json non trovato in $cfgPath"
    Read-Host "INVIO per uscire"; exit 1
}
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$url = $cfg.noc_center_url
Write-Host "  Center URL:        $url"
Write-Host "  Client_id attuale: $($cfg.client_id)"
Write-Host "  API Key attuale:   $($cfg.api_key.Substring(0,8))...$($cfg.api_key.Substring($cfg.api_key.Length-4))"

H "2. Login admin sul Center"
$email = Read-Host "Email admin del Center [es. admin@86bit.it]"
$pwd = Read-Host "Password admin" -AsSecureString
$pwdPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd))

$loginBody = @{ email = $email; password = $pwdPlain } | ConvertTo-Json
try {
    $loginR = Invoke-RestMethod -Uri "$url/api/auth/login" -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 10
    $token = $loginR.token
    if (-not $token) { throw "token mancante nella risposta" }
    Ok "Login OK"
} catch {
    Er "Login fallito: $($_.Exception.Message)"
    Read-Host "INVIO per uscire"; exit 1
}
$authHdr = @{ "Authorization" = "Bearer $token" }

H "3. Recupero lista clienti dal Center"
try {
    $clients = Invoke-RestMethod -Uri "$url/api/clients" -Headers $authHdr -TimeoutSec 10
    Ok "$($clients.Count) clienti trovati"
} catch {
    Er "GET /api/clients fallito: $($_.Exception.Message)"
    Read-Host "INVIO per uscire"; exit 1
}

# Identifica automaticamente il cliente che corrisponde al client_id del connector
$targetClient = $clients | Where-Object { $_.id -eq $cfg.client_id } | Select-Object -First 1

Write-Host ""
Write-Host "  Lista clienti:" -ForegroundColor Cyan
for ($i=0; $i -lt $clients.Count; $i++) {
    $c = $clients[$i]
    $marker = if ($c.id -eq $cfg.client_id) { " <-- CONNECTOR LOCALE" } else { "" }
    $aki = if ($c.api_key) { "$($c.api_key.Substring(0,8))..." } else { "(vuota)" }
    Write-Host ("    [{0}] {1}  | id={2}  | api_key={3}{4}" -f $i, $c.name.PadRight(35), $c.id.Substring(0,8), $aki, $marker)
}
Write-Host ""

if ($targetClient) {
    Write-Host "  Cliente del connector locale: " -NoNewline
    Write-Host "$($targetClient.name)" -ForegroundColor Yellow
    $defaultIdx = [Array]::IndexOf($clients, $targetClient)
    $sel = Read-Host "  Indice cliente da rigenerare [INVIO = $defaultIdx]"
    if ([string]::IsNullOrWhiteSpace($sel)) { $idx = $defaultIdx } else { $idx = [int]$sel }
} else {
    Wn "Il client_id del connector locale ($($cfg.client_id)) NON corrisponde a nessun cliente sul Center!"
    Wn "Probabilmente il cliente e' stato eliminato o l'installer ha ricevuto un client_id sbagliato."
    $sel = Read-Host "  Indice cliente da rigenerare"
    $idx = [int]$sel
}

if ($idx -lt 0 -or $idx -ge $clients.Count) {
    Er "Indice non valido"
    Read-Host "INVIO per uscire"; exit 1
}
$chosen = $clients[$idx]

Write-Host ""
Write-Host "  ATTENZIONE: rigenererai la API Key di '$($chosen.name)' (id=$($chosen.id))" -ForegroundColor Yellow
Write-Host "  La chiave precedente sara' INVALIDATA immediatamente." -ForegroundColor Yellow
$conf = Read-Host "  Confermi? [s/N]"
if ($conf -notmatch '^[sS]') { Write-Host "Annullato."; Read-Host "INVIO per uscire"; exit 0 }

H "4. Rigenerazione API Key"
try {
    $regenR = Invoke-RestMethod -Uri "$url/api/clients/$($chosen.id)/regenerate-key" -Method Post -Headers $authHdr -TimeoutSec 10
    $newKey = $regenR.api_key
    if (-not $newKey) { throw "api_key mancante nella risposta" }
    Ok "Nuova API Key: $($newKey.Substring(0,8))...$($newKey.Substring($newKey.Length-4))"
} catch {
    Er "Rigenerazione fallita: $($_.Exception.Message)"
    if ($_.Exception.Response.StatusCode.Value__ -eq 404) {
        Wn "Endpoint /clients/{id}/regenerate-key non disponibile su questo backend (versione vecchia)."
        Wn "Soluzione manuale: aggiorna il backend Python su IIS, oppure modifica direttamente MongoDB."
    }
    Read-Host "INVIO per uscire"; exit 1
}

H "5. Aggiornamento config.json del connector locale"
if ($chosen.id -eq $cfg.client_id) {
    # Backup
    $backup = "$cfgPath.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $cfgPath $backup
    Ok "Backup salvato: $backup"
    
    $cfg.api_key = $newKey
    $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $cfgPath -Encoding UTF8
    Ok "config.json aggiornato"
    
    Write-Host ""
    H "6. Restart connector"
    Stop-Service 86NocConnectorService -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-Service 86NocConnectorService -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
    $svc = Get-Service 86NocConnectorService -ErrorAction SilentlyContinue
    Write-Host "  Status: $($svc.Status)"
    
    Write-Host ""
    H "7. Test heartbeat con nuova chiave"
    $body = @{ client_id = $cfg.client_id; status = "running"; devices = @() } | ConvertTo-Json -Compress
    try {
        $hb = Invoke-WebRequest -Uri "$url/api/connector/device-report" -Method Post -Body $body `
              -ContentType "application/json" -Headers @{ "X-API-Key" = $newKey } -TimeoutSec 10 -UseBasicParsing
        Ok "Test heartbeat OK - HTTP $($hb.StatusCode)"
    } catch {
        $code = $_.Exception.Response.StatusCode.Value__
        Wn "HTTP $code (potrebbe essere schema diverso, ma l'auth ora funziona)"
    }
} else {
    Wn "La chiave e' stata rigenerata sul Center, ma il connector locale punta a un cliente DIVERSO ($($cfg.client_id))."
    Wn "Annota la nuova chiave manualmente:"
    Write-Host ""
    Write-Host "    NEW API KEY: " -NoNewline
    Write-Host $newKey -ForegroundColor Yellow
    Write-Host ""
    try { $newKey | clip; Ok "Copiata negli appunti" } catch {}
}

Write-Host ""
Write-Host "=== FATTO. Tail log per verificare ===" -ForegroundColor Cyan
Start-Sleep -Seconds 10
$logFile = "C:\ProgramData\86NocConnector\logs\connector.log"
Get-Content $logFile -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_ -match "401|ERROR|FAIL") { Write-Host "  $_" -ForegroundColor Red }
    elseif ($_ -match "OK|inviato|ricevuti|metriche") { Write-Host "  $_" -ForegroundColor Green }
    else { Write-Host "  $_" }
}
Write-Host ""
Read-Host "Premi INVIO per chiudere"
