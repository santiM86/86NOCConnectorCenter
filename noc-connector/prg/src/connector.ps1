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
        
        $udpClient.Close()
        Write-Log "WoL Magic Packet inviato a $macAddress (target: $targetIP) - broadcast 255.255.255.255 e subnet" "INFO"
    } catch {
        Write-Log "Errore invio WoL a $macAddress : $($_.Exception.Message)" "ERROR"
    }
}


function Invoke-SecureGet($config, $endpoint, $timeoutSec = 15) {
    # Secure GET with HMAC-SHA256 + Anti-Replay
    try {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }
        $url = "$($config.noc_center_url)/api/$endpoint"
        $timestamp = [math]::Floor(([DateTimeOffset]::UtcNow).ToUnixTimeSeconds())
        $nonce = [guid]::NewGuid().ToString("N")
        $hmacSecret = "argus-hmac-k3y-2026!" + $config.api_key
        $message = "$($config.api_key)$timestamp$nonce"
        $hmac = New-Object System.Security.Cryptography.HMACSHA256
        $hmac.Key = [Text.Encoding]::UTF8.GetBytes($hmacSecret)
        $signature = [BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($message))).Replace("-","").ToLower()
        $headers = @{
            "X-API-Key"        = $config.api_key
            "X-HMAC-Signature" = $signature
            "X-Timestamp"      = $timestamp.ToString()
            "X-Nonce"          = $nonce
        }
        return Invoke-RestMethod -Uri $url -Method Get -Headers $headers -TimeoutSec $timeoutSec -ErrorAction Stop
    } catch {
        Write-Log "Errore secure GET ($endpoint): $($_.Exception.Message)" "ERROR"
        return $null
    }
}


function Send-ToNOC($config, $endpoint, $payload) {
    try {
        # === TLS 1.2/1.3 enforcement ===
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }
        
        $body = $payload | ConvertTo-Json -Depth 5 -Compress
        $url = "$($config.noc_center_url)/api/$endpoint"
        
        # === HMAC-SHA256 Signature + Anti-Replay ===
        $timestamp = [math]::Floor(([DateTimeOffset]::UtcNow).ToUnixTimeSeconds())
        $nonce = [guid]::NewGuid().ToString("N")
        $hmacSecret = "argus-hmac-k3y-2026!" + $config.api_key
        
        # Body hash
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $bodyHash = if ($body) { [BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($body))).Replace("-","").ToLower() } else { "" }
        
        # HMAC message = api_key + timestamp + nonce + body_hash
        $message = "$($config.api_key)$timestamp$nonce$bodyHash"
        $hmac = New-Object System.Security.Cryptography.HMACSHA256
        $hmac.Key = [Text.Encoding]::UTF8.GetBytes($hmacSecret)
        $signature = [BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($message))).Replace("-","").ToLower()
        
        $headers = @{
            "X-API-Key"        = $config.api_key
            "X-HMAC-Signature" = $signature
            "X-Timestamp"      = $timestamp.ToString()
            "X-Nonce"          = $nonce
            "Content-Type"     = "application/json"
        }
        
        $response = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15 -ErrorAction Stop
        
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
        Write-Log "Errore invio a NOC ($endpoint): $errMsg" "ERROR"
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
        Write-Log "FORCE UPDATE ricevuto dal NOC! Aggiornamento a v$($response.latest_version)..." "INFO"
        $updateInfo = @{
            update_available = $true
            latest_version = $response.latest_version
            download_url = $response.download_url
            changelog = $response.changelog
        }
        $success = Install-Update $config $updateInfo
        if ($success) {
            Write-Log "Updater avviato. Connector in chiusura..." "INFO"
            # L'updater gestisce: stop -> copia file -> riavvio
            # Non serve fare nient'altro qui
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
                
                $httpDetails.status_code = [int]$resp.StatusCode
                $httpDetails.response_ms = $httpStart.ElapsedMilliseconds
                $httpDetails.server_header = $resp.Headers["Server"]
                $httpDetails.content_type = $resp.ContentType
                
                # Try to read page title
                try {
                    $stream = $resp.GetResponseStream()
                    $reader = New-Object System.IO.StreamReader($stream)
                    $bodyText = $reader.ReadToEnd()
                    $reader.Close()
                    $stream.Close()
                    if ($bodyText.Length -gt 4000) { $bodyText = $bodyText.Substring(0, 4000) }
                    if ($bodyText -match '<title[^>]*>([^<]+)</title>') {
                        $httpDetails.title = $Matches[1].Trim()
                    }
                } catch {}
                
                $resp.Close()
                
                # SSL Certificate check
                if ($protocol -eq "https") {
                    try {
                        $cert = $req.ServicePoint.Certificate
                        if ($cert) {
                            $cert2 = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($cert)
                            $httpDetails.ssl_expiry = $cert2.NotAfter.ToString("yyyy-MM-dd")
                            $httpDetails.ssl_issuer = $cert2.Issuer
                            
                            # Alert if SSL expires within 30 days
                            $daysLeft = ($cert2.NotAfter - (Get-Date)).Days
                            if ($daysLeft -lt 30 -and $daysLeft -gt 0) {
                                $alerts += @{
                                    device_ip   = $ip
                                    oid         = "ssl.expiry"
                                    value       = "Certificato SSL di $name ($ip) scade tra $daysLeft giorni ($($cert2.NotAfter.ToString('dd/MM/yyyy')))"
                                    trap_type   = "sslExpiring"
                                    severity    = "high"
                                    device_name = $name
                                }
                            }
                        }
                    } catch {}
                }
            } catch [System.Net.WebException] {
                $httpStart.Stop()
                $httpDetails.response_ms = $httpStart.ElapsedMilliseconds
                if ($_.Exception.Response) {
                    $httpDetails.status_code = [int]$_.Exception.Response.StatusCode
                    $httpDetails.server_header = $_.Exception.Response.Headers["Server"]
                } else {
                    $httpDetails.status_code = 0
                }
            } catch {
                $httpDetails.status_code = 0
            }
            
            [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $null
        }
    }
    
    # ========== 5. State change alerts ==========
    $wasUp = $script:DeviceUp.ContainsKey($ip) -and $script:DeviceUp[$ip]
    
    if (-not $reachable -and $wasUp) {
        $alerts += @{
            device_ip  = $ip
            oid        = "ping.monitor"
            value      = "Dispositivo $name ($ip) NON RAGGIUNGIBILE - ping fallito (packet loss: ${packetLoss}%)"
            trap_type  = "deviceDown"
            severity   = "critical"
            device_name = $name
        }
    }
    if ($reachable -and $script:DeviceUp.ContainsKey($ip) -and -not $wasUp) {
        $alerts += @{
            device_ip  = $ip
            oid        = "ping.monitor"
            value      = "Dispositivo $name ($ip) di nuovo RAGGIUNGIBILE (latenza: ${pingAvg}ms)"
            trap_type  = "deviceUp"
            severity   = "low"
            device_name = $name
        }
    }
    
    # Alert on high latency
    if ($pingAvg -and $pingAvg -gt 200) {
        $alerts += @{
            device_ip  = $ip
            oid        = "ping.latency"
            value      = "Latenza alta su $name ($ip): ${pingAvg}ms (jitter: ${pingJitter}ms)"
            trap_type  = "highLatency"
            severity   = "high"
            device_name = $name
        }
    }
    
    # Alert on packet loss
    if ($packetLoss -gt 0 -and $packetLoss -lt 100) {
        $plSeverity = "medium"
        if ($packetLoss -ge 40) { $plSeverity = "high" }
        $alerts += @{
            device_ip  = $ip
            oid        = "ping.packetloss"
            value      = "Packet loss su $name ($ip): ${packetLoss}% ($totalReceived/$totalSent)"
            trap_type  = "packetLoss"
            severity   = $plSeverity
            device_name = $name
        }
    }
    
    $script:DeviceUp[$ip] = $reachable
    
  } catch {
    Write-Log "Errore critico in Poll-PingDevice per $name ($ip): $($_.Exception.Message)" "ERROR"
    $script:DeviceUp[$ip] = $false
  }

    $httpStatusVal = $null
    if ($httpDetails -and $httpDetails.status_code) { $httpStatusVal = $httpDetails.status_code }

    return @{
        alerts      = $alerts
        reachable   = $reachable
        ping_ms     = $pingAvg
        ping_min    = $pingMin
        ping_max    = $pingMax
        ping_avg    = $pingAvg
        ping_jitter = $pingJitter
        packet_loss = $packetLoss
        ttl         = $ttl
        dns_ms      = $dnsMs
        open_ports  = $openPorts
        http_details = $httpDetails
        http_status = $httpStatusVal
    }
}

# ==================== SNMP POLLING ====================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pollerPath = Join-Path $ScriptDir "snmp_poller.ps1"
if (Test-Path $pollerPath) {
    . $pollerPath
}

function Send-DeviceReport($config, $devices) {
    $reportDevices = @()
    foreach ($dev in $devices) {
        $ip = $dev.ip
        $devName = if ($dev.name) { $dev.name } else { $ip }
        $monitorType = if ($dev.monitor_type) { $dev.monitor_type } else { "snmp" }
        $community = if ($dev.community) { $dev.community } else { "public" }
        
        if ($monitorType -eq "ping" -or $monitorType -eq "http") {
            # Ping/HTTP device - use cached poll results with advanced metrics
            $reachable = $script:DeviceUp.ContainsKey($ip) -and $script:DeviceUp[$ip]
            $pingData = if ($script:PingResults.ContainsKey($ip)) { $script:PingResults[$ip] } else { $null }
            
            $deviceReport = @{
                device_ip = $ip
                device_name = $devName
                monitor_type = $monitorType
                reachable = $reachable
                ping_ms = if ($pingData) { $pingData.ping_ms } else { $null }
                http_status = if ($pingData) { $pingData.http_status } else { $null }
                ports = @()
                sys_descr = ""
                sys_uptime = ""
                poll_timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
                # Advanced ping metrics
                ping_stats = $null
                open_ports = $null
                http_details = $null
            }
            
            if ($pingData) {
                $deviceReport.ping_stats = @{
                    min = $pingData.ping_min
                    max = $pingData.ping_max
                    avg = $pingData.ping_avg
                    jitter = $pingData.ping_jitter
                    packet_loss = $pingData.packet_loss
                    ttl = $pingData.ttl
                    dns_ms = $pingData.dns_ms
                }
                $deviceReport.open_ports = $pingData.open_ports
                $deviceReport.http_details = $pingData.http_details
                
                # Build sys_descr from collected info
                $descParts = @()
                if ($pingData.http_details -and $pingData.http_details.server_header) {
                    $descParts += $pingData.http_details.server_header
                }
                if ($pingData.http_details -and $pingData.http_details.title) {
                    $descParts += $pingData.http_details.title
                }
                if ($pingData.open_ports -and $pingData.open_ports.Count -gt 0) {
                    $portNames = ($pingData.open_ports | ForEach-Object { $_.name }) -join ", "
                    $descParts += "Servizi: $portNames"
                }
                if ($descParts.Count -gt 0) {
                    $deviceReport.sys_descr = $descParts -join " | "
                } else {
                    $deviceReport.sys_descr = if ($reachable) { "Raggiungibile (ping OK)" } else { "Non raggiungibile" }
                }
            }
            
            $reportDevices += $deviceReport
        } else {
            # SNMP device - full extended metrics
            $reachable = $script:DeviceUp.ContainsKey($ip) -and $script:DeviceUp[$ip]
            $ports = @()
            
            if ($script:PortStates.ContainsKey($ip)) {
                foreach ($idx in $script:PortStates[$ip].Keys) {
                    $operStatus = $script:PortStates[$ip][$idx]
                    $statusName = if ($script:IfStatusMap.ContainsKey($operStatus)) { $script:IfStatusMap[$operStatus] } else { "unknown" }
                    $ports += @{
                        index = $idx
                        status = $statusName
                        status_code = $operStatus
                    }
                }
            }
            
            $sysDescr = ""
            $sysName = ""
            $sysUptime = ""
            $extMetrics = $null
            $trafficData = $null
            if ($reachable) {
                try {
                    $sysDescr = Get-SnmpValue $ip $community "1.3.6.1.2.1.1.1.0"
                    $sysName = Get-SnmpValue $ip $community "1.3.6.1.2.1.1.5.0"
                    $uptimeTicks = Get-SnmpValue $ip $community "1.3.6.1.2.1.1.3.0"
                    if ($uptimeTicks) {
                        $secs = [math]::Floor($uptimeTicks / 100)
                        $d = [math]::Floor($secs / 86400)
                        $h = [math]::Floor(($secs % 86400) / 3600)
                        $m = [math]::Floor(($secs % 3600) / 60)
                        $sysUptime = "${d}g ${h}h ${m}m"
                    }
                } catch {}
                
                # Extended metrics (CPU, Memory, Temperature, Hardware health)
                try { $extMetrics = Poll-ExtendedMetrics $ip $community } catch {}
                
                # Interface traffic (bandwidth, speed, errors)
                try { $trafficData = Poll-InterfaceTraffic $ip $community } catch {}
            }
            
            # Enrich ports with traffic data
            if ($trafficData) {
                foreach ($p in $ports) {
                    $idx = $p.index
                    if ($trafficData.ContainsKey($idx)) {
                        $t = $trafficData[$idx]
                        $p.speed_bps = $t.speed_bps
                        $p.in_bps = $t.in_bps
                        $p.out_bps = $t.out_bps
                        $p.in_errors = $t.in_errors
                        $p.out_errors = $t.out_errors
                    }
                }
            }
            
            $deviceReport = @{
                device_ip = $ip
                device_name = $devName
                monitor_type = "snmp"
                reachable = $reachable
                ports = $ports
                sys_descr = "$sysDescr"
                sys_name = "$sysName"
                sys_uptime = $sysUptime
                poll_timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
            }
            
            # Add extended metrics if available
            if ($extMetrics) {
                $deviceReport.cpu_usage = $extMetrics.cpu_usage
                $deviceReport.memory_usage = $extMetrics.memory_usage
                $deviceReport.temperature = $extMetrics.temperature
                $deviceReport.device_class = $extMetrics.device_class
                $deviceReport.hardware = $extMetrics.hardware
                if ($extMetrics.firewall) {
                    $deviceReport.firewall = $extMetrics.firewall
                }
            }
            
            # Redfish/iLO deep polling
            # Trigger when EITHER:
            #  - SNMP classified the device as hpe-ilo, OR
            #  - Device is manually tagged as ilo/server_type, OR
            #  - Vault contains credentials of type "ilo" for this IP (even without SNMP)
            $credEntry = $null
            if ($vaultCreds.ContainsKey($ip)) { $credEntry = $vaultCreds[$ip] }
            $redfishTrigger = $false
            if ($credEntry -and ($credEntry.credential_type -eq "ilo" -or $credEntry.credential_type -eq "redfish")) {
                $redfishTrigger = $true
            } elseif ($extMetrics -and $extMetrics.device_class -eq "hpe-ilo" -and $credEntry) {
                $redfishTrigger = $true
            } elseif ($dev.device_type -eq "ilo" -and $credEntry) {
                $redfishTrigger = $true
            }

            if ($redfishTrigger) {
                # === Enterprise dedup (v3.3.2) ===
                # Se questa credenziale ha external_url configurata E non ha connector_only=true,
                # il backend ARGUS polla gia' iLO direttamente. Skippiamo per evitare doppio polling
                # e rate-limit dell'iLO (iLO 5 max ~30 sessioni concorrenti).
                $hasExternalUrl = $credEntry.external_url -and $credEntry.external_url.Length -gt 0
                $connectorOnly = $credEntry.connector_only -eq $true
                if ($hasExternalUrl -and -not $connectorOnly) {
                    Write-Log "  Redfish $devName ($ip): skip (backend polla diretto via external_url, modalita' ridondante passiva)" "INFO"
                    $redfishTrigger = $false
                }
            }

            if ($redfishTrigger) {
                try {
                    Write-Log "  Redfish polling $devName ($ip) con credenziali dal Vault (type=$($credEntry.credential_type))..."
                    $rfMetrics = Poll-RedfishMetrics $ip $credEntry
                    if ($rfMetrics.redfish_ok) {
                        $deviceReport.redfish = @{
                            power_watts = $rfMetrics.power_watts
                            bios_version = $rfMetrics.bios_version
                            server_model = $rfMetrics.server_model
                            serial_number = $rfMetrics.serial_number
                            uuid = $rfMetrics.uuid
                            ilo_firmware = $rfMetrics.ilo_firmware
                            ilo_license = $rfMetrics.ilo_license
                            total_memory_gb = $rfMetrics.total_memory_gb
                            memory_dimms = $rfMetrics.memory_dimms
                            network_adapters = $rfMetrics.network_adapters
                            storage_controllers = $rfMetrics.storage_controllers
                        }
                        # Ensure device_class is set so backend/UI recognises it as iLO
                        if (-not $deviceReport.device_class) { $deviceReport.device_class = "hpe-ilo" }
                        Write-Log "  Redfish OK: $($rfMetrics.server_model) | Power: $($rfMetrics.power_watts)W | BIOS: $($rfMetrics.bios_version)"
                    } else {
                        Write-Log "  Redfish non disponibile per ${ip}: $($rfMetrics.error)" "WARN"
                    }
                } catch {
                    Write-Log "  Errore Redfish $ip : $($_.Exception.Message)" "WARN"
                }
            } elseif ($credEntry -and -not $extMetrics) {
                Write-Log "  $devName ($ip): SNMP non disponibile e credenziali Vault type=$($credEntry.credential_type) non compatibili con Redfish" "INFO"
            }
            
            $reportDevices += $deviceReport
        }
    }
    
    $payload = @{
        hostname = $env:COMPUTERNAME
        devices = $reportDevices
    }
    Send-ToNOC $config "connector/device-report" $payload | Out-Null
    Write-Log "Report stato dispositivi inviato ($($reportDevices.Count) dispositivi)"
}

function Fetch-DevicesFromNOC($config) {
    try {
        $response = Invoke-SecureGet $config "connector/fetch-devices"
        if ($response -and $response.Count -gt 0) {
            Write-Log "Dispositivi ricevuti dal NOC: $($response.Count)"
            return @($response)
        }
    } catch {
        Write-Log "Errore fetch dispositivi dal NOC: $($_.Exception.Message)" "WARN"
    }
    return $null
}

function Fetch-VaultCredentials($config) {
    <#
    .SYNOPSIS
        Recupera le credenziali cifrate dal Vault del SOC per interrogare iLO via Redfish.
    #>
    try {
        $response = Invoke-SecureGet $config "connector/vault/credentials"
        if ($response -and $response.Count -gt 0) {
            Write-Log "Credenziali Vault ricevute: $($response.Count)"
            # Build lookup table by device IP
            $credMap = @{}
            foreach ($c in $response) {
                if ($c.device_ip) {
                    $credMap[$c.device_ip] = @{
                        username = $c.username
                        password = $c.password
                        port = $c.port
                        credential_type = $c.credential_type
                    }
                }
            }
            return $credMap
        } else {
            Write-Log "Vault: nessuna credenziale presente" "INFO"
        }
    } catch {
        Write-Log "Errore fetch credenziali Vault: $($_.Exception.Message)" "WARN"
    }
    return @{}
}

function Start-PollingLoop($config) {
    $devices = @()
    if ($config.devices) {
        $devices = @($config.devices)
    }
    
    # Also fetch from NOC (centralized management)
    $nocDevices = Fetch-DevicesFromNOC $config
    if ($nocDevices) {
        # Merge: NOC devices take priority, add local-only devices
        $nocIPs = $nocDevices | ForEach-Object { $_.ip }
        foreach ($localDev in $devices) {
            if ($localDev.ip -notin $nocIPs) {
                $nocDevices += $localDev
            }
        }
        $devices = $nocDevices
    }
    
    if ($devices.Count -eq 0) {
        Write-Log "Nessun dispositivo configurato per polling"
        return
    }

    # Fetch Vault credentials for Redfish/iLO polling
    $vaultCreds = Fetch-VaultCredentials $config
    if ($vaultCreds.Count -gt 0) {
        Write-Log "Credenziali Vault disponibili per $($vaultCreds.Count) dispositivi"
    }

    # Separate SNMP, Ping/HTTP, and Printer devices
    $snmpDevices = @($devices | Where-Object { (-not $_.monitor_type -or $_.monitor_type -eq "snmp") -and $_.device_type -ne "printer" })
    $pingDevices = @($devices | Where-Object { $_.monitor_type -eq "ping" -or $_.monitor_type -eq "http" })
    $printerDevices = @($devices | Where-Object { $_.device_type -eq "printer" })
    
    # Initialize ping results cache
    if (-not $script:PingResults) { $script:PingResults = @{} }

    $interval = if ($config.poll_interval_seconds) { $config.poll_interval_seconds } else { 60 }
    Write-Log "Polling attivo per $($devices.Count) dispositivi ogni ${interval}s (SNMP: $($snmpDevices.Count), Ping/HTTP: $($pingDevices.Count), Stampanti: $($printerDevices.Count))"
    foreach ($dev in $devices) {
        $mType = if ($dev.monitor_type) { $dev.monitor_type } else { "snmp" }
        $dType = if ($dev.device_type) { $dev.device_type } else { "network" }
        Write-Log "  - $($dev.name) ($($dev.ip)) tipo=$mType device_type=$dType"
    }

    # First poll - initialize states and send initial report
    Write-Log "Prima scansione in corso..."
    if ($snmpDevices.Count -gt 0) { $null = Poll-AllDevices $snmpDevices $config }
    if ($printerDevices.Count -gt 0) { Poll-AllPrinters $printerDevices $config }
    foreach ($pd in $pingDevices) {
        $httpPort = if ($pd.http_port) { $pd.http_port } else { 80 }
        $result = Poll-PingDevice $pd.ip $pd.name $httpPort
        $script:PingResults[$pd.ip] = $result
    }
    Write-Log "Stato iniziale acquisito. Invio report al NOC..."
    Send-DeviceReport $config $devices
    
    $refreshCounter = 0

    while ($global:Running) {
        try {
            # Poll SNMP devices
            if ($snmpDevices.Count -gt 0) {
                $alerts = Poll-AllDevices $snmpDevices $config
                foreach ($alert in $alerts) {
                    Write-Log "[POLL] $($alert.trap_type): $($alert.value)" "WARN"
                    Send-SNMPToNOC $config $alert
                }
            }
            
            # Poll Ping/HTTP devices
            foreach ($pd in $pingDevices) {
                $httpPort = if ($pd.http_port) { $pd.http_port } else { 80 }
                $result = Poll-PingDevice $pd.ip $pd.name $httpPort
                $script:PingResults[$pd.ip] = $result
                foreach ($alert in $result.alerts) {
                    Write-Log "[PING] $($alert.trap_type): $($alert.value)" "WARN"
                    Send-SNMPToNOC $config $alert
                }
            }

            # Poll Printer devices (SNMP Printer-MIB)
            if ($printerDevices.Count -gt 0) {
                Poll-AllPrinters $printerDevices $config
            }
            
            # Send full status report after every poll
            Send-DeviceReport $config $devices
            
            # Refresh device list from NOC every 10 cycles
            $refreshCounter++
            if ($refreshCounter -ge 10) {
                $refreshCounter = 0
                $nocDevices = Fetch-DevicesFromNOC $config
                if ($nocDevices) {
                    $nocIPs = $nocDevices | ForEach-Object { $_.ip }
                    $localOnly = @()
                    if ($config.devices) {
                        foreach ($localDev in @($config.devices)) {
                            if ($localDev.ip -notin $nocIPs) { $localOnly += $localDev }
                        }
                    }
                    $devices = @($nocDevices) + $localOnly
                    $snmpDevices = @($devices | Where-Object { (-not $_.monitor_type -or $_.monitor_type -eq "snmp") -and $_.device_type -ne "printer" })
                    $pingDevices = @($devices | Where-Object { $_.monitor_type -eq "ping" -or $_.monitor_type -eq "http" })
                    $printerDevices = @($devices | Where-Object { $_.device_type -eq "printer" })
                    Write-Log "Lista dispositivi aggiornata dal NOC: $($devices.Count) totali (SNMP: $($snmpDevices.Count), Ping: $($pingDevices.Count), Stampanti: $($printerDevices.Count))"
                }
                
                # Full Network Discovery - ogni 10 cicli
                if ($snmpDevices.Count -gt 0) {
                    try {
                        Write-Log "Avvio Full Network Discovery (LLDP + MAC + Speed)..." "INFO"
                        Run-FullDiscovery $config $snmpDevices
                    } catch {
                        Write-Log "Errore Network Discovery: $($_.Exception.Message)" "WARN"
                    }
                }
            }
        } catch {
            Write-Log "Errore polling: $($_.Exception.Message)" "ERROR"
        }
        Start-Sleep -Seconds $interval
    }
}

# ==================== AUTO-UPDATE ====================

function Check-ForUpdate($config) {
    try {
        $response = Invoke-SecureGet $config "connector/update-check"
        
        if ($response.update_available -and $response.latest_version -ne $global:Version) {
            Write-Log "Aggiornamento disponibile: v$($global:Version) -> v$($response.latest_version)" "INFO"
            return $response
        }
    } catch {
        Write-Log "Errore check aggiornamento: $($_.Exception.Message)" "WARN"
    }
    return $null
}

function Send-UpdateProgress($config, $progress, $status, $message) {
    try {
        Send-ToNOC $config "connector/update-progress" @{ progress = $progress; status = $status; message = $message } | Out-Null
    } catch {}
}


function Install-Update($config, $updateInfo) {
    try {
        Write-Log "Download aggiornamento v$($updateInfo.latest_version)..." "INFO"
        Send-UpdateProgress $config 5 "downloading" "Inizio download v$($updateInfo.latest_version)..."
        $headers = @{ "X-API-Key" = $config.api_key }
        $downloadUrl = "$($config.noc_center_url)$($updateInfo.download_url)"
        $tempZip = Join-Path $env:TEMP "86NocConnector_update.zip"
        $tempExtract = Join-Path $env:TEMP "86NocConnector_update"
        
        # Download
        Send-UpdateProgress $config 10 "downloading" "Download in corso..."
        Invoke-WebRequest -Uri $downloadUrl -Headers $headers -OutFile $tempZip -TimeoutSec 120 -ErrorAction Stop
        Write-Log "Download completato: $tempZip" "INFO"
        Send-UpdateProgress $config 30 "downloading" "Download completato"
        
        # Extract to temp
        Send-UpdateProgress $config 35 "extracting" "Estrazione file..."
        if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($tempZip, $tempExtract)
        Write-Log "File estratti in: $tempExtract" "INFO"
        Send-UpdateProgress $config 45 "extracting" "File estratti. Avvio updater..."
        
        # Launch updater OUTSIDE the NSSM Job Object.
        # ROOT CAUSE del bug "chiude e non si riapre": NSSM mette tutti i processi figli del servizio
        # nel suo Job Object. Quando l'updater chiama Stop-Service, il job viene killato interamente,
        # compreso l'updater stesso, a meta' copia file. Risultato: servizio morto, nessun restart.
        # FIX v3.3.1: usiamo WMI Win32_Process.Create che spawna processi figli del service WMI
        # (wmiprvse.exe), FUORI dal job object di NSSM. L'updater puo' quindi fare Stop/Start/Copy
        # in sicurezza. Fallback schtasks SYSTEM come belt+suspenders.
        $installDir = Split-Path -Parent $PSScriptRoot
        $updaterPath = Join-Path $PSScriptRoot "updater.ps1"
        $newUpdater = Join-Path $tempExtract "src\updater.ps1"
        if (Test-Path $newUpdater) { $updaterPath = $newUpdater }

        if (-not (Test-Path $updaterPath)) {
            $msg = "Updater script non trovato: $updaterPath"
            Write-Log $msg "ERROR"
            Send-UpdateProgress $config 0 "error" $msg
            return $false
        }

        # Copia updater.ps1 in location TRUSTED (InstallDir) invece che in TEMP.
        # ROOT CAUSE v3.3.2 bug: stagiare in %TEMP% causava kill silenzioso da Windows Defender ASR
        # ("Block execution of potentially obfuscated scripts"). Sintomo: WMI Create restituisce PID
        # ma il processo muore immediatamente senza eseguire nemmeno la prima riga.
        # InstallDir e' firmato/trusted dal nostro installer, Defender non blocca.
        $updaterStagingDir = Join-Path $installDir "_update_staging"
        if (-not (Test-Path $updaterStagingDir)) {
            New-Item -ItemType Directory -Path $updaterStagingDir -Force | Out-Null
        }
        $tempUpdater = Join-Path $updaterStagingDir ("updater_" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".ps1")
        Copy-Item $updaterPath $tempUpdater -Force
        Write-Log "Updater staged in InstallDir (Defender-safe): $tempUpdater" "INFO"

        $psExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
        if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }

        $updaterCmd = "`"$psExe`" -ExecutionPolicy Bypass -NoProfile -NonInteractive -WindowStyle Hidden -File `"$tempUpdater`" -ExtractPath `"$tempExtract`" -InstallDir `"$installDir`" -ApiUrl `"$($config.noc_center_url)`" -ApiKey `"$($config.api_key)`""

        $launched = $false

        # === METODO 1 (preferito): WMI Win32_Process.Create ===
        # Il processo creato via WMI diventa figlio di wmiprvse.exe, NON del nostro servizio.
        # Rimane vivo quando NSSM killa il Job Object del connector.
        try {
            Write-Log "Launch updater via WMI Win32_Process.Create..." "INFO"
            $wmi = [WMICLASS]"\\.\root\cimv2:Win32_Process"
            $spawnResult = $wmi.Create($updaterCmd)
            if ($spawnResult.ReturnValue -eq 0) {
                Write-Log "OK: updater spawnato via WMI (PID=$($spawnResult.ProcessId))" "INFO"
                $launched = $true
            } else {
                Write-Log "WMI Create ReturnValue=$($spawnResult.ReturnValue) (!=0 = errore)" "WARN"
            }
        } catch {
            Write-Log "WMI method failed: $($_.Exception.Message)" "WARN"
        }

        # === METODO 2 (fallback): schtasks run-once come SYSTEM ===
        # Task Scheduler e' un servizio separato, task eseguiti come SYSTEM girano fuori dal Job Object.
        if (-not $launched) {
            try {
                Write-Log "Fallback: launch via schtasks SYSTEM..." "WARN"
                $taskName = "86NocUpdate_" + [guid]::NewGuid().ToString("N").Substring(0,8)
                $runTime = (Get-Date).AddSeconds(45).ToString("HH:mm")
                & schtasks.exe /Create /TN $taskName /SC ONCE /ST $runTime /TR $updaterCmd /RU "SYSTEM" /RL HIGHEST /F 2>&1 | Out-String | ForEach-Object { Write-Log "  schtasks-create: $_" }
                & schtasks.exe /Run /TN $taskName 2>&1 | Out-String | ForEach-Object { Write-Log "  schtasks-run: $_" }
                # Salva il task name nell'updater env per permetter cleanup finale
                [Environment]::SetEnvironmentVariable("ARGUS_UPDATE_TASK", $taskName, "Machine")
                Write-Log "Task $taskName creato e avviato" "INFO"
                $launched = $true
            } catch {
                Write-Log "schtasks fallback failed: $($_.Exception.Message)" "ERROR"
            }
        }

        # === METODO 3 (ultima spiaggia): cmd.exe detached ===
        if (-not $launched) {
            try {
                Write-Log "Fallback 3: cmd.exe detached..." "WARN"
                $batPath = Join-Path $env:TEMP ("86Noc_launcher_" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".bat")
                $batContent = @"
@echo off
timeout /t 3 /nobreak > nul 2>&1
start "" /B $updaterCmd
timeout /t 1 /nobreak > nul 2>&1
del /F /Q "%~f0" > nul 2>&1
"@
                [System.IO.File]::WriteAllText($batPath, $batContent, [System.Text.Encoding]::ASCII)
                $psi = New-Object System.Diagnostics.ProcessStartInfo
                $psi.FileName = "cmd.exe"
                $psi.Arguments = "/c `"$batPath`""
                $psi.UseShellExecute = $true
                $psi.CreateNoWindow = $true
                $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
                [System.Diagnostics.Process]::Start($psi) | Out-Null
                Write-Log "cmd.exe detached lanciato" "INFO"
                $launched = $true
            } catch {
                Write-Log "All launcher methods failed: $($_.Exception.Message)" "ERROR"
                Send-UpdateProgress $config 0 "error" "Tutti i metodi di lancio updater sono falliti"
                return $false
            }
        }
        
        # Give updater time to start before we exit
        Start-Sleep -Seconds 2
        
        # Signal to stop the main loop - updater will kill us if needed
        $global:Running = $false
        Write-Log "Connector in chiusura per aggiornamento..." "INFO"
        
        return $true
    } catch {
        Write-Log "Errore aggiornamento: $($_.Exception.Message)" "ERROR"
        Send-UpdateProgress $config 0 "error" "Errore: $($_.Exception.Message)"
        return $false
    }
}

function Start-UpdateCheckLoop($config) {
    $checkInterval = 300   # 5 minuti - controllo rapido per aggiornamenti
    $lastCheck = [datetime]::MinValue
    
    while ($global:Running) {
        $elapsed = ((Get-Date) - $lastCheck).TotalSeconds
        if ($elapsed -ge $checkInterval) {
            $updateInfo = Check-ForUpdate $config
            if ($updateInfo) {
                Write-Log "Nuova versione disponibile: $($updateInfo.latest_version) (corrente: $global:Version)" "INFO"
                $success = Install-Update $config $updateInfo
                if ($success) {
                    Write-Log "Riavvio connector per applicare aggiornamento..." "INFO"
                    # Restart by launching new instance and exiting
                    $batPath = Join-Path (Split-Path -Parent $PSScriptRoot) "86NocConnector.bat"
                    if (Test-Path $batPath) {
                        Start-Process "cmd.exe" -ArgumentList "/c `"$batPath`"" -WindowStyle Hidden
                        Start-Sleep -Seconds 2
                        $global:Running = $false
                        return
                    }
                }
            }
            $lastCheck = Get-Date
        }
        Start-Sleep -Seconds 30
    }
}

# ==================== LISTENERS ====================

function Start-SNMPListener($config) {
    $port = $config.snmp_trap_port
    Write-Log "Avvio SNMP Trap listener su UDP/$port..."
    
    try {
        $udpClient = New-Object System.Net.Sockets.UdpClient($port)
        $udpClient.Client.ReceiveTimeout = 2000
        Write-Log "SNMP listener attivo su porta UDP $port"
        
        while ($global:Running) {
            try {
                $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
                $data = $udpClient.Receive([ref]$remoteEP)
                $global:Stats.snmp_received++
                
                $trap = Parse-SNMPTrap $data $remoteEP.Address.ToString()
                Write-Log "[SNMP] $($trap.trap_type) da $($trap.device_ip)"
                Send-SNMPToNOC $config $trap
            }
            catch [System.Net.Sockets.SocketException] {
                # Timeout - normal
            }
            catch {
                if ($global:Running) {
                    Write-Log "Errore SNMP: $($_.Exception.Message)" "ERROR"
                }
            }
        }
        $udpClient.Close()
    } catch {
        Write-Log "ERRORE porta SNMP $port : $($_.Exception.Message). Serve Amministratore." "ERROR"
    }
}

function Start-SyslogListener($config) {
    $port = $config.syslog_port
    Write-Log "Avvio Syslog listener su UDP/$port..."
    
    try {
        $udpClient = New-Object System.Net.Sockets.UdpClient($port)
        $udpClient.Client.ReceiveTimeout = 2000
        Write-Log "Syslog listener attivo su porta UDP $port"
        
        while ($global:Running) {
            try {
                $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
                $data = $udpClient.Receive([ref]$remoteEP)
                $global:Stats.syslog_received++
                
                $rawMsg = [System.Text.Encoding]::UTF8.GetString($data)
                $syslog = Parse-Syslog $rawMsg $remoteEP.Address.ToString()
                Write-Log "[Syslog] [$($syslog.severity_name)] $($syslog.device_ip): $($syslog.message.Substring(0, [Math]::Min(60, $syslog.message.Length)))"
                Send-SyslogToNOC $config $syslog
            }
            catch [System.Net.Sockets.SocketException] {
                # Timeout - normal
            }
            catch {
                if ($global:Running) {
                    Write-Log "Errore Syslog: $($_.Exception.Message)" "ERROR"
                }
            }
        }
        $udpClient.Close()
    } catch {
        Write-Log "ERRORE porta Syslog $port : $($_.Exception.Message). Serve Amministratore." "ERROR"
    }
}

function Start-HeartbeatLoop($config) {
    $interval = if ($config.heartbeat_interval_seconds) { $config.heartbeat_interval_seconds } else { 60 }
    while ($global:Running) {
        Send-Heartbeat $config
        Start-Sleep -Seconds $interval
    }
}

# ==================== NETWORK DISCOVERY ====================

function Get-LocalSubnet {
    try {
        $adapters = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | 
            Where-Object { $_.OperationalStatus -eq "Up" -and $_.NetworkInterfaceType -ne "Loopback" }
        foreach ($adapter in $adapters) {
            $props = $adapter.GetIPProperties()
            foreach ($unicast in $props.UnicastAddresses) {
                if ($unicast.Address.AddressFamily -eq "InterNetwork") {
                    $ip = $unicast.Address.ToString()
                    $mask = $unicast.IPv4Mask.ToString()
                    if ($ip -notmatch "^169\.254\." -and $ip -ne "127.0.0.1") {
                        # Calculate network address
                        $ipBytes = $unicast.Address.GetAddressBytes()
                        $maskBytes = $unicast.IPv4Mask.GetAddressBytes()
                        $prefix = 0
                        foreach ($b in $maskBytes) {
                            $bits = [Convert]::ToString($b, 2)
                            $prefix += ($bits.ToCharArray() | Where-Object { $_ -eq '1' }).Count
                        }
                        $networkBytes = @()
                        for ($i = 0; $i -lt 4; $i++) {
                            $networkBytes += ($ipBytes[$i] -band $maskBytes[$i])
                        }
                        $network = ($networkBytes -join ".")
                        return @{ network = $network; prefix = $prefix; mask = $mask; local_ip = $ip }
                    }
                }
            }
        }
    } catch {}
    return $null
}

function Start-NetworkDiscovery($config, $subnetOverride) {
    Write-Log "=== AVVIO SCANSIONE RETE ==="
    
    $subnet = $null
    if ($subnetOverride) {
        $subnet = @{ network = $subnetOverride; prefix = 24; local_ip = "" }
        Write-Log "Subnet specificata: $subnetOverride/24"
    } else {
        $subnet = Get-LocalSubnet
        if (-not $subnet) {
            Write-Log "Impossibile rilevare subnet locale" "ERROR"
            return
        }
        Write-Log "Subnet rilevata: $($subnet.network)/$($subnet.prefix) (IP locale: $($subnet.local_ip))"
    }
    
    # Calculate IP range (support /24 only for safety)
    $baseParts = $subnet.network.Split(".")
    $baseNet = "$($baseParts[0]).$($baseParts[1]).$($baseParts[2])"
    
    Write-Log "Scansione $baseNet.1 - $baseNet.254..."
    
    $discoveredDevices = @()
    $ping = New-Object System.Net.NetworkInformation.Ping
    
    # Phase 1: Ping sweep (fast, parallel using runspaces)
    $runspacePool = [RunspaceFactory]::CreateRunspacePool(1, 50)
    $runspacePool.Open()
    $jobs = @()
    
    $scriptBlock = {
        param($ip)
        try {
            $p = New-Object System.Net.NetworkInformation.Ping
            $reply = $p.Send($ip, 1500)
            $p.Dispose()
            if ($reply.Status -eq "Success") {
                return @{ ip = $ip; ms = $reply.RoundtripTime; alive = $true }
            }
        } catch {}
        return @{ ip = $ip; alive = $false }
    }
    
    for ($i = 1; $i -le 254; $i++) {
        $targetIP = "$baseNet.$i"
        $ps = [PowerShell]::Create().AddScript($scriptBlock).AddArgument($targetIP)
        $ps.RunspacePool = $runspacePool
        $jobs += @{ ps = $ps; handle = $ps.BeginInvoke(); ip = $targetIP }
    }
    
    # Collect ping results
    $aliveHosts = @()
    foreach ($job in $jobs) {
        try {
            $result = $job.ps.EndInvoke($job.handle)
            if ($result -and $result.alive) {
                $aliveHosts += $result
            }
        } catch {}
        $job.ps.Dispose()
    }
    $runspacePool.Close()
    $runspacePool.Dispose()
    
    Write-Log "Ping sweep completato: $($aliveHosts.Count) host attivi su 254"
    
    # Phase 2: Port scan on alive hosts
    $commonPorts = @(
        @{ port = 80;  name = "HTTP" },
        @{ port = 443; name = "HTTPS" },
        @{ port = 161; name = "SNMP" },
        @{ port = 22;  name = "SSH" },
        @{ port = 23;  name = "Telnet" },
        @{ port = 3389; name = "RDP" },
        @{ port = 8080; name = "HTTP-Alt" },
        @{ port = 8443; name = "HTTPS-Alt" }
    )
    
    foreach ($host_ in $aliveHosts) {
        $ip = $host_.ip
        $openPorts = @()
        
        foreach ($portInfo in $commonPorts) {
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $asyncResult = $tcp.BeginConnect($ip, $portInfo.port, $null, $null)
                $waitResult = $asyncResult.AsyncWaitHandle.WaitOne(800, $false)
                if ($waitResult -and $tcp.Connected) {
                    $openPorts += @{ port = $portInfo.port; service = $portInfo.name }
                }
                $tcp.Close()
            } catch {
                try { $tcp.Close() } catch {}
            }
        }
        
        # Resolve hostname
        $hostname = ""
        try {
            $dns = [System.Net.Dns]::GetHostEntry($ip)
            if ($dns.HostName -ne $ip) { $hostname = $dns.HostName }
        } catch {}
        
        # Suggest monitor type
        $hasSnmp = ($openPorts | Where-Object { $_.port -eq 161 }).Count -gt 0
        $hasHttp = ($openPorts | Where-Object { $_.port -eq 80 -or $_.port -eq 443 -or $_.port -eq 8080 }).Count -gt 0
        $suggestedType = if ($hasSnmp) { "snmp" } else { "ping" }
        $httpPort = if ($hasHttp) { ($openPorts | Where-Object { $_.port -eq 80 -or $_.port -eq 443 -or $_.port -eq 8080 } | Select-Object -First 1).port } else { 0 }
        
        # Determine device type guess
        $deviceType = "unknown"
        if ($hasSnmp -and $hasHttp) { $deviceType = "switch/router" }
        elseif ($hasSnmp) { $deviceType = "network-device" }
        elseif ($hasHttp -and ($openPorts | Where-Object { $_.port -eq 3389 }).Count -gt 0) { $deviceType = "server-windows" }
        elseif ($hasHttp -and ($openPorts | Where-Object { $_.port -eq 22 }).Count -gt 0) { $deviceType = "server-linux" }
        elseif ($hasHttp) { $deviceType = "web-device" }
        elseif (($openPorts | Where-Object { $_.port -eq 22 }).Count -gt 0) { $deviceType = "server-linux" }
        elseif (($openPorts | Where-Object { $_.port -eq 3389 }).Count -gt 0) { $deviceType = "server-windows" }
        
        $discoveredDevices += @{
            ip = $ip
            hostname = $hostname
            ping_ms = $host_.ms
            open_ports = $openPorts
            device_type = $deviceType
            suggested_type = $suggestedType
            http_port = $httpPort
        }
        
        Write-Log "  $ip ($hostname) - $($openPorts.Count) porte aperte - tipo: $deviceType"
    }
    
    Write-Log "Scansione completata: $($discoveredDevices.Count) dispositivi trovati"
    
    # Send results to NOC
    $payload = @{
        hostname = $env:COMPUTERNAME
        devices = $discoveredDevices
    }
    $result = Send-ToNOC $config "connector/discovery-results" $payload
    if ($result) {
        Write-Log "Risultati discovery inviati al NOC"
    }
    
    Write-Log "=== SCANSIONE RETE COMPLETATA ==="
}

function Check-DiscoveryRequest($config) {
    try {
        $response = Invoke-SecureGet $config "connector/discovery-check"
        if ($response.scan_requested) {
            Write-Log "Richiesta di discovery ricevuta dal NOC"
            Start-NetworkDiscovery $config $response.subnet
        }
    } catch {}
}

# ==================== WEB CONSOLE PROXY ====================

function Check-WebProxyRequests($config) {
    try {
        # Long-poll: attende fino a 20s che arrivi una richiesta (hot-trigger server).
        # TimeoutSec 25 > wait 20 così la richiesta HTTP non scade prima del server.
        $response = Invoke-SecureGet $config "connector/web-proxy/pending?wait=20" 25
        
        if ($response.requests -and $response.requests.Count -gt 0) {
            foreach ($req in $response.requests) {
                Process-WebProxyRequest $config $req
            }
        }
    } catch {}
}

function Process-WebProxyRequest($config, $req) {
    # =========================================================================
    # Web Console Enterprise B - Binary-safe proxy
    # - Supporto method GET/POST/PUT/DELETE/HEAD/OPTIONS con request body
    # - Cookie jar cross-request (sessione persistente)
    # - Response body inviato in base64 (binary-safe, gestisce NUL byte)
    # - Response headers + cookies back al backend per cookie jar browser
    # - Auto fallback HTTPS/HTTP, SSL bypass per self-signed
    # - Response SEMPRE inviata (anche su error) -> nessun timeout browser
    # =========================================================================
    $deviceIp = $req.device_ip
    $port = if ($req.port) { [int]$req.port } else { 80 }
    $path = if ($req.path) { [string]$req.path } else { "/" }
    $method = if ($req.method) { [string]$req.method } else { "GET" }
    $scheme = if ($req.scheme) { [string]$req.scheme } else { "" }
    $requestId = $req.request_id
    $reqBody = if ($req.request_body) { [string]$req.request_body } else { "" }
    $reqBodyEnc = if ($req.request_body_encoding) { [string]$req.request_body_encoding } else { "text" }
    $reqHeaders = $req.request_headers
    $sessionCookies = $req.session_cookies
    $tStart = [DateTime]::UtcNow

    Write-Log "[WEB-PROXY] IN  $method -> $deviceIp`:$port$path (ID: $($requestId.Substring(0, 8)))"

    $statusCode = 0
    $contentType = "text/html"
    $title = ""
    $errorMsg = $null
    $respBytes = [byte[]]@()
    $respHeaders = @{}
    $respCookies = @{}

    # Whitelist porte — combina default + extra forniti dal backend tramite command config
    # Il backend può inviare `allowed_ports_extra` (array di int) via endpoint /api/connector/command-poll
    # così l'admin aggiunge nuove porte da UI senza ricompilare il connector.
    $defaultAllowedPorts = @(
        80, 443, 8080, 8443, 8000, 8888, 4443, 4080, 9090, 10000,
        5000, 5001,        # Synology DSM
        8006,              # Proxmox PVE
        81, 8088,          # TrueNAS legacy / QNAP secondary
        3000, 19999,       # AdGuard/Pihole/Grafana / Netdata
        4444,              # pfSense/OPNsense alt
        2222, 8083,        # DirectAdmin / Plesk
        17988, 17990       # iLO XMLagent / XMLssl
    )
    $extraAllowedPorts = @()
    try {
        if ($script:DynamicAllowedPorts -and $script:DynamicAllowedPorts.Count -gt 0) {
            $extraAllowedPorts = $script:DynamicAllowedPorts
        }
    } catch {}
    $allAllowedPorts = $defaultAllowedPorts + $extraAllowedPorts
    if ($port -notin $allAllowedPorts) {
        $errorMsg = "Porta $port non consentita per motivi di sicurezza"
        $statusCode = 403
        $errHtml = Build-WebProxyErrorPage $deviceIp $port $path $errorMsg
        $respBytes = [System.Text.Encoding]::UTF8.GetBytes($errHtml)
        Send-WebProxyResponse $config $requestId $statusCode $contentType $respBytes $title $errorMsg $respHeaders $respCookies $tStart
        return
    }

    # Determina schemi da provare
    $schemes = if ($scheme -in @("http","https")) {
        @($scheme)
    } elseif ($port -in @(443, 8443, 4443)) {
        @("https", "http")
    } else {
        @("http", "https")
    }

    # TLS 1.0-1.3
    try {
        [Net.ServicePointManager]::SecurityProtocol = `
            [Net.SecurityProtocolType]::Tls -bor [Net.SecurityProtocolType]::Tls11 -bor `
            [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
    } catch {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    }

    # SSL Bypass (self-signed: iLO/switch/firewall)
    # IMPORTANTE: l'handler e' GLOBAL (statico in .NET). Per evitare race condition
    # con altri thread (Redfish polling, SNMP discovery, WAN probe) che fanno Disable()
    # in parallelo durante la negoziazione TLS di questa request, lo lasciamo SEMPRE ON.
    # Il connector gira in rete cliente controllata: il rischio MITM interno e' accettato.
    if (-not ("CertBypass" -as [type])) {
        Add-Type -TypeDefinition @"
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
public static class CertBypass {
    public static void Enable() {
        System.Net.ServicePointManager.ServerCertificateValidationCallback = (s, c, ch, e) => true;
    }
    public static void Disable() {
        // NO-OP: una volta abilitato il bypass nel connector, lo teniamo on per evitare
        // race condition con altri thread paralleli (Redfish/SNMP/Web-Proxy).
    }
}
"@
    }
    [CertBypass]::Enable()

    # WebSession con cookie jar
    $webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $webSession.UserAgent = "86NocConnector/WebProxy-Ent"
    if ($sessionCookies -and ($sessionCookies.PSObject.Properties.Count -gt 0 -or $sessionCookies.Keys.Count -gt 0)) {
        try {
            $cookieProps = if ($sessionCookies.PSObject -and $sessionCookies.PSObject.Properties) {
                $sessionCookies.PSObject.Properties
            } else { $null }
            if ($cookieProps) {
                foreach ($p in $cookieProps) {
                    $c = New-Object System.Net.Cookie($p.Name, [string]$p.Value, "/", $deviceIp)
                    $webSession.Cookies.Add($c)
                }
            } elseif ($sessionCookies -is [hashtable]) {
                foreach ($k in $sessionCookies.Keys) {
                    $c = New-Object System.Net.Cookie($k, [string]$sessionCookies[$k], "/", $deviceIp)
                    $webSession.Cookies.Add($c)
                }
            }
        } catch {
            Write-Log "[WEB-PROXY] Impossibile caricare session cookies: $($_.Exception.Message)" "DEBUG"
        }
    }

    # Headers custom
    $ihHeaders = @{}
    if ($reqHeaders) {
        try {
            $headerProps = if ($reqHeaders.PSObject -and $reqHeaders.PSObject.Properties) { $reqHeaders.PSObject.Properties } else { $null }
            if ($headerProps) {
                foreach ($h in $headerProps) {
                    $ihHeaders[$h.Name] = [string]$h.Value
                }
            } elseif ($reqHeaders -is [hashtable]) {
                foreach ($k in $reqHeaders.Keys) { $ihHeaders[$k] = [string]$reqHeaders[$k] }
            }
        } catch {}
    }

    # Body request decode
    $ihBody = $null
    if ($reqBody) {
        if ($reqBodyEnc -eq "base64") {
            try { $ihBody = [Convert]::FromBase64String($reqBody) } catch { $ihBody = $null }
        } else {
            $ihBody = $reqBody
        }
    }

    # Referer automatico: sempre la home del device ("/") - risolve device paranoici come HP 5130
    # che restituiscono 404 se non e' presente Referer che punti alla home.
    if (-not $ihHeaders.ContainsKey("Referer") -and -not $ihHeaders.ContainsKey("referer")) {
        $refScheme = if ($scheme) { $scheme } else { $schemes[0] }
        $ihHeaders["Referer"] = "${refScheme}://${deviceIp}:${port}/"
    }
    # User-Agent reale (browser standard) - alcuni device rifiutano user-agent custom
    if (-not $ihHeaders.ContainsKey("User-Agent") -and -not $ihHeaders.ContainsKey("user-agent")) {
        $ihHeaders["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    # Accept header realistico
    if (-not $ihHeaders.ContainsKey("Accept") -and -not $ihHeaders.ContainsKey("accept")) {
        $ihHeaders["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }

    $lastError = $null
    $succeeded = $false

    # Strategia anti-404: se il path NON e' "/" e la sessione non ha ancora cookie,
    # prima fai un warm-up GET sulla home "/" per popolare cookie jar + stabilire Referer,
    # poi esegui la richiesta reale. Questo risolve device tipo HP 5130 che richiedono
    # una sessione "viva" iniziata dalla home.
    $needsWarmup = ($path -ne "/" -and $path -ne "" -and $method -eq "GET" -and $webSession.Cookies.Count -eq 0)
    if ($needsWarmup) {
        $warmScheme = if ($scheme) { $scheme } else { $schemes[0] }
        $homeUrl = "${warmScheme}://${deviceIp}:${port}/"
        try {
            Write-Log "[WEB-PROXY] WARMUP GET $homeUrl (prima di $path)" "DEBUG"
            [CertBypass]::Enable()
            Invoke-WebRequest -Uri $homeUrl -UseBasicParsing -TimeoutSec 8 `
                -WebSession $webSession -MaximumRedirection 3 `
                -UserAgent $ihHeaders["User-Agent"] -ErrorAction SilentlyContinue | Out-Null
        } catch { } finally { [CertBypass]::Disable() }
    }

    foreach ($sch in $schemes) {
        $targetUrl = "${sch}://${deviceIp}:${port}${path}"
        try {
            Write-Log "[WEB-PROXY] TRY $method $targetUrl" "DEBUG"
            $iwrParams = @{
                Uri             = $targetUrl
                Method          = $method
                UseBasicParsing = $true
                TimeoutSec      = 15
                WebSession      = $webSession
                ErrorAction     = "Stop"
                MaximumRedirection = 5
            }
            if ($ihHeaders.Count -gt 0) { $iwrParams.Headers = $ihHeaders }
            if ($ihBody -and ($method -in @("POST","PUT","PATCH"))) { $iwrParams.Body = $ihBody }

            $wr = Invoke-WebRequest @iwrParams

            # Status + Content-Type
            $statusCode = [int]$wr.StatusCode
            if ($wr.Headers.ContainsKey("Content-Type")) {
                $contentType = [string]$wr.Headers["Content-Type"]
            }

            # Response body come byte[] (binary-safe)
            if ($wr.RawContentStream) {
                $ms = New-Object System.IO.MemoryStream
                $wr.RawContentStream.Position = 0
                $wr.RawContentStream.CopyTo($ms)
                $respBytes = $ms.ToArray()
                $ms.Dispose()
            } elseif ($wr.Content -is [byte[]]) {
                $respBytes = $wr.Content
            } else {
                $respBytes = [System.Text.Encoding]::UTF8.GetBytes([string]$wr.Content)
            }

            # Response headers (filtrati, max 100)
            $n = 0
            foreach ($hk in $wr.Headers.Keys) {
                if ($n++ -ge 100) { break }
                $respHeaders[[string]$hk] = [string]$wr.Headers[$hk]
            }

            # Response cookies da WebSession
            try {
                foreach ($ckc in $webSession.Cookies.GetCookies($targetUrl)) {
                    $respCookies[[string]$ckc.Name] = [string]$ckc.Value
                }
            } catch {}

            $succeeded = $true
            break
        } catch {
            $lastError = $_.Exception.Message
            # CRITICAL: se il device ha risposto con status HTTP >= 400 (404, 500, etc.),
            # non e' un vero fallimento di connettivita' - e' il device che ci ha risposto.
            # Estraggo la response dall'exception e la rispedisco al browser.
            # Invoke-WebRequest -ErrorAction Stop lancia WebException con una Response embedded.
            $httpResp = $null
            try {
                $httpResp = $_.Exception.Response
            } catch { }
            if ($httpResp) {
                try {
                    $statusCode = [int]$httpResp.StatusCode
                    if ($httpResp.ContentType) { $contentType = [string]$httpResp.ContentType }
                    # Leggi body dallo stream
                    $respStream = $httpResp.GetResponseStream()
                    $msE = New-Object System.IO.MemoryStream
                    $respStream.CopyTo($msE)
                    $respBytes = $msE.ToArray()
                    $msE.Dispose()
                    $respStream.Close()
                    # Headers
                    foreach ($hk in $httpResp.Headers.AllKeys) {
                        $respHeaders[[string]$hk] = [string]$httpResp.Headers[$hk]
                    }
                    # Cookies
                    try {
                        foreach ($ckc in $webSession.Cookies.GetCookies($targetUrl)) {
                            $respCookies[[string]$ckc.Name] = [string]$ckc.Value
                        }
                    } catch {}
                    Write-Log "[WEB-PROXY] Device risponde HTTP $statusCode su $targetUrl ($($respBytes.Length) bytes) - passo al browser" "INFO"
                    $succeeded = $true
                    break
                } catch {
                    Write-Log "[WEB-PROXY] Impossibile estrarre body da HTTP error: $($_.Exception.Message)" "WARN"
                }
            }
            Write-Log "[WEB-PROXY] FAIL $targetUrl -> $lastError" "WARN"
            continue
        }
    }

    [CertBypass]::Disable()

    if (-not $succeeded) {
        $errorMsg = "Dispositivo $deviceIp non raggiungibile su porta $port ($method). Dettaglio: $lastError"
        $statusCode = 502
        $errHtml = Build-WebProxyErrorPage $deviceIp $port $path $errorMsg
        $respBytes = [System.Text.Encoding]::UTF8.GetBytes($errHtml)
        Send-WebProxyResponse $config $requestId $statusCode $contentType $respBytes $title $errorMsg $respHeaders $respCookies $tStart
        return
    }

    # Estrai title (solo se content HTML-ish)
    if ($contentType -match "html|xml" -and $respBytes.Length -lt 2000000) {
        try {
            $textPreview = [System.Text.Encoding]::UTF8.GetString($respBytes, 0, [math]::Min(8192, $respBytes.Length))
            if ($textPreview -match '<title[^>]*>(.*?)</title>') {
                $title = $Matches[1].Trim()
            }
        } catch {}
    }

    # === AUTO-FOLLOW JS REDIRECT (HP 5130, vecchi device HP/Aruba/Dell) ===
    # Molti device fanno: <body onload="window.location='frame/login.html'">
    # L'iframe con srcDoc ha origine null -> window.location fallisce -> pagina vuota.
    # Soluzione: il connector segue il redirect lato server e restituisce direttamente
    # il body della destinazione (max 3 hops per evitare loop).
    if ($contentType -match "html" -and $respBytes.Length -gt 0 -and $respBytes.Length -lt 500000) {
        try {
            $maxHops = 3
            $hopCount = 0
            $htmlStr = [System.Text.Encoding]::UTF8.GetString($respBytes)
            $baseUrlForRedir = "${scheme}://${deviceIp}:${port}"
            if (-not $scheme) { $baseUrlForRedir = "$($schemes[0])://${deviceIp}:${port}" }
            # Pattern JS redirect (ordinati per specificita')
            $redirectRegex = @(
                'window\.location\.(?:href|replace)\s*=\s*["'']([^"''<>]+?)["'']',
                'window\.location\s*=\s*["'']([^"''<>]+?)["'']',
                'document\.location\.(?:href|replace)\s*=\s*["'']([^"''<>]+?)["'']',
                'document\.location\s*=\s*["'']([^"''<>]+?)["'']',
                'location\.replace\s*\(\s*["'']([^"''<>]+?)["'']',
                'location\.href\s*=\s*["'']([^"''<>]+?)["'']',
                '<meta[^>]+http-equiv\s*=\s*["'']?refresh["'']?[^>]+content\s*=\s*["''][^"''<>]*url\s*=\s*([^"''<>]+?)["'']'
            )
            while ($hopCount -lt $maxHops) {
                $foundRedirect = $null
                foreach ($rx in $redirectRegex) {
                    $matches2 = [regex]::Matches($htmlStr, $rx, "IgnoreCase")
                    # Prendi l'ultimo match in ogni pattern (di solito HP 5130 ha ternary; ultimo = https branch)
                    foreach ($m in $matches2) {
                        $candidate = $m.Groups[1].Value.Trim()
                        if ($candidate -and $candidate -notlike "*__ARGUS_PROXY__*" -and $candidate.Length -lt 2048) {
                            $foundRedirect = $candidate
                        }
                    }
                    if ($foundRedirect) { break }
                }
                if (-not $foundRedirect) { break }

                # Risolvi URL relativo
                $absoluteUrl = $foundRedirect
                if ($absoluteUrl -like "http*://*") { }
                elseif ($absoluteUrl.StartsWith("//")) { $absoluteUrl = "${scheme}:$absoluteUrl" }
                elseif ($absoluteUrl.StartsWith("/")) { $absoluteUrl = "$baseUrlForRedir$absoluteUrl" }
                else { $absoluteUrl = "$baseUrlForRedir/$absoluteUrl" }

                Write-Log "[WEB-PROXY] AUTO-FOLLOW JS redirect hop $($hopCount+1): $foundRedirect -> $absoluteUrl" "INFO"

                [CertBypass]::Enable()
                try {
                    $redirResp = Invoke-WebRequest -Uri $absoluteUrl -UseBasicParsing -TimeoutSec 10 `
                                 -WebSession $webSession -MaximumRedirection 5 -ErrorAction Stop
                    # Nuovo status / content-type
                    $statusCode = [int]$redirResp.StatusCode
                    if ($redirResp.Headers.ContainsKey("Content-Type")) {
                        $contentType = [string]$redirResp.Headers["Content-Type"]
                    }
                    # Body
                    if ($redirResp.RawContentStream) {
                        $ms2 = New-Object System.IO.MemoryStream
                        $redirResp.RawContentStream.Position = 0
                        $redirResp.RawContentStream.CopyTo($ms2)
                        $respBytes = $ms2.ToArray()
                        $ms2.Dispose()
                    } elseif ($redirResp.Content -is [byte[]]) {
                        $respBytes = $redirResp.Content
                    } else {
                        $respBytes = [System.Text.Encoding]::UTF8.GetBytes([string]$redirResp.Content)
                    }
                    # Aggiorna cookies della WebSession
                    try {
                        foreach ($ckc in $webSession.Cookies.GetCookies($absoluteUrl)) {
                            $respCookies[[string]$ckc.Name] = [string]$ckc.Value
                        }
                    } catch {}
                    # Aggiorna title dal nuovo body
                    if ($respBytes.Length -lt 2000000) {
                        try {
                            $titleStr = [System.Text.Encoding]::UTF8.GetString($respBytes, 0, [math]::Min(8192, $respBytes.Length))
                            if ($titleStr -match '<title[^>]*>(.*?)</title>') {
                                $title = $Matches[1].Trim()
                            }
                        } catch {}
                    }
                    # Aggiorna baseUrl per prossimo hop (se redirect a path assoluto su stesso host)
                    if ($absoluteUrl -match '^(https?://[^/]+)') { $baseUrlForRedir = $Matches[1] }
                    # Non-HTML? stop seguendo
                    if ($contentType -notmatch "html") {
                        Write-Log "[WEB-PROXY] Redirect finale non-HTML ($contentType), stop follow" "DEBUG"
                        break
                    }
                    # Nuovo HTML per check successivo hop
                    $htmlStr = [System.Text.Encoding]::UTF8.GetString($respBytes)
                    $hopCount++
                } catch {
                    Write-Log "[WEB-PROXY] Follow redirect fallito: $($_.Exception.Message)" "WARN"
                    break
                } finally {
                    [CertBypass]::Disable()
                }
            }
        } catch {
            Write-Log "[WEB-PROXY] Errore auto-follow: $($_.Exception.Message)" "DEBUG"
        }
    }

    # INJECT <base> TAG per asset proxy automatico (CSS/JS/img/XHR)
    # Il backend risolvera' i path relativi tramite /api/connector/web-proxy/asset/*
    if ($contentType -match "html" -and $respBytes.Length -gt 0 -and $respBytes.Length -lt 5000000) {
        try {
            $htmlStr = [System.Text.Encoding]::UTF8.GetString($respBytes)
            $baseUrlForInline = "${scheme}://${deviceIp}:${port}"
            if (-not $scheme) { $baseUrlForInline = "$($schemes[0])://${deviceIp}:${port}" }

            # --- INLINE CSS (scarica e incorpora <link rel="stylesheet"> come <style>) ---
            [CertBypass]::Enable()
            try {
                $cssPattern = '<link[^>]*\srel\s*=\s*["'']?stylesheet["'']?[^>]*>'
                $cssMatches = [regex]::Matches($htmlStr, $cssPattern, "IgnoreCase")
                $cssCount = 0
                foreach ($cssMatch in $cssMatches) {
                    if ($cssCount -ge 20) { break }
                    $linkTag = $cssMatch.Value
                    if ($linkTag -match 'href\s*=\s*["'']([^"'']+)["'']') {
                        $cssUrl = $Matches[1]
                        if ($cssUrl.StartsWith("data:")) { continue }
                        # Risolvi URL
                        if ($cssUrl -like "http*://*") { }
                        elseif ($cssUrl.StartsWith("//")) { $cssUrl = "${scheme}:$cssUrl" }
                        elseif ($cssUrl.StartsWith("/")) { $cssUrl = "$baseUrlForInline$cssUrl" }
                        else { $cssUrl = "$baseUrlForInline/$cssUrl" }
                        try {
                            $cssResp = Invoke-WebRequest -Uri $cssUrl -UseBasicParsing -TimeoutSec 5 `
                                        -WebSession $webSession -ErrorAction Stop
                            $cssText = if ($cssResp.Content -is [byte[]]) {
                                [System.Text.Encoding]::UTF8.GetString($cssResp.Content)
                            } else { [string]$cssResp.Content }
                            $styleTag = "<style>/* inlined from $($Matches[1]) */`n$cssText`n</style>"
                            $htmlStr = $htmlStr.Replace($linkTag, $styleTag)
                            $cssCount++
                        } catch {
                            # CSS non raggiungibile -> skip, il link tag resta (innocuo)
                        }
                    }
                }
            } catch {
                Write-Log "[WEB-PROXY] CSS inline error: $($_.Exception.Message)" "DEBUG"
            }

            # --- INLINE IMG (converti <img src="..."> in data URI per immagini < 500KB) ---
            try {
                $imgPattern = '<img[^>]*\ssrc\s*=\s*["'']([^"'']+)["''][^>]*/?\s*>'
                $imgMatches = [regex]::Matches($htmlStr, $imgPattern, "IgnoreCase")
                $imgCount = 0
                $mimeMap = @{
                    "png"="image/png"; "jpg"="image/jpeg"; "jpeg"="image/jpeg";
                    "gif"="image/gif"; "svg"="image/svg+xml"; "ico"="image/x-icon";
                    "webp"="image/webp"; "bmp"="image/bmp"
                }
                foreach ($imgMatch in $imgMatches) {
                    if ($imgCount -ge 30) { break }
                    $imgUrl = $imgMatch.Groups[1].Value
                    if ($imgUrl.StartsWith("data:")) { continue }
                    $origImgUrl = $imgUrl
                    # Risolvi URL
                    if ($imgUrl -like "http*://*") { }
                    elseif ($imgUrl.StartsWith("//")) { $imgUrl = "${scheme}:$imgUrl" }
                    elseif ($imgUrl.StartsWith("/")) { $imgUrl = "$baseUrlForInline$imgUrl" }
                    else { $imgUrl = "$baseUrlForInline/$imgUrl" }
                    try {
                        $imgResp = Invoke-WebRequest -Uri $imgUrl -UseBasicParsing -TimeoutSec 4 `
                                    -WebSession $webSession -ErrorAction Stop
                        $imgBytes = if ($imgResp.Content -is [byte[]]) { $imgResp.Content } `
                                    else { [System.Text.Encoding]::UTF8.GetBytes([string]$imgResp.Content) }
                        if ($imgBytes.Length -gt 500000) { continue }
                        $ext = [System.IO.Path]::GetExtension($imgUrl).TrimStart('.').Split('?')[0].ToLower()
                        $mime = if ($mimeMap.ContainsKey($ext)) { $mimeMap[$ext] } else { "image/png" }
                        $b64img = [Convert]::ToBase64String($imgBytes)
                        $dataUri = "data:${mime};base64,$b64img"
                        # Sostituisci in modo preciso
                        $newTag = $imgMatch.Value.Replace($origImgUrl, $dataUri)
                        $htmlStr = $htmlStr.Replace($imgMatch.Value, $newTag)
                        $imgCount++
                    } catch { }
                }
            } catch {
                Write-Log "[WEB-PROXY] IMG inline error: $($_.Exception.Message)" "DEBUG"
            }

            # --- INLINE JS (scarica e incorpora <script src="..."> come inline) ---
            try {
                $jsPattern = '<script[^>]*\ssrc\s*=\s*["'']([^"'']+)["''][^>]*>\s*</script>'
                $jsMatches = [regex]::Matches($htmlStr, $jsPattern, "IgnoreCase")
                $jsCount = 0
                foreach ($jsMatch in $jsMatches) {
                    if ($jsCount -ge 15) { break }
                    $jsUrl = $jsMatch.Groups[1].Value
                    if ($jsUrl.StartsWith("data:")) { continue }
                    if ($jsUrl -like "http*://*") { }
                    elseif ($jsUrl.StartsWith("//")) { $jsUrl = "${scheme}:$jsUrl" }
                    elseif ($jsUrl.StartsWith("/")) { $jsUrl = "$baseUrlForInline$jsUrl" }
                    else { $jsUrl = "$baseUrlForInline/$jsUrl" }
                    try {
                        $jsResp = Invoke-WebRequest -Uri $jsUrl -UseBasicParsing -TimeoutSec 5 `
                                    -WebSession $webSession -ErrorAction Stop
                        $jsText = if ($jsResp.Content -is [byte[]]) {
                            [System.Text.Encoding]::UTF8.GetString($jsResp.Content)
                        } else { [string]$jsResp.Content }
                        # Limite 2MB per singolo JS
                        if ($jsText.Length -gt 2000000) { continue }
                        $inlineScript = "<script>/* inlined from $($jsMatch.Groups[1].Value) */`n$jsText`n</script>"
                        $htmlStr = $htmlStr.Replace($jsMatch.Value, $inlineScript)
                        $jsCount++
                    } catch { }
                }
            } catch {
                Write-Log "[WEB-PROXY] JS inline error: $($_.Exception.Message)" "DEBUG"
            }
            [CertBypass]::Disable()

            # --- Rewrite link/form/iframe con marker ARGUS per intercettazione frontend ---
            $htmlStr = [regex]::Replace($htmlStr, '(<a\b[^>]*\shref\s*=\s*)["'']/', "`$1`"__ARGUS_PROXY__/", "IgnoreCase")
            $htmlStr = [regex]::Replace($htmlStr, '(<form\b[^>]*\saction\s*=\s*)["'']/', "`$1`"__ARGUS_PROXY__/", "IgnoreCase")
            $htmlStr = [regex]::Replace($htmlStr, '(<(?:iframe|frame)\b[^>]*\ssrc\s*=\s*)["'']/', "`$1`"__ARGUS_PROXY__/", "IgnoreCase")

            # --- Interceptor JS per click/submit/location -> postMessage al parent ---
            $interceptScript = @"
<script>
(function(){
  // 1. Click intercept
  document.addEventListener('click', function(e){
    var a = e.target.closest('a');
    if (!a || !a.getAttribute) return;
    var href = a.getAttribute('href');
    if (!href || href.startsWith('javascript:') || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('data:')) return;
    e.preventDefault();
    window.parent.postMessage({type:'argus-proxy-navigate', path: href, method:'GET'}, '*');
  }, true);
  // 2. Form submit intercept
  document.addEventListener('submit', function(e){
    var f = e.target;
    if (!f || f.tagName !== 'FORM') return;
    var action = f.getAttribute('action') || window.location.pathname || '/';
    var method = (f.getAttribute('method') || 'GET').toUpperCase();
    var fd = new FormData(f);
    var params = '';
    try { params = new URLSearchParams(fd).toString(); } catch(e) {}
    e.preventDefault();
    window.parent.postMessage({type:'argus-proxy-navigate', path: action, method: method, body: params, contentType:'application/x-www-form-urlencoded'}, '*');
  }, true);
  // 3. window.location assignment hook (safety net per device che fanno redirect JS)
  try {
    var origAssign = window.location.assign ? window.location.assign.bind(window.location) : null;
    var origReplace = window.location.replace ? window.location.replace.bind(window.location) : null;
    window.location.assign = function(url) {
      window.parent.postMessage({type:'argus-proxy-navigate', path: String(url), method:'GET'}, '*');
    };
    window.location.replace = function(url) {
      window.parent.postMessage({type:'argus-proxy-navigate', path: String(url), method:'GET'}, '*');
    };
    // Proxy per intercettare setter (window.location = "...")
    var origLocation = window.location;
    try {
      Object.defineProperty(window, 'location', {
        configurable: true,
        get: function() { return origLocation; },
        set: function(v) {
          window.parent.postMessage({type:'argus-proxy-navigate', path: String(v), method:'GET'}, '*');
        }
      });
    } catch(e) {}
  } catch(e) {}
})();
</script>
"@
            if ($htmlStr -match '</body>') {
                $htmlStr = $htmlStr -replace '</body>', "$interceptScript</body>"
            } else {
                $htmlStr = $htmlStr + $interceptScript
            }

            $respBytes = [System.Text.Encoding]::UTF8.GetBytes($htmlStr)
        } catch {
            Write-Log "[WEB-PROXY] HTML processing skip: $($_.Exception.Message)" "DEBUG"
        }
    }

    Send-WebProxyResponse $config $requestId $statusCode $contentType $respBytes $title $errorMsg $respHeaders $respCookies $tStart
}


function Build-WebProxyErrorPage($deviceIp, $port, $path, $errorMsg) {
    $safeErr = $errorMsg -replace '<', '&lt;' -replace '>', '&gt;'
    return @"
<!DOCTYPE html><html><head><meta charset="utf-8"><title>Connessione fallita</title>
<style>
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#0d0d12; color:#c9c9d1; margin:0; padding:0; }
.wrap { max-width:560px; margin:80px auto; padding:32px; background:#12121a; border:1px solid #1e1e2e; border-radius:12px; }
h1 { color:#ff6b6b; margin:0 0 8px 0; font-size:18px; }
.detail { color:#8a8a9a; font-size:13px; margin:14px 0; line-height:1.5; }
.target { background:#0f0f17; padding:10px 14px; border-radius:6px; font-family:monospace; font-size:12px; color:#a78bfa; border:1px solid #2a2a3e; }
.hint { margin-top:18px; padding:12px; background:#0f0f17; border-left:3px solid #5e5ce6; font-size:12px; color:#8a8a9a; border-radius:4px; }
</style></head><body><div class="wrap">
<h1>&#9888; Connessione al dispositivo fallita</h1>
<div class="detail">Il connector non e' riuscito a raggiungere il dispositivo.</div>
<div class="target">${deviceIp}:${port}${path}</div>
<div class="detail"><b>Dettaglio:</b> $safeErr</div>
<div class="hint">Verifica: (1) il device risponde al ping dalla LAN del connector; (2) la web console e' attiva sulla porta specificata; (3) nessun firewall blocca 86NocConnector verso il device.</div>
</div></body></html>
"@
}


function Send-WebProxyResponse($config, $requestId, $statusCode, $contentType, [byte[]]$respBytes, $title, $errorMsg, $respHeaders, $respCookies, $tStart) {
    # Envio SEMPRE body in base64 -> binary-safe, gestisce NUL byte, caratteri di controllo
    $bodyB64 = if ($respBytes -and $respBytes.Length -gt 0) { [Convert]::ToBase64String($respBytes) } else { "" }
    $sizeBytes = if ($respBytes) { $respBytes.Length } else { 0 }
    $elapsed = [int](([DateTime]::UtcNow - $tStart).TotalMilliseconds)

    $payload = @{
        request_id       = $requestId
        status_code      = $statusCode
        content_type     = $contentType
        body_b64         = $bodyB64
        body_encoding    = "base64"
        title            = $title
        error            = $errorMsg
        duration_ms      = $elapsed
        response_headers = if ($respHeaders) { $respHeaders } else { @{} }
        response_cookies = if ($respCookies) { $respCookies } else { @{} }
    }
    $headers = @{
        "X-API-Key"    = $config.api_key
        "Content-Type" = "application/json"
    }
    try {
        $jsonPayload = $payload | ConvertTo-Json -Depth 10 -Compress
        $url = "$($config.noc_center_url)/api/connector/web-proxy/response"
        Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $jsonPayload -TimeoutSec 45 -ErrorAction Stop | Out-Null
        $status = if ($statusCode -ge 400) { "FAIL" } else { "OK " }
        Write-Log "[WEB-PROXY] OUT $status $($payload.status_code) size=$sizeBytes in ${elapsed}ms title='$title'"
    } catch {
        Write-Log "[WEB-PROXY] Errore invio risposta: $($_.Exception.Message)" "ERROR"
    }
}

# ==================== STATUS FILE ====================
# Scrive lo stato del connettore su un file JSON leggibile dalla tray app.
# Questo permette alla tray app di monitorare il connettore anche quando
# gira come Scheduled Task (fuori dalla sessione utente).

function Write-StatusFile($status = "running") {
    try {
        $statusPath = Join-Path (Get-ConfigDir) "status.json"
        # Raccogli metriche processo
        $proc = Get-Process -Id $PID -ErrorAction SilentlyContinue
        $memMB = if ($proc) { [math]::Round($proc.WorkingSet64 / 1048576, 1) } else { 0 }
        $cpuTime = if ($proc) { $proc.TotalProcessorTime.TotalSeconds } else { 0 }
        $statusData = @{
            pid = $PID
            status = $status
            version = $global:Version
            hostname = $env:COMPUTERNAME
            start_time = if ($global:Stats.start_time) { $global:Stats.start_time.ToString("yyyy-MM-ddTHH:mm:ss") } else { "" }
            uptime_seconds = if ($global:Stats.start_time) { [int]((Get-Date) - $global:Stats.start_time).TotalSeconds } else { 0 }
            snmp_received = $global:Stats.snmp_received
            syslog_received = $global:Stats.syslog_received
            errors = $global:Stats.errors
            last_error = $global:Stats.last_error
            last_update = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            memory_mb = $memMB
            cpu_seconds = [math]::Round($cpuTime, 1)
        }
        $statusData | ConvertTo-Json -Compress | Set-Content $statusPath -Encoding UTF8 -Force -ErrorAction SilentlyContinue
    } catch {}
}

function Remove-StatusFile {
    try {
        $statusPath = Join-Path (Get-ConfigDir) "status.json"
        if (Test-Path $statusPath) { Remove-Item $statusPath -Force -ErrorAction SilentlyContinue }
    } catch {}
}

# ==================== MAIN ====================

function Start-Connector {
    $config = Read-Config
    if (-not $config) {
        Write-Log "Nessuna configurazione trovata. Esegui install.bat" "ERROR"
        return
    }
    
    $global:Running = $true
    $global:Stats.start_time = Get-Date
    Write-StatusFile "starting"
    
    Write-Log "=================================================="
    Write-Log "  $global:AppName v$global:Version"
    Write-Log "  NOC: $($config.noc_center_url)"
    Write-Log "  SNMP: UDP/$($config.snmp_trap_port)  Syslog: UDP/$($config.syslog_port)"
    Write-Log "  Utente: $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)"
    Write-Log "  Sessione: $(if ($env:SESSIONNAME) { $env:SESSIONNAME } else { 'SYSTEM/Background' })"
    Write-Log "  TLS: $([Net.ServicePointManager]::SecurityProtocol)"
    Write-Log "  Config: $(Get-ConfigPath)"
    Write-Log "=================================================="
    
    # Test connettivita' NOC all'avvio
    Write-Log "Test connettivita' verso il NOC..."
    try {
        $testUrl = "$($config.noc_center_url)/api/health"
        $testResult = Invoke-RestMethod -Uri $testUrl -Method Get -TimeoutSec 10 -ErrorAction Stop
        Write-Log "  NOC raggiungibile! Stato: $($testResult.status)" "INFO"
    } catch {
        $errDetail = $_.Exception.Message
        if ($_.Exception.InnerException) { $errDetail += " | Inner: $($_.Exception.InnerException.Message)" }
        Write-Log "  ERRORE: NOC non raggiungibile: $errDetail" "ERROR"
        Write-Log "  Il connettore continuera' a tentare..." "WARN"
    }
    
    # Start listeners in background jobs
    $snmpJob = Start-Job -ScriptBlock {
        param($scriptPath, $configPath)
        . $scriptPath -ConfigPath $configPath
        Start-SNMPListener (Read-Config)
    } -ArgumentList $PSCommandPath, (Get-ConfigPath)
    
    $syslogJob = Start-Job -ScriptBlock {
        param($scriptPath, $configPath)
        . $scriptPath -ConfigPath $configPath
        Start-SyslogListener (Read-Config)
    } -ArgumentList $PSCommandPath, (Get-ConfigPath)
    
    # Start SNMP polling job
    $pollingJob = $null
    if ($config.devices -and $config.devices.Count -gt 0) {
        $pollingJob = Start-Job -ScriptBlock {
            param($scriptPath, $configPath)
            . $scriptPath -ConfigPath $configPath
            $pollerFile = Join-Path (Split-Path -Parent $scriptPath) "snmp_poller.ps1"
            if (Test-Path $pollerFile) { . $pollerFile }
            $cfg = Read-Config
            $global:Running = $true
            Start-PollingLoop $cfg
        } -ArgumentList $PSCommandPath, (Get-ConfigPath)
        Write-Log "Polling SNMP avviato in background"
    }
    
    # Start auto-update checker job
    $updateJob = Start-Job -ScriptBlock {
        param($scriptPath, $configPath)
        . $scriptPath -ConfigPath $configPath
        $cfg = Read-Config
        $global:Running = $true
        Start-UpdateCheckLoop $cfg
    } -ArgumentList $PSCommandPath, (Get-ConfigPath)
    Write-Log "Auto-update checker avviato (ogni 6 ore)"
    
    # Heartbeat in current thread loop + discovery check + web proxy + memory management
    Write-Log "$global:AppName avviato. Premi Ctrl+C per fermare."
    
    $lastHeartbeat = [datetime]::MinValue
    $lastDiscovery = [datetime]::MinValue
    $lastMemoryCleanup = [datetime]::MinValue
    $lastJobHealthCheck = [datetime]::MinValue
    $heartbeatIntervalSec = 60
    $discoveryIntervalSec = 120
    $memoryCleanupIntervalSec = 300    # Ogni 5 minuti
    $jobHealthCheckIntervalSec = 180   # Ogni 3 minuti
    $webProxyIntervalSec = 3
    
    # Send first heartbeat immediately
    Send-Heartbeat $config
    Write-StatusFile "running"
    $lastHeartbeat = Get-Date
    
    try {
        while ($global:Running) {
            $now = Get-Date
            
            # Check for web proxy requests (fast, every 3s)
            Check-WebProxyRequests $config
            
            # Send heartbeat (every 60s)
            if (($now - $lastHeartbeat).TotalSeconds -ge $heartbeatIntervalSec) {
                Send-Heartbeat $config
                Write-StatusFile "running"
                $lastHeartbeat = $now
            }
            
            # Check for discovery (every 2 min)
            if (($now - $lastDiscovery).TotalSeconds -ge $discoveryIntervalSec) {
                Check-DiscoveryRequest $config
                $lastDiscovery = $now
            }
            
            # Memory cleanup (every 5 min) - previene memory leak nei job
            if (($now - $lastMemoryCleanup).TotalSeconds -ge $memoryCleanupIntervalSec) {
                try {
                    [System.GC]::Collect()
                    [System.GC]::WaitForPendingFinalizers()
                } catch {}
                $lastMemoryCleanup = $now
            }
            
            # Job health check (every 3 min) - riavvia job morti
            if (($now - $lastJobHealthCheck).TotalSeconds -ge $jobHealthCheckIntervalSec) {
                # Check SNMP listener job
                if ($snmpJob -and $snmpJob.State -ne "Running") {
                    Write-Log "SNMP Listener job morto (stato: $($snmpJob.State)), riavvio..." "WARN"
                    try {
                        Remove-Job $snmpJob -Force -ErrorAction SilentlyContinue
                        $snmpJob = Start-Job -ScriptBlock {
                            param($scriptPath, $configPath)
                            . $scriptPath -ConfigPath $configPath
                            Start-SNMPListener (Read-Config)
                        } -ArgumentList $PSCommandPath, (Get-ConfigPath)
                        Write-Log "SNMP Listener riavviato" "INFO"
                    } catch { Write-Log "Errore riavvio SNMP Listener: $($_.Exception.Message)" "ERROR" }
                }
                # Check Syslog listener job
                if ($syslogJob -and $syslogJob.State -ne "Running") {
                    Write-Log "Syslog Listener job morto (stato: $($syslogJob.State)), riavvio..." "WARN"
                    try {
                        Remove-Job $syslogJob -Force -ErrorAction SilentlyContinue
                        $syslogJob = Start-Job -ScriptBlock {
                            param($scriptPath, $configPath)
                            . $scriptPath -ConfigPath $configPath
                            Start-SyslogListener (Read-Config)
                        } -ArgumentList $PSCommandPath, (Get-ConfigPath)
                        Write-Log "Syslog Listener riavviato" "INFO"
                    } catch { Write-Log "Errore riavvio Syslog Listener: $($_.Exception.Message)" "ERROR" }
                }
                # Check Polling job
                if ($pollingJob -and $pollingJob.State -ne "Running") {
                    Write-Log "Polling job morto (stato: $($pollingJob.State)), riavvio..." "WARN"
                    try {
                        Remove-Job $pollingJob -Force -ErrorAction SilentlyContinue
                        $pollingJob = Start-Job -ScriptBlock {
                            param($scriptPath, $configPath)
                            . $scriptPath -ConfigPath $configPath
                            $pollerFile = Join-Path (Split-Path -Parent $scriptPath) "snmp_poller.ps1"
                            if (Test-Path $pollerFile) { . $pollerFile }
                            $cfg = Read-Config
                            $global:Running = $true
                            Start-PollingLoop $cfg
                        } -ArgumentList $PSCommandPath, (Get-ConfigPath)
                        Write-Log "Polling riavviato" "INFO"
                    } catch { Write-Log "Errore riavvio Polling: $($_.Exception.Message)" "ERROR" }
                }
                # Drain completed/failed job output to prevent memory accumulation
                foreach ($j in @($snmpJob, $syslogJob, $pollingJob, $updateJob)) {
                    if ($j) {
                        try { Receive-Job $j -ErrorAction SilentlyContinue | Out-Null } catch {}
                    }
                }
                $lastJobHealthCheck = $now
            }
            
            # Check SNMP trap job health first
            # Note: Check-WebProxyRequests già fa long-poll 20s, quindi non serve Start-Sleep.
            # Breve pausa solo in caso di errore rete per evitare tight-loop.
            Start-Sleep -Milliseconds 200
        }
    } catch {
        Write-Log "Arresto..."
    } finally {
        $global:Running = $false
        Write-StatusFile "stopped"
        Stop-Job $snmpJob -ErrorAction SilentlyContinue
        Stop-Job $syslogJob -ErrorAction SilentlyContinue
        Remove-Job $snmpJob -ErrorAction SilentlyContinue
        Remove-Job $syslogJob -ErrorAction SilentlyContinue
        if ($pollingJob) {
            Stop-Job $pollingJob -ErrorAction SilentlyContinue
            Remove-Job $pollingJob -ErrorAction SilentlyContinue
        }
        Stop-Job $updateJob -ErrorAction SilentlyContinue
        Remove-Job $updateJob -ErrorAction SilentlyContinue
        Write-Log "$global:AppName fermato."
    }
}

# Export for tray_app
function Get-ConnectorStatus {
    $uptime = ((Get-Date) - $global:Stats.start_time).TotalSeconds
    return @{
        running = $global:Running
        version = $global:Version
        uptime = "{0}h {1}m" -f [math]::Floor($uptime / 3600), [math]::Floor(($uptime % 3600) / 60)
        uptime_seconds = [int]$uptime
        snmp_received = $global:Stats.snmp_received
        syslog_received = $global:Stats.syslog_received
        snmp_sent = $global:Stats.snmp_sent
        syslog_sent = $global:Stats.syslog_sent
        errors = $global:Stats.errors
        last_error = $global:Stats.last_error
    }
}

# Run if called directly
if ($MyInvocation.InvocationName -ne ".") {
    Start-Connector
}
