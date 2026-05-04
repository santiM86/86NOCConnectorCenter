# =============================================================================
# switch_enrichment.ps1 (ARGUS Connector v3.7.4)
# =============================================================================
# Estrae dallo switch (via SNMP) 3 dataset aggiuntivi che NON richiedono
# raggiungibilita' L3 verso i client finali (zero-touch cross-VLAN):
#
#   1. ARP table         : ipNetToMediaTable (1.3.6.1.2.1.4.22.1.2)
#      - Usato: se lo switch e' L3 o router, mappa IP<->MAC di tutte le VLAN routate
#
#   2. LLDP-MED inventory: lldpXMedRemInventoryInfo (1.0.8802.1.1.2.1.5.4795.1.3)
#      - Usato: stampanti enterprise (HP LaserJet Enterprise, Xerox WorkCentre,
#        Lexmark MS/MX, Brother enterprise) pubblicano marca/modello/SN via LLDP
#
#   3. DHCP snooping     : Cisco/D-Link/Generic DHCP snooping binding table
#      - Usato: conoscere IP delle stampanti su tutte le VLAN anche se lo
#        switch non e' L3 e il connector non ha routing cross-VLAN
#
# Invia i risultati al backend via POST /api/connector/switch-enrichment.
#
# USO dal connector.ps1 main loop:
#   . "$PSScriptRoot\switch_enrichment.ps1"
#   Invoke-SwitchEnrichment -Config $config -SwitchIp $ip -Community $community
# =============================================================================

# OIDs LLDP-MED (IEEE 802.1AB + ANSI/TIA-1057 LLDP-MED)
$script:OID_LLDP_MED_MfgName       = "1.0.8802.1.1.2.1.5.4795.1.3.4.1.2"   # perPort
$script:OID_LLDP_MED_ModelName     = "1.0.8802.1.1.2.1.5.4795.1.3.5.1.2"
$script:OID_LLDP_MED_SerialNum     = "1.0.8802.1.1.2.1.5.4795.1.3.3.1.2"
$script:OID_LLDP_MED_AssetId       = "1.0.8802.1.1.2.1.5.4795.1.3.7.1.2"
$script:OID_LLDP_MED_HwRev         = "1.0.8802.1.1.2.1.5.4795.1.3.2.1.2"
$script:OID_LLDP_MED_FwRev         = "1.0.8802.1.1.2.1.5.4795.1.3.1.1.2"
$script:OID_LLDP_MED_SwRev         = "1.0.8802.1.1.2.1.5.4795.1.3.6.1.2"
$script:OID_LLDP_RemSysName        = "1.0.8802.1.1.2.1.4.1.1.9"
$script:OID_LLDP_RemSysDesc        = "1.0.8802.1.1.2.1.4.1.1.10"

# OIDs DHCP Snooping (Cisco proprietary + generic)
# Cisco: CISCO-DHCP-SNOOPING-MIB::cdsBindingsTable
$script:OID_CISCO_DHCP_BindIp      = "1.3.6.1.4.1.9.9.380.1.4.1.1.5"
$script:OID_CISCO_DHCP_BindMac     = "1.3.6.1.4.1.9.9.380.1.4.1.1.3"
$script:OID_CISCO_DHCP_BindVlan    = "1.3.6.1.4.1.9.9.380.1.4.1.1.2"
$script:OID_CISCO_DHCP_BindPort    = "1.3.6.1.4.1.9.9.380.1.4.1.1.8"
# Generic: IF-MIB ifDescr + DHCP snooping (alcuni switch usano OID custom)


function Get-ArpTableFromSwitch {
    <#
    .SYNOPSIS  Legge ipNetToMediaTable (ARP cache) dello switch.
    .OUTPUTS   Array di @{ip=...; mac=...}
    #>
    param([string]$Ip, [string]$Community)
    $results = @()
    try {
        $arp = Get-SnmpTable $Ip $Community "1.3.6.1.2.1.4.22.1.2"
        if ($arp) {
            foreach ($k in $arp.Keys) {
                # Key format: .<ifIndex>.<ip-octets>   Value: MAC
                $raw = [string]$arp[$k]
                if (-not $raw) { continue }
                # Extract IP from OID suffix (ultime 4 ottetti)
                $parts = $k -split '\.'
                if ($parts.Count -ge 4) {
                    $ipv4 = ($parts[-4..-1]) -join '.'
                } else {
                    $ipv4 = ""
                }
                # Normalize MAC (BER string -> AA:BB:...)
                $mac = ""
                if ($raw.Length -ge 6) {
                    try {
                        $bytes = [System.Text.Encoding]::Default.GetBytes($raw)
                        if ($bytes.Length -ge 6) {
                            $mac = ("{0:X2}:{1:X2}:{2:X2}:{3:X2}:{4:X2}:{5:X2}" -f $bytes[0],$bytes[1],$bytes[2],$bytes[3],$bytes[4],$bytes[5])
                        }
                    } catch {}
                }
                if ($ipv4 -and $mac -and $mac -ne "00:00:00:00:00:00") {
                    $results += @{ ip = $ipv4; mac = $mac }
                }
            }
        }
    } catch {
        try { Write-Log "ARP snmp walk failed on $Ip : $_" "DEBUG" } catch {}
    }
    return ,$results
}


function Get-LldpMedInventoryFromSwitch {
    <#
    .SYNOPSIS  Legge LLDP-MED Remote Inventory (model/mfg/serial) per ogni porta.
    #>
    param([string]$Ip, [string]$Community)
    $results = @()
    try {
        $mfg   = Get-SnmpTable $Ip $Community $script:OID_LLDP_MED_MfgName
        $model = Get-SnmpTable $Ip $Community $script:OID_LLDP_MED_ModelName
        $sn    = Get-SnmpTable $Ip $Community $script:OID_LLDP_MED_SerialNum
        $at    = Get-SnmpTable $Ip $Community $script:OID_LLDP_MED_AssetId
        $fw    = Get-SnmpTable $Ip $Community $script:OID_LLDP_MED_FwRev
        $rsn   = Get-SnmpTable $Ip $Community $script:OID_LLDP_RemSysName
        $rsd   = Get-SnmpTable $Ip $Community $script:OID_LLDP_RemSysDesc
        if (-not $mfg -and -not $model -and -not $rsd) { return ,$results }

        $keys = @()
        foreach ($t in @($mfg, $model, $sn, $rsn, $rsd)) {
            if ($t) { $keys += $t.Keys }
        }
        $keys = $keys | Select-Object -Unique

        foreach ($k in $keys) {
            # Key format: .<lldpRemTimeMark>.<lldpRemLocalPortNum>.<lldpRemIndex>
            $parts = $k -split '\.'
            if ($parts.Count -lt 3) { continue }
            $portNum = $parts[-2]
            $entry = @{
                port       = [string]$portNum
                mfg        = if ($mfg -and $mfg[$k]) { [string]$mfg[$k] } else { "" }
                model      = if ($model -and $model[$k]) { [string]$model[$k] } else { "" }
                serial     = if ($sn -and $sn[$k]) { [string]$sn[$k] } else { "" }
                asset_tag  = if ($at -and $at[$k]) { [string]$at[$k] } else { "" }
                firmware   = if ($fw -and $fw[$k]) { [string]$fw[$k] } else { "" }
                sys_name   = if ($rsn -and $rsn[$k]) { [string]$rsn[$k] } else { "" }
                sys_desc   = if ($rsd -and $rsd[$k]) { [string]$rsd[$k] } else { "" }
            }
            if ($entry.mfg -or $entry.model -or $entry.sys_desc) {
                $results += $entry
            }
        }
    } catch {
        try { Write-Log "LLDP-MED walk failed on $Ip : $_" "DEBUG" } catch {}
    }
    return ,$results
}


function Get-DhcpSnoopingFromSwitch {
    <#
    .SYNOPSIS  Legge la DHCP Snooping binding table (Cisco MIB, fallback silent).
    #>
    param([string]$Ip, [string]$Community)
    $results = @()
    try {
        $ips   = Get-SnmpTable $Ip $Community $script:OID_CISCO_DHCP_BindIp
        if (-not $ips) { return ,$results }
        $macs  = Get-SnmpTable $Ip $Community $script:OID_CISCO_DHCP_BindMac
        $vlans = Get-SnmpTable $Ip $Community $script:OID_CISCO_DHCP_BindVlan
        $ports = Get-SnmpTable $Ip $Community $script:OID_CISCO_DHCP_BindPort

        foreach ($k in $ips.Keys) {
            $ipVal = [string]$ips[$k]
            if (-not $ipVal) { continue }
            $macRaw = if ($macs -and $macs[$k]) { [string]$macs[$k] } else { "" }
            $mac = ""
            if ($macRaw -and $macRaw.Length -ge 6) {
                try {
                    $bytes = [System.Text.Encoding]::Default.GetBytes($macRaw)
                    if ($bytes.Length -ge 6) {
                        $mac = ("{0:X2}:{1:X2}:{2:X2}:{3:X2}:{4:X2}:{5:X2}" -f $bytes[0],$bytes[1],$bytes[2],$bytes[3],$bytes[4],$bytes[5])
                    }
                } catch {}
            }
            if (-not $mac) { continue }
            $vlan = if ($vlans -and $vlans[$k]) { [int]$vlans[$k] } else { 0 }
            $port = if ($ports -and $ports[$k]) { [string]$ports[$k] } else { "" }
            $results += @{
                ip = $ipVal; mac = $mac; vlan = $vlan; port = $port
            }
        }
    } catch {
        try { Write-Log "DHCP snooping walk failed on $Ip : $_" "DEBUG" } catch {}
    }
    return ,$results
}


function Invoke-SwitchEnrichment {
    <#
    .SYNOPSIS
      Enrichment post-discovery per uno switch. Invia ARP + LLDP-MED + DHCP-snoop
      al backend che arricchira' discovered_endpoints senza probe attivi ai client.
    #>
    param(
        [Parameter(Mandatory=$true)]$Config,
        [Parameter(Mandatory=$true)][string]$SwitchIp,
        [Parameter(Mandatory=$true)][string]$Community
    )

    try { Write-Log "SwitchEnrichment: $SwitchIp (ARP+LLDP-MED+DHCP-snoop)" "INFO" } catch {}

    $arp       = Get-ArpTableFromSwitch -Ip $SwitchIp -Community $Community
    $lldpMed   = Get-LldpMedInventoryFromSwitch -Ip $SwitchIp -Community $Community
    $dhcpBind  = Get-DhcpSnoopingFromSwitch -Ip $SwitchIp -Community $Community

    $totals = "ARP=$($arp.Count) LLDP-MED=$($lldpMed.Count) DHCP=$($dhcpBind.Count)"
    try { Write-Log "  $totals" "INFO" } catch {}

    if ($arp.Count -eq 0 -and $lldpMed.Count -eq 0 -and $dhcpBind.Count -eq 0) {
        return
    }

    $payload = @{
        switch_ip           = $SwitchIp
        arp_entries         = $arp
        lldp_med_inventory  = $lldpMed
        dhcp_bindings       = $dhcpBind
    }

    try {
        $resp = Send-ToNOC $Config "connector/switch-enrichment" $payload
        try { Write-Log "SwitchEnrichment $SwitchIp : enriched=$($resp.endpoints_enriched) LLDPprinters=$($resp.lldp_printers_detected)" "INFO" } catch {}
    } catch {
        try { Write-Log "SwitchEnrichment POST failed: $_" "WARN" } catch {}
    }
}
