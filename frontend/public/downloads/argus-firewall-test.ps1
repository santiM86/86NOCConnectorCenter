# =============================================================================
# ARGUS Firewall-Test + Auto-Restore
# =============================================================================
# Cosa fa:
#   1. Verifica connettivita verso il Center preview Kubernetes (3 test)
#   2. Verifica connettivita verso il tuo Center prod argus.86bit.it (3 test)
#   3. Auto-ripristina il config.json al prod
#   4. Restart servizio
#   5. Stampa raccomandazione next step
# =============================================================================

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

if (-not (Test-Path "C:\Temp")) { New-Item -ItemType Directory -Path "C:\Temp" -Force | Out-Null }
$tFile = "C:\Temp\argus-firewall-test-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
try { Start-Transcript -Path $tFile -Force | Out-Null } catch {}

$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = "ARGUS Firewall-Test"

trap {
    Write-Host ""
    Write-Host "ERRORE NON GESTITO: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Posizione: $($_.InvocationInfo.PositionMessage)" -ForegroundColor Yellow
    Write-Host "Log salvato in: $tFile" -ForegroundColor Cyan
    Read-Host "INVIO per chiudere"
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Pass($t)    { Write-Host "  [OK] $t" -ForegroundColor Green }
function Warn2($t)   { Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Fail($t)    { Write-Host "  [ERR] $t" -ForegroundColor Red }

function TestHost($label, $hostname, $url) {
    $r = [PSCustomObject]@{
        Label = $label; Hostname = $hostname
        DnsOk = $false; TcpOk = $false; HttpOk = $false
        DnsIp = $null; HttpStatus = $null; HttpError = $null
    }
    Write-Host "  Testing $label ($hostname)..." -ForegroundColor Gray

    # 1. DNS
    try {
        $dns = Resolve-DnsName -Name $hostname -Type A -ErrorAction Stop -DnsOnly | Where-Object { $_.IPAddress } | Select -First 3
        if ($dns) {
            $r.DnsOk = $true
            $r.DnsIp = ($dns | ForEach-Object { $_.IPAddress }) -join ", "
            Pass "DNS: $($r.DnsIp)"
        } else { Fail "DNS: nessun IP risolto" }
    } catch { Fail "DNS: $($_.Exception.Message)" }

    # 2. TCP
    if ($r.DnsOk) {
        try {
            $tcp = Test-NetConnection -ComputerName $hostname -Port 443 -WarningAction SilentlyContinue -InformationLevel Quiet
            $r.TcpOk = $tcp
            if ($tcp) { Pass "TCP 443: connessione riuscita" } else { Fail "TCP 443: NON raggiungibile (firewall?)" }
        } catch { Fail "TCP 443: $($_.Exception.Message)" }
    }

    # 3. HTTP
    if ($r.TcpOk) {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
            $h = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 8
            $r.HttpOk = ($h.StatusCode -eq 200)
            $r.HttpStatus = $h.StatusCode
            if ($r.HttpOk) { Pass "HTTP /api/health: $($h.StatusCode) - $($h.Content)" }
            else { Warn2 "HTTP /api/health: $($h.StatusCode)" }
        } catch {
            $r.HttpError = $_.Exception.Message
            Fail "HTTP /api/health: $($_.Exception.Message)"
        }
    }
    return $r
}

Section "ARGUS Firewall Test + Auto-Restore"
Write-Host "  Testa connettivita verso 2 Center e ripristina config al prod"

Section "1. Test Center PREVIEW (Kubernetes)"
$r1 = TestHost "Preview" "noc-monitor-hub.preview.emergentagent.com" "https://device-poller-ws.preview.emergentagent.com"

Section "2. Test Center PROD (argus.86bit.it)"
$r2 = TestHost "Prod" "argus.86bit.it" "https://argus.86bit.it"

Section "3. Ripristino config.json al prod"
$cfgPath = "C:\ProgramData\86NocConnector\config.json"
$bk = "C:\ProgramData\86NocConnector\config.PROD-original.json"
if (Test-Path $bk) {
    Copy-Item $bk $cfgPath -Force
    Pass "Config ripristinato dal backup PROD-original"
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    Write-Host "    URL:    $($cfg.noc_center_url)"
    Write-Host "    Client: $($cfg.client_id)"
    Write-Host "    APIKey: $($cfg.api_key.Substring(0,8))...$($cfg.api_key.Substring($cfg.api_key.Length-4))"
} else {
    Warn2 "Backup PROD-original NON trovato in $bk"
    Warn2 "Il config.json potrebbe puntare ancora al preview - verifica manualmente"
}

Section "4. Restart servizio"
try {
    Stop-Service 86NocConnectorService -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-Service 86NocConnectorService -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
    $svc = Get-Service 86NocConnectorService
    Pass "Servizio: $($svc.Status)"
} catch { Fail "Restart errore: $($_.Exception.Message)" }

Section "DIAGNOSI FINALE"
Write-Host ""
Write-Host "  PREVIEW (Kubernetes):" -ForegroundColor Cyan
Write-Host ("    DNS: {0}  |  TCP 443: {1}  |  HTTP: {2}" -f `
    $(if ($r1.DnsOk) {"OK"} else {"FAIL"}), `
    $(if ($r1.TcpOk) {"OK"} else {"FAIL"}), `
    $(if ($r1.HttpOk) {"OK"} else {"FAIL"}))
Write-Host "  PROD (argus.86bit.it):" -ForegroundColor Cyan
Write-Host ("    DNS: {0}  |  TCP 443: {1}  |  HTTP: {2}" -f `
    $(if ($r2.DnsOk) {"OK"} else {"FAIL"}), `
    $(if ($r2.TcpOk) {"OK"} else {"FAIL"}), `
    $(if ($r2.HttpOk) {"OK"} else {"FAIL"}))

Write-Host ""
Write-Host "  RACCOMANDAZIONE:" -ForegroundColor Yellow
if (-not $r1.HttpOk -and $r2.HttpOk) {
    Write-Host "    -> Il firewall del cliente BLOCCA il preview Kubernetes." -ForegroundColor Red
    Write-Host "    -> Il prod argus.86bit.it e' raggiungibile." -ForegroundColor Green
    Write-Host "    -> SOLUZIONE: deploy del backend Python aggiornato su IIS." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    Pacchetto deploy:" -ForegroundColor Cyan
    Write-Host "      https://device-poller-ws.preview.emergentagent.com/downloads/argus-backend-deploy.zip" -ForegroundColor White
    Write-Host ""
    Write-Host "    Procedura assistita: dopo aver scaricato e estratto, lancia deploy.ps1 da admin" -ForegroundColor Cyan
} elseif ($r1.HttpOk -and $r2.HttpOk) {
    Write-Host "    -> ENTRAMBI raggiungibili. Il problema NON era firewall." -ForegroundColor Green
    Write-Host "    -> Probabilmente lo script Quick-Test non ha terminato in tempo." -ForegroundColor Yellow
    Write-Host "    -> Manda screenshot della finestra Quick-Test" -ForegroundColor Cyan
} elseif (-not $r2.HttpOk) {
    Write-Host "    -> Il tuo Center prod argus.86bit.it NON risponde." -ForegroundColor Red
    Write-Host "    -> Controlla che IIS sia su, App Pool started, backend FastAPI healthy." -ForegroundColor Yellow
    Write-Host "    -> Il connector non puo' funzionare in nessuno scenario in queste condizioni." -ForegroundColor Red
} else {
    Write-Host "    -> Stato anomalo, manda log:" -ForegroundColor Yellow
    Write-Host "       $tFile" -ForegroundColor White
}

Write-Host ""
Write-Host "  Log completo: $tFile" -ForegroundColor Gray
try { Stop-Transcript | Out-Null } catch {}
Read-Host "INVIO per chiudere"
