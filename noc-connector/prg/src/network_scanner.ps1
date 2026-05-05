# =============================================================================
# 86NocConnector - SCANSIONE DI RETE (versione minimal, garantita PS5.1+)
# =============================================================================
# Pattern semplice:
#   - Ping sequenziale con timeout 200ms
#   - Application::DoEvents() ad ogni IP per non freezare la UI
#   - Aggiunta riga ListView in tempo reale
#   - Niente Runspace Pool, niente Timer.Tick (eliminate fonti di silenzio fail)
# =============================================================================

# OUI lookup minimale (top vendor LAN)
$script:NS_OuiMap = @{
    "0019A9"="Cisco"; "001B17"="Cisco"; "F4A99A"="Cisco"; "C46516"="Cisco"
    "00059A"="Cisco"; "001E68"="Cisco"; "0030B6"="Cisco"; "20EA63"="Cisco"
    "0024C4"="Cisco"; "B827EB"="Raspberry"; "DCA632"="Raspberry"
    "5C260A"="Dell"; "001195"="Dell"; "002219"="Dell"; "F8B156"="Dell"
    "001E4F"="Dell"; "00188B"="Dell"; "00219B"="Dell"
    "F4CE46"="HP"; "9C8E99"="HP"; "ECB1D7"="HP"; "B499BA"="HP"
    "001E0B"="HP"; "78ACC0"="HP"; "001CC4"="HP"; "001A4B"="HP"
    "0017A4"="HP"; "001321"="HP"; "5065F3"="HP"; "70106F"="HP"
    "C8D3A3"="HP"; "001B78"="HP"; "9457A5"="HP"; "1062E5"="HP"
    "F0BCC8"="HP"; "44A856"="HP"; "001583"="HP"; "F0921C"="HP"
    "F0B1E7"="HP"; "FC15B4"="HP"; "0023E7"="HP"; "C03FD5"="HP"
    "F84C77"="HP"; "3CD92B"="HP"; "B0227A"="HP"; "001083"="HP"
    "00041B"="Synology"; "001132"="Synology"
    "0017F2"="Apple"; "001451"="Apple"; "F0DCE2"="Apple"
    "B8E856"="Apple"; "78CA39"="Apple"; "A8866D"="Apple"
    "F0F61C"="Apple"; "0026BB"="Apple"
    "001E2A"="NETGEAR"; "9C3DCF"="NETGEAR"
    "281878"="MikroTik"; "4C5E0C"="MikroTik"; "B8699D"="MikroTik"
    "6CF049"="Fortinet"; "9094E4"="Fortinet"; "0009F0"="Fortinet"
    "C8FF77"="Brother"; "0080A1"="Brother"; "FCB4E6"="Brother"; "008094"="Brother"
    "001A1E"="Aruba"; "94B40F"="Aruba"
    "5404A6"="ASUSTek"; "B06EBF"="ASUSTek"; "AC9E17"="ASUSTek"; "001E8C"="ASUSTek"
    "B0A737"="TPLink"; "C04A00"="TPLink"
    "001CC0"="Intel"; "0024D7"="Intel"; "001517"="Intel"
}

function NSv2-GetVendor([string]$Mac) {
    if (-not $Mac -or $Mac.Length -lt 8) { return "" }
    $oui = ($Mac -replace "[:-]","").Substring(0,6).ToUpper()
    if ($script:NS_OuiMap.ContainsKey($oui)) { return $script:NS_OuiMap[$oui] }
    return ""
}

function NSv2-GetMac([string]$ip) {
    try {
        $n = Get-NetNeighbor -IPAddress $ip -ErrorAction SilentlyContinue |
             Where-Object { $_.LinkLayerAddress -and $_.LinkLayerAddress -ne "00-00-00-00-00-00" } |
             Select-Object -First 1
        if ($n) { return ($n.LinkLayerAddress -replace "-",":").ToLower() }
    } catch {}
    return ""
}

function NSv2-GetHostname([string]$ip) {
    try {
        $h = [System.Net.Dns]::GetHostEntry($ip)
        if ($h -and $h.HostName -and $h.HostName -ne $ip) { return $h.HostName.Split('.')[0] }
    } catch {}
    return ""
}

function NSv2-Ping([string]$ip, [int]$timeoutMs = 250) {
    try {
        $p = New-Object System.Net.NetworkInformation.Ping
        $r = $p.Send($ip, $timeoutMs)
        return ($r.Status -eq "Success")
    } catch { return $false }
}

function Show-NetworkScanner {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Scansione di rete - Connector Scanner"
    $form.Size = New-Object System.Drawing.Size(900, 600)
    $form.StartPosition = "CenterScreen"
    $form.BackColor = [System.Drawing.Color]::White
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

    # Titolo
    $lblTitle = New-Object System.Windows.Forms.Label
    $lblTitle.Text = "Scansione di rete"
    $lblTitle.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
    $lblTitle.ForeColor = [System.Drawing.Color]::FromArgb(56, 132, 222)
    $lblTitle.Location = New-Object System.Drawing.Point(20, 15)
    $lblTitle.Size = New-Object System.Drawing.Size(500, 30)
    $form.Controls.Add($lblTitle)

    # Subnet input
    $lblSubnet = New-Object System.Windows.Forms.Label
    $lblSubnet.Text = "Subnet (CIDR):"
    $lblSubnet.Location = New-Object System.Drawing.Point(20, 60)
    $lblSubnet.Size = New-Object System.Drawing.Size(95, 22)
    $form.Controls.Add($lblSubnet)

    $txtSubnet = New-Object System.Windows.Forms.TextBox
    $txtSubnet.Location = New-Object System.Drawing.Point(115, 57)
    $txtSubnet.Size = New-Object System.Drawing.Size(180, 24)
    try {
        $myIp = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual -ErrorAction SilentlyContinue |
                 Where-Object {$_.IPAddress -notlike "169.254.*" -and $_.IPAddress -notlike "127.*"} |
                 Select-Object -First 1).IPAddress
        if ($myIp) { $txtSubnet.Text = ($myIp -replace "\.\d+$",".0/24") } else { $txtSubnet.Text = "192.168.1.0/24" }
    } catch { $txtSubnet.Text = "192.168.1.0/24" }
    $form.Controls.Add($txtSubnet)

    # Avvia
    $btnStart = New-Object System.Windows.Forms.Button
    $btnStart.Text = "Avvia scansione"
    $btnStart.Size = New-Object System.Drawing.Size(180, 36)
    $btnStart.Location = New-Object System.Drawing.Point(310, 52)
    $btnStart.FlatStyle = "Flat"
    $btnStart.BackColor = [System.Drawing.Color]::FromArgb(56, 132, 222)
    $btnStart.ForeColor = [System.Drawing.Color]::White
    $btnStart.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $btnStart.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnStart)

    # ListView
    $lst = New-Object System.Windows.Forms.ListView
    $lst.Location = New-Object System.Drawing.Point(20, 105)
    $lst.Size = New-Object System.Drawing.Size(850, 380)
    $lst.View = [System.Windows.Forms.View]::Details
    $lst.FullRowSelect = $true
    $lst.GridLines = $true
    $lst.Columns.Add("Stato", 60) | Out-Null
    $lst.Columns.Add("IP", 130) | Out-Null
    $lst.Columns.Add("Hostname", 180) | Out-Null
    $lst.Columns.Add("MAC", 160) | Out-Null
    $lst.Columns.Add("Vendor", 110) | Out-Null
    $lst.Columns.Add("RTT (ms)", 80) | Out-Null
    $form.Controls.Add($lst)

    # Status
    $lblStatus = New-Object System.Windows.Forms.Label
    $lblStatus.Text = "Premi 'Avvia scansione' per iniziare."
    $lblStatus.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Italic)
    $lblStatus.ForeColor = [System.Drawing.Color]::FromArgb(80, 80, 90)
    $lblStatus.Location = New-Object System.Drawing.Point(20, 495)
    $lblStatus.Size = New-Object System.Drawing.Size(850, 22)
    $form.Controls.Add($lblStatus)

    # Bottoni in basso
    $btnExport = New-Object System.Windows.Forms.Button
    $btnExport.Text = "Esporta CSV"
    $btnExport.Size = New-Object System.Drawing.Size(140, 32)
    $btnExport.Location = New-Object System.Drawing.Point(20, 525)
    $btnExport.FlatStyle = "Flat"
    $btnExport.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnExport.ForeColor = [System.Drawing.Color]::White
    $btnExport.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnExport)

    $btnSend = New-Object System.Windows.Forms.Button
    $btnSend.Text = "Invia tutti al Center"
    $btnSend.Size = New-Object System.Drawing.Size(180, 32)
    $btnSend.Location = New-Object System.Drawing.Point(690, 525)
    $btnSend.FlatStyle = "Flat"
    $btnSend.BackColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
    $btnSend.ForeColor = [System.Drawing.Color]::White
    $btnSend.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $btnSend.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnSend)

    # ----- AVVIA SCANSIONE: pattern sequenziale + DoEvents -----
    $btnStart.Add_Click({
        $sub = $txtSubnet.Text.Trim()
        if ($sub -notmatch "^\d+\.\d+\.\d+\.\d+/\d+$") {
            [System.Windows.Forms.MessageBox]::Show("Subnet non valida.`r`nEsempio: 192.168.1.0/24","Scansione di rete","OK","Warning") | Out-Null
            return
        }
        $btnStart.Enabled = $false
        $btnStart.Text = "Scansione in corso..."
        $lst.Items.Clear()

        # Calcola lista IP (max 256 per sicurezza)
        $base = ($sub -split "/")[0]
        $mask = [int](($sub -split "/")[1])
        $b = $base -split "\."
        $startIp = ([uint32]$b[0] -shl 24) -bor ([uint32]$b[1] -shl 16) -bor ([uint32]$b[2] -shl 8) -bor [uint32]$b[3]
        $hostBits = 32 - $mask
        $count = if ($hostBits -ge 8) { 254 } else { [int]([math]::Pow(2, $hostBits) - 2) }
        $startIp = ($startIp -band ([uint32]::MaxValue -shl $hostBits)) + 1

        $found = 0
        for ($i = 0; $i -lt $count; $i++) {
            $n = $startIp + $i
            $ip = "$(($n -shr 24) -band 0xFF).$(($n -shr 16) -band 0xFF).$(($n -shr 8) -band 0xFF).$($n -band 0xFF)"
            $lblStatus.Text = "Test $($i+1)/$count : $ip ... ($found host trovati)"
            [System.Windows.Forms.Application]::DoEvents()
            try {
                $p = New-Object System.Net.NetworkInformation.Ping
                $r = $p.Send($ip, 250)
                if ($r.Status -eq "Success") {
                    $found++
                    $mac = NSv2-GetMac $ip
                    $hn = NSv2-GetHostname $ip
                    $vendor = if ($mac) { NSv2-GetVendor $mac } else { "" }
                    $item = New-Object System.Windows.Forms.ListViewItem(([char]0x2713 + " UP"))
                    $item.SubItems.Add($ip) | Out-Null
                    $item.SubItems.Add($hn) | Out-Null
                    $item.SubItems.Add($mac) | Out-Null
                    $item.SubItems.Add($vendor) | Out-Null
                    $item.SubItems.Add([string]$r.RoundtripTime) | Out-Null
                    $item.ForeColor = [System.Drawing.Color]::FromArgb(22, 163, 74)
                    $lst.Items.Add($item) | Out-Null
                }
            } catch {}
        }
        $lblStatus.Text = "Scansione completata: $found host vivi su $count IP testati."
        $btnStart.Enabled = $true
        $btnStart.Text = "Avvia scansione"
    })

    # ----- ESPORTA CSV -----
    $btnExport.Add_Click({
        if ($lst.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun dato da esportare.","Scansione di rete","OK","Information") | Out-Null
            return
        }
        $sfd = New-Object System.Windows.Forms.SaveFileDialog
        $sfd.Filter = "CSV (*.csv)|*.csv"
        $sfd.FileName = "scan-$(Get-Date -Format 'yyyyMMdd-HHmmss').csv"
        if ($sfd.ShowDialog() -eq "OK") {
            $sw = New-Object System.IO.StreamWriter($sfd.FileName, $false, [System.Text.Encoding]::UTF8)
            $sw.WriteLine("Stato;IP;Hostname;MAC;Vendor;RTT")
            foreach ($it in $lst.Items) {
                $row = @($it.Text)
                for ($i = 0; $i -lt 5; $i++) { $row += $it.SubItems[$i+1].Text }
                $sw.WriteLine(($row -join ";"))
            }
            $sw.Close()
            [System.Windows.Forms.MessageBox]::Show("Esportati $($lst.Items.Count) host.","Scansione di rete","OK","Information") | Out-Null
        }
    })

    # ----- INVIA AL CENTER -----
    $btnSend.Add_Click({
        if ($lst.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun host da inviare.","Scansione di rete","OK","Information") | Out-Null
            return
        }
        $cfg = $null
        try {
            if (Test-Path $ConfigPath) {
                $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
            }
        } catch {}
        if (-not $cfg) {
            [System.Windows.Forms.MessageBox]::Show("Config Connector non trovato in $ConfigPath","Scansione di rete","OK","Error") | Out-Null
            return
        }
        # v3.8.11: il config del Connector usa 'noc_center_url' (non 'center_url')
        $centerUrl = if ($cfg.noc_center_url) { $cfg.noc_center_url } elseif ($cfg.center_url) { $cfg.center_url } else { "" }
        $apiKey = if ($cfg.api_key) { $cfg.api_key } else { "" }
        if (-not $centerUrl -or -not $apiKey) {
            [System.Windows.Forms.MessageBox]::Show("Config Connector incompleto:`r`nnoc_center_url='$centerUrl'`r`napi_key= $(if ($apiKey) { 'presente' } else { 'MANCANTE' })","Scansione di rete","OK","Error") | Out-Null
            return
        }
        $endpoints = @()
        foreach ($it in $lst.Items) {
            $endpoints += @{
                ip = $it.SubItems[1].Text
                hostname = $it.SubItems[2].Text
                mac = $it.SubItems[3].Text
                vendor = $it.SubItems[4].Text
                discovered_via = "scanner-ui"
            }
        }
        $body = @{
            subnet = $txtSubnet.Text.Trim()
            scan_started_at = (Get-Date).ToUniversalTime().AddMinutes(-1).ToString("o")
            scan_ended_at = (Get-Date).ToUniversalTime().ToString("o")
            endpoints = $endpoints
            hostname = $env:COMPUTERNAME
        } | ConvertTo-Json -Depth 5 -Compress
        try {
            $r = Invoke-RestMethod -Uri "$centerUrl/api/connector/lan-scan" `
                -Method POST -Headers @{ "X-API-Key" = $apiKey } `
                -Body $body -ContentType "application/json" -TimeoutSec 30
            [System.Windows.Forms.MessageBox]::Show("Inviati $($r.stored)/$($r.total) host al Center.`r`n`r`nVerifica nella dashboard Web nella sezione Discovery.","Scansione di rete","OK","Information") | Out-Null
        } catch {
            [System.Windows.Forms.MessageBox]::Show("Errore invio: $($_.Exception.Message)","Scansione di rete","OK","Error") | Out-Null
        }
    })

    [void]$form.ShowDialog()
}
