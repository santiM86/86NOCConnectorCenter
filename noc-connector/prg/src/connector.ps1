<# 
.SYNOPSIS
    86NocConnector - Motore Collector SNMP Traps + Syslog
.DESCRIPTION
    Raccoglie SNMP Traps e Syslog da dispositivi di rete e li inoltra al NOC Center.
    Nessuna dipendenza esterna. Funziona con PowerShell nativo di Windows.
    Puo' girare come Scheduled Task sotto SYSTEM (sopravvive a disconnessione RDP).
#>

param(
    [string]$ConfigPath = ""
)

# ==================== TLS & ENCODING ====================
# Critico: forza TLS 1.2 (SYSTEM potrebbe avere solo SSL3/TLS1.0 abilitati)
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

$global:AppName = "86NocConnector"
$global:ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$global:BaseDir = Split-Path -Parent $global:ScriptDir
$versionFile = Join-Path $global:BaseDir "version.json"
if (Test-Path $versionFile) {
    $vInfo = Get-Content $versionFile -Raw | ConvertFrom-Json
    $global:Version = $vInfo.version
} else {
    $global:Version = "1.0.0"
}

# ==================== WIREGUARD MODULE ====================
# Dot-source modulo WireGuard se presente. Se mancante (versioni vecchie) il
# connector continua a girare normalmente (graceful degradation).
$wgModule = Join-Path $PSScriptRoot "wireguard_client.ps1"
if (Test-Path $wgModule) {
    . $wgModule
}

# ==================== CONFIGURAZIONE ====================

function Get-ConfigDir {
    $dir = Join-Path $env:ProgramData $global:AppName
    if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

function Get-ConfigPath {
    if ($ConfigPath -ne "") { return $ConfigPath }
    return Join-Path (Get-ConfigDir) "config.json"
}

function Get-LogDir {
    $dir = Join-Path (Get-ConfigDir) "logs"
    if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

function Get-LogPath {
    return Join-Path (Get-LogDir) "connector.log"
}

function Read-Config {
    $path = Get-ConfigPath
    if (Test-Path $path) {
        return Get-Content $path -Raw | ConvertFrom-Json
    }
    return $null
}

function Save-Config($config) {
    $path = Get-ConfigPath
    $config | ConvertTo-Json -Depth 5 | Set-Content $path -Encoding UTF8
}

function Get-ClientIdFromServer($nocUrl, $apiKey) {
    # v3.5.16: auto-discovery del client_id tramite endpoint /api/connector/identify.
    # Risolve il problema di config.json con client_id vuoto (wizard pre-v3.5.16 non
    # chiedeva client_id all'admin) che causava loop infinito di 401 Unauthorized
    # su tutte le chiamate HMAC (heartbeat, device-report, web-proxy, discovery-check).
    if (-not $nocUrl -or -not $apiKey) { return $null }
    try {
        $url = "$($nocUrl.TrimEnd('/'))/api/connector/identify"
        $headers = @{ "X-API-Key" = $apiKey }
        $r = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -TimeoutSec 15 -ErrorAction Stop
        if ($r -and $r.client_id) {
            return $r.client_id
        }
    } catch {
        Write-Host "[WARN] Auto-discovery client_id fallito: $($_.Exception.Message)"
    }
    return $null
}

function Ensure-ClientIdInConfig {
    # Idempotente: se config.json ha client_id vuoto, lo ricava dal server e lo salva.
    # Chiamato all'avvio di Start-PollingLoop e in caso di 401 durante runtime.
    $cfg = Read-Config
    if (-not $cfg) { return $null }
    if ($cfg.client_id -and $cfg.client_id.ToString().Length -gt 0) {
        return $cfg.client_id
    }
    $cid = Get-ClientIdFromServer $cfg.noc_center_url $cfg.api_key
    if ($cid) {
        # Aggiorna config.json in-place
        if ($cfg.PSObject.Properties.Name -contains "client_id") {
            $cfg.client_id = $cid
        } else {
            $cfg | Add-Member -NotePropertyName "client_id" -NotePropertyValue $cid -Force
        }
        try {
            Save-Config $cfg
            Write-Log "Auto-discovery OK: client_id=$cid (salvato in config.json)" "INFO"
        } catch {
            Write-Log "Auto-discovery OK ma salvataggio config fallito: $($_.Exception.Message)" "WARN"
        }
        return $cid
    }
    return $null
}

function Write-Log($Message, $Level = "INFO") {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"
    Write-Host $line
    try {
        $logPath = Get-LogPath
        # Log rotation: se il file supera 5MB, ruota
        if (Test-Path $logPath) {
            $logSize = (Get-Item $logPath -ErrorAction SilentlyContinue).Length
            if ($logSize -and $logSize -gt 5242880) {  # 5 MB
                $archivePath = $logPath -replace '\.log$', "_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
                try {
                    Move-Item $logPath $archivePath -Force -ErrorAction SilentlyContinue
                    # Tieni solo gli ultimi 3 file archiviati
                    $logDir = Split-Path $logPath
                    $archives = Get-ChildItem $logDir -Filter "connector_*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
                    if ($archives.Count -gt 3) {
                        $archives | Select-Object -Skip 3 | Remove-Item -Force -ErrorAction SilentlyContinue
                    }
                } catch {}
            }
        }
        Add-Content -Path $logPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
}

# ==================== SNMP TRAP PARSER ====================

$global:KnownTraps = @{
    "1.3.6.1.6.3.1.1.5.1" = @("coldStart", "Dispositivo riavviato (cold start)", "critical")
    "1.3.6.1.6.3.1.1.5.2" = @("warmStart", "Dispositivo riavviato (warm start)", "high")
    "1.3.6.1.6.3.1.1.5.3" = @("linkDown", "Interfaccia di rete DOWN", "critical")
    "1.3.6.1.6.3.1.1.5.4" = @("linkUp", "Interfaccia di rete UP", "low")
    "1.3.6.1.6.3.1.1.5.5" = @("authenticationFailure", "Tentativo accesso non autorizzato", "high")
    "1.3.6.1.4.1.11.2.14.11.1.7" = @("hpSwitchAuth", "HPE: autenticazione fallita", "high")
    "1.3.6.1.4.1.11.2.14.11.5.1.7" = @("hpPortSecurity", "HPE: violazione sicurezza porta", "critical")
    "1.3.6.1.4.1.25506.2" = @("hpeH3C", "HPE/H3C: evento dispositivo", "medium")
    "1.3.6.1.4.1.232" = @("cpqHealth", "HPE iLO: evento salute server", "high")
}

function Decode-OID([byte[]]$bytes) {
    if ($bytes.Length -eq 0) { return "" }
    $components = @([math]::Floor($bytes[0] / 40), ($bytes[0] % 40))
    $val = 0
    for ($i = 1; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -band 0x80) {
            $val = ($val -shl 7) -bor ($bytes[$i] -band 0x7F)
        } else {
            $val = ($val -shl 7) -bor $bytes[$i]
            $components += $val
            $val = 0
        }
    }
    return ($components -join ".")
}

function Extract-OIDs([byte[]]$data) {
    $oids = @()
    $i = 0
    while ($i -lt ($data.Length - 2)) {
        if ($data[$i] -eq 0x06) {
            $oidLen = $data[$i + 1]
            if ($oidLen -gt 0 -and ($i + 2 + $oidLen) -le $data.Length) {
                try {
                    $oidBytes = $data[($i + 2)..($i + 1 + $oidLen)]
                    $oid = Decode-OID $oidBytes
                    if ($oid) { $oids += $oid }
                } catch {}
                $i += 2 + $oidLen
                continue
            }
        }
        $i++
    }
    return $oids
}

function Parse-SNMPTrap([byte[]]$data, [string]$sourceIP) {
    $oids = Extract-OIDs $data
    
    foreach ($oid in $oids) {
        foreach ($knownOid in $global:KnownTraps.Keys) {
            if ($oid -like "*$knownOid*") {
                $info = $global:KnownTraps[$knownOid]
                return @{
                    device_ip = $sourceIP
                    oid = $knownOid
                    value = $info[1]
                    trap_type = $info[0]
                }
            }
        }
    }
    
    return @{
        device_ip = $sourceIP
        oid = if ($oids.Count -gt 0) { $oids[0] } else { "unknown" }
        value = "Trap da $sourceIP"
        trap_type = "generic"
    }
}

# ==================== SYSLOG PARSER ====================

$global:SyslogSeverity = @{
    0 = "emergency"; 1 = "alert"; 2 = "critical"; 3 = "error"
    4 = "warning"; 5 = "notice"; 6 = "info"; 7 = "debug"
}

function Parse-Syslog([string]$rawMessage, [string]$sourceIP) {
    $facility = 1
    $severityLevel = 5
    $message = $rawMessage.Trim()
    
    if ($message.StartsWith("<")) {
        $endIdx = $message.IndexOf(">")
        if ($endIdx -gt 0) {
            $pri = [int]$message.Substring(1, $endIdx - 1)
            $facility = [math]::Floor($pri / 8)
            $severityLevel = $pri % 8
            $message = $message.Substring($endIdx + 1).Trim()
        }
    }
    
    return @{
        device_ip = $sourceIP
        facility = $facility
        severity_level = $severityLevel
        message = $message.Substring(0, [Math]::Min($message.Length, 1000))
        severity_name = $global:SyslogSeverity[$severityLevel]
        timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }
}

# ==================== API SENDER ====================

$global:Stats = @{
    snmp_received = 0
    syslog_received = 0
    snmp_sent = 0
    syslog_sent = 0
    errors = 0
    auth_failures = 0
    last_error = ""
    start_time = Get-Date
}


function Send-WakeOnLAN([string]$macAddress, [string]$targetIP) {
    <#
    .SYNOPSIS
        Invia un Magic Packet Wake-on-LAN sulla rete locale per accendere un server spento.
    .DESCRIPTION
        Il Magic Packet e' un pacchetto UDP broadcast (porta 9) che contiene:
        - 6 byte di FF (preamble)
        - 16 ripetizioni del MAC address del target (96 byte)
        Totale: 102 byte
    #>
    $udpClient = $null
    try {
        # Pulisci il MAC address (rimuovi : e -)
        $macClean = $macAddress -replace '[:\-]', ''
        if ($macClean.Length -ne 12) {
            Write-Log "MAC address non valido per WoL: $macAddress" "ERROR"
            return
        }
        
        # Costruisci il Magic Packet
        $macBytes = [byte[]]@()
        for ($i = 0; $i -lt 12; $i += 2) {
            $macBytes += [byte]("0x" + $macClean.Substring($i, 2))
        }
        
        # Preamble: 6 byte di FF
        $magicPacket = [byte[]](@(0xFF) * 6)
        
        # 16 ripetizioni del MAC
        for ($r = 0; $r -lt 16; $r++) {
            $magicPacket += $macBytes
        }
        
        # Invia via UDP broadcast sulla porta 9
        $udpClient = New-Object System.Net.Sockets.UdpClient
        $udpClient.EnableBroadcast = $true
        
        # Broadcast su 255.255.255.255
        $endpoint = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Broadcast, 9)
        $udpClient.Send($magicPacket, $magicPacket.Length, $endpoint) | Out-Null
        
        # Invia anche sulla subnet specifica se abbiamo l'IP target
        if ($targetIP) {
            try {
                $ipParts = $targetIP.Split('.')
                if ($ipParts.Count -eq 4) {
                    $broadcastIP = "$($ipParts[0]).$($ipParts[1]).$($ipParts[2]).255"
                    $subnetEndpoint = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse($broadcastIP), 9)
                    $udpClient.Send($magicPacket, $magicPacket.Length, $subnetEndpoint) | Out-Null
                }
            } catch {}
        }
        Write-Log "WoL Magic Packet inviato a $macAddress (target: $targetIP) - broadcast 255.255.255.255 e subnet" "INFO"
    } catch {
        Write-Log "Errore invio WoL a $macAddress : $($_.Exception.Message)" "ERROR"
    } finally {
        # v3.8.25: garantito chiusura socket UDP anche su exception (no resource leak)
        if ($udpClient) { try { $udpClient.Close() } catch {} }
    }
}


# ============================================================================
# v3.8.22 — BACKOFF ESPONENZIALE
# Quando una chiamata al Center fallisce per problema server (5xx/timeout/
# network) il connector entra in cooldown progressivo per quel singolo endpoint:
#   1° fail = 5s, 2° = 10s, 3° = 20s, 4° = 40s, 5°+ = 60s (cap)
# Durante il cooldown la chiamata viene SALTATA (return null) senza riprovare.
# Su prima chiamata di successo, lo stato si resetta a 0.
# Errori CLIENT (401/404/400) NON contano: il problema e' lato config, non
# server overload.
# ============================================================================
function Test-BackoffSkip($endpoint) {
    if (-not $global:BackoffState) { $global:BackoffState = @{} }
    $st = $global:BackoffState[$endpoint]
    if (-not $st) { return $false }
    if ((Get-Date) -lt $st.NextRetryAt) { return $true }
    return $false
}

function Register-BackoffFailure($endpoint) {
    if (-not $global:BackoffState) { $global:BackoffState = @{} }
    $st = $global:BackoffState[$endpoint]
    if (-not $st) { $st = @{ Failures = 0; NextRetryAt = (Get-Date) } }
    $st.Failures = [int]$st.Failures + 1
    # 5s, 10s, 20s, 40s, 60s (cap)
    $delays = @(5, 10, 20, 40, 60)
    $idx = [Math]::Min($st.Failures - 1, $delays.Length - 1)
    $delaySec = $delays[$idx]
    $st.NextRetryAt = (Get-Date).AddSeconds($delaySec)
    $global:BackoffState[$endpoint] = $st
    if ($st.Failures -le 3 -or ($st.Failures % 10) -eq 0) {
        Write-Log "Backoff $endpoint: fallimento #$($st.Failures), prossimo retry tra ${delaySec}s" "WARN"
    }
}

function Reset-BackoffState($endpoint) {
    if (-not $global:BackoffState) { $global:BackoffState = @{} }
    if ($global:BackoffState.ContainsKey($endpoint) -and $global:BackoffState[$endpoint] -and $global:BackoffState[$endpoint].Failures -gt 0) {
        Write-Log "Backoff $endpoint: reset (chiamata riuscita dopo $($global:BackoffState[$endpoint].Failures) fallimenti)" "INFO"
    }
    if ($global:BackoffState.ContainsKey($endpoint)) { [void]$global:BackoffState.Remove($endpoint) }
}


function Invoke-SecureGet($config, $endpoint, $timeoutSec = 15) {
    # GET verso il NOC. v3.5.24: HMAC opzionale (config.enable_hmac).
    # Per default mando solo X-API-Key (modalita' legacy retrocompatibile col
    # backend prod che esisteva prima dell'introduzione di HMAC).
    # v3.8.22: backoff esponenziale per evitare burst di retry su errori
    if (Test-BackoffSkip $endpoint) { return $null }
    try {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }
        $url = "$($config.noc_center_url)/api/$endpoint"

        $headers = @{ "X-API-Key" = $config.api_key }

        # Se l'admin ha abilitato HMAC esplicitamente nel config, calcoliamolo.
        # Default: non lo mandiamo (compat con backend pre-HMAC).
        if ($config.enable_hmac -eq $true) {
            $timestamp = [math]::Floor(([DateTimeOffset]::UtcNow).ToUnixTimeSeconds())
            $nonce = [guid]::NewGuid().ToString("N")
            $hmacSecret = "argus-hmac-k3y-2026!" + $config.api_key
            $message = "$($config.api_key)$timestamp$nonce"
            $hmac = New-Object System.Security.Cryptography.HMACSHA256
            $hmac.Key = [Text.Encoding]::UTF8.GetBytes($hmacSecret)
            $signature = [BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($message))).Replace("-","").ToLower()
            $headers["X-HMAC-Signature"] = $signature
            $headers["X-Timestamp"]      = $timestamp.ToString()
            $headers["X-Nonce"]          = $nonce
        }

        $result = Invoke-RestMethod -Uri $url -Method Get -Headers $headers -TimeoutSec $timeoutSec -ErrorAction Stop
        Reset-BackoffState $endpoint
        return $result
    } catch {
        # v3.5.16: messaggi di errore actionable per 401 (vs 404/500/network)
        $msg = $_.Exception.Message
        $isAuth = ($msg -match "401" -or $msg -match "Non autorizzato" -or $msg -match "Unauthorized")
        # v3.8.22: registra failure per backoff esponenziale (404/401 NON contano: bug client, non server overload)
        $isClientErr = ($msg -match "404" -or $msg -match "400" -or $isAuth)
        if (-not $isClientErr) { Register-BackoffFailure $endpoint }
        if ($isAuth) {
            $global:Stats.auth_failures = [int]($global:Stats.auth_failures) + 1
            # Logga warning DETTAGLIATO solo ogni 10 fallimenti per non inondare il log
            if (($global:Stats.auth_failures % 10) -eq 1) {
                Write-Log "401 Non autorizzato su $endpoint - API Key non accettata dal NOC. Probabile causa: key rigenerata/ruotata nel Center UI. Soluzione: Clienti > [tuo cliente] > Rigenera API Key -> copia in $env:ProgramData\86NocConnector\config.json -> Restart-Service 86NocConnectorService." "ERROR"
            } else {
                Write-Log "401 su $endpoint (fallimento #$($global:Stats.auth_failures))" "WARN"
            }
        } else {
            Write-Log "Errore secure GET ($endpoint): $msg" "ERROR"
        }
        return $null
    }
}


function Send-ToNOC($config, $endpoint, $payload) {
    # v3.8.22: backoff esponenziale per evitare burst di retry su errori server
    if (Test-BackoffSkip $endpoint) { return $null }
    try {
        # === TLS 1.2/1.3 enforcement ===
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }

        $body = $payload | ConvertTo-Json -Depth 5 -Compress
        $url = "$($config.noc_center_url)/api/$endpoint"

        # v3.5.24: HMAC opzionale via config.enable_hmac. Default: legacy mode
        # (solo X-API-Key) per garantire retro-compat con backend pre-HMAC.
        $headers = @{
            "X-API-Key"    = $config.api_key
            "Content-Type" = "application/json"
        }

        if ($config.enable_hmac -eq $true) {
            $timestamp = [math]::Floor(([DateTimeOffset]::UtcNow).ToUnixTimeSeconds())
            $nonce = [guid]::NewGuid().ToString("N")
            $hmacSecret = "argus-hmac-k3y-2026!" + $config.api_key
            $sha256 = [System.Security.Cryptography.SHA256]::Create()
            $bodyHash = if ($body) { [BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($body))).Replace("-","").ToLower() } else { "" }
            $message = "$($config.api_key)$timestamp$nonce$bodyHash"
            $hmac = New-Object System.Security.Cryptography.HMACSHA256
            $hmac.Key = [Text.Encoding]::UTF8.GetBytes($hmacSecret)
            $signature = [BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($message))).Replace("-","").ToLower()
            $headers["X-HMAC-Signature"] = $signature
            $headers["X-Timestamp"]      = $timestamp.ToString()
            $headers["X-Nonce"]          = $nonce
        }

        $response = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15 -ErrorAction Stop
        Reset-BackoffState $endpoint  # v3.8.22

        # Handle key rotation from server
        if ($response.key_rotation -and $response.key_rotation.new_api_key) {
            Write-Log "API Key ruotata dal server. Aggiornamento config..." "WARN"
            $config.api_key = $response.key_rotation.new_api_key
            # Save new key to config file
            try {
                $configPath = Join-Path $PSScriptRoot "config.json"
                if (Test-Path $configPath) {
                    $savedConfig = Get-Content $configPath -Raw | ConvertFrom-Json
                    $savedConfig.api_key = $response.key_rotation.new_api_key
                    $savedConfig | ConvertTo-Json -Depth 3 | Set-Content $configPath -Encoding UTF8
                    Write-Log "Nuova API Key salvata nel config" "INFO"
                }
            } catch { Write-Log "Errore salvataggio nuova API key: $($_.Exception.Message)" "ERROR" }
        }
        
        return $response
    } catch {
        $global:Stats.errors++
        $errMsg = $_.Exception.Message
        if ($_.Exception.InnerException) { $errMsg += " | Inner: $($_.Exception.InnerException.Message)" }
        $global:Stats.last_error = $errMsg
        # v3.5.16: messaggio chiaro + stop-the-bleed su 401
        $isAuth = ($errMsg -match "401" -or $errMsg -match "Non autorizzato" -or $errMsg -match "Unauthorized")
        # v3.8.22: registra failure per backoff (escluso 401/404/400 che sono client error)
        $isClientErr = ($errMsg -match "404" -or $errMsg -match "400" -or $isAuth)
        if (-not $isClientErr) { Register-BackoffFailure $endpoint }
        if ($isAuth) {
            $global:Stats.auth_failures = [int]($global:Stats.auth_failures) + 1
            if (($global:Stats.auth_failures % 10) -eq 1) {
                Write-Log "401 Non autorizzato su $endpoint - API Key non accettata dal NOC. Soluzione: nel Center vai su Clienti > [tuo cliente] > Rigenera API Key -> copia nuova chiave in $env:ProgramData\86NocConnector\config.json -> Restart-Service 86NocConnectorService." "ERROR"
            } else {
                Write-Log "401 su $endpoint (fallimento #$($global:Stats.auth_failures))" "WARN"
            }
        } else {
            Write-Log "Errore invio a NOC ($endpoint): $errMsg" "ERROR"
        }
        return $null
    }
}

function Send-SNMPToNOC($config, $trap) {
    $payload = @{
        device_ip = $trap.device_ip
        oid = $trap.oid
        value = $trap.value
        trap_type = $trap.trap_type
    }
    if (Send-ToNOC $config "ingest/snmp" $payload) {
        $global:Stats.snmp_sent++
        Write-Log "[SNMP -> NOC] $($trap.trap_type) da $($trap.device_ip)"
    }
}

function Send-SyslogToNOC($config, $syslog) {
    $payload = @{
        device_ip = $syslog.device_ip
        facility = $syslog.facility
        severity_level = $syslog.severity_level
        message = $syslog.message
        timestamp = $syslog.timestamp
    }
    if (Send-ToNOC $config "ingest/syslog" $payload) {
        $global:Stats.syslog_sent++
        Write-Log "[Syslog -> NOC] [$($syslog.severity_name)] $($syslog.device_ip): $($syslog.message.Substring(0, [Math]::Min(60, $syslog.message.Length)))"
    }
}

function Send-Heartbeat($config) {
    $uptime = ((Get-Date) - $global:Stats.start_time).TotalSeconds
    $payload = @{
        connector_version = $global:Version
        hostname = $env:COMPUTERNAME
        uptime_seconds = [int]$uptime
        traps_received = $global:Stats.snmp_received
        syslogs_received = $global:Stats.syslog_received
        # v3.8: modalita' connector + dati subnet (per UI Center grouping)
        mode = if ($config.mode) { $config.mode } else { "master" }
        subnet = $config.subnet
        vlan_id = $config.vlan_id
    }
    $response = Send-ToNOC $config "connector/heartbeat" $payload
    
    # Aggiornamento whitelist porte dinamica (da UI Admin)
    if ($response -and $response.allowed_ports_extra) {
        try {
            $ports = @($response.allowed_ports_extra | ForEach-Object { [int]$_ })
            $script:DynamicAllowedPorts = $ports
            if ($ports.Count -gt 0) {
                Write-Log "Allowed ports extra aggiornati: $($ports -join ',')" "INFO"
            }
        } catch {
            Write-Log "Errore parsing allowed_ports_extra: $_" "WARN"
        }
    }

    # "Applica ora" dall'admin del Center: forza re-fetch device list immediato
    # invece di aspettare il ciclo normale (ogni 10 poll, ~10 minuti).
    # Usato quando admin cambia community/monitor-type/profilo e vuole vedere
    # subito il connector applicare la nuova config senza riavviare il servizio.
    # IMPORTANTE: Start-PollingLoop gira in un Start-Job (scope runspace separato),
    # quindi $global:ForceRefreshPending NON e' visibile dal polling job. Usiamo
    # un file flag su disco come canale IPC cross-process.
    if ($response -and $response.refresh_now) {
        Write-Log "[REFRESH] NOC ha richiesto fetch-devices immediato (admin ha cliccato 'Applica ora')" "INFO"
        try {
            $flagFile = Join-Path (Join-Path $env:ProgramData "86NocConnector") "refresh.flag"
            Set-Content -Path $flagFile -Value (Get-Date -Format "o") -Encoding UTF8 -Force
            $global:ForceRefreshPending = $true   # anche global per scope locali
        } catch {
            Write-Log "Errore segnalazione refresh: $_" "WARN"
        }
    }
    
    # Process pending commands (Wake-on-LAN, VA Scan, etc.)
    if ($response -and $response.pending_commands) {
        foreach ($cmd in $response.pending_commands) {
            Write-Log "Comando ricevuto dal NOC: $($cmd.type)" "INFO"
            switch ($cmd.type) {
                "wake_on_lan" {
                    Send-WakeOnLAN $cmd.mac_address $cmd.target_ip
                }
                "va_scan" {
                    Write-Log "Avvio scansione Vulnerability Assessment (scan_id=$($cmd.id))..." "INFO"
                    try {
                        $scanId = $cmd.id
                        $riskyPorts = $cmd.risky_ports
                        if (-not $riskyPorts) {
                            $riskyPorts = @(21,23,25,53,69,80,135,139,161,445,1433,1521,3306,3389,5432,5900,5985,8080,8443)
                        }
                        # Update scan status to in_progress
                        Send-ToNOC $config "vulnerability/update-scan-status" @{
                            scan_id = $scanId
                            status = "in_progress"
                            progress = 5
                            message = "Scansione avviata..."
                        } | Out-Null

                        # Get managed devices for this connector
                        $managedDevices = @()
                        try {
                            $devResponse = Send-ToNOC $config "connector/managed-devices" @{}
                            if ($devResponse -and $devResponse.devices) {
                                $managedDevices = $devResponse.devices
                            }
                        } catch {
                            Write-Log "Impossibile recuperare lista dispositivi: $($_.Exception.Message)" "WARN"
                        }

                        if ($managedDevices.Count -eq 0) {
                            Write-Log "Nessun dispositivo da scansionare" "WARN"
                            Send-ToNOC $config "vulnerability/process-scan-results" @{
                                scan_id = $scanId
                                results = @()
                            } | Out-Null
                        } else {
                            $results = @()
                            $total = $managedDevices.Count
                            $idx = 0
                            foreach ($dev in $managedDevices) {
                                $idx++
                                $pct = [math]::Floor(5 + (90 * $idx / $total))
                                $ip = $dev.ip
                                $community = if ($dev.community) { $dev.community } else { "public" }
                                $devName = if ($dev.name) { $dev.name } else { $ip }

                                Send-ToNOC $config "vulnerability/update-scan-status" @{
                                    scan_id = $scanId
                                    status = "in_progress"
                                    progress = $pct
                                    message = "Scansione $devName ($ip) [$idx/$total]..."
                                } | Out-Null

                                $devResult = Run-VAScan $ip $community $devName $riskyPorts
                                $results += $devResult
                            }

                            # Send results to backend
                            Send-ToNOC $config "vulnerability/process-scan-results" @{
                                scan_id = $scanId
                                results = $results
                            } | Out-Null
                            Write-Log "Scansione VA completata: $($results.Count) dispositivi analizzati" "INFO"
                        }
                    } catch {
                        Write-Log "Errore scansione VA: $($_.Exception.Message)" "ERROR"
                        try {
                            Send-ToNOC $config "vulnerability/update-scan-status" @{
                                scan_id = $scanId
                                status = "error"
                                progress = 0
                                message = "Errore: $($_.Exception.Message)"
                            } | Out-Null
                        } catch {}
                    }
                }
                default {
                    # === ARGUS Remote Browser v3.4.0 ===
                    if ($cmd.type -eq "remote_browser_start") {
                        try {
                            $sid = $cmd.payload.session_id
                            $devIp = $cmd.payload.device_ip
                            $devPort = $cmd.payload.port
                            $token = $cmd.payload.token
                            if (-not $token -and $cmd.payload.ws_relay_url) {
                                # ws_relay_url è formato /api/console-rmt/connector-ws/<token>
                                $token = ($cmd.payload.ws_relay_url -split '/')[-1]
                            }
                            $scheme = if ($devPort -in 80, 8080, 8008) { "http" } else { "https" }
                            $devUrl = "$scheme" + "://" + "$devIp" + ":" + "$devPort" + "/"
                            $rmtScript = Join-Path $PSScriptRoot "remote_browser.ps1"
                            if (-not (Test-Path $rmtScript)) {
                                Write-Log "remote_browser.ps1 non trovato a $rmtScript" "ERROR"
                                break
                            }
                            $rmtLog = Join-Path $env:ProgramData "86NocConnector\rmt_$sid.log"
                            $rmtArgs = @(
                                "-ExecutionPolicy", "Bypass",
                                "-NoProfile",
                                "-NonInteractive",
                                "-WindowStyle", "Hidden",
                                "-File", "`"$rmtScript`"",
                                "-NocCenterUrl", "`"$($config.noc_center_url)`"",
                                "-Token", "`"$token`"",
                                "-DeviceUrl", "`"$devUrl`"",
                                "-SessionId", "`"$sid`"",
                                "-LogFile", "`"$rmtLog`""
                            )
                            Write-Log "Avvio Remote Browser session sid=$sid device=$devUrl log=$rmtLog" "INFO"
                            $psExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
                            Start-Process -FilePath $psExe -ArgumentList $rmtArgs -WindowStyle Hidden | Out-Null
                            Write-Log "Remote Browser process spawn OK per sid=$sid" "INFO"
                        } catch {
                            Write-Log "Errore avvio remote browser: $($_.Exception.Message)" "ERROR"
                        }
                        break
                    }

                    # === ARGUS Remediation Engine (v3.3+) ===
                    if ($cmd.type -eq "remediation") {
                        $exec_id = $cmd.payload.execution_id
                        $dev_ip = $cmd.payload.device_ip
                        $stype = $cmd.payload.script_type
                        $sbody = $cmd.payload.script_body
                        $tout = if ($cmd.payload.timeout_seconds) { [int]$cmd.payload.timeout_seconds } else { 60 }
                        Write-Log "REMEDIATION start: exec=$exec_id script_type=$stype device=$dev_ip" "INFO"
                        $output = ""
                        $errMsg = ""
                        $resultStatus = "success"
                        $exitCode = 0
                        try {
                            switch ($stype) {
                                "powershell" {
                                    $sb = [scriptblock]::Create($sbody)
                                    $job = Start-Job -ScriptBlock $sb -ArgumentList $dev_ip
                                    $completed = Wait-Job -Job $job -Timeout $tout
                                    if (-not $completed) {
                                        Stop-Job -Job $job -ErrorAction SilentlyContinue
                                        $errMsg = "timeout after ${tout}s"
                                        $resultStatus = "failed"
                                    } else {
                                        $output = (Receive-Job -Job $job 2>&1 | Out-String)
                                    }
                                    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
                                }
                                "http-get" {
                                    $cfgJ = $sbody | ConvertFrom-Json
                                    $url = $cfgJ.url -replace '\{device_ip\}', $dev_ip
                                    $r = Invoke-WebRequest -Uri $url -TimeoutSec $tout -UseBasicParsing -ErrorAction Stop
                                    $output = "HTTP $($r.StatusCode)`n$($r.Content.Substring(0, [math]::Min(500, $r.Content.Length)))"
                                }
                                "http-post" {
                                    $cfgJ = $sbody | ConvertFrom-Json
                                    $url = $cfgJ.url -replace '\{device_ip\}', $dev_ip
                                    $body = if ($cfgJ.body) { $cfgJ.body | ConvertTo-Json -Compress } else { "" }
                                    $r = Invoke-WebRequest -Uri $url -Method POST -Body $body -ContentType "application/json" -TimeoutSec $tout -UseBasicParsing -ErrorAction Stop
                                    $output = "HTTP $($r.StatusCode)`n$($r.Content.Substring(0, [math]::Min(500, $r.Content.Length)))"
                                }
                                "snmp-set" {
                                    $output = "SNMP-SET is not implemented yet (payload: $sbody)"
                                    $resultStatus = "failed"
                                    $errMsg = "snmp-set handler missing"
                                }
                                default {
                                    # Shell fallback: use cmd.exe
                                    $tmp = [System.IO.Path]::GetTempFileName() + ".bat"
                                    Set-Content -Path $tmp -Value $sbody -Encoding ASCII
                                    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $tmp -NoNewWindow -PassThru -RedirectStandardOutput "$tmp.out" -RedirectStandardError "$tmp.err"
                                    if (-not $proc.WaitForExit($tout * 1000)) {
                                        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                                        $resultStatus = "failed"; $errMsg = "timeout"
                                    }
                                    $exitCode = $proc.ExitCode
                                    if (Test-Path "$tmp.out") { $output = Get-Content "$tmp.out" -Raw -ErrorAction SilentlyContinue }
                                    if (Test-Path "$tmp.err") { $errMsg = Get-Content "$tmp.err" -Raw -ErrorAction SilentlyContinue }
                                    Remove-Item "$tmp", "$tmp.out", "$tmp.err" -ErrorAction SilentlyContinue
                                }
                            }
                        } catch {
                            $resultStatus = "failed"
                            $errMsg = $_.Exception.Message
                        }
                        if ($output.Length -gt 4000) { $output = $output.Substring(0, 4000) + "...[truncated]" }
                        try {
                            Send-ToNOC $config "remediation/result" @{
                                execution_id = $exec_id
                                result = $resultStatus
                                output = $output
                                error = $errMsg
                                exit_code = $exitCode
                            } | Out-Null
                            Write-Log "REMEDIATION done: exec=$exec_id status=$resultStatus" "INFO"
                        } catch {
                            Write-Log "Failed to report remediation result: $($_.Exception.Message)" "WARN"
                        }
                    } else {
                        Write-Log "Comando sconosciuto: $($cmd.type)" "WARN"
                    }
                }
            }
        }
    }
    
    # Check if server is requesting a forced update
    if ($response -and $response.force_update) {
        Write-Log "FORCE UPDATE ricevuto dal NOC per v$($response.latest_version)." "INFO"
        # v3.6.0+: try Task Scheduler first, fallback to direct child process
        $taskTriggered = $false
        try {
            $taskName = "\86BIT\ArgusConnectorUpdater"
            $tsResult = & schtasks.exe /Run /TN $taskName 2>&1
            $tsExit = $LASTEXITCODE
            if ($tsExit -eq 0) {
                Write-Log "Task Scheduler ArgusConnectorUpdater triggerato (schtasks /Run OK)." "INFO"
                $taskTriggered = $true
            } else {
                Write-Log "schtasks /Run fallito (exit=$tsExit, output: $tsResult). Provo fallback inline." "WARN"
            }
        } catch {
            Write-Log "Task Scheduler error: $($_.Exception.Message). Provo fallback inline." "WARN"
        }

        if (-not $taskTriggered) {
            # FALLBACK: eseguiamo update_check.ps1 direttamente come child process detached.
            # Funziona anche se il Task Scheduler e' stato eliminato/corrotto.
            $updateScript = Join-Path $PSScriptRoot "update_check.ps1"
            if (-not (Test-Path $updateScript)) {
                $updateScript = "C:\Program Files\86NocConnector\src\update_check.ps1"
            }
            if (Test-Path $updateScript) {
                try {
                    Write-Log "FALLBACK: lancio update_check.ps1 direttamente da $updateScript" "INFO"
                    # Detached so the connector can keep running while updater stops it later
                    $psArgs = @("-NoProfile","-ExecutionPolicy","Bypass","-WindowStyle","Hidden","-File",$updateScript)
                    Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WindowStyle Hidden | Out-Null
                    Write-Log "Updater inline lanciato in background." "INFO"
                } catch {
                    Write-Log "FALLBACK fallito: $($_.Exception.Message)" "ERROR"
                }
            } else {
                Write-Log "ERRORE CRITICO: update_check.ps1 non trovato ne' nel folder src ne' in C:\Program Files\86NocConnector\src. Update impossibile." "ERROR"
            }
        }
    }
}

# ==================== PING/HTTP ADVANCED MONITORING ====================

function Poll-PingDevice($ip, $name, $httpPort) {
    $alerts = @()
    $reachable = $false
    $pingMs = $null
    
    # Advanced ping metrics
    $pingMin = $null
    $pingMax = $null
    $pingAvg = $null
    $pingJitter = $null
    $packetLoss = 0
    $ttl = $null
    $dnsMs = $null
    $openPorts = @()
    $httpDetails = $null
    
  try {
    
    # ========== 1. DNS Resolution Time ==========
    try {
        $dnsStart = [System.Diagnostics.Stopwatch]::StartNew()
        $dnsResult = [System.Net.Dns]::GetHostEntry($ip)
        $dnsStart.Stop()
        $dnsMs = $dnsStart.ElapsedMilliseconds
    } catch {
        $dnsMs = -1
    }
    
    # ========== 2. Multi-Ping (5 probes) ==========
    $pingResults = @()
    $pingObj = New-Object System.Net.NetworkInformation.Ping
    for ($i = 0; $i -lt 5; $i++) {
        try {
            $reply = $pingObj.Send($ip, 3000)
            if ($reply.Status -eq "Success") {
                $pingResults += $reply.RoundtripTime
                if ($null -eq $ttl) { $ttl = $reply.Options.Ttl }
            }
        } catch {}
        if ($i -lt 4) { Start-Sleep -Milliseconds 200 }
    }
    $pingObj.Dispose()
    
    $totalSent = 5
    $totalReceived = $pingResults.Count
    $packetLoss = [math]::Round((($totalSent - $totalReceived) / $totalSent) * 100, 1)
    
    if ($totalReceived -gt 0) {
        $reachable = $true
        $pingMin = ($pingResults | Measure-Object -Minimum).Minimum
        $pingMax = ($pingResults | Measure-Object -Maximum).Maximum
        $pingAvg = [math]::Round(($pingResults | Measure-Object -Average).Average, 1)
        $pingMs = $pingAvg
        
        # Jitter: average deviation between consecutive pings
        if ($pingResults.Count -gt 1) {
            $diffs = @()
            for ($j = 1; $j -lt $pingResults.Count; $j++) {
                $diffs += [math]::Abs($pingResults[$j] - $pingResults[$j-1])
            }
            $pingJitter = [math]::Round(($diffs | Measure-Object -Average).Average, 1)
        } else {
            $pingJitter = 0
        }
    }
    
    # ========== 3. TCP Port Scan (common services) ==========
    $portsToScan = @(
        @{port=22;  name="SSH"},
        @{port=23;  name="Telnet"},
        @{port=80;  name="HTTP"},
        @{port=443; name="HTTPS"},
        @{port=3389;name="RDP"},
        @{port=8080;name="HTTP-Alt"},
        @{port=8443;name="HTTPS-Alt"},
        @{port=161; name="SNMP"},
        @{port=53;  name="DNS"},
        @{port=21;  name="FTP"},
        @{port=25;  name="SMTP"},
        @{port=5900;name="VNC"},
        @{port=3306;name="MySQL"},
        @{port=1433;name="MSSQL"},
        @{port=445; name="SMB"}
    )
    
    if ($reachable) {
        foreach ($p in $portsToScan) {
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $asyncResult = $tcp.BeginConnect($ip, $p.port, $null, $null)
                $wait = $asyncResult.AsyncWaitHandle.WaitOne(500, $false)
                if ($wait) {
                    try {
                        $tcp.EndConnect($asyncResult)
                        if ($tcp.Connected) {
                            $openPorts += @{ port = $p.port; name = $p.name; open = $true }
                        }
                    } catch {}
                }
                $tcp.Close()
                $tcp.Dispose()
            } catch {
                # Silently skip unreachable ports
            }
        }
    }
    
    # ========== 4. HTTP/HTTPS Deep Check ==========
    if ($reachable) {
        $httpCheckPort = $httpPort
        # Auto-detect: if port 80 or 443 is open, use it
        if (-not $httpCheckPort) {
            $has443 = $openPorts | Where-Object { $_.port -eq 443 }
            $has80 = $openPorts | Where-Object { $_.port -eq 80 }
            $has8080 = $openPorts | Where-Object { $_.port -eq 8080 }
            if ($has443) { $httpCheckPort = 443 }
            elseif ($has80) { $httpCheckPort = 80 }
            elseif ($has8080) { $httpCheckPort = 8080 }
        }
        
        if ($httpCheckPort) {
            $httpDetails = @{
                port = $httpCheckPort
                status_code = $null
                response_ms = $null
                server_header = $null
                content_type = $null
                ssl_expiry = $null
                ssl_issuer = $null
                title = $null
            }
            
            $protocol = if ($httpCheckPort -eq 443 -or $httpCheckPort -eq 8443) { "https" } else { "http" }
            $url = "${protocol}://${ip}:${httpCheckPort}/"
            
            try {
                # Bypass SSL errors safely
                try {
                    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { param($s,$c,$ch,$e) return $true }
                    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls11
                } catch {}
                
                $httpStart = [System.Diagnostics.Stopwatch]::StartNew()
                $req = [System.Net.HttpWebRequest]::Create($url)
                $req.Timeout = 5000
                $req.Method = "GET"
                $req.AllowAutoRedirect = $true
                $req.UserAgent = "86NocConnector/2.2.0"
                $resp = $req.GetResponse()
                $httpStart.Stop()
                
                $httpDetails.status_code = [in