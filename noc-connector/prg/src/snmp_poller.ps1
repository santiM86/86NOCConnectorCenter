<#
.SYNOPSIS
    86NocConnector - SNMP v1/v2c/v3 Poller
.DESCRIPTION
    Client SNMP nativo per polling attivo di switch e dispositivi di rete.
    Usa raw UDP sockets con encoding BER/ASN.1 - ZERO dipendenze esterne.
    
    Supporta:
    - SNMP v1/v2c (community string)
    - SNMP v3 (USM: noAuthNoPriv, authNoPriv, authPriv)
      - Auth: MD5, SHA
      - Privacy: DES, AES128
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

# ==================== SNMP v3 USM ENGINE ====================

$script:SnmpV3MsgId = 1
$script:EngineCache = @{}  # IP -> @{ engine_id, boots, time }

function Get-HMACMD5([byte[]]$key, [byte[]]$data) {
    $hmac = New-Object System.Security.Cryptography.HMACMD5
    $hmac.Key = $key
    return $hmac.ComputeHash($data)
}

function Get-HMACSHA1([byte[]]$key, [byte[]]$data) {
    $hmac = New-Object System.Security.Cryptography.HMACSHA1
    $hmac.Key = $key
    return $hmac.ComputeHash($data)
}

function Get-MD5Hash([byte[]]$data) {
    $md5 = [System.Security.Cryptography.MD5]::Create()
    return $md5.ComputeHash($data)
}

function Get-SHA1Hash([byte[]]$data) {
    $sha = [System.Security.Cryptography.SHA1]::Create()
    return $sha.ComputeHash($data)
}

function Get-PasswordToKey([string]$password, [byte[]]$engineId, [string]$authProto = "MD5") {
    <#
    .SYNOPSIS
        RFC 3414 password-to-key localization.
        Expands password to 1MB, hashes, then localizes with engineId.
    #>
    $pwBytes = [System.Text.Encoding]::UTF8.GetBytes($password)
    if ($pwBytes.Length -eq 0) { return [byte[]]::new(0) }
    
    # Step 1: Generate Ku (master key) - hash 1MB of repeated password
    $count = 1048576  # 1 MB
    $buf = [byte[]]::new(64)
    $pwLen = $pwBytes.Length
    
    if ($authProto -eq "SHA") {
        $hasher = [System.Security.Cryptography.SHA1]::Create()
    } else {
        $hasher = [System.Security.Cryptography.MD5]::Create()
    }
    
    $hashStream = New-Object System.IO.MemoryStream
    $written = 0
    while ($written -lt $count) {
        $idx = 0
        for ($i = 0; $i -lt 64; $i++) {
            $buf[$i] = $pwBytes[$idx % $pwLen]
            $idx++
        }
        $hashStream.Write($buf, 0, 64)
        $written += 64
    }
    $hashStream.Position = 0
    $ku = $hasher.ComputeHash($hashStream)
    $hashStream.Dispose()
    
    # Step 2: Localize Ku with engineId -> Kul
    $localInput = [System.Collections.Generic.List[byte]]::new()
    $localInput.AddRange($ku)
    $localInput.AddRange($engineId)
    $localInput.AddRange($ku)
    $kul = $hasher.ComputeHash($localInput.ToArray())
    $hasher.Dispose()
    
    return $kul
}

function Encrypt-SnmpV3DES([byte[]]$data, [byte[]]$privKey, [byte[]]$engineBoots, [byte[]]$salt) {
    <#
    .SYNOPSIS
        DES-CBC encryption per SNMP v3 privacy (RFC 3414).
    #>
    # DES key is first 8 bytes of privKey
    $desKey = $privKey[0..7]
    
    # IV = pre-IV XOR salt (pre-IV = privKey bytes 8-15)
    $preIV = $privKey[8..15]
    $iv = [byte[]]::new(8)
    for ($i = 0; $i -lt 8; $i++) {
        $iv[$i] = $preIV[$i] -bxor $salt[$i]
    }
    
    # Pad data to 8-byte boundary
    $padLen = 8 - ($data.Length % 8)
    if ($padLen -eq 8) { $padLen = 0 }
    $padded = [byte[]]::new($data.Length + $padLen)
    [Array]::Copy($data, $padded, $data.Length)
    
    $des = [System.Security.Cryptography.DESCryptoServiceProvider]::new()
    $des.Mode = [System.Security.Cryptography.CipherMode]::CBC
    $des.Padding = [System.Security.Cryptography.PaddingMode]::None
    $des.Key = $desKey
    $des.IV = $iv
    $enc = $des.CreateEncryptor()
    $result = $enc.TransformFinalBlock($padded, 0, $padded.Length)
    $des.Dispose()
    return $result
}

function Decrypt-SnmpV3DES([byte[]]$data, [byte[]]$privKey, [byte[]]$salt) {
    $desKey = $privKey[0..7]
    $preIV = $privKey[8..15]
    $iv = [byte[]]::new(8)
    for ($i = 0; $i -lt 8; $i++) {
        $iv[$i] = $preIV[$i] -bxor $salt[$i]
    }
    $des = [System.Security.Cryptography.DESCryptoServiceProvider]::new()
    $des.Mode = [System.Security.Cryptography.CipherMode]::CBC
    $des.Padding = [System.Security.Cryptography.PaddingMode]::None
    $des.Key = $desKey
    $des.IV = $iv
    $dec = $des.CreateDecryptor()
    $result = $dec.TransformFinalBlock($data, 0, $data.Length)
    $des.Dispose()
    return $result
}

function Encrypt-SnmpV3AES([byte[]]$data, [byte[]]$privKey, [int]$engineBoots, [int]$engineTime, [byte[]]$salt) {
    <#
    .SYNOPSIS
        AES-128-CFB encryption per SNMP v3 privacy (RFC 3826).
    #>
    $aesKey = $privKey[0..15]
    
    # IV = engineBoots (4 bytes BE) + engineTime (4 bytes BE) + salt (8 bytes)
    $iv = [byte[]]::new(16)
    $iv[0] = [byte](($engineBoots -shr 24) -band 0xFF)
    $iv[1] = [byte](($engineBoots -shr 16) -band 0xFF)
    $iv[2] = [byte](($engineBoots -shr 8) -band 0xFF)
    $iv[3] = [byte]($engineBoots -band 0xFF)
    $iv[4] = [byte](($engineTime -shr 24) -band 0xFF)
    $iv[5] = [byte](($engineTime -shr 16) -band 0xFF)
    $iv[6] = [byte](($engineTime -shr 8) -band 0xFF)
    $iv[7] = [byte]($engineTime -band 0xFF)
    [Array]::Copy($salt, 0, $iv, 8, 8)
    
    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = [System.Security.Cryptography.CipherMode]::CFB
    $aes.FeedbackSize = 128
    $aes.Padding = [System.Security.Cryptography.PaddingMode]::None
    $aes.Key = $aesKey
    $aes.IV = $iv
    
    # Pad to 16-byte boundary for AES
    $padLen = 16 - ($data.Length % 16)
    if ($padLen -eq 16) { $padLen = 0 }
    $padded = [byte[]]::new($data.Length + $padLen)
    [Array]::Copy($data, $padded, $data.Length)
    
    $enc = $aes.CreateEncryptor()
    $result = $enc.TransformFinalBlock($padded, 0, $padded.Length)
    $aes.Dispose()
    return $result
}

function Build-SnmpV3EngineDiscovery {
    <#
    .SYNOPSIS
        Builds an SNMP v3 engine discovery message (empty user, no auth).
    #>
    $script:SnmpV3MsgId++
    
    # msgVersion = 3
    $version = ConvertTo-BerInteger 3
    
    # msgGlobalData: SEQUENCE { msgID, msgMaxSize, msgFlags, msgSecurityModel }
    $msgId = ConvertTo-BerInteger $script:SnmpV3MsgId
    $msgMaxSize = ConvertTo-BerInteger 65507
    $msgFlags = ConvertTo-BerOctetString ([char]0x04)  # reportable, noAuth, noPriv
    # Fix: msgFlags is a single-byte octet string
    $msgFlagsRaw = [byte[]]@(0x04, 0x01, 0x04)  # OCTET STRING, len 1, value 0x04 (reportable)
    $msgSecModel = ConvertTo-BerInteger 3  # USM
    $globalData = ConvertTo-BerSequence ([byte[]]($msgId + $msgMaxSize + $msgFlagsRaw + $msgSecModel))
    
    # USM Security Parameters (empty for discovery)
    $usmEngineId = ConvertTo-BerOctetString ""
    $usmBoots = ConvertTo-BerInteger 0
    $usmTime = ConvertTo-BerInteger 0
    $usmUser = ConvertTo-BerOctetString ""
    $usmAuthParams = ConvertTo-BerOctetString ""
    $usmPrivParams = ConvertTo-BerOctetString ""
    $usmSeq = ConvertTo-BerSequence ([byte[]]($usmEngineId + $usmBoots + $usmTime + $usmUser + $usmAuthParams + $usmPrivParams))
    $secParams = ConvertTo-BerOctetString ""
    # Wrap USM sequence as an OCTET STRING
    $usmLen = ConvertTo-BerLength $usmSeq.Length
    $secParamsBytes = [System.Collections.Generic.List[byte]]::new()
    $secParamsBytes.Add(0x04)
    $secParamsBytes.AddRange($usmLen)
    $secParamsBytes.AddRange($usmSeq)
    
    # ScopedPDU: contextEngineID="" contextName="" GET PDU (empty varbind)
    $ctxEngineId = ConvertTo-BerOctetString ""
    $ctxName = ConvertTo-BerOctetString ""
    # Empty GET request
    $reqId = ConvertTo-BerInteger $script:SnmpV3MsgId
    $errStat = ConvertTo-BerInteger 0
    $errIdx = ConvertTo-BerInteger 0
    $varbindList = ConvertTo-BerSequence ([byte[]]@())
    $pduContent = [byte[]]($reqId + $errStat + $errIdx + $varbindList)
    $pdu = [System.Collections.Generic.List[byte]]::new()
    $pdu.Add(0xA0)  # GET
    $pdu.AddRange((ConvertTo-BerLength $pduContent.Length))
    $pdu.AddRange($pduContent)
    $scopedPdu = ConvertTo-BerSequence ([byte[]]($ctxEngineId + $ctxName + $pdu.ToArray()))
    
    # Build message
    $msgContent = [byte[]]($version + $globalData + $secParamsBytes.ToArray() + $scopedPdu)
    return ConvertTo-BerSequence $msgContent
}

function Parse-SnmpV3Response([byte[]]$data) {
    <#
    .SYNOPSIS
        Parsa una risposta SNMPv3 e restituisce engineId, boots, time e i varbind.
    #>
    $result = @{
        engine_id = [byte[]]@()
        engine_boots = 0
        engine_time = 0
        varbinds = @{}
        error = $null
    }
    
    try {
        $off = [ref]0
        # Outer SEQUENCE
        if ($data[$off.Value] -ne 0x30) { $result.error = "Not a SEQUENCE"; return $result }
        $off.Value++; $null = Read-BerLength $data $off
        
        # Version
        $off.Value++; $vLen = Read-BerLength $data $off
        $version = Read-BerInteger $data $off.Value $vLen
        $off.Value += $vLen
        
        # HeaderData SEQUENCE
        if ($data[$off.Value] -ne 0x30) { $result.error = "Expected HeaderData SEQUENCE"; return $result }
        $off.Value++; $hLen = Read-BerLength $data $off
        $hEnd = $off.Value + $hLen
        $off.Value = $hEnd  # Skip header for now
        
        # Security Parameters OCTET STRING (contains USM SEQUENCE)
        if ($data[$off.Value] -ne 0x04) { $result.error = "Expected secParams OCTET STRING"; return $result }
        $off.Value++; $spLen = Read-BerLength $data $off
        $spStart = $off.Value
        
        # Parse USM SEQUENCE inside
        if ($data[$off.Value] -ne 0x30) { $off.Value = $spStart + $spLen } else {
            $off.Value++; $null = Read-BerLength $data $off
            
            # Engine ID (OCTET STRING)
            if ($data[$off.Value] -eq 0x04) {
                $off.Value++; $eidLen = Read-BerLength $data $off
                if ($eidLen -gt 0) {
                    $result.engine_id = $data[$off.Value..($off.Value + $eidLen - 1)]
                }
                $off.Value += $eidLen
            }
            # Engine Boots (INTEGER)
            if ($data[$off.Value] -eq 0x02) {
                $off.Value++; $bLen = Read-BerLength $data $off
                $result.engine_boots = Read-BerInteger $data $off.Value $bLen
                $off.Value += $bLen
            }
            # Engine Time (INTEGER)
            if ($data[$off.Value] -eq 0x02) {
                $off.Value++; $tLen = Read-BerLength $data $off
                $result.engine_time = Read-BerInteger $data $off.Value $tLen
                $off.Value += $tLen
            }
        }
        $off.Value = $spStart + $spLen
        
        # ScopedPDU (may be SEQUENCE or encrypted OCTET STRING)
        if ($data[$off.Value] -eq 0x30) {
            # Unencrypted scopedPDU
            $off.Value++; $null = Read-BerLength $data $off
            # contextEngineID
            if ($data[$off.Value] -eq 0x04) { $off.Value++; $cLen = Read-BerLength $data $off; $off.Value += $cLen }
            # contextName
            if ($data[$off.Value] -eq 0x04) { $off.Value++; $cLen = Read-BerLength $data $off; $off.Value += $cLen }
            # PDU (GetResponse = 0xA2, Report = 0xA8)
            $pduTag = $data[$off.Value]
            if ($pduTag -eq 0xA2 -or $pduTag -eq 0xA8) {
                $off.Value++; $null = Read-BerLength $data $off
                # Request ID
                $off.Value++; $ridLen = Read-BerLength $data $off; $off.Value += $ridLen
                # Error Status
                $off.Value++; $esLen = Read-BerLength $data $off; $off.Value += $esLen
                # Error Index
                $off.Value++; $eiLen = Read-BerLength $data $off; $off.Value += $eiLen
                # Varbind list
                if ($off.Value -lt $data.Length -and $data[$off.Value] -eq 0x30) {
                    $off.Value++; $null = Read-BerLength $data $off
                    while ($off.Value -lt $data.Length - 2) {
                        if ($data[$off.Value] -ne 0x30) { break }
                        $off.Value++; $vbLen = Read-BerLength $data $off
                        $vbEnd = $off.Value + $vbLen
                        if ($data[$off.Value] -eq 0x06) {
                            $off.Value++; $oidLen = Read-BerLength $data $off
                            $oid = Read-BerOID $data $off.Value $oidLen
                            $off.Value += $oidLen
                            $valTag = $data[$off.Value]; $off.Value++
                            $valLen = Read-BerLength $data $off
                            $valStart = $off.Value
                            switch ($valTag) {
                                0x02 { $result.varbinds[$oid] = Read-BerInteger $data $valStart $valLen }
                                0x04 { $result.varbinds[$oid] = [System.Text.Encoding]::UTF8.GetString($data, $valStart, $valLen) }
                                0x41 { $result.varbinds[$oid] = Read-BerInteger $data $valStart $valLen }
                                0x42 { $result.varbinds[$oid] = Read-BerInteger $data $valStart $valLen }
                                0x43 { $result.varbinds[$oid] = Read-BerInteger $data $valStart $valLen }
                                0x06 { $result.varbinds[$oid] = Read-BerOID $data $valStart $valLen }
                                default {
                                    if ($valLen -gt 0) { $result.varbinds[$oid] = [System.Text.Encoding]::UTF8.GetString($data, $valStart, [Math]::Min($valLen, $data.Length - $valStart)) }
                                }
                            }
                        }
                        $off.Value = $vbEnd
                    }
                }
            }
        }
    } catch {
        $result.error = $_.Exception.Message
    }
    return $result
}

function Discover-SnmpV3Engine([string]$target, [int]$port = 161) {
    <#
    .SYNOPSIS
        Esegue engine discovery SNMPv3 per ottenere engineId, boots e time.
    #>
    if ($script:EngineCache.ContainsKey($target)) {
        return $script:EngineCache[$target]
    }
    
    $packet = Build-SnmpV3EngineDiscovery
    try {
        $udp = New-Object System.Net.Sockets.UdpClient
        $udp.Client.ReceiveTimeout = 4000
        $ep = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse($target), $port)
        $null = $udp.Send($packet, $packet.Length, $ep)
        $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
        $response = $udp.Receive([ref]$remoteEP)
        $udp.Close()
        
        $parsed = Parse-SnmpV3Response $response
        if ($parsed.engine_id -and $parsed.engine_id.Length -gt 0) {
            $engineInfo = @{
                engine_id = $parsed.engine_id
                boots = [int]$parsed.engine_boots
                time = [int]$parsed.engine_time
            }
            $script:EngineCache[$target] = $engineInfo
            return $engineInfo
        }
    } catch {
        if ($udp) { $udp.Close() }
    }
    return $null
}

function Send-SnmpV3Get([string]$target, [hashtable]$v3cred, [string]$oid, [int]$port = 161, [bool]$getNext = $false) {
    <#
    .SYNOPSIS
        Invia una richiesta SNMP v3 GET o GET-NEXT con autenticazione e privacy opzionali.
    .PARAMETER v3cred
        @{ username; auth_protocol (MD5/SHA); auth_password; priv_protocol (DES/AES); priv_password; security_level (noAuthNoPriv/authNoPriv/authPriv) }
    #>
    # 1. Engine discovery
    $engine = Discover-SnmpV3Engine $target $port
    if (-not $engine) {
        Write-Host "[SNMPv3] Engine discovery fallito per $target"
        return $null
    }
    
    $script:SnmpV3MsgId++
    $secLevel = $v3cred.security_level
    $useAuth = $secLevel -in @("authNoPriv", "authPriv")
    $usePriv = $secLevel -eq "authPriv"
    
    # msgFlags byte: bit0=auth, bit1=priv, bit2=reportable
    $flagByte = 0x04  # reportable
    if ($useAuth) { $flagByte = $flagByte -bor 0x01 }
    if ($usePriv) { $flagByte = $flagByte -bor 0x02 }
    
    # Derive keys
    $authKey = $null
    $privKey = $null
    if ($useAuth -and $v3cred.auth_password) {
        $authKey = Get-PasswordToKey $v3cred.auth_password $engine.engine_id $v3cred.auth_protocol
    }
    if ($usePriv -and $v3cred.priv_password) {
        $privKey = Get-PasswordToKey $v3cred.priv_password $engine.engine_id $v3cred.auth_protocol
    }
    
    # Build PDU
    $oidBytes = ConvertTo-BerOID $oid
    $nullBytes = ConvertTo-BerNull
    $varbind = ConvertTo-BerSequence ([byte[]]($oidBytes + $nullBytes))
    $varbindList = ConvertTo-BerSequence $varbind
    $reqId = ConvertTo-BerInteger $script:SnmpV3MsgId
    $errStat = ConvertTo-BerInteger 0
    $errIdx = ConvertTo-BerInteger 0
    $pduContent = [byte[]]($reqId + $errStat + $errIdx + $varbindList)
    $pduTag = if ($getNext) { [byte]0xA1 } else { [byte]0xA0 }
    $pdu = [System.Collections.Generic.List[byte]]::new()
    $pdu.Add($pduTag)
    $pdu.AddRange((ConvertTo-BerLength $pduContent.Length))
    $pdu.AddRange($pduContent)
    
    # Build ScopedPDU
    $eidOctet = [byte[]]@(0x04) + (ConvertTo-BerLength $engine.engine_id.Length) + $engine.engine_id
    $ctxName = ConvertTo-BerOctetString ""
    $scopedPdu = ConvertTo-BerSequence ([byte[]]($eidOctet + $ctxName + $pdu.ToArray()))
    
    # Generate salt for privacy
    $salt = [byte[]]::new(8)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($salt)
    
    # Encrypt ScopedPDU if needed
    $scopedPduFinal = $scopedPdu
    if ($usePriv -and $privKey) {
        $encrypted = $null
        if ($v3cred.priv_protocol -eq "AES") {
            $encrypted = Encrypt-SnmpV3AES $scopedPdu $privKey $engine.boots $engine.time $salt
        } else {
            $encrypted = Encrypt-SnmpV3DES $scopedPdu $privKey $engine.boots $salt
        }
        # Wrap encrypted data as OCTET STRING
        $encLen = ConvertTo-BerLength $encrypted.Length
        $scopedPduFinal = [System.Collections.Generic.List[byte]]::new()
        $scopedPduFinal.Add(0x04)
        $scopedPduFinal.AddRange($encLen)
        $scopedPduFinal.AddRange($encrypted)
        $scopedPduFinal = [byte[]]$scopedPduFinal.ToArray()
    }
    
    # Build USM Security Parameters
    $usmEngineId = [byte[]]@(0x04) + (ConvertTo-BerLength $engine.engine_id.Length) + $engine.engine_id
    $usmBoots = ConvertTo-BerInteger $engine.boots
    $usmTime = ConvertTo-BerInteger $engine.time
    $userBytes = [System.Text.Encoding]::UTF8.GetBytes($v3cred.username)
    $usmUser = [byte[]]@(0x04) + (ConvertTo-BerLength $userBytes.Length) + $userBytes
    
    # Auth params placeholder (12 zero bytes for HMAC, filled after signing)
    $authPlaceholder = if ($useAuth) { [byte[]]@(0x04, 0x0C) + [byte[]]::new(12) } else { [byte[]]@(0x04, 0x00) }
    
    # Privacy params
    $privParams = if ($usePriv) { [byte[]]@(0x04, 0x08) + $salt } else { [byte[]]@(0x04, 0x00) }
    
    $usmSeq = ConvertTo-BerSequence ([byte[]]($usmEngineId + $usmBoots + $usmTime + $usmUser + $authPlaceholder + $privParams))
    $secParamsLen = ConvertTo-BerLength $usmSeq.Length
    $secParamsBytes = [byte[]]@(0x04) + $secParamsLen + $usmSeq
    
    # Build header
    $version = ConvertTo-BerInteger 3
    $msgId = ConvertTo-BerInteger $script:SnmpV3MsgId
    $msgMaxSize = ConvertTo-BerInteger 65507
    $msgFlags = [byte[]]@(0x04, 0x01, $flagByte)
    $msgSecModel = ConvertTo-BerInteger 3
    $globalData = ConvertTo-BerSequence ([byte[]]($msgId + $msgMaxSize + $msgFlags + $msgSecModel))
    
    # Assemble full message
    $msgContent = [byte[]]($version + $globalData + $secParamsBytes + $scopedPduFinal)
    $fullMsg = ConvertTo-BerSequence $msgContent
    
    # Sign if auth enabled
    if ($useAuth -and $authKey) {
        # Find auth params placeholder position (12 zero bytes after 0x04 0x0C)
        $authOffset = -1
        for ($i = 0; $i -lt $fullMsg.Length - 13; $i++) {
            if ($fullMsg[$i] -eq 0x04 -and $fullMsg[$i+1] -eq 0x0C) {
                $allZero = $true
                for ($j = 2; $j -lt 14; $j++) {
                    if ($fullMsg[$i+$j] -ne 0) { $allZero = $false; break }
                }
                if ($allZero) { $authOffset = $i + 2; break }
            }
        }
        
        if ($authOffset -gt 0) {
            # Compute HMAC over entire message (with zeroed auth params)
            $hmac = $null
            if ($v3cred.auth_protocol -eq "SHA") {
                $hmac = Get-HMACSHA1 $authKey $fullMsg
            } else {
                $hmac = Get-HMACMD5 $authKey $fullMsg
            }
            # Copy first 12 bytes of HMAC into auth params
            [Array]::Copy($hmac, 0, $fullMsg, $authOffset, 12)
        }
    }
    
    # Send via UDP
    try {
        $udp = New-Object System.Net.Sockets.UdpClient
        $udp.Client.ReceiveTimeout = 4000
        $ep = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse($target), $port)
        $null = $udp.Send($fullMsg, $fullMsg.Length, $ep)
        $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
        $response = $udp.Receive([ref]$remoteEP)
        $udp.Close()
        
        $parsed = Parse-SnmpV3Response $response
        # Update engine cache
        if ($parsed.engine_id -and $parsed.engine_id.Length -gt 0) {
            $script:EngineCache[$target] = @{
                engine_id = $parsed.engine_id
                boots = [int]$parsed.engine_boots
                time = [int]$parsed.engine_time
            }
        }
        return $parsed.varbinds
    } catch {
        if ($udp) { $udp.Close() }
        return $null
    }
}

function Get-SnmpV3Value([string]$target, [hashtable]$v3cred, [string]$oid) {
    $result = Send-SnmpV3Get $target $v3cred $oid
    if ($result -and $result.Count -gt 0) {
        return $result.Values | Select-Object -First 1
    }
    return $null
}

function Get-SnmpV3Table([string]$target, [hashtable]$v3cred, [string]$baseOid) {
    $results = @{}
    $currentOid = $baseOid
    $maxIter = 200
    for ($i = 0; $i -lt $maxIter; $i++) {
        $response = Send-SnmpV3Get $target $v3cred $currentOid -getNext $true
        if (-not $response -or $response.Count -eq 0) { break }
        $respOid = $response.Keys | Select-Object -First 1
        $respVal = $response[$respOid]
        if (-not $respOid.StartsWith($baseOid)) { break }
        $results[$respOid] = $respVal
        $currentOid = $respOid
    }
    return $results
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
        $devName = if ($dev.name) { $dev.name } else { $ip }
        $snmpVersion = if ($dev.snmp_version) { $dev.snmp_version } else { "v2c" }

        try {
            if ($snmpVersion -eq "v3") {
                # SNMPv3 - usa credenziali USM
                $v3cred = @{
                    username = if ($dev.snmpv3_username) { $dev.snmpv3_username } else { "" }
                    auth_protocol = if ($dev.snmpv3_auth_protocol) { $dev.snmpv3_auth_protocol } else { "MD5" }
                    auth_password = if ($dev.snmpv3_auth_password) { $dev.snmpv3_auth_password } else { "" }
                    priv_protocol = if ($dev.snmpv3_priv_protocol) { $dev.snmpv3_priv_protocol } else { "DES" }
                    priv_password = if ($dev.snmpv3_priv_password) { $dev.snmpv3_priv_password } else { "" }
                    security_level = if ($dev.snmpv3_security_level) { $dev.snmpv3_security_level } else { "authPriv" }
                }
                Write-Host "[SNMPv3] Polling $devName ($ip) con utente $($v3cred.username), livello: $($v3cred.security_level)"
                $alerts = Poll-DeviceV3 $ip $v3cred $devName
                $allAlerts += $alerts
            } else {
                # SNMPv1/v2c - usa community string
                $community = if ($dev.community) { $dev.community } else { "public" }
                $alerts = Poll-Device $ip $community $devName
                $allAlerts += $alerts
            }
        } catch {
            Write-Host "[SNMP Poll] Errore polling $devName ($ip): $($_.Exception.Message)"
        }
    }
    return $allAlerts
}

function Poll-DeviceV3([string]$ip, [hashtable]$v3cred, [string]$name) {
    <#
    .SYNOPSIS
        Polling SNMPv3 di un dispositivo. Stessa logica di Poll-Device ma usa Send-SnmpV3Get.
    #>
    $alerts = @()

    # Quick ping
    $pingOk = $false
    $pingMs = $null
    try {
        $ping = New-Object System.Net.NetworkInformation.Ping
        $reply = $ping.Send($ip, 2000)
        $pingOk = ($reply.Status -eq "Success")
        if ($pingOk) { $pingMs = $reply.RoundtripTime }
        $ping.Dispose()
    } catch {}

    # SNMP v3 reachability check
    $reachable = $false
    $sysDescr = $null
    try {
        $probeResult = Send-SnmpV3Get $ip $v3cred $script:OID_sysDescr
        if ($probeResult -and $probeResult.Count -gt 0) {
            $sysDescr = $probeResult.Values | Select-Object -First 1
            $reachable = $true
        }
    } catch {}

    if (-not $reachable -and $pingOk) {
        $reachable = $true
        if (-not $sysDescr) { $sysDescr = "Dispositivo raggiungibile (ping OK, SNMPv3 non disponibile)" }
    }

    if (-not $reachable) {
        if ($script:DeviceUp.ContainsKey($ip) -and $script:DeviceUp[$ip]) {
            $alerts += @{
                device_ip = $ip; oid = "1.3.6.1.2.1.1.1.0"
                value = "Dispositivo $name ($ip) NON RAGGIUNGIBILE - nessuna risposta SNMPv3"
                trap_type = "deviceDown"; severity = "critical"; device_name = $name
            }
        }
        $script:DeviceUp[$ip] = $false
        return $alerts
    }

    if ($script:DeviceUp.ContainsKey($ip) -and -not $script:DeviceUp[$ip]) {
        $alerts += @{
            device_ip = $ip; oid = "1.3.6.1.2.1.1.1.0"
            value = "Dispositivo $name ($ip) di nuovo RAGGIUNGIBILE (SNMPv3)"
            trap_type = "deviceUp"; severity = "low"; device_name = $name
        }
    }
    $script:DeviceUp[$ip] = $true

    # Interface status via v3
    $ifDescrTable = Get-SnmpV3Table $ip $v3cred $script:OID_ifDescr
    $ifOperTable = Get-SnmpV3Table $ip $v3cred $script:OID_ifOperStat
    $ifAdminTable = Get-SnmpV3Table $ip $v3cred $script:OID_ifAdminStat

    $portMap = @{}
    foreach ($key in $ifDescrTable.Keys) {
        $idx = $key.Split('.')[-1]
        $portMap[$idx] = @{ name = $ifDescrTable[$key]; oper = $null; admin = $null }
    }
    foreach ($key in $ifOperTable.Keys) {
        $idx = $key.Split('.')[-1]
        if ($portMap.ContainsKey($idx)) { $portMap[$idx].oper = [int]$ifOperTable[$key] }
    }
    foreach ($key in $ifAdminTable.Keys) {
        $idx = $key.Split('.')[-1]
        if ($portMap.ContainsKey($idx)) { $portMap[$idx].admin = [int]$ifAdminTable[$key] }
    }

    if (-not $script:PortStates.ContainsKey($ip)) { $script:PortStates[$ip] = @{} }
    $prevStates = $script:PortStates[$ip]

    foreach ($idx in $portMap.Keys) {
        $port = $portMap[$idx]
        if ($port.admin -eq 2) { continue }
        $prevOper = if ($prevStates.ContainsKey($idx)) { $prevStates[$idx] } else { $null }
        if ($prevOper -ne $null -and $prevOper -ne $port.oper) {
            $statusName = if ($script:IfStatusMap.ContainsKey($port.oper)) { $script:IfStatusMap[$port.oper] } else { "unknown" }
            if ($port.oper -eq 2 -and $prevOper -eq 1) {
                $alerts += @{
                    device_ip = $ip; oid = "1.3.6.1.2.1.2.2.1.8.$idx"
                    value = "Porta $($port.name) DOWN su $name ($ip)"; trap_type = "linkDown"
                    severity = "critical"; device_name = $name
                }
            } elseif ($port.oper -eq 1 -and $prevOper -eq 2) {
                $alerts += @{
                    device_ip = $ip; oid = "1.3.6.1.2.1.2.2.1.8.$idx"
                    value = "Porta $($port.name) UP su $name ($ip)"; trap_type = "linkUp"
                    severity = "low"; device_name = $name
                }
            }
        }
        $prevStates[$idx] = $port.oper
    }
    $script:PortStates[$ip] = $prevStates

    # Extended metrics via v3 (CPU/Memory/Temperature)
    try {
        $cpuTable = Get-SnmpV3Table $ip $v3cred "1.3.6.1.2.1.25.3.3.1.2"
        if ($cpuTable -and $cpuTable.Count -gt 0) {
            $cpuVals = @($cpuTable.Values | Where-Object { $_ -is [long] -or $_ -is [int] })
            if ($cpuVals.Count -gt 0) {
                $cpuAvg = [int](($cpuVals | Measure-Object -Average).Average)
                if ($cpuAvg -gt 90) {
                    $alerts += @{
                        device_ip = $ip; oid = "host.cpu.high"
                        value = "CPU al $cpuAvg% su $name ($ip) [SNMPv3]"
                        trap_type = "cpuHigh"; severity = "high"; device_name = $name
                    }
                }
            }
        }
    } catch {}

    return $alerts
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


# ==================== PRINTER SNMP POLLING ====================
# Printer-MIB OIDs for toner, page count, and status monitoring

function Poll-PrinterData([string]$ip, [string]$community, [string]$name) {
    <#
    .SYNOPSIS
        Polls a network printer via SNMP Printer-MIB OIDs.
        Extracts toner levels, page counts, printer status, model, serial.
    .DESCRIPTION
        Standard OIDs used:
        - hrPrinterStatus:          .1.3.6.1.2.1.25.3.5.1.1 (printer status)
        - prtMarkerSuppliesDesc:    .1.3.6.1.2.1.43.11.1.1.6 (supply description/name)
        - prtMarkerSuppliesMaxCap:  .1.3.6.1.2.1.43.11.1.1.8 (max capacity)
        - prtMarkerSuppliesLevel:   .1.3.6.1.2.1.43.11.1.1.9 (current level)
        - prtMarkerSuppliesType:    .1.3.6.1.2.1.43.11.1.1.4 (supply type code)
        - prtMarkerLifeCount:       .1.3.6.1.2.1.43.10.2.1.4 (total page count)
        - prtInputDescription:      .1.3.6.1.2.1.43.8.2.1.18 (tray description)
        - prtInputMaxCapacity:      .1.3.6.1.2.1.43.8.2.1.9  (tray max capacity)
        - prtInputCurrentLevel:     .1.3.6.1.2.1.43.8.2.1.10 (tray current level)
        - prtInputStatus:           .1.3.6.1.2.1.43.8.2.1.11 (tray status)
        - sysDescr:                 .1.3.6.1.2.1.1.1.0       (device description/model)
        - prtGeneralSerialNumber:   .1.3.6.1.2.1.43.5.1.1.17 (serial number)
        - prtAlertDescription:      .1.3.6.1.2.1.43.18.1.1.8 (alert messages)
    #>
    
    $result = @{
        device_ip = $ip
        device_name = $name
        model = ""
        serial = ""
        reachable = $false
        printer_status_code = $null
        printer_status = ""
        page_count = 0
        color_page_count = 0
        duplex_count = 0
        supplies = @()
        trays = @()
        alert_messages = @()
    }

    # 1. Check reachability
    $sysDescr = Get-SnmpValue $ip $community "1.3.6.1.2.1.1.1.0"
    if (-not $sysDescr) {
        # Try ping as fallback
        try {
            $ping = New-Object System.Net.NetworkInformation.Ping
            $reply = $ping.Send($ip, 2000)
            $ping.Dispose()
            if ($reply.Status -ne "Success") { return $result }
        } catch { return $result }
    }
    $result.reachable = $true
    if ($sysDescr) { $result.model = [string]$sysDescr }

    # 2. Serial Number
    $serial = Get-SnmpValue $ip $community "1.3.6.1.2.1.43.5.1.1.17.1"
    if ($serial) { $result.serial = [string]$serial }

    # 3. Printer Status (hrPrinterStatus)
    $status = Get-SnmpValue $ip $community "1.3.6.1.2.1.25.3.5.1.1.1"
    if ($status) {
        $statusCode = [int]$status
        $result.printer_status_code = $statusCode
        $statusNames = @{ 1 = "Altro"; 2 = "Sconosciuto"; 3 = "Idle"; 4 = "In Stampa"; 5 = "Riscaldamento" }
        $result.printer_status = if ($statusNames.ContainsKey($statusCode)) { $statusNames[$statusCode] } else { "Stato $statusCode" }
    }

    # 4. Page Count (prtMarkerLifeCount)
    $pageCountTable = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.10.2.1.4"
    if ($pageCountTable -and $pageCountTable.Count -gt 0) {
        $pageCounts = @($pageCountTable.Values | ForEach-Object { try { [int]$_ } catch { 0 } })
        if ($pageCounts.Count -gt 0) {
            $result.page_count = ($pageCounts | Measure-Object -Maximum).Maximum
        }
    }

    # 5. Supplies (Toner, Drum, etc.)
    $supplyDescs = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.11.1.1.6"
    $supplyMaxCap = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.11.1.1.8"
    $supplyLevels = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.11.1.1.9"
    $supplyTypes  = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.11.1.1.4"
    
    $supplyTypeNames = @{
        1 = "altro"; 3 = "toner"; 4 = "inchiostro"; 5 = "cartuccia_inchiostro"
        6 = "cartuccia_toner"; 7 = "drum"; 8 = "nastro_trasferimento"
        9 = "waste_toner"; 12 = "fuser"; 13 = "opc_drum"
    }

    if ($supplyDescs -and $supplyDescs.Count -gt 0) {
        foreach ($key in $supplyDescs.Keys) {
            $idx = $key.Split('.')[-1]
            $supplyName = [string]$supplyDescs[$key]
            
            $maxCap = 0
            $currentLevel = 0
            $typeCode = 3  # default toner
            
            # Find matching max capacity
            foreach ($mk in $supplyMaxCap.Keys) {
                if ($mk.Split('.')[-1] -eq $idx) { 
                    try { $maxCap = [int]$supplyMaxCap[$mk] } catch {} 
                    break 
                }
            }
            # Find matching current level
            foreach ($lk in $supplyLevels.Keys) {
                if ($lk.Split('.')[-1] -eq $idx) { 
                    try { $currentLevel = [int]$supplyLevels[$lk] } catch {} 
                    break 
                }
            }
            # Find matching type
            foreach ($tk in $supplyTypes.Keys) {
                if ($tk.Split('.')[-1] -eq $idx) { 
                    try { $typeCode = [int]$supplyTypes[$tk] } catch {} 
                    break 
                }
            }
            
            $typeName = if ($supplyTypeNames.ContainsKey($typeCode)) { $supplyTypeNames[$typeCode] } else { "altro" }
            
            $result.supplies += @{
                name = $supplyName
                type = $typeName
                max_capacity = $maxCap
                current_level = $currentLevel
            }
        }
    }

    # 6. Paper Trays
    $trayDescs   = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.8.2.1.18"
    $trayMaxCap  = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.8.2.1.9"
    $trayLevels  = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.8.2.1.10"
    
    if ($trayDescs -and $trayDescs.Count -gt 0) {
        foreach ($key in $trayDescs.Keys) {
            $idx = $key.Split('.')[-1]
            $trayName = [string]$trayDescs[$key]
            if (-not $trayName) { $trayName = "Vassoio $idx" }
            
            $tMaxCap = 0
            $tLevel = 0
            foreach ($mk in $trayMaxCap.Keys) {
                if ($mk.Split('.')[-1] -eq $idx) { try { $tMaxCap = [int]$trayMaxCap[$mk] } catch {}; break }
            }
            foreach ($lk in $trayLevels.Keys) {
                if ($lk.Split('.')[-1] -eq $idx) { try { $tLevel = [int]$trayLevels[$lk] } catch {}; break }
            }
            
            $tStatus = "ok"
            if ($tLevel -le 0) { $tStatus = "empty" }
            elseif ($tMaxCap -gt 0 -and ($tLevel / $tMaxCap) -lt 0.15) { $tStatus = "low" }
            
            $result.trays += @{
                name = $trayName
                status = $tStatus
                capacity = $tMaxCap
                level = $tLevel
            }
        }
    }

    # 7. Alert Messages
    $alertDescs = Get-SnmpTable $ip $community "1.3.6.1.2.1.43.18.1.1.8"
    if ($alertDescs -and $alertDescs.Count -gt 0) {
        foreach ($key in $alertDescs.Keys) {
            $msg = [string]$alertDescs[$key]
            if ($msg -and $msg.Trim()) {
                $result.alert_messages += $msg.Trim()
            }
        }
    }

    Write-Host "[Printer Poll] $name ($ip): Stato=$($result.printer_status), Pagine=$($result.page_count), Supplies=$($result.supplies.Count)"
    return $result
}

function Poll-AllPrinters($printerDevices, $config) {
    <#
    .SYNOPSIS
        Polls all printer devices and sends data to the NOC backend.
        The backend derives client_id from the API key, so no separate lookup needed.
    #>
    foreach ($dev in $printerDevices) {
        $ip = $dev.ip
        $community = if ($dev.community) { $dev.community } else { "public" }
        $devName = if ($dev.name) { $dev.name } else { $ip }

        try {
            $printerData = Poll-PrinterData $ip $community $devName
            # client_id will be derived by backend from API key
            $printerData.client_id = "auto"
            
            Send-ToNOC $config "printers/process-poll" $printerData | Out-Null
            Write-Host "[Printer] Dati stampante $devName ($ip) inviati al NOC"
        } catch {
            Write-Host "[Printer Poll] Errore polling stampante $devName ($ip): $($_.Exception.Message)"
        }
    }
}


function Run-VAScan($ip, $community, $deviceName, $riskyPorts) {
    <#
    .SYNOPSIS
        Esegue una scansione di Vulnerability Assessment su un singolo dispositivo.
        Controlla porte pericolose aperte e community SNMP di default.
        Restituisce i risultati nel formato atteso dal backend.
    #>
    $result = @{
        device_ip = $ip
        device_name = $deviceName
        open_ports = @()
        scan_time = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    }

    Write-Host "[VA Scan] Scansione $deviceName ($ip) - $($riskyPorts.Count) porte da controllare..."

    # 1. TCP Port Scan - Check each risky port
    foreach ($port in $riskyPorts) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $asyncResult = $tcp.BeginConnect($ip, $port, $null, $null)
            $waited = $asyncResult.AsyncWaitHandle.WaitOne(1500, $false)
            if ($waited -and $tcp.Connected) {
                $result.open_ports += @{
                    port = [int]$port
                    open = $true
                    service = ""
                }
                Write-Host "[VA Scan]   Porta $port APERTA su $ip"
            }
            $tcp.Close()
        } catch {
            # Port is closed or unreachable - skip
        }
    }

    # 2. SNMP community string check (probe UDP 161)
    $defaultCommunities = @("public", "private", "community", "default", "admin", "snmp", "monitor")
    $weakCommunityFound = $false
    
    # Check if the configured community is a known weak one
    if ($community -and ($defaultCommunities -contains $community.ToLower())) {
        $weakCommunityFound = $true
        Write-Host "[VA Scan]   Community SNMP debole rilevata: '$community' su $ip"
    }

    # If SNMP port (161) is not already in open_ports but device responds to SNMP, add it
    $snmpAlreadyFound = $result.open_ports | Where-Object { $_.port -eq 161 }
    if (-not $snmpAlreadyFound) {
        try {
            # Quick SNMP GET test using raw UDP
            $udpClient = New-Object System.Net.Sockets.UdpClient
            $udpClient.Client.ReceiveTimeout = 2000
            $udpClient.Connect($ip, 161)
            
            $communityBytes = [System.Text.Encoding]::ASCII.GetBytes($community)
            $communityLen = $communityBytes.Length
            
            # SNMP GET request for sysDescr.0 (1.3.6.1.2.1.1.1.0)
            $oid = @(0x06, 0x08, 0x2B, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00)
            $varbind = @(0x30) + @([byte]($oid.Length + 4)) + $oid + @(0x05, 0x00)
            $varbindList = @(0x30) + @([byte]$varbind.Length) + $varbind
            $pdu = @(0xA0) + @([byte]($varbindList.Length + 12)) + @(0x02, 0x04, 0x00, 0x00, 0x00, 0x01, 0x02, 0x01, 0x00, 0x02, 0x01, 0x00) + $varbindList
            $communityTlv = @(0x04, [byte]$communityLen) + $communityBytes
            $innerLen = 3 + $communityTlv.Length + $pdu.Length
            $snmpPacket = @(0x30, [byte]$innerLen, 0x02, 0x01, 0x01) + $communityTlv + $pdu
            
            $udpClient.Send($snmpPacket, $snmpPacket.Length) | Out-Null
            $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
            $responseBytes = $udpClient.Receive([ref]$remoteEP)
            
            if ($responseBytes -and $responseBytes.Length -gt 0) {
                $result.open_ports += @{
                    port = 161
                    open = $true
                    service = "SNMP"
                }
                Write-Host "[VA Scan]   Porta 161 (SNMP) APERTA su $ip"
            }
            $udpClient.Close()
        } catch {
            # SNMP not responding - that's fine
        }
    }

    Write-Host "[VA Scan] Completato $deviceName ($ip): $($result.open_ports.Count) porte aperte trovate"
    return $result
}
