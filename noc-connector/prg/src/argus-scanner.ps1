# =============================================================================
# 86NocConnector — ARGUS LAN Scanner v3.8.0
# =============================================================================
# Modalita': SCANNER (discovery LAN passivo via ARP/mDNS/SNMP locale).
# Si "aggancia" al cliente nel Center via API key.
# Compatibile con Windows PowerShell 5.1+ e PowerShell 7+.
# Esegui come Admin per ARP scan completo. Senza Admin = solo SNMP/mDNS.
# =============================================================================

param(
    [switch]$Setup,           # Forza riconfigurazione (anche se config esiste)
    [switch]$Test,            # Test connessione + lista endpoint senza salvare
    [string]$ConfigPath = "$env:ProgramData\86NocConnector\scanner-config.json"
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "ARGUS LAN Scanner"

# ---------- BANNER ----------
function Show-Banner {
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "    ARGUS  ::  86NocConnector  Scanner Mode  v3.8.0" -ForegroundColor Cyan
    Write-Host "    Discovery LAN cross-VLAN per il Center NOC" -ForegroundColor DarkCyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# ---------- CRIPTAZIONE LOCALE (DPAPI Windows) ----------
# Le credenziali vengono cifrate con la chiave macchina Windows.
# Solo lo stesso utente sulla stessa macchina puo' leggerle.
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
        Write-Warning "Decrypt fallito (config corrotto o eseguito da utente diverso)"
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
    if ($mode -eq "scanner") {
        # Auto-detect IP locale + subnet /24
        $localIp = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual `
            -ErrorAction SilentlyContinue | Where-Object {$_.IPAddress -notlike "169.254.*"} `
            | Select-Object -First 1).IPAddress
        if (-not $localIp) {
            $localIp = (Test-Connection -ComputerName "127.0.0.1" -Count 1).IPV4Address.IPAddressToString
        }
        $defaultSubnet = if ($localIp) { ($localIp -replace "\.\d+$",".0/24") } else { "" }
        Write-Host ""
        $subnet = Read-Host "  Subnet locale da scansionare [$defaultSubnet]"
        if (-not $subnet) { $subnet = $defaultSubnet }
        $vlanInput = Read-Host "  VLAN ID (opzionale, lascia vuoto se non sai)"
        if ($vlanInput -match "^\d+$") { $vlanId = [int]$vlanInput }
    }

    $config = @{
        center_url = $centerUrl
        api_key_encrypted = Protect-String $apiKeyPlain
        mode = $mode
        subnet = $subnet
        vlan_id = $vlanId
        hostname = $env:COMPUTERNAME
        scan_interval_seconds = 300
        heartbeat_interval_seconds = 60
        version = "3.8.0"
        installed_at = (Get-Date -Format "o")
    }

    $cfgDir = Split-Path $ConfigPath -Parent
    if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null }
    $config | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigPath -Encoding UTF8
    Write-Host ""
    Write-Host "  [OK] Configurazione salvata in: $ConfigPath" -ForegroundColor Green
    Write-Host "       (API Key cifrata con DPAPI, leggibile solo da $env:USERNAME su questa macchina)"
    Write-Host ""

    # Test immediato di aggancio
    Test-Hookup -Config $config
    return $config
}

function Get-Config {
    if (-not (Test-Path $ConfigPath)) { return $null }
    return Get-Content $ConfigPath -Raw | ConvertFrom-Json
}

# ---------- AGGANCIO + HEARTBEAT ----------
function Test-Hookup($Config) {
    Write-Host "  Test aggancio Center..." -NoNewline
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
        Write-Host " OK" -ForegroundColor Green
        Write-Host "  [OK] Connector AGGANCIATO al Center come $($Config.mode.ToUpper())" -ForegroundColor Green
        Write-Host "       Vai su $($Config.center_url)/connectors per vederlo." -ForegroundColor DarkGray
        return $true
    } catch {
        Write-Host " FAIL" -ForegroundColor Red
        Write-Warning "  Impossibile contattare il Center: $($_.Exception.Message)"
        Write-Host "  Verifica URL e API Key." -ForegroundColor Yellow
        return $false
    }
}

# ---------- ARP SCAN LOCALE (no admin: usa cache ARP) ----------
function Invoke-ArpScan([string]$Subnet) {
    $endpoints = @()
    # Trigger ARP refresh: ping broadcast (non sempre risponde)
    $base = ($Subnet -split "/")[0] -replace "\.0$","."
    1..254 | ForEach-Object -ThrottleLimit 50 -Parallel {
        $null = Test-Connection -ComputerName "$using:base$_" -Count 1 -TimeoutSeconds 1 -ErrorAction SilentlyContinue
    } 2>$null

    # Leggi tabella ARP
    Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.State -in @("Reachable","Stale") -and $_.LinkLayerAddress -ne "00-00-00-00-00-00" } |
        ForEach-Object {
            $endpoints += [PSCustomObject]@{
                mac = ($_.LinkLayerAddress -replace "-",":").ToLower()
                ip = $_.IPAddress
                discovered_via = "arp"
            }
        }
    return $endpoints
}

# ---------- mDNS DISCOVERY (224.0.0.251:5353) ----------
function Invoke-MdnsDiscovery {
    $endpoints = @()
    try {
        # Query mDNS PTR _services._dns-sd._udp.local
        $udpClient = New-Object System.Net.Sockets.UdpClient
        $udpClient.Client.ReceiveTimeout = 3000
        $endpoint = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse("224.0.0.251"), 5353)
        # Pacchetto mDNS minimale (PTR query per _services._dns-sd._udp.local)
        $query = [byte[]](0,0,0,0,0,1,0,0,0,0,0,0,9,0x5f,0x73,0x65,0x72,0x76,0x69,0x63,0x65,0x73,7,0x5f,0x64,0x6e,0x73,0x2d,0x73,0x64,4,0x5f,0x75,0x64,0x70,5,0x6c,0x6f,0x63,0x61,0x6c,0,0,12,0,1)
        $udpClient.Send($query, $query.Length, $endpoint) | Out-Null
        $start = Get-Date
        while (((Get-Date) - $start).TotalSeconds -lt 3) {
            try {
                $remote = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
                $resp = $udpClient.Receive([ref]$remote)
                # Estrai IP del rispondente (mDNS dice gia' chi e' lui)
                if ($resp.Length -gt 12) {
                    $endpoints += [PSCustomObject]@{
                        ip = $remote.Address.ToString()
                        discovered_via = "mdns"
                        # mac sara' aggiunto dopo via ARP table merge
                    }
                }
            } catch { break }
        }
        $udpClient.Close()
    } catch {
        Write-Warning "mDNS scan failed: $_"
    }
    return $endpoints
}

# ---------- INVIO REPORT AL CENTER ----------
function Send-LanScanReport($Config, $Endpoints) {
    if ($Endpoints.Count -eq 0) {
        Write-Host "  Nessun endpoint da inviare." -ForegroundColor DarkGray
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
        Write-Host "  [SCAN] Inviati $($r.stored)/$($r.total) endpoint al Center" -ForegroundColor Green
    } catch {
        Write-Warning "Invio report fallito: $($_.Exception.Message)"
    }
}

# ---------- LOOP PRINCIPALE ----------
function Start-ScannerLoop($Config) {
    Show-Banner
    Write-Host "  Avvio loop scanner..." -ForegroundColor Cyan
    Write-Host "  Modalita: $($Config.mode.ToUpper()) | Subnet: $($Config.subnet) | VLAN: $($Config.vlan_id)" -ForegroundColor DarkCyan
    Write-Host "  Heartbeat ogni $($Config.heartbeat_interval_seconds)s, Scan ogni $($Config.scan_interval_seconds)s"
    Write-Host "  Premi CTRL+C per uscire."
    Write-Host ""

    $lastHeartbeat = (Get-Date).AddYears(-1)
    $lastScan = (Get-Date).AddYears(-1)

    while ($true) {
        $now = Get-Date
        if (($now - $lastHeartbeat).TotalSeconds -ge $Config.heartbeat_interval_seconds) {
            Test-Hookup -Config $Config | Out-Null
            $lastHeartbeat = $now
        }
        if ($Config.mode -eq "scanner" -and ($now - $lastScan).TotalSeconds -ge $Config.scan_interval_seconds) {
            Write-Host "  [SCAN] Avvio discovery..." -ForegroundColor DarkCyan
            $arp = Invoke-ArpScan -Subnet $Config.subnet
            $mdns = Invoke-MdnsDiscovery
            # Merge per IP (mDNS senza MAC + ARP con MAC)
            $merged = @{}
            foreach ($e in $arp) { if ($e.mac) { $merged[$e.mac] = $e } }
            foreach ($e in $mdns) {
                if ($e.ip) {
                    $arpMatch = $arp | Where-Object { $_.ip -eq $e.ip } | Select-Object -First 1
                    if ($arpMatch) {
                        $merged[$arpMatch.mac].discovered_via = "arp+mdns"
                    }
                }
            }
            Send-LanScanReport -Config $Config -Endpoints @($merged.Values)
            $lastScan = $now
        }
        Start-Sleep -Seconds 5
    }
}

# ---------- ENTRY POINT ----------
$config = Get-Config
if ($Setup -or -not $config) {
    $config = Invoke-SetupWizard
}
if ($Test) {
    Test-Hookup -Config $config | Out-Null
    exit 0
}
Start-ScannerLoop -Config $config
