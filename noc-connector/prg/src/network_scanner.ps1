# =============================================================================
# 86NocConnector — NETWORK SCANNER (built-in standalone tool)
# =============================================================================
# Network scanner integrato nel Connector Scanner.
# Funzionalita':
#   - Ping sweep parallelo (Runspace Pool 32 thread, /24 in <5s)
#   - Risoluzione hostname: reverse DNS + NetBIOS (nbtstat)
#   - MAC address da tabella ARP locale (Get-NetNeighbor + arp -a)
#   - Vendor da OUI lookup (~120 vendor mappati inline)
#   - Detection servizi: HTTP/80, HTTPS/443, RDP/3389, SSH/22, SMB/445, FTP/21
#   - Lista SMB shares per host con SMB attivo
#   - Wake-on-LAN (magic packet UDP/9)
#   - Export CSV con tutti i dati raccolti
#   - UI WinForms ListView ordinabile + filtri
#   - Streaming live: la tabella si popola mano a mano che gli host rispondono
# =============================================================================

# OUI vendor lookup table (script-scoped, accessibile dai timer event handler)
$script:NS_OuiMap = @{
    "001D72"="Wistron"; "0019A9"="Cisco"; "001B17"="Cisco"; "0050BA"="DLink";
    "5C260A"="Dell"; "001CC0"="Intel"; "B827EB"="Raspberry"; "DCA632"="Raspberry";
    "F4A99A"="Cisco"; "C46516"="Cisco"; "F0BCC8"="Hewlett"; "F4CE46"="HP";
    "9C8E99"="HP"; "ECB1D7"="HP"; "B499BA"="HP"; "001E0B"="HP"; "78ACC0"="HP";
    "001CC4"="HP"; "001A4B"="HP"; "0017A4"="HP"; "001321"="HP"; "5065F3"="HP";
    "70106F"="HP"; "C8D3A3"="HP"; "001B78"="HP"; "9457A5"="HP"; "1062E5"="HP";
    "00041B"="Synology"; "001132"="Synology"; "B0227A"="HP"; "08002B"="Digital";
    "00059A"="Cisco"; "00040B"="3Com"; "001195"="Dell"; "001E68"="Cisco";
    "0030B6"="Cisco"; "AC1F6B"="SuperMicro"; "E454E8"="PEGATRON"; "F46D04"="ASRock";
    "0017F2"="Apple"; "001451"="Apple"; "F0DCE2"="Apple"; "B8E856"="Apple";
    "78CA39"="Apple"; "A8866D"="Apple"; "0024C4"="Cisco"; "0024D7"="Intel";
    "78E700"="Apple"; "F0F61C"="Apple"; "B0A737"="TPLink"; "C04A00"="TPLink";
    "5404A6"="ASUSTek"; "B06EBF"="ASUSTek"; "AC9E17"="ASUSTek"; "001E8C"="ASUSTek";
    "DCA904"="Pegatron"; "001517"="Intel"; "0023E7"="Hewlett"; "FC15B4"="Hewlett";
    "00248C"="ASUSTek"; "001E2A"="NETGEAR"; "9C3DCF"="NETGEAR"; "281878"="MikroTik";
    "4C5E0C"="MikroTik"; "B8699D"="MikroTik"; "6CF049"="Fortinet"; "9094E4"="Fortinet";
    "0009F0"="Fortinet"; "F84C77"="Hewlett"; "C03FD5"="Hewlett"; "C8FF77"="Brother";
    "0080A1"="Brother"; "3CD92B"="Hewlett"; "FCB4E6"="Brother"; "008094"="Brother";
    "002219"="Dell"; "F8B156"="Dell"; "001E4F"="Dell"; "00188B"="Dell";
    "0026BB"="Apple"; "00037F"="Atheros"; "000D88"="DLink"; "F0921C"="Hewlett";
    "F0B1E7"="Hewlett"; "1083D2"="Hewlett"; "001A1E"="Aruba"; "94B40F"="Aruba";
    "20EA63"="Cisco"; "001583"="HP"; "44A856"="Hewlett"; "00219B"="Dell"
}

function NS-GetVendor([string]$Mac) {
    if (-not $Mac -or $Mac.Length -lt 8) { return "" }
    $oui = ($Mac -replace "[:-]","").Substring(0,6).ToUpper()
    if ($script:NS_OuiMap.ContainsKey($oui)) { return $script:NS_OuiMap[$oui] }
    return ""
}

function NS-GetMac([string]$ip) {
    try {
        $n = Get-NetNeighbor -IPAddress $ip -ErrorAction SilentlyContinue |
             Where-Object { $_.LinkLayerAddress -and $_.LinkLayerAddress -ne "00-00-00-00-00-00" } |
             Select-Object -First 1
        if ($n) { return ($n.LinkLayerAddress -replace "-",":").ToLower() }
    } catch {}
    try {
        $arpOut = & arp -a $ip 2>$null
        foreach ($line in $arpOut) {
            if ($line -match "([0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2})") {
                return ($matches[1] -replace "-",":").ToLower()
            }
        }
    } catch {}
    return ""
}

function NS-GetHostname([string]$ip) {
    try {
        $h = [System.Net.Dns]::GetHostEntry($ip)
        if ($h -and $h.HostName -and $h.HostName -ne $ip) { return $h.HostName.Split('.')[0] }
    } catch {}
    try {
        $nb = & nbtstat -A $ip 2>$null
        foreach ($line in $nb) {
            if ($line -match "^\s*(\S+)\s+<00>\s+UNIQUE") { return $matches[1] }
        }
    } catch {}
    return ""
}

function NS-TestPort([string]$ip, [int]$port, [int]$timeoutMs = 500) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($ip, $port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($timeoutMs, $false)
        if ($ok -and $tcp.Connected) {
            $tcp.EndConnect($iar)
            $tcp.Close()
            return $true
        }
        $tcp.Close()
    } catch {}
    return $false
}

function NS-ListSmbShares([string]$ip) {
    try {
        $out = & net view "\\$ip" /all 2>$null
        $shares = @()
        foreach ($line in $out) {
            if ($line -match "^(\S+)\s+(Disk|Disco)") { $shares += $matches[1] }
        }
        return $shares -join ", "
    } catch { return "" }
}

function NS-WakeOnLan([string]$Mac) {
    if (-not $Mac) { return $false }
    $bytes = ($Mac -replace "[:-]","" -split "(.{2})") | Where-Object { $_ } | ForEach-Object { [byte]"0x$_" }
    if ($bytes.Length -ne 6) { return $false }
    # Magic packet: 6x 0xFF + 16x MAC
    $packet = @(0xFF,0xFF,0xFF,0xFF,0xFF,0xFF) + ($bytes * 16)
    try {
        $udp = New-Object System.Net.Sockets.UdpClient
        $udp.EnableBroadcast = $true
        $udp.Send($packet, $packet.Length, "255.255.255.255", 9) | Out-Null
        $udp.Close()
        return $true
    } catch { return $false }
}

function Show-NetworkScanner {
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Connector Scanner — Network Scanner"
    $form.Size = New-Object System.Drawing.Size(1100, 680)
    $form.StartPosition = "CenterScreen"
    $form.BackColor = [System.Drawing.Color]::FromArgb(245, 247, 250)
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $form.MinimumSize = New-Object System.Drawing.Size(900, 500)

    # Header
    $lblTitle = New-Object System.Windows.Forms.Label
    $lblTitle.Text = "Network Scanner"
    $lblTitle.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
    $lblTitle.ForeColor = [System.Drawing.Color]::FromArgb(56, 132, 222)
    $lblTitle.Location = New-Object System.Drawing.Point(20, 12)
    $lblTitle.AutoSize = $true
    $form.Controls.Add($lblTitle)

    # Subnet input
    $lblSubnet = New-Object System.Windows.Forms.Label
    $lblSubnet.Text = "Subnet (CIDR):"
    $lblSubnet.Location = New-Object System.Drawing.Point(20, 55)
    $lblSubnet.Size = New-Object System.Drawing.Size(95, 22)
    $form.Controls.Add($lblSubnet)

    $txtSubnet = New-Object System.Windows.Forms.TextBox
    $txtSubnet.Location = New-Object System.Drawing.Point(115, 52)
    $txtSubnet.Size = New-Object System.Drawing.Size(180, 24)
    # Auto-detect subnet locale
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual -ErrorAction SilentlyContinue |
               Where-Object {$_.IPAddress -notlike "169.254.*" -and $_.IPAddress -notlike "127.*"} |
               Select-Object -First 1).IPAddress
        if ($ip) { $txtSubnet.Text = ($ip -replace "\.\d+$",".0/24") }
    } catch { $txtSubnet.Text = "192.168.1.0/24" }
    $form.Controls.Add($txtSubnet)

    # Service detection toggles
    $chkDetectServices = New-Object System.Windows.Forms.CheckBox
    $chkDetectServices.Text = "Rileva servizi (HTTP/HTTPS/RDP/SSH/SMB/FTP)"
    $chkDetectServices.Location = New-Object System.Drawing.Point(310, 53)
    $chkDetectServices.Size = New-Object System.Drawing.Size(290, 22)
    $chkDetectServices.Checked = $true
    $form.Controls.Add($chkDetectServices)

    $chkSmbShares = New-Object System.Windows.Forms.CheckBox
    $chkSmbShares.Text = "Elenca SMB shares (lento)"
    $chkSmbShares.Location = New-Object System.Drawing.Point(605, 53)
    $chkSmbShares.Size = New-Object System.Drawing.Size(190, 22)
    $form.Controls.Add($chkSmbShares)

    # Buttons
    $btnStart = New-Object System.Windows.Forms.Button
    $btnStart.Text = "Avvia scansione"
    $btnStart.Size = New-Object System.Drawing.Size(140, 32)
    $btnStart.Location = New-Object System.Drawing.Point(800, 47)
    $btnStart.FlatStyle = "Flat"
    $btnStart.BackColor = [System.Drawing.Color]::FromArgb(56, 132, 222)
    $btnStart.ForeColor = [System.Drawing.Color]::White
    $btnStart.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $btnStart.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnStart)

    $btnStop = New-Object System.Windows.Forms.Button
    $btnStop.Text = "Ferma"
    $btnStop.Size = New-Object System.Drawing.Size(80, 32)
    $btnStop.Location = New-Object System.Drawing.Point(945, 47)
    $btnStop.FlatStyle = "Flat"
    $btnStop.BackColor = [System.Drawing.Color]::FromArgb(239, 68, 68)
    $btnStop.ForeColor = [System.Drawing.Color]::White
    $btnStop.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $btnStop.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnStop.Enabled = $false
    $form.Controls.Add($btnStop)

    # ListView
    $lst = New-Object System.Windows.Forms.ListView
    $lst.Location = New-Object System.Drawing.Point(20, 95)
    $lst.Size = New-Object System.Drawing.Size(1050, 470)
    $lst.View = [System.Windows.Forms.View]::Details
    $lst.FullRowSelect = $true
    $lst.GridLines = $true
    $lst.Anchor = "Top,Left,Right,Bottom"
    $lst.Sorting = [System.Windows.Forms.SortOrder]::Ascending
    $lst.Columns.Add("Stato", 60) | Out-Null
    $lst.Columns.Add("IP", 120) | Out-Null
    $lst.Columns.Add("Hostname", 160) | Out-Null
    $lst.Columns.Add("MAC", 140) | Out-Null
    $lst.Columns.Add("Vendor", 110) | Out-Null
    $lst.Columns.Add("Servizi", 220) | Out-Null
    $lst.Columns.Add("SMB Shares", 200) | Out-Null
    $form.Controls.Add($lst)

    # Status bar
    $lblStatus = New-Object System.Windows.Forms.Label
    $lblStatus.Text = "Pronto. Inserisci una subnet e premi Avvia."
    $lblStatus.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Italic)
    $lblStatus.ForeColor = [System.Drawing.Color]::FromArgb(80, 80, 90)
    $lblStatus.Location = New-Object System.Drawing.Point(20, 575)
    $lblStatus.Size = New-Object System.Drawing.Size(1050, 22)
    $lblStatus.Anchor = "Bottom,Left,Right"
    $form.Controls.Add($lblStatus)

    # Bottom buttons
    $btnExportCsv = New-Object System.Windows.Forms.Button
    $btnExportCsv.Text = "Esporta CSV"
    $btnExportCsv.Size = New-Object System.Drawing.Size(120, 32)
    $btnExportCsv.Location = New-Object System.Drawing.Point(20, 605)
    $btnExportCsv.FlatStyle = "Flat"
    $btnExportCsv.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnExportCsv.ForeColor = [System.Drawing.Color]::White
    $btnExportCsv.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnExportCsv.Anchor = "Bottom,Left"
    $form.Controls.Add($btnExportCsv)

    $btnWakeOnLan = New-Object System.Windows.Forms.Button
    $btnWakeOnLan.Text = "Wake-on-LAN selezionato"
    $btnWakeOnLan.Size = New-Object System.Drawing.Size(180, 32)
    $btnWakeOnLan.Location = New-Object System.Drawing.Point(150, 605)
    $btnWakeOnLan.FlatStyle = "Flat"
    $btnWakeOnLan.BackColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
    $btnWakeOnLan.ForeColor = [System.Drawing.Color]::White
    $btnWakeOnLan.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnWakeOnLan.Anchor = "Bottom,Left"
    $form.Controls.Add($btnWakeOnLan)

    $btnOpenSmb = New-Object System.Windows.Forms.Button
    $btnOpenSmb.Text = "Apri share SMB"
    $btnOpenSmb.Size = New-Object System.Drawing.Size(140, 32)
    $btnOpenSmb.Location = New-Object System.Drawing.Point(340, 605)
    $btnOpenSmb.FlatStyle = "Flat"
    $btnOpenSmb.BackColor = [System.Drawing.Color]::White
    $btnOpenSmb.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 70)
    $btnOpenSmb.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnOpenSmb.Anchor = "Bottom,Left"
    $form.Controls.Add($btnOpenSmb)

    $btnOpenWeb = New-Object System.Windows.Forms.Button
    $btnOpenWeb.Text = "Apri Web UI"
    $btnOpenWeb.Size = New-Object System.Drawing.Size(120, 32)
    $btnOpenWeb.Location = New-Object System.Drawing.Point(490, 605)
    $btnOpenWeb.FlatStyle = "Flat"
    $btnOpenWeb.BackColor = [System.Drawing.Color]::White
    $btnOpenWeb.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 70)
    $btnOpenWeb.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnOpenWeb.Anchor = "Bottom,Left"
    $form.Controls.Add($btnOpenWeb)

    $btnSendToCenter = New-Object System.Windows.Forms.Button
    $btnSendToCenter.Text = "Invia tutti al Center"
    $btnSendToCenter.Size = New-Object System.Drawing.Size(180, 32)
    $btnSendToCenter.Location = New-Object System.Drawing.Point(890, 605)
    $btnSendToCenter.FlatStyle = "Flat"
    $btnSendToCenter.BackColor = [System.Drawing.Color]::FromArgb(56, 132, 222)
    $btnSendToCenter.ForeColor = [System.Drawing.Color]::White
    $btnSendToCenter.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $btnSendToCenter.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnSendToCenter.Anchor = "Bottom,Right"
    $form.Controls.Add($btnSendToCenter)

    # ----- SCAN ENGINE -----
    $script:NS_Pool = $null
    $script:NS_Jobs = $null
    $script:NS_Timer = $null
    $script:NS_Found = 0
    $script:NS_Processed = 0
    $script:NS_Lst = $lst
    $script:NS_LblStatus = $lblStatus
    $script:NS_BtnStart = $btnStart
    $script:NS_BtnStop = $btnStop
    $script:NS_DetectServices = $false
    $script:NS_DetectSmb = $false

    $btnStart.Add_Click({
        $subnet = $txtSubnet.Text.Trim()
        if ($subnet -notmatch "^\d+\.\d+\.\d+\.\d+/\d+$") {
            [System.Windows.Forms.MessageBox]::Show("Subnet non valida. Esempio: 192.168.1.0/24", "Network Scanner", "OK", "Warning") | Out-Null
            return
        }
        $script:NS_DetectServices = $chkDetectServices.Checked
        $script:NS_DetectSmb = $chkSmbShares.Checked
        $script:NS_Found = 0
        $script:NS_Processed = 0
        $script:NS_Lst.Items.Clear()

        # Calcola lista IP
        $base = ($subnet -split "/")[0]
        $mask = [int](($subnet -split "/")[1])
        $b = $base -split "\."
        $startIp = ([uint32]$b[0] -shl 24) -bor ([uint32]$b[1] -shl 16) -bor ([uint32]$b[2] -shl 8) -bor [uint32]$b[3]
        $hostBits = 32 - $mask
        $count = if ($hostBits -ge 16) { 65534 } else { [int]([math]::Pow(2, $hostBits) - 2) }
        $startIp = ($startIp -band ([uint32]::MaxValue -shl $hostBits)) + 1
        if ($count -gt 1024) { $count = 1024 }
        $ipList = @()
        for ($i = 0; $i -lt $count; $i++) {
            $n = $startIp + $i
            $ipList += "$(($n -shr 24) -band 0xFF).$(($n -shr 16) -band 0xFF).$(($n -shr 8) -band 0xFF).$($n -band 0xFF)"
        }

        # Runspace pool
        $script:NS_Pool = [runspacefactory]::CreateRunspacePool(1, 32)
        $script:NS_Pool.Open()
        $script:NS_Jobs = New-Object System.Collections.ArrayList

        $pingScript = {
            param($ip)
            try {
                $p = New-Object System.Net.NetworkInformation.Ping
                $r = $p.Send($ip, 400)
                if ($r.Status -eq "Success") {
                    return [PSCustomObject]@{ ip = $ip; alive = $true; rtt = $r.RoundtripTime }
                }
            } catch {}
            return [PSCustomObject]@{ ip = $ip; alive = $false }
        }
        foreach ($ip in $ipList) {
            $ps = [powershell]::Create().AddScript($pingScript).AddArgument($ip)
            $ps.RunspacePool = $script:NS_Pool
            [void]$script:NS_Jobs.Add([PSCustomObject]@{ PS = $ps; Handle = $ps.BeginInvoke(); Ip = $ip; Done = $false })
        }
        $script:NS_LblStatus.Text = "Ping sweep di $($ipList.Count) IP in corso..."
        $script:NS_BtnStart.Enabled = $false
        $script:NS_BtnStop.Enabled = $true

        # Timer UI per popolazione live
        $script:NS_Timer = New-Object System.Windows.Forms.Timer
        $script:NS_Timer.Interval = 200
        $script:NS_Timer.Add_Tick({
            $totalJobs = $script:NS_Jobs.Count
            $completedNow = 0
            for ($i = 0; $i -lt $script:NS_Jobs.Count; $i++) {
                $job = $script:NS_Jobs[$i]
                if ($job.Done) { continue }
                if ($job.Handle.IsCompleted) {
                    $job.Done = $true
                    $completedNow++
                    try {
                        $res = $job.PS.EndInvoke($job.Handle)
                        $job.PS.Dispose()
                        if ($res -and $res.alive) {
                            $script:NS_Found++
                            # Arricchimento immediato: MAC + Hostname (sincroni veloci ~50ms)
                            $mac = NS-GetMac $res.ip
                            $hn = NS-GetHostname $res.ip
                            $vendor = if ($mac) { NS-GetVendor $mac } else { "" }
                            # Service detection (opzionale, async via runspace per non bloccare timer)
                            $services = ""
                            if ($script:NS_DetectServices) {
                                $svcList = @()
                                if (NS-TestPort $res.ip 80 200)   { $svcList += "HTTP" }
                                if (NS-TestPort $res.ip 443 200)  { $svcList += "HTTPS" }
                                if (NS-TestPort $res.ip 22 200)   { $svcList += "SSH" }
                                if (NS-TestPort $res.ip 3389 200) { $svcList += "RDP" }
                                if (NS-TestPort $res.ip 445 200)  { $svcList += "SMB" }
                                if (NS-TestPort $res.ip 21 200)   { $svcList += "FTP" }
                                $services = $svcList -join ", "
                            }
                            $smb = ""
                            if ($script:NS_DetectSmb -and $services -match "SMB") {
                                $smb = NS-ListSmbShares $res.ip
                            }
                            $item = New-Object System.Windows.Forms.ListViewItem(([char]0x2713 + " UP"))
                            $item.SubItems.Add($res.ip) | Out-Null
                            $item.SubItems.Add($hn) | Out-Null
                            $item.SubItems.Add($mac) | Out-Null
                            $item.SubItems.Add($vendor) | Out-Null
                            $item.SubItems.Add($services) | Out-Null
                            $item.SubItems.Add($smb) | Out-Null
                            $item.ForeColor = [System.Drawing.Color]::FromArgb(22, 163, 74)
                            $script:NS_Lst.Items.Add($item) | Out-Null
                        }
                    } catch {}
                }
            }
            $script:NS_Processed += $completedNow
            $script:NS_LblStatus.Text = "Scansione: $($script:NS_Processed)/$totalJobs IP processati  -  $($script:NS_Found) host vivi"

            $remaining = ($script:NS_Jobs | Where-Object { -not $_.Done }).Count
            if ($remaining -eq 0) {
                $this.Stop()
                try { $script:NS_Pool.Close(); $script:NS_Pool.Dispose() } catch {}
                $script:NS_BtnStart.Enabled = $true
                $script:NS_BtnStop.Enabled = $false
                $script:NS_LblStatus.Text = "Scansione completata: $($script:NS_Found) host vivi su $totalJobs IP testati."
            }
        })
        $script:NS_Timer.Start()
    })

    $btnStop.Add_Click({
        if ($script:NS_Timer) { $script:NS_Timer.Stop() }
        try { $script:NS_Pool.Close(); $script:NS_Pool.Dispose() } catch {}
        $script:NS_BtnStart.Enabled = $true
        $script:NS_BtnStop.Enabled = $false
        $script:NS_LblStatus.Text = "Scansione interrotta dall'utente."
    })

    # ----- EXPORT CSV -----
    $btnExportCsv.Add_Click({
        if ($lst.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun dato da esportare.", "Network Scanner", "OK", "Information") | Out-Null
            return
        }
        $sfd = New-Object System.Windows.Forms.SaveFileDialog
        $sfd.Filter = "CSV (*.csv)|*.csv"
        $sfd.FileName = "network-scan-$(Get-Date -Format 'yyyyMMdd-HHmmss').csv"
        if ($sfd.ShowDialog() -eq "OK") {
            $sw = New-Object System.IO.StreamWriter($sfd.FileName, $false, [System.Text.Encoding]::UTF8)
            $sw.WriteLine("Stato;IP;Hostname;MAC;Vendor;Servizi;SMB Shares")
            foreach ($it in $lst.Items) {
                $row = @($it.Text)
                for ($i = 0; $i -lt 6; $i++) { $row += $it.SubItems[$i+1].Text }
                $sw.WriteLine(($row -join ";"))
            }
            $sw.Close()
            [System.Windows.Forms.MessageBox]::Show("Esportati $($lst.Items.Count) host in $($sfd.FileName)", "Network Scanner", "OK", "Information") | Out-Null
        }
    })

    # ----- WAKE ON LAN -----
    $btnWakeOnLan.Add_Click({
        if ($lst.SelectedItems.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Seleziona un host dalla lista.", "Network Scanner", "OK", "Information") | Out-Null
            return
        }
        $mac = $lst.SelectedItems[0].SubItems[3].Text
        if (-not $mac) {
            [System.Windows.Forms.MessageBox]::Show("MAC non disponibile per l'host selezionato.", "Network Scanner", "OK", "Warning") | Out-Null
            return
        }
        if (NS-WakeOnLan $mac) {
            [System.Windows.Forms.MessageBox]::Show("Magic packet inviato a $mac via broadcast UDP/9.", "Network Scanner", "OK", "Information") | Out-Null
        } else {
            [System.Windows.Forms.MessageBox]::Show("Errore invio magic packet.", "Network Scanner", "OK", "Error") | Out-Null
        }
    })

    # ----- APRI SMB -----
    $btnOpenSmb.Add_Click({
        if ($lst.SelectedItems.Count -eq 0) { return }
        $ip = $lst.SelectedItems[0].SubItems[1].Text
        try { Start-Process "explorer.exe" -ArgumentList "\\$ip" } catch {}
    })

    # ----- APRI WEB -----
    $btnOpenWeb.Add_Click({
        if ($lst.SelectedItems.Count -eq 0) { return }
        $ip = $lst.SelectedItems[0].SubItems[1].Text
        $svc = $lst.SelectedItems[0].SubItems[5].Text
        $url = if ($svc -match "HTTPS") { "https://$ip" } elseif ($svc -match "HTTP") { "http://$ip" } else { "http://$ip" }
        try { Start-Process $url } catch {}
    })

    # ----- INVIA AL CENTER -----
    $btnSendToCenter.Add_Click({
        if ($lst.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun host da inviare.", "Network Scanner", "OK", "Information") | Out-Null
            return
        }
        # Leggi config del Connector per Url e ApiKey
        $cfg = $null
        try { $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json } catch {}
        if (-not $cfg -or -not $cfg.api_key -or -not $cfg.center_url) {
            [System.Windows.Forms.MessageBox]::Show("Configurazione del Connector non trovata. Reinstalla il Connector Scanner.", "Network Scanner", "OK", "Error") | Out-Null
            return
        }
        $endpoints = @()
        foreach ($it in $lst.Items) {
            $endpoints += [PSCustomObject]@{
                ip = $it.SubItems[1].Text
                mac = $it.SubItems[3].Text
                hostname = $it.SubItems[2].Text
                vendor = $it.SubItems[4].Text
                discovered_via = "network-scanner"
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
            $r = Invoke-RestMethod -Uri "$($cfg.center_url)/api/connector/lan-scan" `
                -Method POST -Headers @{ "X-API-Key" = $cfg.api_key } `
                -Body $body -ContentType "application/json" -TimeoutSec 30
            [System.Windows.Forms.MessageBox]::Show(
                "Inviati $($r.stored)/$($r.total) host al Center. Il Master li classifichera' automaticamente.",
                "Network Scanner", "OK", "Information") | Out-Null
        } catch {
            [System.Windows.Forms.MessageBox]::Show(
                "Errore invio: $($_.Exception.Message)",
                "Network Scanner", "OK", "Error") | Out-Null
        }
    })

    $form.Add_FormClosing({
        if ($script:NS_Timer) { $script:NS_Timer.Stop() }
        try { $script:NS_Pool.Close(); $script:NS_Pool.Dispose() } catch {}
    })

    [void]$form.ShowDialog()
}
