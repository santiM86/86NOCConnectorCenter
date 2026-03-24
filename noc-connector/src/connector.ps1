<# 
.SYNOPSIS
    86NocConnector - Motore Collector SNMP Traps + Syslog
.DESCRIPTION
    Raccoglie SNMP Traps e Syslog da dispositivi di rete e li inoltra al NOC Center.
    Nessuna dipendenza esterna. Funziona con PowerShell nativo di Windows.
#>

param(
    [string]$ConfigPath = ""
)

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

function Send-ToNOC($config, $endpoint, $payload) {
    try {
        $headers = @{
            "X-API-Key" = $config.api_key
            "Content-Type" = "application/json"
        }
        $body = $payload | ConvertTo-Json -Depth 5 -Compress
        $url = "$($config.noc_center_url)/api/$endpoint"
        
        $response = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15 -ErrorAction Stop
        return $response
    } catch {
        $global:Stats.errors++
        $global:Stats.last_error = $_.Exception.Message
        Write-Log "Errore invio a NOC: $($_.Exception.Message)" "ERROR"
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

# ==================== PING/HTTP MONITORING ====================

function Poll-PingDevice($ip, $name, $httpPort) {
    $alerts = @()
    $reachable = $false
    $pingMs = $null
    $httpStatus = $null
    
    # 1. Ping test
    try {
        $ping = New-Object System.Net.NetworkInformation.Ping
        $reply = $ping.Send($ip, 3000)
        if ($reply.Status -eq "Success") {
            $reachable = $true
            $pingMs = $reply.RoundtripTime
        }
        $ping.Dispose()
    } catch {}
    
    # 2. HTTP test (if reachable)
    if ($reachable -and $httpPort) {
        try {
            $url = "http://${ip}:${httpPort}/"
            $req = [System.Net.HttpWebRequest]::Create($url)
            $req.Timeout = 5000
            $req.Method = "HEAD"
            $resp = $req.GetResponse()
            $httpStatus = [int]$resp.StatusCode
            $resp.Close()
        } catch [System.Net.WebException] {
            if ($_.Exception.Response) {
                $httpStatus = [int]$_.Exception.Response.StatusCode
            } else {
                $httpStatus = 0
            }
        } catch {
            $httpStatus = 0
        }
    }
    
    # 3. State change alerts
    $wasUp = $script:DeviceUp.ContainsKey($ip) -and $script:DeviceUp[$ip]
    
    if (-not $reachable -and $wasUp) {
        $alerts += @{
            device_ip  = $ip
            oid        = "ping.monitor"
            value      = "Dispositivo $name ($ip) NON RAGGIUNGIBILE - ping fallito"
            trap_type  = "deviceDown"
            severity   = "critical"
            device_name = $name
        }
    }
    if ($reachable -and $script:DeviceUp.ContainsKey($ip) -and -not $wasUp) {
        $alerts += @{
            device_ip  = $ip
            oid        = "ping.monitor"
            value      = "Dispositivo $name ($ip) di nuovo RAGGIUNGIBILE"
            trap_type  = "deviceUp"
            severity   = "low"
            device_name = $name
        }
    }
    $script:DeviceUp[$ip] = $reachable
    
    return @{
        alerts = $alerts
        reachable = $reachable
        ping_ms = $pingMs
        http_status = $httpStatus
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
            # Ping/HTTP device - use cached poll results
            $reachable = $script:DeviceUp.ContainsKey($ip) -and $script:DeviceUp[$ip]
            $pingMs = if ($script:PingResults.ContainsKey($ip)) { $script:PingResults[$ip].ping_ms } else { $null }
            $httpStatus = if ($script:PingResults.ContainsKey($ip)) { $script:PingResults[$ip].http_status } else { $null }
            
            $reportDevices += @{
                device_ip = $ip
                device_name = $devName
                monitor_type = $monitorType
                reachable = $reachable
                ping_ms = $pingMs
                http_status = $httpStatus
                ports = @()
                sys_descr = if ($httpStatus -and $httpStatus -gt 0) { "Web management attivo (HTTP $httpStatus)" } else { "Smart managed switch" }
                sys_uptime = ""
                poll_timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
            }
        } else {
            # SNMP device - original logic
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
            $sysUptime = ""
            if ($reachable) {
                try {
                    $sysDescr = Get-SnmpValue $ip $community "1.3.6.1.2.1.1.1.0"
                    $uptimeTicks = Get-SnmpValue $ip $community "1.3.6.1.2.1.1.3.0"
                    if ($uptimeTicks) {
                        $secs = [math]::Floor($uptimeTicks / 100)
                        $d = [math]::Floor($secs / 86400)
                        $h = [math]::Floor(($secs % 86400) / 3600)
                        $m = [math]::Floor(($secs % 3600) / 60)
                        $sysUptime = "${d}g ${h}h ${m}m"
                    }
                } catch {}
            }
            
            $reportDevices += @{
                device_ip = $ip
                device_name = $devName
                monitor_type = "snmp"
                reachable = $reachable
                ports = $ports
                sys_descr = "$sysDescr"
                sys_uptime = $sysUptime
                poll_timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
            }
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
        $headers = @{ "X-API-Key" = $config.api_key }
        $url = "$($config.noc_center_url)/api/connector/fetch-devices"
        $response = Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 15 -ErrorAction Stop
        if ($response -and $response.Count -gt 0) {
            Write-Log "Dispositivi ricevuti dal NOC: $($response.Count)"
            return @($response)
        }
    } catch {
        Write-Log "Errore fetch dispositivi dal NOC: $($_.Exception.Message)" "WARN"
    }
    return $null
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

    # Separate SNMP and Ping/HTTP devices
    $snmpDevices = @($devices | Where-Object { -not $_.monitor_type -or $_.monitor_type -eq "snmp" })
    $pingDevices = @($devices | Where-Object { $_.monitor_type -eq "ping" -or $_.monitor_type -eq "http" })
    
    # Initialize ping results cache
    if (-not $script:PingResults) { $script:PingResults = @{} }

    $interval = if ($config.poll_interval_seconds) { $config.poll_interval_seconds } else { 60 }
    Write-Log "Polling attivo per $($devices.Count) dispositivi ogni ${interval}s (SNMP: $($snmpDevices.Count), Ping/HTTP: $($pingDevices.Count))"
    foreach ($dev in $devices) {
        $mType = if ($dev.monitor_type) { $dev.monitor_type } else { "snmp" }
        Write-Log "  - $($dev.name) ($($dev.ip)) tipo=$mType"
    }

    # First poll - initialize states and send initial report
    Write-Log "Prima scansione in corso..."
    if ($snmpDevices.Count -gt 0) { $null = Poll-AllDevices $snmpDevices $config }
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
                    $snmpDevices = @($devices | Where-Object { -not $_.monitor_type -or $_.monitor_type -eq "snmp" })
                    $pingDevices = @($devices | Where-Object { $_.monitor_type -eq "ping" -or $_.monitor_type -eq "http" })
                    Write-Log "Lista dispositivi aggiornata dal NOC: $($devices.Count) totali (SNMP: $($snmpDevices.Count), Ping: $($pingDevices.Count))"
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
        $headers = @{ "X-API-Key" = $config.api_key }
        $url = "$($config.noc_center_url)/api/connector/update-check"
        $response = Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 15 -ErrorAction Stop
        
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
        $headers = @{
            "X-API-Key" = $config.api_key
            "Content-Type" = "application/json"
        }
        $body = @{ progress = $progress; status = $status; message = $message } | ConvertTo-Json -Compress
        $url = "$($config.noc_center_url)/api/connector/update-progress"
        Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 10 -ErrorAction SilentlyContinue | Out-Null
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
        
        # Launch updater as independent process and EXIT
        $installDir = Split-Path -Parent $PSScriptRoot
        $updaterPath = Join-Path $PSScriptRoot "updater.ps1"
        
        # If updater.ps1 was just extracted, use the new one
        $newUpdater = Join-Path $tempExtract "src\updater.ps1"
        if (Test-Path $newUpdater) {
            $updaterPath = $newUpdater
        }
        
        $args = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$updaterPath`" -ExtractPath `"$tempExtract`" -InstallDir `"$installDir`" -ApiUrl `"$($config.noc_center_url)`" -ApiKey `"$($config.api_key)`""
        
        Write-Log "Lancio updater: $updaterPath" "INFO"
        Start-Process "powershell.exe" -ArgumentList $args -WindowStyle Hidden
        
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
    $checkInterval = 21600  # 6 ore in secondi
    $lastCheck = [datetime]::MinValue
    
    while ($global:Running) {
        $elapsed = ((Get-Date) - $lastCheck).TotalSeconds
        if ($elapsed -ge $checkInterval) {
            $updateInfo = Check-ForUpdate $config
            if ($updateInfo) {
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
        Start-Sleep -Seconds 60
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
        $headers = @{ "X-API-Key" = $config.api_key }
        $url = "$($config.noc_center_url)/api/connector/discovery-check"
        $response = Invoke-RestMethod -Uri $url -Method Get -Headers $headers -TimeoutSec 10 -ErrorAction Stop
        if ($response.scan_requested) {
            Write-Log "Richiesta di discovery ricevuta dal NOC"
            Start-NetworkDiscovery $config $response.subnet
        }
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
    
    Write-Log "=================================================="
    Write-Log "  $global:AppName v$global:Version"
    Write-Log "  NOC: $($config.noc_center_url)"
    Write-Log "  SNMP: UDP/$($config.snmp_trap_port)  Syslog: UDP/$($config.syslog_port)"
    Write-Log "=================================================="
    
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
    
    # Heartbeat in current thread loop + discovery check
    Write-Log "$global:AppName avviato. Premi Ctrl+C per fermare."
    
    $discoveryCheckCounter = 0
    try {
        while ($global:Running) {
            Send-Heartbeat $config
            
            # Check for discovery request every 2 heartbeats (2 min)
            $discoveryCheckCounter++
            if ($discoveryCheckCounter -ge 2) {
                $discoveryCheckCounter = 0
                Check-DiscoveryRequest $config
            }
            
            Start-Sleep -Seconds 60
        }
    } catch {
        Write-Log "Arresto..."
    } finally {
        $global:Running = $false
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
