<#
.SYNOPSIS
    86NocConnector - SNMP v2c Poller
.DESCRIPTION
    Client SNMP v2c nativo per polling attivo di switch e dispositivi di rete.
    Usa raw UDP sockets con encoding BER/ASN.1 - ZERO dipendenze esterne.
#>

# ==================== BER / ASN.1 ENCODING ====================

function ConvertTo-BerLength([int]$length) {
    if ($length -lt 128) {
        return [byte[]]@($length)
    } elseif ($length -lt 256) {
        return [byte[]]@(0x81, $length)
    } else {
        $hi = [byte](($length -shr 8) -band 0xFF)
        $lo = [byte]($length -band 0xFF)
        return [byte[]]@(0x82, $hi, $lo)
    }
}

function ConvertTo-BerInteger([int]$value) {
    $bytes = [System.Collections.Generic.List[byte]]::new()
    if ($value -eq 0) {
        $bytes.Add(0)
    } else {
        $v = $value
        $temp = [System.Collections.Generic.List[byte]]::new()
        while ($v -gt 0) {
            $temp.Insert(0, [byte]($v -band 0xFF))
            $v = $v -shr 8
        }
        if ($temp[0] -band 0x80) { $temp.Insert(0, [byte]0) }
        $bytes.AddRange($temp)
    }
    $lenBytes = ConvertTo-BerLength $bytes.Count
    $result = [System.Collections.Generic.List[byte]]::new()
    $result.Add(0x02)
    $result.AddRange($lenBytes)
    $result.AddRange($bytes)
    return [byte[]]$result.ToArray()
}

function ConvertTo-BerOctetString([string]$text) {
    $data = [System.Text.Encoding]::ASCII.GetBytes($text)
    $lenBytes = ConvertTo-BerLength $data.Length
    $result = [System.Collections.Generic.List[byte]]::new()
    $result.Add(0x04)
    $result.AddRange($lenBytes)
    $result.AddRange($data)
    return [byte[]]$result.ToArray()
}

function ConvertTo-BerOID([string]$oidStr) {
    $parts = $oidStr.Split('.') | Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ }
    $bytes = [System.Collections.Generic.List[byte]]::new()
    $bytes.Add([byte]($parts[0] * 40 + $parts[1]))
    for ($i = 2; $i -lt $parts.Count; $i++) {
        $val = $parts[$i]
        if ($val -lt 128) {
            $bytes.Add([byte]$val)
        } else {
            $temp = [System.Collections.Generic.List[byte]]::new()
            $temp.Insert(0, [byte]($val -band 0x7F))
            $val = $val -shr 7
            while ($val -gt 0) {
                $temp.Insert(0, [byte](($val -band 0x7F) -bor 0x80))
                $val = $val -shr 7
            }
            $bytes.AddRange($temp)
        }
    }
    $lenBytes = ConvertTo-BerLength $bytes.Count
    $result = [System.Collections.Generic.List[byte]]::new()
    $result.Add(0x06)
    $result.AddRange($lenBytes)
    $result.AddRange($bytes)
    return [byte[]]$result.ToArray()
}

function ConvertTo-BerNull {
    return [byte[]]@(0x05, 0x00)
}

function ConvertTo-BerSequence([byte[]]$content) {
    $lenBytes = ConvertTo-BerLength $content.Length
    $result = [System.Collections.Generic.List[byte]]::new()
    $result.Add(0x30)
    $result.AddRange($lenBytes)
    $result.AddRange($content)
    return [byte[]]$result.ToArray()
}

# ==================== BER DECODING ====================

function Read-BerLength([byte[]]$data, [ref]$offset) {
    $b = $data[$offset.Value]
    $offset.Value++
    if ($b -lt 128) { return $b }
    $numBytes = $b -band 0x7F
    $length = 0
    for ($i = 0; $i -lt $numBytes; $i++) {
        $length = ($length -shl 8) -bor $data[$offset.Value]
        $offset.Value++
    }
    return $length
}

function Read-BerOID([byte[]]$data, [int]$start, [int]$length) {
    $parts = [System.Collections.Generic.List[string]]::new()
    $parts.Add([string][math]::Floor($data[$start] / 40))
    $parts.Add([string]($data[$start] % 40))
    $val = 0
    for ($i = 1; $i -lt $length; $i++) {
        if ($data[$start + $i] -band 0x80) {
            $val = ($val -shl 7) -bor ($data[$start + $i] -band 0x7F)
        } else {
            $val = ($val -shl 7) -bor $data[$start + $i]
            $parts.Add([string]$val)
            $val = 0
        }
    }
    return $parts -join "."
}

function Read-BerInteger([byte[]]$data, [int]$start, [int]$length) {
    $val = 0
    $signed = $data[$start] -band 0x80
    for ($i = 0; $i -lt $length; $i++) {
        $val = ($val -shl 8) -bor $data[$start + $i]
    }
    if ($signed -and $length -le 4) {
        $val = $val - [math]::Pow(2, $length * 8)
    }
    return [long]$val
}

function Parse-SnmpResponse([byte[]]$data) {
    $results = @{}
    try {
        $off = [ref]0
        # Outer SEQUENCE
        if ($data[$off.Value] -ne 0x30) { return $results }
        $off.Value++
        $null = Read-BerLength $data $off

        # Version INTEGER
        if ($data[$off.Value] -ne 0x02) { return $results }
        $off.Value++
        $vLen = Read-BerLength $data $off
        $off.Value += $vLen

        # Community OCTET STRING
        if ($data[$off.Value] -ne 0x04) { return $results }
        $off.Value++
        $cLen = Read-BerLength $data $off
        $off.Value += $cLen

        # PDU (GetResponse = 0xA2)
        $pduTag = $data[$off.Value]
        $off.Value++
        $null = Read-BerLength $data $off

        # Request ID
        $off.Value++
        $ridLen = Read-BerLength $data $off
        $off.Value += $ridLen

        # Error Status
        $off.Value++
        $esLen = Read-BerLength $data $off
        $errorStatus = 0
        if ($esLen -gt 0) { $errorStatus = $data[$off.Value] }
        $off.Value += $esLen
        if ($errorStatus -ne 0) { return $results }

        # Error Index
        $off.Value++
        $eiLen = Read-BerLength $data $off
        $off.Value += $eiLen

        # Varbind list SEQUENCE
        if ($data[$off.Value] -ne 0x30) { return $results }
        $off.Value++
        $null = Read-BerLength $data $off

        # Parse varbinds
        while ($off.Value -lt $data.Length - 2) {
            if ($data[$off.Value] -ne 0x30) { break }
            $off.Value++
            $vbLen = Read-BerLength $data $off
            $vbEnd = $off.Value + $vbLen

            # OID
            if ($data[$off.Value] -ne 0x06) { $off.Value = $vbEnd; continue }
            $off.Value++
            $oidLen = Read-BerLength $data $off
            $oid = Read-BerOID $data $off.Value $oidLen
            $off.Value += $oidLen

            # Value
            $valTag = $data[$off.Value]
            $off.Value++
            $valLen = Read-BerLength $data $off
            $valStart = $off.Value

            switch ($valTag) {
                0x02 { # INTEGER
                    $results[$oid] = Read-BerInteger $data $valStart $valLen
                }
                0x04 { # OCTET STRING
                    $results[$oid] = [System.Text.Encoding]::UTF8.GetString($data, $valStart, $valLen)
                }
                0x41 { # Counter32
                    $results[$oid] = Read-BerInteger $data $valStart $valLen
                }
                0x42 { # Gauge32
                    $results[$oid] = Read-BerInteger $data $valStart $valLen
                }
                0x43 { # TimeTicks
                    $results[$oid] = Read-BerInteger $data $valStart $valLen
                }
                0x06 { # OID value
                    $results[$oid] = Read-BerOID $data $valStart $valLen
                }
                default {
                    if ($valLen -gt 0) {
                        $results[$oid] = [System.Text.Encoding]::UTF8.GetString($data, $valStart, [Math]::Min($valLen, $data.Length - $valStart))
                    }
                }
            }
            $off.Value = $vbEnd
        }
    } catch {
        # Parse error - return what we have
    }
    return $results
}

# ==================== SNMP GET / GET-NEXT ====================

$script:RequestId = 1

function Send-SnmpGet([string]$target, [string]$community, [string]$oid, [int]$port = 161, [bool]$getNext = $false) {
    $script:RequestId++
    if ($script:RequestId -gt 65000) { $script:RequestId = 1 }

    # Build varbind: OID + NULL
    $oidBytes = ConvertTo-BerOID $oid
    $nullBytes = ConvertTo-BerNull
    $varbind = ConvertTo-BerSequence ([byte[]]($oidBytes + $nullBytes))
    $varbindList = ConvertTo-BerSequence $varbind

    # Build PDU content
    $reqIdBytes = ConvertTo-BerInteger $script:RequestId
    $errorStatus = ConvertTo-BerInteger 0
    $errorIndex = ConvertTo-BerInteger 0
    $pduContent = [byte[]]($reqIdBytes + $errorStatus + $errorIndex + $varbindList)

    # PDU tag: 0xA0 = GET, 0xA1 = GET-NEXT
    $pduTag = if ($getNext) { [byte]0xA1 } else { [byte]0xA0 }
    $pduLenBytes = ConvertTo-BerLength $pduContent.Length
    $pdu = [System.Collections.Generic.List[byte]]::new()
    $pdu.Add($pduTag)
    $pdu.AddRange($pduLenBytes)
    $pdu.AddRange($pduContent)

    # Build message
    $versionBytes = ConvertTo-BerInteger 1  # v2c
    $communityBytes = ConvertTo-BerOctetString $community
    $messageContent = [byte[]]($versionBytes + $communityBytes + $pdu.ToArray())
    $packet = ConvertTo-BerSequence $messageContent

    # Send via UDP
    try {
        $udp = New-Object System.Net.Sockets.UdpClient
        $udp.Client.ReceiveTimeout = 3000
        $ep = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse($target), $port)
        $null = $udp.Send($packet, $packet.Length, $ep)
        $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
        $response = $udp.Receive([ref]$remoteEP)
        $udp.Close()
        return Parse-SnmpResponse $response
    } catch {
        if ($udp) { $udp.Close() }
        return $null
    }
}

function Get-SnmpValue([string]$target, [string]$community, [string]$oid) {
    $result = Send-SnmpGet $target $community $oid
    if ($result -and $result.Count -gt 0) {
        return $result.Values | Select-Object -First 1
    }
    return $null
}

# ==================== SNMP TABLE WALK ====================

function Get-SnmpTable([string]$target, [string]$community, [string]$baseOid) {
    $results = @{}
    $currentOid = $baseOid
    $maxIter = 200

    for ($i = 0; $i -lt $maxIter; $i++) {
        $response = Send-SnmpGet $target $community $currentOid -getNext $true
        if (-not $response -or $response.Count -eq 0) { break }

        $respOid = $response.Keys | Select-Object -First 1
        $respVal = $response[$respOid]

        # Stop if we left the table
        if (-not $respOid.StartsWith($baseOid)) { break }

        $results[$respOid] = $respVal
        $currentOid = $respOid
    }
    return $results
}

# ==================== DEVICE POLLING ====================

# OID definitions - Standard MIB-II
$script:OID_sysDescr    = "1.3.6.1.2.1.1.1.0"
$script:OID_sysUpTime   = "1.3.6.1.2.1.1.3.0"
$script:OID_sysName     = "1.3.6.1.2.1.1.5.0"
$script:OID_ifDescr     = "1.3.6.1.2.1.2.2.1.2"
$script:OID_ifAdminStat = "1.3.6.1.2.1.2.2.1.7"
$script:OID_ifOperStat  = "1.3.6.1.2.1.2.2.1.8"
$script:OID_ifInErrors  = "1.3.6.1.2.1.2.2.1.14"
$script:OID_ifOutErrors = "1.3.6.1.2.1.2.2.1.20"
$script:OID_ifSpeed     = "1.3.6.1.2.1.2.2.1.5"
$script:OID_ifInOctets  = "1.3.6.1.2.1.2.2.1.10"
$script:OID_ifOutOctets = "1.3.6.1.2.1.2.2.1.16"
$script:OID_ifAlias     = "1.3.6.1.2.1.31.1.1.1.18"
$script:OID_ifHCInOctets  = "1.3.6.1.2.1.31.1.1.1.6"
$script:OID_ifHCOutOctets = "1.3.6.1.2.1.31.1.1.1.10"

# HPE Comware / H3C OIDs (HPE 5130, 5500, 5900, etc.)
$script:OID_hh3cCpuUsage   = "1.3.6.1.4.1.25506.2.6.1.1.1.1.6"
$script:OID_hh3cMemUsage    = "1.3.6.1.4.1.25506.2.6.1.1.1.1.8"
$script:OID_hh3cTemperature = "1.3.6.1.4.1.25506.2.6.1.1.1.1.12"

# HPE ILO / ProLiant OIDs (CPQHLTH-MIB)
$script:OID_cpqHealth       = "1.3.6.1.4.1.232.6.1.3.0"           # cpqHeMibCondition (2=ok,3=degraded,4=failed)
$script:OID_cpqTempTable    = "1.3.6.1.4.1.232.6.2.6.8.1"         # cpqHeTemperatureTable
$script:OID_cpqTempValue    = "1.3.6.1.4.1.232.6.2.6.8.1.4"       # cpqHeTemperatureCelsius
$script:OID_cpqTempLocale   = "1.3.6.1.4.1.232.6.2.6.8.1.3"       # cpqHeTemperatureLocale
$script:OID_cpqTempCondition= "1.3.6.1.4.1.232.6.2.6.8.1.6"       # cpqHeTemperatureCondition
$script:OID_cpqFanCondition = "1.3.6.1.4.1.232.6.2.6.7.1.1.9"     # cpqHeFltTolFanCondition
$script:OID_cpqFanLocale    = "1.3.6.1.4.1.232.6.2.6.7.1.1.3"     # cpqHeFltTolFanLocale
$script:OID_cpqFanSpeed     = "1.3.6.1.4.1.232.6.2.6.7.1.1.6"     # cpqHeFltTolFanCurrentSpeed
$script:OID_cpqPsuCondition = "1.3.6.1.4.1.232.6.2.9.3.1.1.4"     # cpqHeFltTolPowerSupplyCondition
$script:OID_cpqPsuStatus    = "1.3.6.1.4.1.232.6.2.9.3.1.1.5"     # cpqHeFltTolPowerSupplyStatus
$script:OID_cpqDiskStatus   = "1.3.6.1.4.1.232.3.2.5.1.1.6"       # cpqDaPhyDrvStatus
$script:OID_cpqDiskModel    = "1.3.6.1.4.1.232.3.2.5.1.1.3"       # cpqDaPhyDrvModel

# Zyxel USG / ATP / VPN Firewall OIDs (Enterprise .1.3.6.1.4.1.890)
$script:OID_zyxelCpuCurrent    = "1.3.6.1.4.1.890.1.6.22.1.1.0"   # CPU usage current %
$script:OID_zyxelCpu5sec       = "1.3.6.1.4.1.890.1.6.22.1.3.0"   # CPU usage 5 sec avg
$script:OID_zyxelCpu1min       = "1.3.6.1.4.1.890.1.6.22.1.4.0"   # CPU usage 1 min avg
$script:OID_zyxelCpu5min       = "1.3.6.1.4.1.890.1.6.22.1.5.0"   # CPU usage 5 min avg
$script:OID_zyxelRamUsage      = "1.3.6.1.4.1.890.1.6.22.1.2.0"   # RAM usage current %
$script:OID_zyxelSessions      = "1.3.6.1.4.1.890.1.6.22.1.6.0"   # Active sessions count
$script:OID_zyxelFlashUsage    = "1.3.6.1.4.1.890.1.6.22.1.7.0"   # Flash usage %
$script:OID_zyxelVpnThroughput = "1.3.6.1.4.1.890.1.6.22.2.1.0"   # IPSec VPN total throughput
$script:OID_zyxelFirmware      = "1.3.6.1.4.1.890.1.15.3.1.6.0"   # Firmware version
$script:OID_zyxelProduct       = "1.3.6.1.4.1.890.1.15.3.1.11.0"  # Product name
$script:OID_zyxelSerial        = "1.3.6.1.4.1.890.1.15.3.1.12.0"  # Serial number

# Port status memory per device
$script:PortStates = @{}
$script:DeviceUp = @{}
$script:TrafficCounters = @{}  # Stores previous octet counters for bandwidth calc
$script:LastPollTime = @{}     # Timestamp of last poll per device

$script:IfStatusMap = @{
    1 = "up"
    2 = "down"
    3 = "testing"
    4 = "unknown"
    5 = "dormant"
    6 = "notPresent"
    7 = "lowerLayerDown"
}

$script:CpqConditionMap = @{
    1 = "other"
    2 = "ok"
    3 = "degraded"
    4 = "failed"
}

$script:CpqTempLocaleMap = @{
    1 = "other"; 2 = "unknown"; 3 = "system"; 4 = "systemBoard"
    5 = "ioBoard"; 6 = "cpu"; 7 = "memory"; 8 = "storage"
    9 = "removableMedia"; 10 = "powerSupply"; 11 = "ambient"
    12 = "chassis"; 13 = "bridgeCard"
}

$script:CpqFanLocaleMap = @{
    1 = "other"; 2 = "unknown"; 3 = "system"; 4 = "systemBoard"
    5 = "ioBoard"; 6 = "cpu"; 7 = "memory"; 8 = "storage"
    9 = "removableMedia"; 10 = "powerSupply"; 11 = "ambient"
}

$script:CpqDiskStatusMap = @{
    1 = "other"; 2 = "ok"; 3 = "failed"; 4 = "predictiveFailure"
    5 = "erasing"; 6 = "eraseDone"; 7 = "eraseQueued"; 8 = "ssdWearOut"
}

function Poll-ExtendedMetrics([string]$ip, [string]$community) {
    $metrics = @{
        cpu_usage = $null
        memory_usage = $null
        temperature = $null
        device_class = "generic"  # generic, hpe-comware, hpe-ilo
        hardware = @{
            fans = @()
            power_supplies = @()
            temperatures = @()
            disks = @()
            health_status = $null
        }
    }
    
    # --- Detect device type from sysDescr ---
    $sysDescr = Get-SnmpValue $ip $community $script:OID_sysDescr
    $isComware = $false
    $isILO = $false
    $isZyxel = $false
    if ($sysDescr) {
        if ($sysDescr -match "Comware|H3C|HPE.*Switch|5130|5500|5900|FlexNetwork") { $isComware = $true }
        if ($sysDescr -match "iLO|Integrated Lights-Out|ProLiant") { $isILO = $true }
        if ($sysDescr -match "ZyXEL|Zyxel|ZyWALL|USG|ATP|VPN.*Series|FLEX") { $isZyxel = $true }
    }
    
    # --- HPE Comware / H3C Metrics (5130, 5500, etc.) ---
    if ($isComware) {
        $metrics.device_class = "hpe-comware"
        try {
            # CPU usage - walk the table and take the first valid value
            $cpuTable = Get-SnmpTable $ip $community $script:OID_hh3cCpuUsage
            if ($cpuTable -and $cpuTable.Count -gt 0) {
                $cpuVals = @($cpuTable.Values | Where-Object { $_ -is [long] -or $_ -is [int] } | Where-Object { $_ -ge 0 -and $_ -le 100 })
                if ($cpuVals.Count -gt 0) { $metrics.cpu_usage = [int]$cpuVals[0] }
            }
        } catch {}
        try {
            # Memory usage
            $memTable = Get-SnmpTable $ip $community $script:OID_hh3cMemUsage
            if ($memTable -and $memTable.Count -gt 0) {
                $memVals = @($memTable.Values | Where-Object { $_ -is [long] -or $_ -is [int] } | Where-Object { $_ -ge 0 -and $_ -le 100 })
                if ($memVals.Count -gt 0) { $metrics.memory_usage = [int]$memVals[0] }
            }
        } catch {}
        try {
            # Temperature
            $tempTable = Get-SnmpTable $ip $community $script:OID_hh3cTemperature
            if ($tempTable -and $tempTable.Count -gt 0) {
                $tempVals = @($tempTable.Values | Where-Object { $_ -is [long] -or $_ -is [int] } | Where-Object { $_ -gt 0 -and $_ -lt 150 })
                if ($tempVals.Count -gt 0) { $metrics.temperature = [int]$tempVals[0] }
                # Store all temperature readings
                $idx = 1
                foreach ($v in $tempVals) {
                    $metrics.hardware.temperatures += @{ locale = "sensor-$idx"; value = [int]$v; condition = "ok" }
                    $idx++
                }
            }
        } catch {}
    }
    
    # --- HPE ILO Metrics ---
    if ($isILO) {
        $metrics.device_class = "hpe-ilo"
        try {
            # Overall health condition
            $health = Get-SnmpValue $ip $community $script:OID_cpqHealth
            if ($health -ne $null) {
                $metrics.hardware.health_status = if ($script:CpqConditionMap.ContainsKey([int]$health)) { $script:CpqConditionMap[[int]$health] } else { "unknown" }
            }
        } catch {}
        try {
            # Temperature sensors
            $tempValues = Get-SnmpTable $ip $community $script:OID_cpqTempValue
            $tempLocales = Get-SnmpTable $ip $community $script:OID_cpqTempLocale
            $tempConditions = Get-SnmpTable $ip $community $script:OID_cpqTempCondition
            if ($tempValues -and $tempValues.Count -gt 0) {
                foreach ($key in $tempValues.Keys) {
                    $idx = $key.Split('.')[-1]
                    $val = [int]$tempValues[$key]
                    if ($val -le 0 -or $val -ge 200) { continue }
                    $localeKey = ($tempLocales.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
                    $condKey = ($tempConditions.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
                    $locale = if ($localeKey -and $script:CpqTempLocaleMap.ContainsKey([int]$tempLocales[$localeKey])) { $script:CpqTempLocaleMap[[int]$tempLocales[$localeKey]] } else { "sensor-$idx" }
                    $cond = if ($condKey -and $script:CpqConditionMap.ContainsKey([int]$tempConditions[$condKey])) { $script:CpqConditionMap[[int]$tempConditions[$condKey]] } else { "ok" }
                    $metrics.hardware.temperatures += @{ locale = $locale; value = $val; condition = $cond }
                    # Use first CPU or ambient temp as main temperature
                    if ($metrics.temperature -eq $null) { $metrics.temperature = $val }
                }
            }
        } catch {}
        try {
            # Fans
            $fanConditions = Get-SnmpTable $ip $community $script:OID_cpqFanCondition
            $fanLocales = Get-SnmpTable $ip $community $script:OID_cpqFanLocale
            $fanSpeeds = Get-SnmpTable $ip $community $script:OID_cpqFanSpeed
            if ($fanConditions -and $fanConditions.Count -gt 0) {
                foreach ($key in $fanConditions.Keys) {
                    $idx = $key.Split('.')[-1]
                    $cond = if ($script:CpqConditionMap.ContainsKey([int]$fanConditions[$key])) { $script:CpqConditionMap[[int]$fanConditions[$key]] } else { "unknown" }
                    $localeKey = ($fanLocales.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
                    $locale = if ($localeKey -and $script:CpqFanLocaleMap.ContainsKey([int]$fanLocales[$localeKey])) { $script:CpqFanLocaleMap[[int]$fanLocales[$localeKey]] } else { "fan-$idx" }
                    $speedKey = ($fanSpeeds.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
                    $speed = if ($speedKey) { [int]$fanSpeeds[$speedKey] } else { $null }
                    $metrics.hardware.fans += @{ locale = $locale; condition = $cond; speed = $speed }
                }
            }
        } catch {}
        try {
            # Power Supplies
            $psuConditions = Get-SnmpTable $ip $community $script:OID_cpqPsuCondition
            $psuStatuses = Get-SnmpTable $ip $community $script:OID_cpqPsuStatus
            if ($psuConditions -and $psuConditions.Count -gt 0) {
                $idx = 1
                foreach ($key in $psuConditions.Keys) {
                    $cond = if ($script:CpqConditionMap.ContainsKey([int]$psuConditions[$key])) { $script:CpqConditionMap[[int]$psuConditions[$key]] } else { "unknown" }
                    $metrics.hardware.power_supplies += @{ name = "PSU-$idx"; condition = $cond }
                    $idx++
                }
            }
        } catch {}
        try {
            # Physical Disks
            $diskStatuses = Get-SnmpTable $ip $community $script:OID_cpqDiskStatus
            $diskModels = Get-SnmpTable $ip $community $script:OID_cpqDiskModel
            if ($diskStatuses -and $diskStatuses.Count -gt 0) {
                foreach ($key in $diskStatuses.Keys) {
                    $idx = $key.Split('.')[-1]
                    $status = if ($script:CpqDiskStatusMap.ContainsKey([int]$diskStatuses[$key])) { $script:CpqDiskStatusMap[[int]$diskStatuses[$key]] } else { "unknown" }
                    $modelKey = ($diskModels.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
                    $model = if ($modelKey) { "$($diskModels[$modelKey])" } else { "Disk-$idx" }
                    $metrics.hardware.disks += @{ name = $model; status = $status }
                }
            }
        } catch {}
    }
    
    # --- Zyxel USG / ATP / VPN Firewall Metrics ---
    if ($isZyxel) {
        $metrics.device_class = "zyxel-usg"
        try {
            # CPU usage (5 min average is the most stable)
            $cpu5min = Get-SnmpValue $ip $community $script:OID_zyxelCpu5min
            if ($cpu5min -ne $null -and $cpu5min -ge 0 -and $cpu5min -le 100) {
                $metrics.cpu_usage = [int]$cpu5min
            } else {
                # Fallback to current CPU
                $cpuCurrent = Get-SnmpValue $ip $community $script:OID_zyxelCpuCurrent
                if ($cpuCurrent -ne $null -and $cpuCurrent -ge 0 -and $cpuCurrent -le 100) {
                    $metrics.cpu_usage = [int]$cpuCurrent
                }
            }
        } catch {}
        try {
            # RAM usage
            $ram = Get-SnmpValue $ip $community $script:OID_zyxelRamUsage
            if ($ram -ne $null -and $ram -ge 0 -and $ram -le 100) {
                $metrics.memory_usage = [int]$ram
            }
        } catch {}
        try {
            # Active sessions
            $sessions = Get-SnmpValue $ip $community $script:OID_zyxelSessions
            if ($sessions -ne $null) {
                $metrics.firewall = @{
                    active_sessions = [int]$sessions
                }
            }
        } catch {}
        try {
            # Flash usage
            $flash = Get-SnmpValue $ip $community $script:OID_zyxelFlashUsage
            if ($flash -ne $null -and $flash -ge 0 -and $flash -le 100) {
                if (-not $metrics.firewall) { $metrics.firewall = @{} }
                $metrics.firewall.flash_usage = [int]$flash
            }
        } catch {}
        try {
            # IPSec VPN throughput
            $vpn = Get-SnmpValue $ip $community $script:OID_zyxelVpnThroughput
            if ($vpn -ne $null) {
                if (-not $metrics.firewall) { $metrics.firewall = @{} }
                $metrics.firewall.vpn_throughput = [long]$vpn
            }
        } catch {}
        try {
            # CPU detail (all intervals)
            $cpuCurrent = Get-SnmpValue $ip $community $script:OID_zyxelCpuCurrent
            $cpu5sec = Get-SnmpValue $ip $community $script:OID_zyxelCpu5sec
            $cpu1min = Get-SnmpValue $ip $community $script:OID_zyxelCpu1min
            if (-not $metrics.firewall) { $metrics.firewall = @{} }
            $metrics.firewall.cpu_detail = @{
                current = if ($cpuCurrent -ne $null) { [int]$cpuCurrent } else { $null }
                avg_5sec = if ($cpu5sec -ne $null) { [int]$cpu5sec } else { $null }
                avg_1min = if ($cpu1min -ne $null) { [int]$cpu1min } else { $null }
                avg_5min = $metrics.cpu_usage
            }
        } catch {}
        try {
            # Firmware version
            $fw = Get-SnmpValue $ip $community $script:OID_zyxelFirmware
            if ($fw) {
                if (-not $metrics.firewall) { $metrics.firewall = @{} }
                $metrics.firewall.firmware = "$fw"
            }
        } catch {}
        try {
            # Product name
            $product = Get-SnmpValue $ip $community $script:OID_zyxelProduct
            if ($product) {
                if (-not $metrics.firewall) { $metrics.firewall = @{} }
                $metrics.firewall.product_name = "$product"
            }
        } catch {}
        try {
            # Serial number
            $serial = Get-SnmpValue $ip $community $script:OID_zyxelSerial
            if ($serial) {
                if (-not $metrics.firewall) { $metrics.firewall = @{} }
                $metrics.firewall.serial_number = "$serial"
            }
        } catch {}
    }
    
    # --- Generic fallback: Try standard HOST-RESOURCES-MIB for CPU/Memory ---
    if (-not $isComware -and -not $isILO -and -not $isZyxel) {
        try {
            # hrProcessorLoad (1.3.6.1.2.1.25.3.3.1.2) - works on many devices
            $cpuTable = Get-SnmpTable $ip $community "1.3.6.1.2.1.25.3.3.1.2"
            if ($cpuTable -and $cpuTable.Count -gt 0) {
                $cpuVals = @($cpuTable.Values | Where-Object { $_ -is [long] -or $_ -is [int] })
                if ($cpuVals.Count -gt 0) {
                    $avg = ($cpuVals | Measure-Object -Average).Average
                    $metrics.cpu_usage = [int]$avg
                }
            }
        } catch {}
    }
    
    return $metrics
}

function Poll-InterfaceTraffic([string]$ip, [string]$community) {
    $traffic = @{}
    $now = Get-Date
    
    # Get interface octets
    $inOctets = Get-SnmpTable $ip $community $script:OID_ifInOctets
    $outOctets = Get-SnmpTable $ip $community $script:OID_ifOutOctets
    $ifSpeeds = Get-SnmpTable $ip $community $script:OID_ifSpeed
    $ifErrors = Get-SnmpTable $ip $community $script:OID_ifInErrors
    $ifOutErrors = Get-SnmpTable $ip $community $script:OID_ifOutErrors
    
    # Calculate bandwidth if we have previous counters
    $prevCounters = if ($script:TrafficCounters.ContainsKey($ip)) { $script:TrafficCounters[$ip] } else { $null }
    $prevTime = if ($script:LastPollTime.ContainsKey($ip)) { $script:LastPollTime[$ip] } else { $null }
    $newCounters = @{}
    
    if ($inOctets) {
        foreach ($key in $inOctets.Keys) {
            $idx = $key.Split('.')[-1]
            $inVal = [long]$inOctets[$key]
            $outKey = ($outOctets.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
            $outVal = if ($outKey) { [long]$outOctets[$outKey] } else { 0 }
            $speedKey = ($ifSpeeds.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
            $speed = if ($speedKey) { [long]$ifSpeeds[$speedKey] } else { 0 }
            $errInKey = ($ifErrors.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
            $errIn = if ($errInKey) { [long]$ifErrors[$errInKey] } else { 0 }
            $errOutKey = ($ifOutErrors.Keys | Where-Object { $_.EndsWith(".$idx") } | Select-Object -First 1)
            $errOut = if ($errOutKey) { [long]$ifOutErrors[$errOutKey] } else { 0 }
            
            $newCounters[$idx] = @{ in = $inVal; out = $outVal }
            
            $bpsIn = 0; $bpsOut = 0
            if ($prevCounters -and $prevTime -and $prevCounters.ContainsKey($idx)) {
                $elapsed = ($now - $prevTime).TotalSeconds
                if ($elapsed -gt 0) {
                    $deltaIn = $inVal - $prevCounters[$idx].in
                    $deltaOut = $outVal - $prevCounters[$idx].out
                    # Handle counter wrap (32-bit)
                    if ($deltaIn -lt 0) { $deltaIn += [math]::Pow(2, 32) }
                    if ($deltaOut -lt 0) { $deltaOut += [math]::Pow(2, 32) }
                    $bpsIn = [math]::Round(($deltaIn * 8) / $elapsed)
                    $bpsOut = [math]::Round(($deltaOut * 8) / $elapsed)
                }
            }
            
            $traffic[$idx] = @{
                speed_bps = $speed
                in_bps = $bpsIn
                out_bps = $bpsOut
                in_errors = $errIn
                out_errors = $errOut
            }
        }
    }
    
    $script:TrafficCounters[$ip] = $newCounters
    $script:LastPollTime[$ip] = $now
    
    return $traffic
}

function Poll-Device([string]$ip, [string]$community, [string]$name) {
    $alerts = @()

    # 0. Quick ping check first (most reliable reachability test)
    $pingOk = $false
    $pingMs = $null
    try {
        $ping = New-Object System.Net.NetworkInformation.Ping
        $reply = $ping.Send($ip, 2000)
        $pingOk = ($reply.Status -eq "Success")
        if ($pingOk) { $pingMs = $reply.RoundtripTime }
        $ping.Dispose()
    } catch {}

    # 1. Check reachability with SNMP
    $reachable = $false
    $sysDescr = $null
    try {
        $probeResult = Send-SnmpGet $ip $community $script:OID_sysDescr
        if ($probeResult -and $probeResult.Count -gt 0) {
            $sysDescr = $probeResult.Values | Select-Object -First 1
            $reachable = $true
        }
    } catch {}
    
    # Fallback: raw UDP reachability check if parser failed
    if (-not $reachable) {
        try {
            $udp = New-Object System.Net.Sockets.UdpClient
            $udp.Client.ReceiveTimeout = 3000
            $oidBytes = @(0x06, 0x08, 0x2B, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00)
            $varbind = @(0x30) + @([byte]($oidBytes.Length + 2)) + $oidBytes + @(0x05, 0x00)
            $varbindList = @(0x30) + @([byte]$varbind.Length) + $varbind
            $reqId = @(0x02, 0x01, 0x01)
            $errStat = @(0x02, 0x01, 0x00)
            $errIdx = @(0x02, 0x01, 0x00)
            $pduContent = $reqId + $errStat + $errIdx + $varbindList
            $pdu = @([byte]0xA0) + @([byte]$pduContent.Length) + $pduContent
            $commBytes = [System.Text.Encoding]::ASCII.GetBytes($community)
            $commTlv = @(0x04, [byte]$commBytes.Length) + $commBytes
            $version = @(0x02, 0x01, 0x01)
            $msgContent = $version + $commTlv + $pdu
            $packet = [byte[]](@(0x30) + @([byte]$msgContent.Length) + $msgContent)
            
            $ep = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse($ip), 161)
            $null = $udp.Send($packet, $packet.Length, $ep)
            $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
            $response = $udp.Receive([ref]$remoteEP)
            $udp.Close()
            
            if ($response.Length -gt 10) {
                $reachable = $true
                try {
                    $parsed = Parse-SnmpResponse $response
                    if ($parsed -and $parsed.Count -gt 0) {
                        $sysDescr = $parsed.Values | Select-Object -First 1
                    }
                } catch {}
            }
        } catch {
            try { $udp.Close() } catch {}
        }
    }

    if (-not $reachable) {
        if ($pingOk) {
            $reachable = $true
            if (-not $sysDescr) { $sysDescr = "Dispositivo raggiungibile (ping OK, SNMP non disponibile)" }
        }
    }

    if (-not $reachable) {
        if ($script:DeviceUp.ContainsKey($ip) -and $script:DeviceUp[$ip]) {
            $alerts += @{
                device_ip  = $ip
                oid        = "1.3.6.1.2.1.1.1.0"
                value      = "Dispositivo $name ($ip) NON RAGGIUNGIBILE - nessuna risposta SNMP"
                trap_type  = "deviceDown"
                severity   = "critical"
                device_name = $name
            }
        }
        $script:DeviceUp[$ip] = $false
        return $alerts
    }

    # Device came back online
    if ($script:DeviceUp.ContainsKey($ip) -and -not $script:DeviceUp[$ip]) {
        $alerts += @{
            device_ip  = $ip
            oid        = "1.3.6.1.2.1.1.1.0"
            value      = "Dispositivo $name ($ip) di nuovo RAGGIUNGIBILE"
            trap_type  = "deviceUp"
            severity   = "low"
            device_name = $name
        }
    }
    $script:DeviceUp[$ip] = $true

    # 2. Get interface names
    $ifDescrTable = Get-SnmpTable $ip $community $script:OID_ifDescr

    # 3. Get operational status
    $ifOperTable = Get-SnmpTable $ip $community $script:OID_ifOperStat

    # 4. Get admin status (to know which ports are intentionally down)
    $ifAdminTable = Get-SnmpTable $ip $community $script:OID_ifAdminStat

    # Build port index map
    $portMap = @{}
    foreach ($key in $ifDescrTable.Keys) {
        $idx = $key.Split('.')[-1]
        $portMap[$idx] = @{
            name = $ifDescrTable[$key]
            oper = $null
            admin = $null
        }
    }
    foreach ($key in $ifOperTable.Keys) {
        $idx = $key.Split('.')[-1]
        if ($portMap.ContainsKey($idx)) {
            $portMap[$idx].oper = [int]$ifOperTable[$key]
        }
    }
    foreach ($key in $ifAdminTable.Keys) {
        $idx = $key.Split('.')[-1]
        if ($portMap.ContainsKey($idx)) {
            $portMap[$idx].admin = [int]$ifAdminTable[$key]
        }
    }

    # 5. Compare with previous state
    if (-not $script:PortStates.ContainsKey($ip)) {
        $script:PortStates[$ip] = @{}
    }
    $prevStates = $script:PortStates[$ip]

    foreach ($idx in $portMap.Keys) {
        $port = $portMap[$idx]
        $portName = $port.name
        $operStatus = $port.oper
        $adminStatus = $port.admin

        # Skip ports that are admin-down (intentionally disabled)
        if ($adminStatus -eq 2) { continue }

        $prevOper = $null
        if ($prevStates.ContainsKey($idx)) {
            $prevOper = $prevStates[$idx]
        }

        if ($prevOper -ne $null -and $prevOper -ne $operStatus) {
            $statusName = if ($script:IfStatusMap.ContainsKey($operStatus)) { $script:IfStatusMap[$operStatus] } else { "unknown($operStatus)" }
            $prevName = if ($script:IfStatusMap.ContainsKey($prevOper)) { $script:IfStatusMap[$prevOper] } else { "unknown($prevOper)" }

            if ($operStatus -eq 2 -and $prevOper -eq 1) {
                # Port went DOWN
                $alerts += @{
                    device_ip  = $ip
                    oid        = "1.3.6.1.2.1.2.2.1.8.$idx"
                    value      = "Porta $portName DOWN su $name ($ip) - era $prevName, ora $statusName"
                    trap_type  = "linkDown"
                    severity   = "critical"
                    device_name = $name
                }
            } elseif ($operStatus -eq 1 -and $prevOper -eq 2) {
                # Port came UP
                $alerts += @{
                    device_ip  = $ip
                    oid        = "1.3.6.1.2.1.2.2.1.8.$idx"
                    value      = "Porta $portName UP su $name ($ip) - ripristinata"
                    trap_type  = "linkUp"
                    severity   = "low"
                    device_name = $name
                }
            }
        }

        $prevStates[$idx] = $operStatus
    }
    $script:PortStates[$ip] = $prevStates

    # 6. Extended metrics alerts (threshold-based)
    $extMetrics = Poll-ExtendedMetrics $ip $community
    if ($extMetrics.cpu_usage -ne $null -and $extMetrics.cpu_usage -gt 90) {
        $alerts += @{
            device_ip  = $ip
            oid        = "hpe.cpu.high"
            value      = "CPU al $($extMetrics.cpu_usage)% su $name ($ip)"
            trap_type  = "cpuHigh"
            severity   = "high"
            device_name = $name
        }
    }
    if ($extMetrics.memory_usage -ne $null -and $extMetrics.memory_usage -gt 90) {
        $alerts += @{
            device_ip  = $ip
            oid        = "hpe.memory.high"
            value      = "Memoria al $($extMetrics.memory_usage)% su $name ($ip)"
            trap_type  = "memoryHigh"
            severity   = "high"
            device_name = $name
        }
    }
    if ($extMetrics.temperature -ne $null -and $extMetrics.temperature -gt 75) {
        $alerts += @{
            device_ip  = $ip
            oid        = "hpe.temperature.high"
            value      = "Temperatura $($extMetrics.temperature)C su $name ($ip)"
            trap_type  = "temperatureHigh"
            severity   = "critical"
            device_name = $name
        }
    }
    # ILO hardware alerts
    if ($extMetrics.hardware.health_status -and $extMetrics.hardware.health_status -ne "ok" -and $extMetrics.hardware.health_status -ne "other") {
        $alerts += @{
            device_ip  = $ip
            oid        = "hpe.ilo.health"
            value      = "Stato salute ILO: $($extMetrics.hardware.health_status) su $name ($ip)"
            trap_type  = "healthDegraded"
            severity   = "critical"
            device_name = $name
        }
    }
    foreach ($disk in $extMetrics.hardware.disks) {
        if ($disk.status -ne "ok" -and $disk.status -ne "other") {
            $alerts += @{
                device_ip  = $ip
                oid        = "hpe.ilo.disk"
                value      = "Disco $($disk.name) in stato $($disk.status) su $name ($ip)"
                trap_type  = "diskFailure"
                severity   = "critical"
                device_name = $name
            }
        }
    }
    foreach ($fan in $extMetrics.hardware.fans) {
        if ($fan.condition -ne "ok" -and $fan.condition -ne "other") {
            $alerts += @{
                device_ip  = $ip
                oid        = "hpe.ilo.fan"
                value      = "Ventola $($fan.locale) in stato $($fan.condition) su $name ($ip)"
                trap_type  = "fanFailure"
                severity   = "high"
                device_name = $name
            }
        }
    }
    # Zyxel firewall-specific alerts
    if ($extMetrics.firewall) {
        $fw = $extMetrics.firewall
        if ($fw.active_sessions -ne $null -and $fw.active_sessions -gt 50000) {
            $alerts += @{
                device_ip  = $ip
                oid        = "zyxel.sessions.high"
                value      = "Sessioni attive: $($fw.active_sessions) su $name ($ip)"
                trap_type  = "sessionsHigh"
                severity   = "high"
                device_name = $name
            }
        }
        if ($fw.flash_usage -ne $null -and $fw.flash_usage -gt 90) {
            $alerts += @{
                device_ip  = $ip
                oid        = "zyxel.flash.high"
                value      = "Flash al $($fw.flash_usage)% su $name ($ip)"
                trap_type  = "flashHigh"
                severity   = "high"
                device_name = $name
            }
        }
    }

    return $alerts
}

function Poll-AllDevices($devices, $config) {
    $allAlerts = @()
    foreach ($dev in $devices) {
        $ip = $dev.ip
        $community = if ($dev.community) { $dev.community } else { "public" }
        $devName = if ($dev.name) { $dev.name } else { $ip }

        try {
            $alerts = Poll-Device $ip $community $devName
            $allAlerts += $alerts
        } catch {
            Write-Host "[SNMP Poll] Errore polling $devName ($ip): $($_.Exception.Message)"
        }
    }
    return $allAlerts
}


# ==================== REDFISH / iLO REST API ====================

function Poll-RedfishMetrics([string]$ip, [hashtable]$cred) {
    <#
    .SYNOPSIS
        Interroga un server HPE iLO tramite API Redfish (REST/HTTPS).
        Richiede credenziali (username/password) dal Vault.
    .DESCRIPTION
        Supporta iLO 4, 5 e 6. Estrae metriche profonde non disponibili via SNMP:
        - Power consumption (Watt)
        - BIOS version
        - Server model, serial number, UUID
        - Memory DIMM details (size, speed, status)
        - Storage controllers & logical drives
        - Network adapters
        - iLO firmware version
        - License type
    #>
    $result = @{
        redfish_ok = $false
        power_watts = $null
        bios_version = $null
        server_model = $null
        serial_number = $null
        uuid = $null
        ilo_firmware = $null
        ilo_license = $null
        memory_dimms = @()
        total_memory_gb = $null
        network_adapters = @()
        storage_controllers = @()
        error = $null
    }
    
    $username = $cred.username
    $password = $cred.password
    $portNum = 443
    if ($cred.port) { $portNum = $cred.port }
    $baseUrl = "https://${ip}:${portNum}"
    
    # Bypass SSL certificate validation (self-signed certs on iLO)
    try {
        if (-not ([System.Management.Automation.PSTypeName]'TrustAllCertsPolicy').Type) {
            Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) { return true; }
}
"@
        }
        [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    } catch {}
    
    # Basic Auth header
    $pair = "${username}:${password}"
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($pair)
    $base64 = [System.Convert]::ToBase64String($bytes)
    $headers = @{
        "Authorization" = "Basic $base64"
        "Content-Type" = "application/json"
        "OData-Version" = "4.0"
    }
    
    function Invoke-RedfishGet([string]$path) {
        try {
            $url = "${baseUrl}${path}"
            $response = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -TimeoutSec 10 -ErrorAction Stop
            return $response
        } catch {
            return $null
        }
    }
    
    try {
        # 1. System info (/redfish/v1/Systems/1/)
        $system = Invoke-RedfishGet "/redfish/v1/Systems/1/"
        if ($system) {
            $result.redfish_ok = $true
            $result.server_model = $system.Model
            $result.serial_number = $system.SerialNumber
            $result.uuid = $system.UUID
            $result.bios_version = $system.BiosVersion
            
            # Memory summary
            if ($system.MemorySummary) {
                $result.total_memory_gb = $system.MemorySummary.TotalSystemMemoryGiB
            }
        }
        
        # 2. Power info (/redfish/v1/Chassis/1/Power/)
        $power = Invoke-RedfishGet "/redfish/v1/Chassis/1/Power/"
        if ($power -and $power.PowerControl -and $power.PowerControl.Count -gt 0) {
            $pc = $power.PowerControl[0]
            $result.power_watts = $pc.PowerConsumedWatts
        }
        
        # 3. iLO firmware info (/redfish/v1/Managers/1/)
        $manager = Invoke-RedfishGet "/redfish/v1/Managers/1/"
        if ($manager) {
            $result.ilo_firmware = $manager.FirmwareVersion
            if ($manager.Oem -and $manager.Oem.Hpe -and $manager.Oem.Hpe.License) {
                $result.ilo_license = $manager.Oem.Hpe.License.LicenseString
            } elseif ($manager.Oem -and $manager.Oem.Hp -and $manager.Oem.Hp.License) {
                $result.ilo_license = $manager.Oem.Hp.License.LicenseString
            }
        }
        
        # 4. Memory DIMMs (/redfish/v1/Systems/1/Memory/)
        $memCollection = Invoke-RedfishGet "/redfish/v1/Systems/1/Memory/"
        if ($memCollection -and $memCollection.Members) {
            foreach ($memRef in $memCollection.Members) {
                $dimm = Invoke-RedfishGet $memRef.'@odata.id'
                if ($dimm -and $dimm.Status.State -eq "Enabled") {
                    $result.memory_dimms += @{
                        name = $dimm.DeviceLocator
                        size_gb = $dimm.CapacityMiB / 1024
                        speed_mhz = $dimm.OperatingSpeedMhz
                        type = $dimm.MemoryDeviceType
                        status = $dimm.Status.Health
                    }
                }
            }
        }
        
        # 5. Network Adapters (/redfish/v1/Systems/1/EthernetInterfaces/)
        $nics = Invoke-RedfishGet "/redfish/v1/Systems/1/EthernetInterfaces/"
        if ($nics -and $nics.Members) {
            foreach ($nicRef in $nics.Members) {
                $nic = Invoke-RedfishGet $nicRef.'@odata.id'
                if ($nic) {
                    $result.network_adapters += @{
                        name = $nic.Name
                        mac = $nic.MACAddress
                        speed_mbps = $nic.SpeedMbps
                        status = if ($nic.Status) { $nic.Status.Health } else { "N/A" }
                        ipv4 = if ($nic.IPv4Addresses -and $nic.IPv4Addresses.Count -gt 0) { $nic.IPv4Addresses[0].Address } else { $null }
                    }
                }
            }
        }
        
        # 6. Storage (/redfish/v1/Systems/1/SmartStorage/ArrayControllers/) - HPE specific
        $storage = Invoke-RedfishGet "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/"
        if (-not $storage) {
            # Try standard Redfish storage path
            $storage = Invoke-RedfishGet "/redfish/v1/Systems/1/Storage/"
        }
        if ($storage -and $storage.Members) {
            foreach ($ctrlRef in $storage.Members) {
                $ctrl = Invoke-RedfishGet $ctrlRef.'@odata.id'
                if ($ctrl) {
                    $ctrlInfo = @{
                        name = $ctrl.Model
                        status = if ($ctrl.Status) { $ctrl.Status.Health } else { "N/A" }
                        logical_drives = @()
                    }
                    # Try to get logical drives
                    $ldPath = $ctrlRef.'@odata.id' + "/LogicalDrives/"
                    $lds = Invoke-RedfishGet $ldPath
                    if ($lds -and $lds.Members) {
                        foreach ($ldRef in $lds.Members) {
                            $ld = Invoke-RedfishGet $ldRef.'@odata.id'
                            if ($ld) {
                                $ctrlInfo.logical_drives += @{
                                    name = $ld.LogicalDriveName
                                    capacity_gb = if ($ld.CapacityMiB) { [math]::Round($ld.CapacityMiB / 1024, 1) } else { $null }
                                    raid = $ld.Raid
                                    status = if ($ld.Status) { $ld.Status.Health } else { "N/A" }
                                }
                            }
                        }
                    }
                    $result.storage_controllers += $ctrlInfo
                }
            }
        }
        
    } catch {
        $result.error = $_.Exception.Message
    }
    
    return $result
}


# ==================== LLDP NEIGHBOR DISCOVERY ====================

<#
.SYNOPSIS
    Interroga la tabella LLDP-MIB di uno switch managed per ottenere i neighbor
    collegati porta-per-porta.
    
    OID base: 1.0.8802.1.1.2.1 (lldpMIB)
    - lldpLocPortId:     1.0.8802.1.1.2.1.3.7.1.3  (ID porta locale)
    - lldpLocPortDesc:   1.0.8802.1.1.2.1.3.7.1.4  (Descrizione porta locale)
    - lldpRemSysName:    1.0.8802.1.1.2.1.4.1.1.9  (Nome sistema remoto)
    - lldpRemPortId:     1.0.8802.1.1.2.1.4.1.1.7  (ID porta remota)
    - lldpRemPortDesc:   1.0.8802.1.1.2.1.4.1.1.8  (Descrizione porta remota)
    - lldpRemSysDesc:    1.0.8802.1.1.2.1.4.1.1.10 (Descrizione sistema remoto)
    - lldpRemChassisId:  1.0.8802.1.1.2.1.4.1.1.5  (Chassis ID remoto)
    - lldpRemManAddr:    1.0.8802.1.1.2.1.4.2.1.4  (Indirizzo management remoto)
    
    La tabella remota e' indicizzata per: timeMark.localPortNum.index
#>
function Poll-LldpNeighbors($ip, $community) {
    $neighbors = @()
    
    try {
        # Walk lldpRemSysName (1.0.8802.1.1.2.1.4.1.1.9)
        $sysNames = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.4.1.1.9"
        if (-not $sysNames -or $sysNames.Count -eq 0) {
            Write-Log "  LLDP: Nessun neighbor trovato su $ip (tabella vuota)" "DEBUG"
            return $neighbors
        }
        
        # Walk additional tables
        $portIds    = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.4.1.1.7"
        $portDescs  = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.4.1.1.8"
        $sysDescs   = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.4.1.1.10"
        $chassisIds = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.4.1.1.5"
        $manAddrs   = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.4.2.1.4"
        
        # Walk local port descriptions
        $locPortIds  = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.3.7.1.3"
        $locPortDesc = Walk-SnmpTable $ip $community "1.0.8802.1.1.2.1.3.7.1.4"
        
        # Build a lookup: local port number -> description
        $localPortMap = @{}
        if ($locPortIds) {
            foreach ($entry in $locPortIds) {
                # OID suffix is the port number
                $portNum = ($entry.oid -split '\.')[-1]
                $localPortMap[$portNum] = @{
                    id = $entry.value
                    desc = ""
                }
            }
        }
        if ($locPortDesc) {
            foreach ($entry in $locPortDesc) {
                $portNum = ($entry.oid -split '\.')[-1]
                if ($localPortMap.ContainsKey($portNum)) {
                    $localPortMap[$portNum].desc = $entry.value
                }
            }
        }
        
        # Parse sysNames entries — index pattern: .timeMark.localPortNum.remIndex
        foreach ($entry in $sysNames) {
            # Extract the 3-part index from the OID
            $baseSuffix = $entry.oid.Replace("1.0.8802.1.1.2.1.4.1.1.9.", "")
            $indexParts = $baseSuffix -split '\.'
            if ($indexParts.Count -lt 3) { continue }
            
            $timeMark = $indexParts[0]
            $localPortNum = $indexParts[1]
            $remIndex = $indexParts[2]
            $fullIndex = "$timeMark.$localPortNum.$remIndex"
            
            $remoteSysName = $entry.value
            $remotePortId = ""
            $remotePortDesc = ""
            $remoteSysDesc = ""
            $remoteChassisId = ""
            $remoteManAddr = ""
            
            # Look up corresponding entries by matching index suffix
            if ($portIds) {
                $match = $portIds | Where-Object { $_.oid.EndsWith(".$fullIndex") }
                if ($match) { $remotePortId = $match.value }
            }
            if ($portDescs) {
                $match = $portDescs | Where-Object { $_.oid.EndsWith(".$fullIndex") }
                if ($match) { $remotePortDesc = $match.value }
            }
            if ($sysDescs) {
                $match = $sysDescs | Where-Object { $_.oid.EndsWith(".$fullIndex") }
                if ($match) { $remoteSysDesc = $match.value }
            }
            if ($chassisIds) {
                $match = $chassisIds | Where-Object { $_.oid.EndsWith(".$fullIndex") }
                if ($match) { $remoteChassisId = $match.value }
            }
            
            # Try to extract management IP from lldpRemManAddr
            # The OID index for manAddr table is different: timeMark.localPortNum.remIndex.addrSubtype.addr
            if ($manAddrs) {
                $prefix = ".$timeMark.$localPortNum.$remIndex."
                $addrMatch = $manAddrs | Where-Object { $_.oid -match [regex]::Escape($prefix) } | Select-Object -First 1
                if ($addrMatch) {
                    # Try to extract IPv4 from OID suffix (subtype=1, then 4 octets)
                    $addrSuffix = $addrMatch.oid.Substring($addrMatch.oid.IndexOf($prefix) + $prefix.Length)
                    $addrParts = $addrSuffix -split '\.'
                    if ($addrParts.Count -ge 5 -and $addrParts[0] -eq "1") {
                        # IPv4 address
                        $remoteManAddr = "$($addrParts[1]).$($addrParts[2]).$($addrParts[3]).$($addrParts[4])"
                    }
                }
            }
            
            # Get local port info
            $localPortId = ""
            $localPortDesc = ""
            if ($localPortMap.ContainsKey($localPortNum)) {
                $localPortId = $localPortMap[$localPortNum].id
                $localPortDesc = $localPortMap[$localPortNum].desc
            }
            
            $neighbor = @{
                local_ip = $ip
                local_port_num = [int]$localPortNum
                local_port_id = "$localPortId"
                local_port_desc = "$localPortDesc"
                remote_sys_name = "$remoteSysName"
                remote_port_id = "$remotePortId"
                remote_port_desc = "$remotePortDesc"
                remote_sys_desc = "$remoteSysDesc"
                remote_chassis_id = "$remoteChassisId"
                remote_ip = "$remoteManAddr"
            }
            
            $neighbors += $neighbor
            Write-Log "  LLDP: $ip porta $localPortNum -> $remoteSysName ($remoteManAddr) porta $remotePortId" "INFO"
        }
        
        Write-Log "  LLDP: $($neighbors.Count) neighbor trovati su $ip" "INFO"
        
    } catch {
        Write-Log "  LLDP: Errore polling $ip - $($_.Exception.Message)" "WARN"
    }
    
    return $neighbors
}

<#
.SYNOPSIS
    Esegue il discovery LLDP su tutti i dispositivi SNMP managed e invia i risultati al NOC.
    Viene chiamata dal main loop del connettore.
#>
function Run-LldpDiscovery($config, $devices) {
    $allNeighbors = @()
    
    foreach ($dev in $devices) {
        if ($dev.monitor_type -ne "snmp") { continue }
        
        $ip = $dev.ip
        $community = if ($dev.community) { $dev.community } else { "public" }
        
        Write-Log "LLDP Discovery su $($dev.name) ($ip)..."
        $neighbors = Poll-LldpNeighbors $ip $community
        
        if ($neighbors -and $neighbors.Count -gt 0) {
            $allNeighbors += $neighbors
        }
    }
    
    if ($allNeighbors.Count -gt 0) {
        $payload = @{
            neighbors = $allNeighbors
        }
        Send-ToNOC $config "connector/lldp-neighbors" $payload | Out-Null
        Write-Log "LLDP: $($allNeighbors.Count) neighbor totali inviati al NOC" "INFO"
    } else {
        Write-Log "LLDP: Nessun neighbor LLDP trovato su nessun dispositivo" "INFO"
    }
}


# ==================== MAC ADDRESS TABLE + PORT SPEED DISCOVERY ====================

<#
.SYNOPSIS
    Interroga la tabella MAC address (Bridge-MIB) di uno switch per scoprire
    quali dispositivi sono collegati a quale porta.
    
    OID: 1.3.6.1.2.1.17.4.3.1.1 (dot1dTpFdbAddress - MAC address)
    OID: 1.3.6.1.2.1.17.4.3.1.2 (dot1dTpFdbPort - porta su cui il MAC e' visto)
    OID: 1.3.6.1.2.1.2.2.1.6    (ifPhysAddress - MAC dell'interfaccia dello switch)
    OID: 1.3.6.1.2.1.2.2.1.5    (ifSpeed - velocita' interfaccia in bps)
    OID: 1.3.6.1.2.1.31.1.1.1.15 (ifHighSpeed - velocita' in Mbps per 10G+)
    
    Confrontando la MAC table con la ARP table e gli indirizzi delle interfacce
    degli altri switch, possiamo ricostruire le connessioni fisiche.
#>
function Poll-MacTable($ip, $community) {
    $macEntries = @()
    
    try {
        # Walk dot1dTpFdbPort (MAC -> bridge port number)
        $fdbPorts = Walk-SnmpTable $ip $community "1.3.6.1.2.1.17.4.3.1.2"
        if (-not $fdbPorts -or $fdbPorts.Count -eq 0) { return $macEntries }
        
        # Walk dot1dTpFdbAddress (MAC address in tabella)
        $fdbAddrs = Walk-SnmpTable $ip $community "1.3.6.1.2.1.17.4.3.1.1"
        
        foreach ($entry in $fdbPorts) {
            $portNum = $entry.value
            # Estrai il MAC dall'OID suffix (6 ottetti decimali)
            $suffix = $entry.oid.Replace("1.3.6.1.2.1.17.4.3.1.2.", "")
            $macOctets = $suffix -split '\.'
            if ($macOctets.Count -eq 6) {
                $mac = ($macOctets | ForEach-Object { "{0:X2}" -f [int]$_ }) -join ":"
                $macEntries += @{
                    mac = $mac
                    port = [int]$portNum
                }
            }
        }
        
        Write-Log "  MAC Table: $($macEntries.Count) entries su $ip" "DEBUG"
    } catch {
        Write-Log "  MAC Table: Errore polling ${ip}: $($_.Exception.Message)" "WARN"
    }
    
    return $macEntries
}

function Poll-InterfaceMacs($ip, $community) {
    $ifMacs = @{}
    
    try {
        # Walk ifPhysAddress (MAC dell'interfaccia di ogni porta dello switch)
        $results = Walk-SnmpTable $ip $community "1.3.6.1.2.1.2.2.1.6"
        foreach ($entry in $results) {
            $ifIndex = ($entry.oid -split '\.')[-1]
            $rawMac = $entry.value
            if ($rawMac -and $rawMac.Length -ge 12) {
                # Prova a parsare come hex string
                $mac = ""
                if ($rawMac -match '^[0-9A-Fa-f:.\-]+$') {
                    $mac = ($rawMac -replace '[:\.\-]','').ToUpper()
                    if ($mac.Length -eq 12) {
                        $mac = ($mac -replace '(.{2})','$1:').TrimEnd(':')
                    }
                }
                if ($mac) { $ifMacs[$ifIndex] = $mac }
            }
        }
    } catch {
        Write-Log "  InterfaceMACs: Errore ${ip}: $($_.Exception.Message)" "WARN"
    }
    
    return $ifMacs
}

function Poll-PortSpeeds($ip, $community) {
    $speeds = @{}
    
    try {
        # Walk ifHighSpeed (Mbps - per porte 10G+)
        $results = Walk-SnmpTable $ip $community "1.3.6.1.2.1.31.1.1.1.15"
        foreach ($entry in $results) {
            $ifIndex = ($entry.oid -split '\.')[-1]
            $speedMbps = [int]$entry.value
            if ($speedMbps -gt 0) {
                $speeds[$ifIndex] = $speedMbps
            }
        }
        
        # Se non abbiamo ifHighSpeed, usa ifSpeed (bps)
        if ($speeds.Count -eq 0) {
            $results = Walk-SnmpTable $ip $community "1.3.6.1.2.1.2.2.1.5"
            foreach ($entry in $results) {
                $ifIndex = ($entry.oid -split '\.')[-1]
                $speedBps = [long]$entry.value
                if ($speedBps -gt 0) {
                    $speeds[$ifIndex] = [int]($speedBps / 1000000)
                }
            }
        }
    } catch {
        Write-Log "  PortSpeeds: Errore ${ip}: $($_.Exception.Message)" "WARN"
    }
    
    return $speeds
}

<#
.SYNOPSIS
    Esegue il discovery completo della rete:
    1. LLDP neighbors (connessioni dirette porta-per-porta)
    2. MAC address table (quali dispositivi su quale porta)
    3. Port speeds (identifica uplink 10G)
    4. Interface MACs (identifica i MAC di ogni switch per cross-reference)
    
    Combina tutti i dati per ricostruire la topologia fisica reale.
#>
function Run-FullDiscovery($config, $devices) {
    $allNeighbors = @()
    $allMacTables = @()
    $allPortSpeeds = @()
    $deviceMacs = @()  # MAC di ogni dispositivo managed
    
    foreach ($dev in $devices) {
        if ($dev.monitor_type -ne "snmp") { continue }
        
        $ip = $dev.ip
        $community = if ($dev.community) { $dev.community } else { "public" }
        
        Write-Log "Discovery su $($dev.name) ($ip)..."
        
        # 1. LLDP
        $neighbors = Poll-LldpNeighbors $ip $community
        if ($neighbors -and $neighbors.Count -gt 0) {
            $allNeighbors += $neighbors
        }
        
        # 2. MAC Table (solo per switch)
        $macTable = Poll-MacTable $ip $community
        if ($macTable -and $macTable.Count -gt 0) {
            $allMacTables += @{
                switch_ip = $ip
                entries = $macTable
            }
        }
        
        # 3. Port Speeds
        $portSpeeds = Poll-PortSpeeds $ip $community
        if ($portSpeeds -and $portSpeeds.Count -gt 0) {
            $highSpeedPorts = @()
            foreach ($key in $portSpeeds.Keys) {
                $speed = $portSpeeds[$key]
                if ($speed -ge 1000) {  # 1Gbps+
                    $highSpeedPorts += @{ port = $key; speed_mbps = $speed }
                }
            }
            if ($highSpeedPorts.Count -gt 0) {
                $allPortSpeeds += @{
                    switch_ip = $ip
                    high_speed_ports = $highSpeedPorts
                }
            }
        }
        
        # 4. Interface MACs dello switch
        $ifMacs = Poll-InterfaceMacs $ip $community
        if ($ifMacs -and $ifMacs.Count -gt 0) {
            $macList = @()
            foreach ($key in $ifMacs.Keys) {
                $macList += $ifMacs[$key]
            }
            $deviceMacs += @{
                ip = $ip
                name = $dev.name
                macs = $macList
            }
        }
    }
    
    # Invia dati LLDP
    if ($allNeighbors.Count -gt 0) {
        Send-ToNOC $config "connector/lldp-neighbors" @{ neighbors = $allNeighbors } | Out-Null
        Write-Log "Discovery: $($allNeighbors.Count) LLDP neighbors inviati" "INFO"
    }
    
    # Invia dati MAC/Speed per la ricostruzione topologica
    $discoveryPayload = @{
        mac_tables = $allMacTables
        port_speeds = $allPortSpeeds
        device_macs = $deviceMacs
    }
    Send-ToNOC $config "connector/network-discovery" $discoveryPayload | Out-Null
    Write-Log "Discovery: $($allMacTables.Count) MAC tables, $($allPortSpeeds.Count) port speed reports inviati" "INFO"
}
