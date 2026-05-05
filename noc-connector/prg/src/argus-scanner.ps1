# =============================================================================
# 86NocConnector — ARGUS LAN Scanner v3.8.1
# =============================================================================
# Modalita': SCANNER (discovery LAN passivo via ARP/mDNS/SNMP locale).
# Si "aggancia" al cliente nel Center via API key.
# Compatibile con Windows PowerShell 5.1+ e PowerShell 7+.
# Esegui come Admin per ARP scan completo. Senza Admin = solo SNMP/mDNS.
#
# v3.8.1 fix:
#   - Rimosso ForEach-Object -Parallel (PS7+ only) che faceva morire lo scanner su PS5.1
#   - ErrorActionPreference = Continue nel loop principale per non terminare a errori
#   - Logging completo su file (C:\ProgramData\86NocConnector\scanner.log)
#   - Try/catch difensivi su ARP/mDNS scan
#   - Esposta funzione Invoke-LanScanOnce per uso esterno (tray app, wizard)
# =============================================================================

param(
    [switch]$Setup,           # Forza riconfigurazione (anche se config esiste)
    [switch]$Test,            # Test connessione + lista endpoint senza salvare
    [switch]$ScanOnce,        # Esegue una sola scansione e invia al Center, poi exit
    [switch]$AsLibrary,       # Carica funzioni senza eseguire entry point (per dot-source)
    [string]$ConfigPath = "$env:ProgramData\86NocConnector\scanner-config.json",
    [string]$LogPath = "$env:ProgramData\86NocConnector\scanner.log"
)

# v3.8.1: nel loop usiamo Continue per non far morire lo script su un errore singolo.
# Lo lasciamo Stop solo durante setup/wizard (errori critici devono interrompere).
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "ARGUS LAN Scanner v3.8.1"

# ---------- LOGGING ----------
function Write-Log([string]$Level, [string]$Message) {
    $ts = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$Level] $Message"
    try {
        $dir = Split-Path $LogPath -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Add-Content -Path $LogPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
    $color = switch ($Level) {
        "ERR"  { "Red" }
        "WARN" { "Yellow" }
        "OK"   { "Green" }
        "INFO" { "Cyan" }
        default { "Gray" }
    }
    Write-Host $line -ForegroundColor $color
}

# ---------- BANNER ----------
function Show-Banner {
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "    ARGUS  ::  86NocConnector  Scanner Mode  v3.8.1" -ForegroundColor Cyan
    Write-Host "    Discovery LAN cross-VLAN per il Center NOC" -ForegroundColor DarkCyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# ---------- CRIPTAZIONE LOCALE (DPAPI Windows) ----------
function Protect-String([string]$Plain) {
    $secure = ConvertTo-SecureString $Plain -AsPlainText -Force
    return $secure | ConvertFrom-SecureString
}
function Unprotect-String([string]$Cipher) {
    if ([string]::IsNullOrEmpty($Cipher)) { return "" }
    try {
        $secure = ConvertTo-SecureString $Cipher
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } catch {
        Write-Log "WARN" "Decrypt fallito (config corrotto o eseguito da utente diverso)"
        return ""
    }
}

# ---------- WIZARD SETUP ----------
function Invoke-SetupWizard {
    Show-Banner
    Write-Host "  CONFIGURAZIONE INIZIALE" -ForegroundColor Yellow
    Write-Host "  Inserisci i dati che ti ha fornito il NOC Center."
    Write-Host ""

    $centerUrl = Read-Host "  URL Center (es. https://argus.86bit.it)"
    if (-not $centerUrl.StartsWith("http")) { $centerUrl = "https://$centerUrl" }
    $centerUrl = $centerUrl.TrimEnd("/")

    Write-Host ""
    Write-Host "  API Key cliente (visibile su 'Gestione Clienti' nel Center):" -ForegroundColor Yellow
    $apiKey = Read-Host "  API Key" -AsSecureString
    $apiKeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($apiKey))
    if ($apiKeyPlain.Length -lt 8) { throw "API Key troppo corta" }

    Write-Host ""
    Write-Host "  Modalita' di funzionamento:" -ForegroundColor Yellow
    Write-Host "    [1] MASTER  - Polling completo (1 per sito, gia' configurato altrove?)"
    Write-Host "    [2] SCANNER - Discovery LAN locale (consigliato per VLAN aggiuntive)"
    $modeChoice = Read-Host "  Scelta (1 o 2)"
    $mode = if ($modeChoice -eq "1") { "master" } else { "scanner" }

    $subnet = ""
    $vlanId = $null
    $hostnameOverride = $env:COMPUTERNAME
    if ($mode -eq "scanner") {
        # Auto-detect IP locale + subnet /24
        $localIp = $null
        try {
            $localIp = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual `
                -ErrorAction SilentlyContinue | Where-Object {$_.IPAddress -notlike "169.254.*"} `
                | Select-Object -First 1).IPAddress
        } catch {}
        if (-not $localIp) {
            try { $localIp = (Test-Connection -ComputerName "127.0.0.1" -Count 1).IPV4Address.IPAddressToString } catch {}
        }
        $defaultSubnet = if ($localIp) { ($localIp -replace "\.\d+$",".0/24") } else { "" }
        Write-Host ""
        $subnet = Read-Host "  Subnet locale da scansionare [$defaultSubnet]"
        if (-not $subnet) { $subnet = $defaultSubnet }
        $vlanInput = Read-Host "  VLAN ID (opzionale, lascia vuoto se non sai)"
        if ($vlanInput -match "^\d+$") { $vlanId = [int]$vlanInput }

        # v3.8.1: se sulla stessa macchina gira gia' un master, suffisso "-scanner"
        # per evitare collisione di hostname nel Center.
        $hbCheck = $null
        try {
            $hbCheck = Invoke-RestMethod -Uri "$centerUrl/api/connector/by-hostname/$env:COMPUTERNAME" `
                -Method GET -Headers @{ "X-API-Key" = $apiKeyPlain } -TimeoutSec 5
        } catch {}
        if ($hbCheck -and $hbCheck.mode -eq "master") {
            $hostnameOverride = "$env:COMPUTERNAME-scanner"
            Write-Host "  [INFO] Master gia' presente con hostname '$env:COMPUTERNAME'." -ForegroundColor DarkCyan
            Write-Host "         Lo scanner si registrera' come '$hostnameOverride' per evitare conflitti." -ForegroundColor DarkCyan
        }
    }

    $config = @{
        center_url = $centerUrl
        api_key_encrypted = Protect-String $apiKeyPlain
        mode = $mode
        subnet = $subnet
        vlan_id = $vlanId
        hostname = $hostnameOverride
        scan_interval_seconds = 300
        heartbeat_interval_seconds = 60
        version = "3.8.1"
        installed_at = (Get-Date -Format "o")
    }

    $cfgDir = Split-Path $ConfigPath -Parent
    if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null }
    $config | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigPath -Encoding UTF8
    Write-Host ""
    Write-Host "  [OK] Configurazione salvata in: $ConfigPath" -ForegroundColor Green
    Write-Host "       Hostname registrato: $hostnameOverride" -ForegroundColor DarkGray
    Write-Host ""

    Test-Hookup -Config $config
    return $config
}

function Get-Config {
    if (-not (Test-Path $ConfigPath)) { return $null }
    return Get-Content $ConfigPath -Raw | ConvertFrom-Json
}

# ---------- AGGANCIO + HEARTBEAT ----------
function Test-Hookup($Config) {
    $apiKey = Unprotect-String $Config.api_key_encrypted
    try {
        $body = @{
            connector_version = $Config.version
            hostname = $Config.hostname
            uptime_seconds = 0
            traps_received = 0
            syslogs_received = 0
            mode = $Config.mode
            subnet = $Config.subnet
            vlan_id = $Config.vlan_id
        } | ConvertTo-Json -Compress
        $r = Invoke-RestMethod -Uri "$($Config.center_url)/api/connector/heartbeat" `
            -Method POST -Headers @{ "X-API-Key" = $apiKey } `
            -Body $body -ContentType "application/json" -TimeoutSec 10
        Write-Log "OK" "Heartbeat OK ($($Config.mode) - $($Config.hostname))"
        return $true
    } catch {
        Write-Log "ERR" "Heartbeat fallito: $($_.Exception.Message)"
        return $false
    }
}

# ---------- ARP SCAN LOCALE (compat PS5.1: nessun -Parallel) ----------
function Invoke-ArpScan([string]$Subnet) {
    $endpoints = @()
    if (-not $Subnet) { Write-Log "WARN" "ARP scan saltato: subnet vuota"; return $endpoints }
    try {
        $base = ($Subnet -split "/")[0] -replace "\.0$","."
        # Trigger ARP refresh: ping seriale veloce (1 al volo, timeout 1s)
        # PS5.1-safe: usiamo Start-Job a piccoli batch per non bloccare 250s
        $jobs = @()
        1..254 | ForEach-Object {
            $ip = "$base$_"
            $jobs += Start-Job -ScriptBlock {
                param($targetIp)
                try { Test-Connection -ComputerName $targetIp -Count 1 -BufferSize 16 -Quiet -ErrorAction SilentlyContinue | Out-Null } catch {}
            } -ArgumentList $ip
            # Limita 50 job paralleli a rotazione
            if ($jobs.Count -ge 50) {
                $jobs | Wait-Job -Timeout 2 | Out-Null
                $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
                $jobs = @()
            }
        }
        if ($jobs.Count -gt 0) {
            $jobs | Wait-Job -Timeout 3 | Out-Null
            $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
        }

        # Leggi tabella ARP
        Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.State -in @("Reachable","Stale","Permanent") -and $_.LinkLayerAddress -and $_.LinkLayerAddress -ne "00-00-00-00-00-00" } |
            ForEach-Object {
                $endpoints += [PSCustomObject]@{
                    mac = ($_.LinkLayerAddress -replace "-",":").ToLower()
                    ip = $_.IPAddress
                    discovered_via = "arp"
                }
            }
        Write-Log "INFO" "ARP scan completato: $($endpoints.Count) endpoint trovati"
    } catch {
        Write-Log "ERR" "ARP scan exception: $($_.Exception.Message)"
    }
    return $endpoints
}

# ---------- mDNS DISCOVERY (224.0.0.251:5353) ----------
function Invoke-MdnsDiscovery {
    $endpoints = @()
    $udpClient = $null
    try {
        $udpClient = New-Object System.Net.Sockets.UdpClient
        $udpClient.Client.ReceiveTimeout = 3000
        $endpoint = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse("224.0.0.251"), 5353)
        $query = [byte[]](0,0,0,0,0,1,0,0,0,0,0,0,9,0x5f,0x73,0x65,0x72,0x76,0x69,0x63,0x65,0x73,7,0x5f,0x64,0x6e,0x73,0x2d,0x73,0x64,4,0x5f,0x75,0x64,0x70,5,0x6c,0x6f,0x63,0x61,0x6c,0,0,12,0,1)
        $udpClient.Send($query, $query.Length, $endpoint) | Out-Null
        $start = Get-Date
        while (((Get-Date) - $start).TotalSeconds -lt 3) {
            try {
                $remote = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
                $resp = $udpClient.Receive([ref]$remote)
                if ($resp.Length -gt 12) {
                    $endpoints += [PSCustomObject]@{
                        ip = $remote.Address.ToString()
                        discovered_via = "mdns"
                    }
                }
            } catch { break }
        }
        Write-Log "INFO" "mDNS scan completato: $($endpoints.Count) risposte"
    } catch {
        Write-Log "WARN" "mDNS scan failed: $($_.Exception.Message)"
    } finally {
        if ($udpClient) { try { $udpClient.Close() } catch {} }
    }
    return $endpoints
}

# ---------- SCAN UNIFICATA + INVIO (riusabile da tray/wizard) ----------
function Invoke-LanScanOnce([object]$Config, [switch]$DryRun) {
    Write-Log "INFO" "Avvio scan LAN (subnet=$($Config.subnet))"
    $arp = Invoke-ArpScan -Subnet $Config.subnet
    $mdns = Invoke-MdnsDiscovery
    # Merge per MAC (priorita' ARP che ha sia IP che MAC)
    $merged = @{}
    foreach ($e in $arp) { if ($e.mac) { $merged[$e.mac] = $e } }
    foreach ($e in $mdns) {
        if ($e.ip) {
            $arpMatch = $arp | Where-Object { $_.ip -eq $e.ip } | Select-Object -First 1
            if ($arpMatch -and $merged[$arpMatch.mac]) {
                $merged[$arpMatch.mac].discovered_via = "arp+mdns"
            }
        }
    }
    $endpoints = @($merged.Values)
    Write-Log "INFO" "Endpoint deduplicati: $($endpoints.Count)"
    if (-not $DryRun) {
        Send-LanScanReport -Config $Config -Endpoints $endpoints
    }
    return $endpoints
}

# ---------- INVIO REPORT AL CENTER ----------
function Send-LanScanReport($Config, $Endpoints) {
    if (-not $Endpoints -or $Endpoints.Count -eq 0) {
        Write-Log "INFO" "Nessun endpoint da inviare"
        return
    }
    $apiKey = Unprotect-String $Config.api_key_encrypted
    $body = @{
        subnet = $Config.subnet
        vlan_id = $Config.vlan_id
        scan_started_at = (Get-Date).ToUniversalTime().AddSeconds(-30).ToString("o")
        scan_ended_at = (Get-Date).ToUniversalTime().ToString("o")
        endpoints = @($Endpoints)
        hostname = $Config.hostname
    } | ConvertTo-Json -Depth 5 -Compress
    try {
        $r = Invoke-RestMethod -Uri "$($Config.center_url)/api/connector/lan-scan" `
            -Method POST -Headers @{ "X-API-Key" = $apiKey } `
            -Body $body -ContentType "application/json" -TimeoutSec 30
        Write-Log "OK" "Inviati $($r.stored)/$($r.total) endpoint al Center"
    } catch {
        Write-Log "ERR" "Invio report fallito: $($_.Exception.Message)"
    }
}

# ---------- LOOP PRINCIPALE ----------
function Start-ScannerLoop($Config) {
    Show-Banner
    Write-Log "INFO" "Avvio loop scanner (mode=$($Config.mode), subnet=$($Config.subnet), vlan=$($Config.vlan_id))"
    Write-Host "  Heartbeat ogni $($Config.heartbeat_interval_seconds)s, Scan ogni $($Config.scan_interval_seconds)s"
    Write-Host "  Log: $LogPath"
    Write-Host "  Premi CTRL+C per uscire."
    Write-Host ""

    # v3.8.1: nel loop non vogliamo mai terminare lo script per un errore.
    $ErrorActionPreference = "Continue"

    $lastHeartbeat = (Get-Date).AddYears(-1)
    $lastScan = (Get-Date).AddYears(-1)

    while ($true) {
        try {
            $now = Get-Date
            if (($now - $lastHeartbeat).TotalSeconds -ge $Config.heartbeat_interval_seconds) {
                Test-Hookup -Config $Config | Out-Null
                $lastHeartbeat = $now
            }
            if ($Config.mode -eq "scanner" -and ($now - $lastScan).TotalSeconds -ge $Config.scan_interval_seconds) {
                Invoke-LanScanOnce -Config $Config | Out-Null
                $lastScan = $now
            }
        } catch {
            Write-Log "ERR" "Eccezione nel loop principale: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 5
    }
}

# ---------- ENTRY POINT ----------
if ($AsLibrary) { return }
$config = Get-Config
# v3.8: se invocato dal connector master con env vars, usa quelle invece del wizard.
if (-not $config -and $env:ARGUS_SCANNER_CENTER -and $env:ARGUS_SCANNER_APIKEY) {
    $vlan = $null
    if ($env:ARGUS_SCANNER_VLAN -and $env:ARGUS_SCANNER_VLAN -match "^\d+$") {
        $vlan = [int]$env:ARGUS_SCANNER_VLAN
    }
    $config = [PSCustomObject]@{
        center_url = $env:ARGUS_SCANNER_CENTER
        api_key_encrypted = Protect-String $env:ARGUS_SCANNER_APIKEY
        mode = "scanner"
        subnet = $env:ARGUS_SCANNER_SUBNET
        vlan_id = $vlan
        hostname = $env:COMPUTERNAME
        scan_interval_seconds = 300
        heartbeat_interval_seconds = 60
        version = "3.8.1"
    }
    Write-Log "INFO" "Scanner avviato dal connector master (env config)"
}
if ($Setup -or -not $config) {
    $config = Invoke-SetupWizard
}
if ($Test) {
    Test-Hookup -Config $config | Out-Null
    exit 0
}
if ($ScanOnce) {
    # Una scansione singola, utile per pulsante "Scansiona ora" da tray/wizard
    Test-Hookup -Config $config | Out-Null
    Invoke-LanScanOnce -Config $config | Out-Null
    exit 0
}
Start-ScannerLoop -Config $config
