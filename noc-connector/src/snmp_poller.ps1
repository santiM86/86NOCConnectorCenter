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

# OID definitions
$script:OID_sysDescr    = "1.3.6.1.2.1.1.1.0"
$script:OID_sysUpTime   = "1.3.6.1.2.1.1.3.0"
$script:OID_sysName     = "1.3.6.1.2.1.1.5.0"
$script:OID_ifDescr     = "1.3.6.1.2.1.2.2.1.2"
$script:OID_ifAdminStat = "1.3.6.1.2.1.2.2.1.7"
$script:OID_ifOperStat  = "1.3.6.1.2.1.2.2.1.8"
$script:OID_ifInErrors  = "1.3.6.1.2.1.2.2.1.14"
$script:OID_ifOutErrors = "1.3.6.1.2.1.2.2.1.20"

# Port status memory per device
$script:PortStates = @{}
$script:DeviceUp = @{}

$script:IfStatusMap = @{
    1 = "up"
    2 = "down"
    3 = "testing"
    4 = "unknown"
    5 = "dormant"
    6 = "notPresent"
    7 = "lowerLayerDown"
}

function Poll-Device([string]$ip, [string]$community, [string]$name) {
    $alerts = @()

    # 1. Check reachability
    $sysDescr = Get-SnmpValue $ip $community $script:OID_sysDescr
    if (-not $sysDescr) {
        # Device unreachable
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
