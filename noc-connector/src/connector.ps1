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
$global:Version = "1.0.0"

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
        return $true
    } catch {
        $global:Stats.errors++
        $global:Stats.last_error = $_.Exception.Message
        Write-Log "Errore invio a NOC: $($_.Exception.Message)" "ERROR"
        return $false
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
    Send-ToNOC $config "connector/heartbeat" $payload | Out-Null
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
    
    # Heartbeat in current thread loop
    Write-Log "$global:AppName avviato. Premi Ctrl+C per fermare."
    
    try {
        while ($global:Running) {
            Send-Heartbeat $config
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
