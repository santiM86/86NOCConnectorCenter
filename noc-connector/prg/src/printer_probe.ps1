# =============================================================================
# printer_probe.ps1 (ARGUS Connector v3.7.3)
# =============================================================================
# Identifica stampanti di rete incrociando:
#   1. TCP port probe (9100 JetDirect, 515 LPD, 631 IPP, 80 HTTP, 443 HTTPS)
#   2. SNMP GetRequest su sysDescr (OID 1.3.6.1.2.1.1.1.0) se TCP aperto o OUI stampante
#
# Invia risultati al backend via POST /api/connector/printer-probe (Send-ToNOC).
# Il backend restituisce la lista di IP candidati via GET /api/connector/printer-probe/candidates.
#
# USO dal connector.ps1 main loop:
#   . "$PSScriptRoot\printer_probe.ps1"
#   Invoke-PrinterProbe -Config $config
# =============================================================================

$script:PRINTER_TCP_PORTS = @(9100, 631, 515, 80, 443)
$script:PRINTER_PROBE_TIMEOUT_MS = 1500
$script:PRINTER_SYSDESCR_OID = "1.3.6.1.2.1.1.1.0"


function Test-PrinterTcpPort {
    param([string]$Ip, [int]$Port, [int]$TimeoutMs = 1500)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($Ip, $Port, $null, $null)
        $connected = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $connected) { return $false }
        $client.EndConnect($iar) | Out-Null
        return $true
    } catch { return $false }
    finally { try { $client.Close() } catch {} }
}


function Probe-PrinterTcp {
    # Ritorna array di porte TCP aperte tra quelle stampante
    param([string]$Ip)
    $open = @()
    foreach ($p in $script:PRINTER_TCP_PORTS) {
        if (Test-PrinterTcpPort -Ip $Ip -Port $p -TimeoutMs $script:PRINTER_PROBE_TIMEOUT_MS) {
            $open += $p
        }
    }
    return ,$open
}


function Probe-PrinterSnmp {
    # Legge sysDescr via SNMP. Usa Get-SnmpValue del connector (community "public" fallback).
    param([string]$Ip, [string]$Community = "public")
    try {
        $v = Get-SnmpValue $Ip $Community $script:PRINTER_SYSDESCR_OID
        if ($v) { return [string]$v }
    } catch { }
    return ""
}


function Extract-PrinterModel {
    param([string]$SysDescr)
    if (-not $SysDescr) { return "" }
    $m = $SysDescr.Trim()
    $m = $m -replace "^(SNMP|HP ETHERNET|ETHERNET)[^,;]*[,;]\s*", ""
    if ($m.Length -gt 80) { $m = $m.Substring(0, 80) + "..." }
    return $m
}


function Invoke-PrinterProbe {
    <#
    .SYNOPSIS
      Main entry point. Pull candidates dal backend, probe TCP+SNMP, POST risultati.
    .PARAMETER Config
      Hashtable config del connector (contiene api_url, api_key, client_id, communities)
    .PARAMETER MaxCandidates
      Numero max di IP da probare per ciclo (default 200)
    #>
    param(
        [Parameter(Mandatory=$true)]$Config,
        [int]$MaxCandidates = 200
    )

    try { Write-Log "PrinterProbe: inizio ciclo probe stampanti" "INFO" } catch {}

    # 1. Pull candidates (OUI stampante noti) dal backend
    $candidates = @()
    try {
        $resp = Invoke-SecureGet $Config "connector/printer-probe/candidates" 15
        if ($resp -and $resp.items) { $candidates = $resp.items }
    } catch {
        try { Write-Log "PrinterProbe: fetch candidates failed: $_" "WARN" } catch {}
        return
    }
    if (-not $candidates -or $candidates.Count -eq 0) {
        try { Write-Log "PrinterProbe: nessun candidato" "INFO" } catch {}
        return
    }
    if ($candidates.Count -gt $MaxCandidates) {
        $candidates = $candidates | Select-Object -First $MaxCandidates
    }

    try { Write-Log "PrinterProbe: probing $($candidates.Count) IP candidati..." "INFO" } catch {}

    # Community list del config (fallback a "public" se non presente)
    $communities = @("public")
    if ($Config.snmp_communities) { $communities = $Config.snmp_communities }
    elseif ($Config.communities) { $communities = $Config.communities }

    $results = @()
    foreach ($c in $candidates) {
        $ip = $c.ip
        $mac = $c.mac
        $vendor = $c.vendor
        if (-not $ip) { continue }

        # Step 1: TCP port probe (veloce)
        $open_ports = Probe-PrinterTcp -Ip $ip
        $is_printer = $open_ports.Count -gt 0

        # Step 2: SNMP sysDescr (solo se TCP aperto o OUI stampante)
        $sys_descr = ""
        $model = ""
        if ($is_printer -or $vendor) {
            foreach ($comm in $communities) {
                $sys_descr = Probe-PrinterSnmp -Ip $ip -Community $comm
                if ($sys_descr) { break }
            }
            if ($sys_descr) {
                $model = Extract-PrinterModel -SysDescr $sys_descr
                $is_printer = $true
            }
        }

        if ($is_printer) {
            $results += @{
                ip         = $ip
                mac        = $mac
                vendor     = $vendor
                tcp_ports  = $open_ports
                sys_descr  = $sys_descr
                model      = $model
                is_printer = $true
            }
            try { Write-Log "  [PRINTER] $ip ports=[$($open_ports -join ',')] model='$model'" "INFO" } catch {}
        }
    }

    if ($results.Count -eq 0) {
        try { Write-Log "PrinterProbe: nessuna stampante confermata" "INFO" } catch {}
        return
    }

    # Step 3: POST risultati via Send-ToNOC (HMAC-signed)
    try {
        $payload = @{ results = $results }
        $resp = Send-ToNOC $Config "connector/printer-probe" $payload
        try { Write-Log "PrinterProbe: inviati $($results.Count) risultati. Endpoints_enriched=$($resp.endpoints_enriched), Managed_upserted=$($resp.managed_upserted)" "INFO" } catch {}
    } catch {
        try { Write-Log "PrinterProbe: upload failed: $_" "WARN" } catch {}
    }
}
