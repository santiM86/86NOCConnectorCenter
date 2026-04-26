# =============================================================================
# ARGUS Connector — Diagnostica automatica (v1)
# =============================================================================
# Esegui questo file con doppio click (richiede UAC).
# Scrive un report dettagliato in C:\Temp\argus-diag-<timestamp>.txt
# Manda quel file all'agente per analisi.
# =============================================================================

# Auto-elevation (chiede UAC se non Admin)
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$ErrorActionPreference = 'Continue'
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$out = "C:\Temp\argus-diag-$ts.txt"
if (-not (Test-Path "C:\Temp")) { New-Item -ItemType Directory -Path "C:\Temp" -Force | Out-Null }

function Section($title) {
    $line = "=" * 78
    Add-Content -Path $out -Value ""
    Add-Content -Path $out -Value $line
    Add-Content -Path $out -Value " $title"
    Add-Content -Path $out -Value $line
    Write-Host "`n$line" -ForegroundColor Cyan
    Write-Host " $title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
}
function Log($msg) {
    Add-Content -Path $out -Value $msg
    Write-Host $msg
}

"ARGUS Diagnostica - $ts" | Set-Content -Path $out
Log "Server: $env:COMPUTERNAME"
Log "User:   $env:USERNAME"
Log "OS:     $((Get-CimInstance Win32_OperatingSystem).Caption) $((Get-CimInstance Win32_OperatingSystem).Version)"
Log "PSVer:  $($PSVersionTable.PSVersion)"

# ======================================================================
Section "1. CONFIG.JSON del connector"
# ======================================================================
$cfgPath = "C:\ProgramData\86NocConnector\config.json"
if (Test-Path $cfgPath) {
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    Log "  noc_center_url: $($cfg.noc_center_url)"
    Log "  client_id:      $($cfg.client_id)"
    $maskedKey = if ($cfg.api_key) { $cfg.api_key.Substring(0,8) + "..." + $cfg.api_key.Substring($cfg.api_key.Length - 4) } else { "(vuota)" }
    Log "  api_key:        $maskedKey"
    Log "  devices count:  $($cfg.devices.Count)"
    Log "  hb_interval:    $($cfg.heartbeat_interval_seconds)s"
    Log "  poll_interval:  $($cfg.poll_interval_seconds)s"
} else {
    Log "  ERRORE: config.json non trovato in $cfgPath"
    Log "  STOP - re-installare il connector"
    Read-Host "`nPremi INVIO per uscire"
    exit 1
}
$url = $cfg.noc_center_url
$host_only = ([Uri]$url).Host

# ======================================================================
Section "2. STATO SERVIZIO NSSM"
# ======================================================================
$svc = Get-Service 86NocConnectorService -ErrorAction SilentlyContinue
if ($svc) {
    Log "  Status:    $($svc.Status)"
    Log "  StartType: $($svc.StartType)"
    Log "  CanStop:   $($svc.CanStop)"
    if ($svc.Status -ne 'Running') {
        Log "  ATTENZIONE: il servizio non gira ($($svc.Status))"
    }
} else {
    Log "  ERRORE: servizio non installato"
}

# ======================================================================
Section "3. RAGGIUNGIBILITA CENTER"
# ======================================================================
Log "  Test DNS '$host_only':"
$dns = Resolve-DnsName $host_only -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress }
if ($dns) {
    foreach ($r in $dns) { Log "    -> $($r.IPAddress)" }
} else {
    Log "    FAIL DNS"
}
Log ""
Log "  Test TCP $host_only`:443:"
$tcp = Test-NetConnection -ComputerName $host_only -Port 443 -WarningAction SilentlyContinue -InformationLevel Quiet
Log "    Connection: $tcp"

# ======================================================================
Section "4. HEALTH CHECK CENTER"
# ======================================================================
Log "  GET $url/api/health"
try {
    $hr = Invoke-WebRequest -Uri "$url/api/health" -TimeoutSec 8 -UseBasicParsing
    Log "    HTTP $($hr.StatusCode)"
    Log "    Body: $($hr.Content)"
} catch {
    Log "    FAIL: $($_.Exception.Message)"
    Log "    StatusCode: $($_.Exception.Response.StatusCode.Value__)"
}

# ======================================================================
Section "5. HEARTBEAT MANUALE (scopre lo schema atteso dal backend)"
# ======================================================================
$body = @{
    client_id = $cfg.client_id
    connector_version = "3.5.23"
    hostname = $env:COMPUTERNAME
    status = "running"
} | ConvertTo-Json -Compress
Log "  POST $url/api/connector/heartbeat"
Log "  Body: $body"
try {
    $hb = Invoke-WebRequest -Uri "$url/api/connector/heartbeat" -Method Post `
          -Body $body -ContentType "application/json" `
          -Headers @{ "X-API-Key" = $cfg.api_key } -TimeoutSec 12 -UseBasicParsing
    Log "    HTTP $($hb.StatusCode)"
    Log "    Body: $($hb.Content)"
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    $resp = ""
    try {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object IO.StreamReader($stream)
        $resp = $reader.ReadToEnd()
    } catch {}
    Log "    FAIL HTTP $code"
    Log "    Message: $($_.Exception.Message)"
    Log "    Response body: $resp"
}

# ======================================================================
Section "6. ENDPOINT IDENTIFY (vediamo che versione di backend gira sull'IIS)"
# ======================================================================
Log "  POST $url/api/connector/identify"
$idBody = @{ api_key = $cfg.api_key } | ConvertTo-Json -Compress
try {
    $idr = Invoke-WebRequest -Uri "$url/api/connector/identify" -Method Post `
           -Body $idBody -ContentType "application/json" -TimeoutSec 8 -UseBasicParsing
    Log "    HTTP $($idr.StatusCode)"
    Log "    Body: $($idr.Content)"
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    Log "    HTTP $code (se 404 -> backend IIS produzione e' VECCHIO, manca questo endpoint)"
    Log "    Message: $($_.Exception.Message)"
}

# ======================================================================
Section "7. CERCA LOG OVUNQUE"
# ======================================================================
$logPaths = @(
    "C:\ProgramData\86NocConnector",
    "C:\Program Files\86NocConnector",
    "$env:TEMP\argus*",
    "$env:TEMP\nssm*"
)
foreach ($p in $logPaths) {
    Get-ChildItem $p -Recurse -Filter "*.log" -ErrorAction SilentlyContinue | ForEach-Object {
        Log "  $($_.FullName)  ($($_.Length) bytes, mod $($_.LastWriteTime))"
    }
}

# ======================================================================
Section "8. ULTIMI EVENTI NSSM (ultime 2 ore)"
# ======================================================================
$cutoff = (Get-Date).AddHours(-2)
$events = @()
$events += Get-WinEvent -LogName System -MaxEvents 500 -ErrorAction SilentlyContinue | 
    Where-Object { $_.TimeCreated -gt $cutoff -and ($_.Message -like "*86NocConnector*" -or $_.Message -like "*nssm*") }
$events += Get-WinEvent -LogName Application -MaxEvents 500 -ErrorAction SilentlyContinue | 
    Where-Object { $_.TimeCreated -gt $cutoff -and ($_.Message -like "*86NocConnector*") }
foreach ($e in $events | Sort-Object TimeCreated -Desc | Select -First 30) {
    Log ("  [{0}] [{1}] {2}" -f $e.TimeCreated, $e.LevelDisplayName, ($e.Message -replace "`r?`n", " | ").Substring(0, [Math]::Min(200, $e.Message.Length)))
}

# ======================================================================
Section "9. NSSM CONFIG (cosa lancia il servizio)"
# ======================================================================
$nssm = "C:\Program Files\86NocConnector\nssm.exe"
if (Test-Path $nssm) {
    Log "  Application:   $(& $nssm get 86NocConnectorService Application 2>$null)"
    Log "  AppParameters: $(& $nssm get 86NocConnectorService AppParameters 2>$null)"
    Log "  AppDirectory:  $(& $nssm get 86NocConnectorService AppDirectory 2>$null)"
    Log "  AppStdout:     $(& $nssm get 86NocConnectorService AppStdout 2>$null)"
    Log "  AppStderr:     $(& $nssm get 86NocConnectorService AppStderr 2>$null)"
}

Section "DIAGNOSTICA COMPLETATA"
Log ""
Log "Report salvato in: $out"
Log ""
Log "INVIA QUESTO FILE per analisi."
Write-Host ""
Write-Host "  >>> Apro la cartella..." -ForegroundColor Yellow
Start-Process explorer.exe -ArgumentList "/select,`"$out`""
Read-Host "`nPremi INVIO per chiudere"
