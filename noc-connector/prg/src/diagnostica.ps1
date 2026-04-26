<#
.SYNOPSIS
    86NocConnector - Script di Diagnostica
.DESCRIPTION
    Verifica la connettivita' e la configurazione del connettore.
    Eseguire come Amministratore per i test completi.
#>

$AppName = "86NocConnector"
$BaseDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ConfigDir = Join-Path $env:ProgramData $AppName
$ConfigPath = Join-Path $ConfigDir "config.json"
$LogPath = Join-Path $ConfigDir "logs\connector.log"
$VersionFile = Join-Path $BaseDir "version.json"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  $AppName - DIAGNOSTICA" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check version
Write-Host "[1] VERSIONE" -ForegroundColor Yellow
if (Test-Path $VersionFile) {
    $vInfo = Get-Content $VersionFile -Raw | ConvertFrom-Json
    Write-Host "    Versione installata: v$($vInfo.version)" -ForegroundColor Green
} else {
    Write-Host "    ERRORE: version.json non trovato in $BaseDir" -ForegroundColor Red
}
Write-Host ""

# 2. Check config
Write-Host "[2] CONFIGURAZIONE" -ForegroundColor Yellow
if (Test-Path $ConfigPath) {
    $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    Write-Host "    Config trovata: $ConfigPath" -ForegroundColor Green
    Write-Host "    NOC URL: $($config.noc_center_url)" -ForegroundColor White
    Write-Host "    API Key: $($config.api_key.Substring(0, [Math]::Min(15, $config.api_key.Length)))..." -ForegroundColor White
    Write-Host "    SNMP Port: $($config.snmp_trap_port)" -ForegroundColor White
    Write-Host "    Syslog Port: $($config.syslog_port)" -ForegroundColor White
    if ($config.devices) {
        Write-Host "    Dispositivi: $($config.devices.Count)" -ForegroundColor White
    }
} else {
    Write-Host "    ERRORE: config.json non trovato!" -ForegroundColor Red
    Write-Host "    Percorso atteso: $ConfigPath" -ForegroundColor Red
    Write-Host "    Esegui install.bat per creare la configurazione." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Premi un tasto per uscire..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit
}
Write-Host ""

# 3. Test DNS resolution
Write-Host "[3] RISOLUZIONE DNS" -ForegroundColor Yellow
$nocUrl = $config.noc_center_url
try {
    $uri = [System.Uri]$nocUrl
    $hostname = $uri.Host
    $dns = [System.Net.Dns]::GetHostAddresses($hostname)
    Write-Host "    $hostname -> $($dns[0])" -ForegroundColor Green
} catch {
    Write-Host "    ERRORE DNS: impossibile risolvere $hostname" -ForegroundColor Red
    Write-Host "    Dettaglio: $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# 4. Test HTTPS connectivity
Write-Host "[4] CONNETTIVITA' HTTPS" -ForegroundColor Yellow
try {
    $testUrl = "$nocUrl/api/health"
    Write-Host "    Test: $testUrl"
    $response = Invoke-WebRequest -Uri $testUrl -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    Write-Host "    Stato: $($response.StatusCode) - OK" -ForegroundColor Green
} catch {
    Write-Host "    ERRORE: $($_.Exception.Message)" -ForegroundColor Red
    
    # Check if it's a certificate error
    if ($_.Exception.Message -match "SSL|certificate|TLS") {
        Write-Host "    Probabile problema certificato SSL. Provare:" -ForegroundColor Yellow
        Write-Host "    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12" -ForegroundColor Gray
    }
}
Write-Host ""

# 5. Test API Key (heartbeat)
Write-Host "[5] TEST API KEY (Heartbeat)" -ForegroundColor Yellow
try {
    $headers = @{
        "X-API-Key" = $config.api_key
        "Content-Type" = "application/json"
    }
    $body = @{
        connector_version = if (Test-Path $VersionFile) { (Get-Content $VersionFile -Raw | ConvertFrom-Json).version } else { "unknown" }
        hostname = $env:COMPUTERNAME
        uptime_seconds = 0
        traps_received = 0
        syslogs_received = 0
    } | ConvertTo-Json -Compress
    
    $url = "$nocUrl/api/connector/heartbeat"
    Write-Host "    Invio heartbeat a: $url"
    $response = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15 -ErrorAction Stop
    Write-Host "    Risposta: $($response | ConvertTo-Json -Compress)" -ForegroundColor Green
    Write-Host "    HEARTBEAT INVIATO CON SUCCESSO!" -ForegroundColor Green
} catch {
    Write-Host "    ERRORE HEARTBEAT: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
        Write-Host "    HTTP Status: $statusCode" -ForegroundColor Red
        if ($statusCode -eq 401 -or $statusCode -eq 403) {
            Write-Host "    API Key non valida o scaduta. Verificare nella pagina Clienti del SOC." -ForegroundColor Yellow
        }
    }
}
Write-Host ""

# 6. Check running processes
Write-Host "[6] PROCESSI IN ESECUZIONE" -ForegroundColor Yellow
$found = $false
Get-Process -Name powershell, pwsh -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        if ($cmdLine -match "tray_app\.ps1|connector\.ps1|86NocConnector") {
            Write-Host "    PID $($_.Id): $cmdLine" -ForegroundColor Green
            $found = $true
        }
    } catch {}
}
if (-not $found) {
    Write-Host "    Nessun processo 86NocConnector trovato in esecuzione." -ForegroundColor Yellow
}
Write-Host ""

# 7. Check log
Write-Host "[7] ULTIMI LOG" -ForegroundColor Yellow
if (Test-Path $LogPath) {
    Write-Host "    File: $LogPath" -ForegroundColor White
    $lines = Get-Content $LogPath -Tail 10
    foreach ($line in $lines) {
        $color = if ($line -match "ERROR") { "Red" } elseif ($line -match "WARN") { "Yellow" } else { "Gray" }
        Write-Host "    $line" -ForegroundColor $color
    }
} else {
    Write-Host "    Nessun file log trovato. Il connector non e' mai stato avviato." -ForegroundColor Yellow
}
Write-Host ""

# 8. Check ports
Write-Host "[8] PORTE UDP" -ForegroundColor Yellow
$snmpPort = if ($config.snmp_trap_port) { $config.snmp_trap_port } else { 162 }
$syslogPort = if ($config.syslog_port) { $config.syslog_port } else { 514 }

foreach ($port in @($snmpPort, $syslogPort)) {
    $portName = if ($port -eq $snmpPort) { "SNMP Trap" } else { "Syslog" }
    try {
        $udp = New-Object System.Net.Sockets.UdpClient($port)
        $udp.Close()
        Write-Host "    Porta UDP/$port ($portName): DISPONIBILE" -ForegroundColor Green
    } catch {
        Write-Host "    Porta UDP/$port ($portName): OCCUPATA o bloccata" -ForegroundColor Red
        Write-Host "    Dettaglio: $($_.Exception.Message)" -ForegroundColor Gray
    }
}
Write-Host ""

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  DIAGNOSTICA COMPLETATA" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Se hai problemi, invia l'output di questo script a supporto@86bit.it" -ForegroundColor White
Write-Host ""
Write-Host "Premi un tasto per uscire..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
