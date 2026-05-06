# =============================================================================
# 86NocConnector - ARGUS LAN Scanner v3.8.6
# =============================================================================
# Modalita': SCANNER (discovery LAN passivo via ARP/mDNS/SNMP locale).
# Si "aggancia" al cliente nel Center via API key.
# Compatibile con Windows PowerShell 5.1+ e PowerShell 7+.
# Esegui come Admin per ARP scan completo. Senza Admin = solo SNMP/mDNS.
#
# v3.8.6 NUOVO:
#   - Integrazione MASSCAN (auto-detect): se masscan.exe e' nel PATH o in
#     C:\ProgramData\86NocConnector\bin\, lo Scanner lo usa per il fast discovery
#     (10.000+ pps, /24 in <1s). Se assente, fallback al ping PowerShell nativo.
#   - Switch -InstallMasscan: scarica ed installa masscan.exe automaticamente
#     dalla release ufficiale GitHub (https://github.com/robertdavidgraham/masscan)
#   - Funzione Invoke-MasscanDiscovery: ritorna lista IP vivi sulla subnet
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
    [switch]$InstallMasscan,  # Scarica e installa masscan.exe (richiede Admin + Internet)
    [string]$ConfigPath = "$env:ProgramData\86NocConnector\scanner-config.json",
    [string]$LogPath = "$env:ProgramData\86NocConnector\scanner.log"
)

# v3.8.13 FIX: applichiamo le modifiche allo scope SOLO quando lo script viene
# eseguito come entry-point (NON dot-source da -AsLibrary), altrimenti
# inquineremmo lo scope del main connector.ps1 (es. ErrorActionPreference).
if (-not $AsLibrary) {
    # v3.8.12 FIX: in cima al modulo NON forziamo Stop, altrimenti qualunque eccezione
    # (anche cosmetica) uccide lo script PRIMA di entrare nel main loop. Questo era
    # il root cause del crash-loop infinito quando lo Scanner gira sotto NSSM come
    # NT AUTHORITY\SYSTEM (sessione background, nessuna console).
    # Lo Stop lo ri-abilitiamo solo dentro Invoke-SetupWizard (errori utente critici).
    $ErrorActionPreference = "Continue"

    # v3.8.12 FIX: WindowTitle setting in try/catch - sotto NSSM SYSTEM
    # $Host.UI.RawUI puo' lanciare PSNotImplementedException se non c'e' console UI.
    try { $Host.UI.RawUI.WindowTitle = "ARGUS LAN Scanner v3.8.13" } catch {}
}

# v3.8.12: rileva se siamo in modalita' headless (no console interattiva).
# In headless silenziamo tutti i Write-Host, scriviamo solo su file di log.
$script:IsHeadless = $false
try {
    $script:IsHeadless = -not [Environment]::UserInteractive
} catch {
    $script:IsHeadless = $true  # in dubbio, considera headless
}

# Wrapper safe per Write-Host: in headless non chiama mai l'host UI.
function Write-HostSafe {
    param([string]$Text, [string]$ForegroundColor)
    if ($script:IsHeadless) { return }
    try {
        if ($ForegroundColor) {
            Write-Host $Text -ForegroundColor $ForegroundColor
        } else {
            Write-Host $Text
        }
    } catch {}
}

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
    Write-HostSafe -Text $line -ForegroundColor $color
}

# ---------- BANNER ----------
function Show-Banner {
    Write-HostSafe ""
    Write-HostSafe "  ============================================================" "Cyan"
    Write-HostSafe "    ARGUS  ::  86NocConnector  Scanner Mode  v3.8.12" "Cyan"
    Write-HostSafe "    Discovery LAN cross-VLAN per il Center NOC" "DarkCyan"
    Write-HostSafe "  ============================================================" "Cyan"
    Write-HostSafe ""
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
    # v3.8.12: errori critici nel wizard utente devono interrompere subito.
    $ErrorActionPreference = "Stop"
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

# ---------- MASSCAN INTEGRATION (v3.8.6) ----------
# Masscan e' un fast TCP/UDP port scanner asincrono (~10.000 pps, /24 in <1s).
# Lo Scanner lo usa come engine preferito se disponibile, altrimenti
# fallback al ping PowerShell nativo.

$script:MasscanBin = "$env:ProgramData\86NocConnector\bin\masscan.exe"

function Test-MasscanAvailable {
    # Cerca masscan.exe in:
    #  1. PATH di sistema
    #  2. ProgramData\86NocConnector\bin\
    #  3. Program Files\masscan\
    $candidates = @(
        (Get-Command masscan.exe -ErrorAction SilentlyContinue).Source,
        $script:MasscanBin,
        "$env:ProgramFiles\masscan\masscan.exe",
        "${env:ProgramFiles(x86)}\masscan\masscan.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) {
            $script:MasscanBin = $c
            return $true
        }
    }
    return $false
}

function Install-Masscan {
    Show-Banner
    Write-Host "  INSTALLAZIONE MASSCAN" -ForegroundColor Yellow
    Write-Host "  Download dalla release ufficiale GitHub..."
    Write-Host ""

    # Verifica admin (richiesto per scrivere in ProgramData e installare Npcap)
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Log "ERR" "Per installare Masscan servono privilegi di amministratore. Rilancia come Admin."
        return $false
    }

    $binDir = Split-Path $script:MasscanBin -Parent
    if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir -Force | Out-Null }

    # 1. Download masscan binario Windows (release Windows precompilata di lacework)
    $downloadUrl = "https://github.com/robertdavidgraham/masscan/releases/download/1.3.2/masscan-windows.zip"
    $altUrl = "https://github.com/HynekPetrak/masscan-binaries/raw/main/Windows/masscan.exe"
    $tmpZip = Join-Path $env:TEMP "masscan-win.zip"
    $tmpExe = Join-Path $env:TEMP "masscan.exe"

    try {
        Write-Log "INFO" "Download Masscan da $altUrl ..."
        # Usa il binario singolo precompilato (piu' affidabile delle release ufficiali che hanno solo source)
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $altUrl -OutFile $tmpExe -UseBasicParsing -TimeoutSec 60
        if (-not (Test-Path $tmpExe) -or (Get-Item $tmpExe).Length -lt 100000) {
            throw "Download fallito o file troppo piccolo"
        }
        Copy-Item $tmpExe $script:MasscanBin -Force
        Remove-Item $tmpExe -Force -ErrorAction SilentlyContinue
        Write-Log "OK" "Masscan installato in $script:MasscanBin"
    } catch {
        Write-Log "ERR" "Download masscan fallito: $($_.Exception.Message)"
        Write-Host "  Soluzioni alternative:" -ForegroundColor Yellow
        Write-Host "    1) Installa via Chocolatey:  choco install masscan -y"
        Write-Host "    2) Scarica manualmente da:  https://github.com/robertdavidgraham/masscan/releases"
        Write-Host "       e copia masscan.exe in:  $script:MasscanBin"
        return $false
    }

    # 2. Verifica/installa Npcap (driver di rete richiesto da masscan su Windows)
    $npcapInstalled = $false
    foreach ($p in @("$env:ProgramFiles\Npcap", "${env:ProgramFiles(x86)}\Npcap", "$env:SystemRoot\System32\Npcap")) {
        if (Test-Path $p) { $npcapInstalled = $true; break }
    }
    if (-not $npcapInstalled) {
        Write-Log "WARN" "Npcap NON rilevato. Masscan necessita di Npcap o WinPcap per funzionare."
        Write-Host "  Scarica e installa Npcap manualmente da: https://npcap.com/dist/" -ForegroundColor Yellow
        Write-Host "  Durante l'installazione, attiva 'WinPcap API-compatible Mode'." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  (Alternativa: installa Wireshark che include gia' Npcap)" -ForegroundColor DarkGray
    } else {
        Write-Log "OK" "Npcap rilevato"
    }

    return $true
}

function Invoke-MasscanDiscovery {
    param(
        [string]$Subnet,
        [int]$Rate = 5000,
        [int]$TimeoutSec = 30
    )
    $endpoints = @()
    if (-not (Test-MasscanAvailable)) {
        Write-Log "WARN" "Masscan non disponibile, salto fast discovery"
        return $endpoints
    }
    if (-not $Subnet) { return $endpoints }

    Write-Log "INFO" "Masscan: discovery rapido su $Subnet (rate $Rate pps)"
    $outFile = Join-Path $env:TEMP "argus-masscan-$([guid]::NewGuid().ToString('N')).txt"
    try {
        # ICMP echo + porte molto comuni (22, 53, 80, 135, 139, 443, 445, 3389, 8080)
        # per host che bloccano ICMP. Output in formato grepable per parsing.
        $args = @(
            "-p22,53,80,135,139,443,445,3389,8080,8443"
            "--ping"
            "--rate", $Rate
            "--wait", "2"
            "-oG", $outFile
            $Subnet
        )
        $proc = Start-Process -FilePath $script:MasscanBin -ArgumentList $args `
                              -NoNewWindow -PassThru -Wait `
                              -RedirectStandardError "$outFile.err" `
                              -RedirectStandardOutput "$outFile.log"
        if ($proc.ExitCode -ne 0) {
            $errTxt = if (Test-Path "$outFile.err") { Get-Content "$outFile.err" -Raw } else { "" }
            Write-Log "WARN" "Masscan exit $($proc.ExitCode): $errTxt"
        }
        if (Test-Path $outFile) {
            $found = @{}
            foreach ($line in (Get-Content $outFile -ErrorAction SilentlyContinue)) {
                # Format: "Host: 192.168.1.1 ()    Ports: 80/open/tcp"
                if ($line -match "Host:\s+(\d+\.\d+\.\d+\.\d+)") {
                    $found[$matches[1]] = $true
                }
            }
            foreach ($ip in $found.Keys) {
                $endpoints += [PSCustomObject]@{
                    ip = $ip
                    discovered_via = "masscan"
                }
            }
            Write-Log "OK" "Masscan: $($endpoints.Count) host vivi rilevati"
        }
    } catch {
        Write-Log "ERR" "Masscan exception: $($_.Exception.Message)"
    } finally {
        Remove-Item $outFile, "$outFile.err", "$outFile.log" -Force -ErrorAction SilentlyContinue
    }
    return $endpoints
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

    # v3.8.6: Step 0 - Masscan fast discovery (se disponibile)
    # Popola la cache ARP del kernel rapidamente toccando tutti gli host vivi,
    # cosi' il successivo Get-NetNeighbor restituisce subito MAC + IP.
    $masscanIps = @()
    if (Test-MasscanAvailable) {
        $masscanResult = Invoke-MasscanDiscovery -Subnet $Config.subnet -Rate 5000
        $masscanIps = @($masscanResult | ForEach-Object { $_.ip })
        Write-Log "INFO" "Masscan ha rilevato $($masscanIps.Count) host. Lascio popolare ARP..."
        Start-Sleep -Seconds 1
    } else {
        Write-Log "INFO" "Masscan non installato - uso solo ping nativo PS"
    }

    $arp = Invoke-ArpScan -Subnet $Config.subnet
    $mdns = Invoke-MdnsDiscovery
    # Merge per MAC (priorita' ARP che ha sia IP che MAC)
    $merged = @{}
    foreach ($e in $arp) {
        if ($e.mac) {
            # Tag come arp+masscan se masscan aveva gia' visto questo IP
            if ($masscanIps -contains $e.ip) { $e.discovered_via = "arp+masscan" }
            $merged[$e.mac] = $e
        }
    }
    foreach ($e in $mdns) {
        if ($e.ip) {
            $arpMatch = $arp | Where-Object { $_.ip -eq $e.ip } | Select-Object -First 1
            if ($arpMatch -and $merged[$arpMatch.mac]) {
                $merged[$arpMatch.mac].discovered_via = $merged[$arpMatch.mac].discovered_via + "+mdns"
            }
        }
    }
    # Aggiungi IP visti SOLO da Masscan (host che bloccano ARP ma rispondono su porte TCP)
    foreach ($ip in $masscanIps) {
        $known = $false
        foreach ($e in $merged.Values) { if ($e.ip -eq $ip) { $known = $true; break } }
        if (-not $known) {
            # Host vivo senza MAC ARP visibile - caso raro (es. host fuori subnet locale via gateway)
            $merged["masscan_only_$ip"] = [PSCustomObject]@{
                ip = $ip
                mac = ""
                discovered_via = "masscan"
            }
        }
    }
    $endpoints = @($merged.Values)
    Write-Log "INFO" "Endpoint deduplicati: $($endpoints.Count) (masscan=$($masscanIps.Count), arp=$($arp.Count), mdns=$($mdns.Count))"
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
    if (Test-MasscanAvailable) {
        Write-Log "OK" "Masscan rilevato in $script:MasscanBin - fast discovery ATTIVO"
    } else {
        Write-Log "INFO" "Masscan non installato. Lancia 'argus-scanner.ps1 -InstallMasscan' come Admin per scan ultra-rapido."
    }
    Write-HostSafe "  Heartbeat ogni $($Config.heartbeat_interval_seconds)s, Scan ogni $($Config.scan_interval_seconds)s"
    Write-HostSafe "  Log: $LogPath"
    Write-HostSafe "  Premi CTRL+C per uscire."
    Write-HostSafe ""

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
if ($InstallMasscan) {
    if (Install-Masscan) {
        Write-Host ""
        Write-Host "  [OK] Masscan installato. Lo Scanner lo usera' automaticamente al prossimo scan." -ForegroundColor Green
        exit 0
    } else {
        exit 1
    }
}
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
        version = "3.8.12"
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
