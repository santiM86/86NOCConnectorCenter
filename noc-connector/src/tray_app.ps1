<#
.SYNOPSIS
    86NocConnector - System Tray Application
.DESCRIPTION
    Icona nella system tray vicino all'orologio.
    Usa .NET Windows.Forms nativo (incluso in Windows).
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$AppName = "86NocConnector"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = Split-Path -Parent $ScriptDir
$versionFile = Join-Path $BaseDir "version.json"
if (Test-Path $versionFile) {
    $vInfo = Get-Content $versionFile -Raw | ConvertFrom-Json
    $Version = $vInfo.version
} else {
    $Version = "1.0.0"
}
$ConnectorScript = Join-Path $ScriptDir "connector.ps1"
$ConfigDir = Join-Path $env:ProgramData $AppName
$ConfigPath = Join-Path $ConfigDir "config.json"
$LogPath = Join-Path $ConfigDir "logs\connector.log"

# ==================== ICON GENERATION ====================

function New-TrayIcon([string]$status = "running") {
    $bmp = New-Object System.Drawing.Bitmap(32, 32)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    
    # Background color based on status
    switch ($status) {
        "running" { $bgColor = [System.Drawing.Color]::FromArgb(34, 197, 94) }   # Green
        "error"   { $bgColor = [System.Drawing.Color]::FromArgb(239, 68, 68) }   # Red
        "stopped" { $bgColor = [System.Drawing.Color]::FromArgb(107, 114, 128) }  # Gray
        default   { $bgColor = [System.Drawing.Color]::FromArgb(99, 102, 241) }   # Purple
    }
    
    # Draw rounded rect background
    $brush = New-Object System.Drawing.SolidBrush($bgColor)
    $g.FillRectangle($brush, 0, 0, 32, 32)
    
    # Draw "86" text
    $font = New-Object System.Drawing.Font("Arial", 10, [System.Drawing.FontStyle]::Bold)
    $whiteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $g.DrawString("86", $font, $whiteBrush, 2, 1)
    
    # Draw "NC" text smaller
    $fontSmall = New-Object System.Drawing.Font("Arial", 7, [System.Drawing.FontStyle]::Bold)
    $g.DrawString("NC", $fontSmall, $whiteBrush, 5, 18)
    
    # Status dot
    $dotColor = switch ($status) {
        "running" { [System.Drawing.Color]::White }
        "error"   { [System.Drawing.Color]::FromArgb(254, 202, 202) }
        default   { [System.Drawing.Color]::FromArgb(200, 200, 200) }
    }
    $dotBrush = New-Object System.Drawing.SolidBrush($dotColor)
    $g.FillEllipse($dotBrush, 24, 24, 7, 7)
    
    $g.Dispose()
    $font.Dispose()
    $fontSmall.Dispose()
    $brush.Dispose()
    $whiteBrush.Dispose()
    $dotBrush.Dispose()
    
    $hIcon = $bmp.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($hIcon)
    return $icon
}

# ==================== CONNECTOR PROCESS (via Scheduled Task) ====================

$global:ConnectorProcess = $null
$global:IsRunning = $false
$global:TaskName = "86NocConnectorService"

<#
.SYNOPSIS
    Legge lo status file scritto dal connector engine.
    Ritorna $null se il file non esiste o e' vecchio (>120s).
#>
function Read-ConnectorStatus {
    $statusPath = Join-Path $ConfigDir "status.json"
    if (-not (Test-Path $statusPath)) { return $null }
    try {
        $data = Get-Content $statusPath -Raw | ConvertFrom-Json
        # Se l'ultimo aggiornamento e' piu' vecchio di 120s, il connettore e' morto
        $lastUpdate = [datetime]::ParseExact($data.last_update, "yyyy-MM-ddTHH:mm:ss", $null)
        $age = (Get-Date) - $lastUpdate
        if ($age.TotalSeconds -gt 120) { return $null }
        return $data
    } catch { return $null }
}

<#
.SYNOPSIS
    Verifica se il Scheduled Task del connettore esiste ed e' in esecuzione.
#>
function Test-ConnectorTask {
    try {
        $task = Get-ScheduledTask -TaskName $global:TaskName -ErrorAction SilentlyContinue
        return ($task -and $task.State -eq "Running")
    } catch { return $false }
}

<#
.SYNOPSIS
    Registra il connettore come Windows Scheduled Task.
    Gira come SYSTEM, sopravvive a disconnessioni RDP.
#>
function Register-ConnectorTask {
    try {
        # Rimuovi vecchio task se esiste
        Unregister-ScheduledTask -TaskName $global:TaskName -Confirm:$false -ErrorAction SilentlyContinue
        
        $action = New-ScheduledTaskAction `
            -Execute "powershell.exe" `
            -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ConnectorScript`"" `
            -WorkingDirectory (Split-Path $ConnectorScript)
        
        # Trigger: all'avvio del sistema
        $triggerBoot = New-ScheduledTaskTrigger -AtStartup
        
        # Settings: riavvio automatico se fallisce, no scadenza, puo' girare su batteria
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Days 365)
        
        Register-ScheduledTask `
            -TaskName $global:TaskName `
            -Action $action `
            -Trigger $triggerBoot `
            -Settings $settings `
            -RunLevel Highest `
            -User "SYSTEM" `
            -Description "86NocConnector - Servizio di raccolta SNMP/Syslog per il NOC Center. Gira in background indipendentemente dalla sessione utente." `
            -ErrorAction Stop
        
        return $true
    } catch {
        Write-Host "Errore registrazione task: $($_.Exception.Message)"
        return $false
    }
}

function Start-ConnectorViaTask {
    try {
        # Prima prova via Scheduled Task
        $task = Get-ScheduledTask -TaskName $global:TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Start-ScheduledTask -TaskName $global:TaskName -ErrorAction Stop
            Start-Sleep -Seconds 2
            $global:IsRunning = $true
            return $true
        }
        
        # Fallback: registra il task e avvialo
        if (Register-ConnectorTask) {
            Start-ScheduledTask -TaskName $global:TaskName -ErrorAction Stop
            Start-Sleep -Seconds 2
            $global:IsRunning = $true
            return $true
        }
        
        # Ultimo fallback: avvia direttamente (vecchio metodo, per retrocompatibilita')
        return Start-ConnectorDirect
    } catch {
        # Se non abbiamo i permessi per Task Scheduler, avvia direttamente
        return Start-ConnectorDirect
    }
}

function Start-ConnectorDirect {
    if ($global:ConnectorProcess -and !$global:ConnectorProcess.HasExited) {
        return $true
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "powershell.exe"
    $psi.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ConnectorScript`""
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.CreateNoWindow = $true
    $psi.UseShellExecute = $false
    try {
        $global:ConnectorProcess = [System.Diagnostics.Process]::Start($psi)
        $global:IsRunning = $true
        return $true
    } catch {
        $global:IsRunning = $false
        return $false
    }
}

function Stop-ConnectorProcess {
    # Ferma via Scheduled Task
    try {
        Stop-ScheduledTask -TaskName $global:TaskName -ErrorAction SilentlyContinue
    } catch {}
    
    # Ferma anche eventuali processi diretti
    if ($global:ConnectorProcess -and !$global:ConnectorProcess.HasExited) {
        try {
            $global:ConnectorProcess.Kill()
            $global:ConnectorProcess.WaitForExit(5000)
        } catch {}
    }
    
    # Kill qualsiasi processo connector.ps1 orfano
    Get-Process -Name powershell, pwsh -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Id -ne $PID) {
            try {
                $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
                if ($cmdLine -match "connector\.ps1") {
                    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
    }
    $global:IsRunning = $false
}

function Get-StatusText {
    $status = Read-ConnectorStatus
    if ($status -and $status.status -eq "running") {
        $upH = [math]::Floor($status.uptime_seconds / 3600)
        $upM = [math]::Floor(($status.uptime_seconds % 3600) / 60)
        $config = if (Test-Path $ConfigPath) { Get-Content $ConfigPath -Raw | ConvertFrom-Json } else { $null }
        $nocUrl = if ($config) { $config.noc_center_url } else { "N/D" }
        $taskRunning = Test-ConnectorTask
        $mode = if ($taskRunning) { "Servizio Windows (Task)" } else { "Processo diretto" }
        return "$AppName v$($status.version)`nStato: ATTIVO ($mode)`nUptime: ${upH}h ${upM}m`nNOC: $nocUrl`nSNMP: $($status.snmp_received) | Syslog: $($status.syslog_received)"
    }
    return "$AppName v$Version`nStato: FERMO"
}

# ==================== DEVICE MANAGER ====================

function Show-DeviceManager {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "$AppName - Gestisci Dispositivi"
    $form.Size = New-Object System.Drawing.Size(580, 520)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(245, 245, 248)
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

    # Title
    $lblTitle = New-Object System.Windows.Forms.Label
    $lblTitle.Text = "Dispositivi Monitorati (SNMP Polling)"
    $lblTitle.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
    $lblTitle.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 40)
    $lblTitle.Location = New-Object System.Drawing.Point(20, 15)
    $lblTitle.AutoSize = $true
    $form.Controls.Add($lblTitle)

    $lblDesc = New-Object System.Windows.Forms.Label
    $lblDesc.Text = "Aggiungi o rimuovi switch, firewall e server da monitorare via SNMP."
    $lblDesc.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
    $lblDesc.ForeColor = [System.Drawing.Color]::FromArgb(100, 100, 115)
    $lblDesc.Location = New-Object System.Drawing.Point(20, 42)
    $lblDesc.AutoSize = $true
    $form.Controls.Add($lblDesc)

    # Input row
    $lblIP = New-Object System.Windows.Forms.Label
    $lblIP.Text = "IP Address"
    $lblIP.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $lblIP.ForeColor = [System.Drawing.Color]::FromArgb(50, 50, 65)
    $lblIP.Location = New-Object System.Drawing.Point(20, 72)
    $lblIP.AutoSize = $true
    $form.Controls.Add($lblIP)

    $txtIP = New-Object System.Windows.Forms.TextBox
    $txtIP.Location = New-Object System.Drawing.Point(20, 90)
    $txtIP.Size = New-Object System.Drawing.Size(130, 26)
    $txtIP.Font = New-Object System.Drawing.Font("Consolas", 9.5)
    $form.Controls.Add($txtIP)

    $lblComm = New-Object System.Windows.Forms.Label
    $lblComm.Text = "Community"
    $lblComm.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $lblComm.ForeColor = [System.Drawing.Color]::FromArgb(50, 50, 65)
    $lblComm.Location = New-Object System.Drawing.Point(160, 72)
    $lblComm.AutoSize = $true
    $form.Controls.Add($lblComm)

    $txtComm = New-Object System.Windows.Forms.TextBox
    $txtComm.Location = New-Object System.Drawing.Point(160, 90)
    $txtComm.Size = New-Object System.Drawing.Size(100, 26)
    $txtComm.Font = New-Object System.Drawing.Font("Consolas", 9.5)
    $txtComm.Text = "public"
    $form.Controls.Add($txtComm)

    $lblName = New-Object System.Windows.Forms.Label
    $lblName.Text = "Nome dispositivo"
    $lblName.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $lblName.ForeColor = [System.Drawing.Color]::FromArgb(50, 50, 65)
    $lblName.Location = New-Object System.Drawing.Point(270, 72)
    $lblName.AutoSize = $true
    $form.Controls.Add($lblName)

    $txtName = New-Object System.Windows.Forms.TextBox
    $txtName.Location = New-Object System.Drawing.Point(270, 90)
    $txtName.Size = New-Object System.Drawing.Size(180, 26)
    $txtName.Font = New-Object System.Drawing.Font("Consolas", 9.5)
    $form.Controls.Add($txtName)

    $btnAdd = New-Object System.Windows.Forms.Button
    $btnAdd.Text = "Aggiungi"
    $btnAdd.Size = New-Object System.Drawing.Size(80, 26)
    $btnAdd.Location = New-Object System.Drawing.Point(458, 90)
    $btnAdd.FlatStyle = "Flat"
    $btnAdd.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnAdd.ForeColor = [System.Drawing.Color]::White
    $btnAdd.Font = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Bold)
    $btnAdd.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnAdd)

    # ListView
    $listView = New-Object System.Windows.Forms.ListView
    $listView.Location = New-Object System.Drawing.Point(20, 130)
    $listView.Size = New-Object System.Drawing.Size(518, 240)
    $listView.View = [System.Windows.Forms.View]::Details
    $listView.FullRowSelect = $true
    $listView.GridLines = $true
    $listView.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $listView.BackColor = [System.Drawing.Color]::White
    $null = $listView.Columns.Add("IP Address", 150)
    $null = $listView.Columns.Add("Community", 100)
    $null = $listView.Columns.Add("Nome", 260)
    $form.Controls.Add($listView)

    # Load current devices from config
    if (Test-Path $ConfigPath) {
        $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($config.devices) {
            foreach ($dev in $config.devices) {
                $item = New-Object System.Windows.Forms.ListViewItem($dev.ip)
                $null = $item.SubItems.Add($dev.community)
                $null = $item.SubItems.Add($dev.name)
                $listView.Items.Add($item)
            }
        }
    }

    # Export/Import row
    $btnExport = New-Object System.Windows.Forms.Button
    $btnExport.Text = "Esporta CSV"
    $btnExport.Size = New-Object System.Drawing.Size(110, 28)
    $btnExport.Location = New-Object System.Drawing.Point(20, 378)
    $btnExport.FlatStyle = "Flat"
    $btnExport.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnExport.ForeColor = [System.Drawing.Color]::White
    $btnExport.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $btnExport.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnExport)

    $btnImport = New-Object System.Windows.Forms.Button
    $btnImport.Text = "Importa CSV"
    $btnImport.Size = New-Object System.Drawing.Size(110, 28)
    $btnImport.Location = New-Object System.Drawing.Point(140, 378)
    $btnImport.FlatStyle = "Flat"
    $btnImport.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnImport.ForeColor = [System.Drawing.Color]::White
    $btnImport.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $btnImport.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnImport)

    # Bottom buttons row
    $btnRemove = New-Object System.Windows.Forms.Button
    $btnRemove.Text = "Rimuovi selezionato"
    $btnRemove.Size = New-Object System.Drawing.Size(125, 30)
    $btnRemove.Location = New-Object System.Drawing.Point(20, 415)
    $btnRemove.FlatStyle = "Flat"
    $btnRemove.BackColor = [System.Drawing.Color]::White
    $btnRemove.ForeColor = [System.Drawing.Color]::FromArgb(220, 50, 50)
    $btnRemove.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
    $btnRemove.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnRemove)

    $btnTestSnmp = New-Object System.Windows.Forms.Button
    $btnTestSnmp.Text = "Test SNMP"
    $btnTestSnmp.Size = New-Object System.Drawing.Size(110, 30)
    $btnTestSnmp.Location = New-Object System.Drawing.Point(225, 415)
    $btnTestSnmp.FlatStyle = "Flat"
    $btnTestSnmp.BackColor = [System.Drawing.Color]::FromArgb(59, 130, 246)
    $btnTestSnmp.ForeColor = [System.Drawing.Color]::White
    $btnTestSnmp.Font = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Bold)
    $btnTestSnmp.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnTestSnmp)

    $btnSave = New-Object System.Windows.Forms.Button
    $btnSave.Text = "Salva e Riavvia"
    $btnSave.Size = New-Object System.Drawing.Size(135, 30)
    $btnSave.Location = New-Object System.Drawing.Point(403, 415)
    $btnSave.FlatStyle = "Flat"
    $btnSave.BackColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
    $btnSave.ForeColor = [System.Drawing.Color]::White
    $btnSave.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $btnSave.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnSave)

    $lblHint = New-Object System.Windows.Forms.Label
    $lblHint.Text = "Il connector verra' riavviato per applicare le modifiche."
    $lblHint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $lblHint.ForeColor = [System.Drawing.Color]::FromArgb(140, 140, 155)
    $lblHint.Location = New-Object System.Drawing.Point(20, 455)
    $lblHint.AutoSize = $true
    $form.Controls.Add($lblHint)

    # Add button handler
    $btnAdd.Add_Click({
        $ip = $txtIP.Text.Trim()
        if (-not $ip) {
            [System.Windows.Forms.MessageBox]::Show("Inserisci un indirizzo IP.", $AppName, "OK", "Warning")
            return
        }
        $comm = if ($txtComm.Text.Trim()) { $txtComm.Text.Trim() } else { "public" }
        $devName = if ($txtName.Text.Trim()) { $txtName.Text.Trim() } else { $ip }

        # Check duplicate
        foreach ($existing in $listView.Items) {
            if ($existing.Text -eq $ip) {
                [System.Windows.Forms.MessageBox]::Show("IP gia' presente nella lista.", $AppName, "OK", "Warning")
                return
            }
        }

        $item = New-Object System.Windows.Forms.ListViewItem($ip)
        $null = $item.SubItems.Add($comm)
        $null = $item.SubItems.Add($devName)
        $listView.Items.Add($item)
        $txtIP.Text = ""
        $txtName.Text = ""
    })

    # Export CSV handler
    $btnExport.Add_Click({
        if ($listView.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun dispositivo da esportare.", $AppName, "OK", "Warning")
            return
        }
        $saveDialog = New-Object System.Windows.Forms.SaveFileDialog
        $saveDialog.Filter = "CSV (*.csv)|*.csv"
        $saveDialog.FileName = "dispositivi_86NocConnector.csv"
        $saveDialog.Title = "Esporta dispositivi"
        if ($saveDialog.ShowDialog() -eq "OK") {
            $lines = @("IP,Community,Nome")
            foreach ($item in $listView.Items) {
                $lines += "$($item.Text),$($item.SubItems[1].Text),$($item.SubItems[2].Text)"
            }
            $lines -join "`r`n" | Set-Content $saveDialog.FileName -Encoding UTF8
            [System.Windows.Forms.MessageBox]::Show("$($listView.Items.Count) dispositivi esportati in:`n$($saveDialog.FileName)", $AppName, "OK", "Information")
        }
    })

    # Import CSV handler
    $btnImport.Add_Click({
        $openDialog = New-Object System.Windows.Forms.OpenFileDialog
        $openDialog.Filter = "CSV (*.csv)|*.csv|Tutti i file (*.*)|*.*"
        $openDialog.Title = "Importa dispositivi"
        if ($openDialog.ShowDialog() -eq "OK") {
            $lines = Get-Content $openDialog.FileName -Encoding UTF8 | Where-Object { $_.Trim() -ne "" }
            $imported = 0
            foreach ($line in $lines) {
                if ($line.Trim().ToLower().StartsWith("ip")) { continue }
                $parts = $line.Split(",")
                $ip = $parts[0].Trim()
                $comm = if ($parts.Length -gt 1 -and $parts[1].Trim()) { $parts[1].Trim() } else { "public" }
                $devName = if ($parts.Length -gt 2 -and $parts[2].Trim()) { $parts[2].Trim() } else { $ip }
                if (-not $ip) { continue }
                # Check duplicate
                $duplicate = $false
                foreach ($existing in $listView.Items) {
                    if ($existing.Text -eq $ip) { $duplicate = $true; break }
                }
                if ($duplicate) { continue }
                $item = New-Object System.Windows.Forms.ListViewItem($ip)
                $null = $item.SubItems.Add($comm)
                $null = $item.SubItems.Add($devName)
                $listView.Items.Add($item)
                $imported++
            }
            [System.Windows.Forms.MessageBox]::Show("$imported dispositivi importati.", $AppName, "OK", "Information")
        }
    })

    # Remove button handler
    $btnRemove.Add_Click({
        if ($listView.SelectedItems.Count -gt 0) {
            $listView.Items.Remove($listView.SelectedItems[0])
        } else {
            [System.Windows.Forms.MessageBox]::Show("Seleziona un dispositivo dalla lista.", $AppName, "OK", "Information")
        }
    })

    # Test SNMP button handler
    $btnTestSnmp.Add_Click({
        if ($listView.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun dispositivo nella lista.", $AppName, "OK", "Warning")
            return
        }
        $btnTestSnmp.Enabled = $false
        $btnTestSnmp.Text = "Testing..."
        $form.Refresh()
        
        $results = ""
        foreach ($item in $listView.Items) {
            $ip = $item.Text
            $community = $item.SubItems[1].Text
            $devName = $item.SubItems[2].Text
            $results += "== $devName ($ip) ==`r`n"
            
            # Test 1: Ping
            $pingOk = $false
            try {
                $ping = New-Object System.Net.NetworkInformation.Ping
                $reply = $ping.Send($ip, 2000)
                if ($reply.Status -eq "Success") {
                    $results += "  PING: OK ($($reply.RoundtripTime)ms)`r`n"
                    $pingOk = $true
                } else {
                    $results += "  PING: FALLITO ($($reply.Status))`r`n"
                }
                $ping.Dispose()
            } catch {
                $results += "  PING: ERRORE - $($_.Exception.Message)`r`n"
            }
            
            # Test 2: SNMP GET sysDescr
            try {
                $udp = New-Object System.Net.Sockets.UdpClient
                $udp.Client.ReceiveTimeout = 3000
                
                # Build simple SNMP v2c GET for sysDescr (1.3.6.1.2.1.1.1.0)
                $oid = @(0x06, 0x08, 0x2B, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00)
                $varbind = @(0x30) + @([byte]($oid.Length + 2)) + $oid + @(0x05, 0x00)
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
                $packet = @(0x30) + @([byte]$msgContent.Length) + $msgContent
                
                $ep = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse($ip), 161)
                $null = $udp.Send([byte[]]$packet, $packet.Length, $ep)
                $remoteEP = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
                $response = $udp.Receive([ref]$remoteEP)
                $udp.Close()
                
                if ($response.Length -gt 20) {
                    $results += "  SNMP: OK (risposta $($response.Length) bytes)`r`n"
                } else {
                    $results += "  SNMP: RISPOSTA ANOMALA ($($response.Length) bytes)`r`n"
                }
            } catch [System.Net.Sockets.SocketException] {
                $udp.Close()
                if ($_.Exception.SocketErrorCode -eq "TimedOut") {
                    $results += "  SNMP: TIMEOUT - nessuna risposta UDP 161`r`n"
                    $results += "         Verifica: SNMP abilitato? Community '$community' corretta? Firewall?`r`n"
                } else {
                    $results += "  SNMP: ERRORE SOCKET - $($_.Exception.Message)`r`n"
                }
            } catch {
                try { $udp.Close() } catch {}
                $results += "  SNMP: ERRORE - $($_.Exception.Message)`r`n"
            }
            $results += "`r`n"
        }
        
        # Show results
        $resultForm = New-Object System.Windows.Forms.Form
        $resultForm.Text = "$AppName - Risultati Test SNMP"
        $resultForm.Size = New-Object System.Drawing.Size(520, 350)
        $resultForm.StartPosition = "CenterScreen"
        $resultForm.FormBorderStyle = "FixedDialog"
        $resultForm.MaximizeBox = $false
        
        $txtResult = New-Object System.Windows.Forms.TextBox
        $txtResult.Multiline = $true
        $txtResult.ScrollBars = "Vertical"
        $txtResult.ReadOnly = $true
        $txtResult.Font = New-Object System.Drawing.Font("Consolas", 9.5)
        $txtResult.Location = New-Object System.Drawing.Point(10, 10)
        $txtResult.Size = New-Object System.Drawing.Size(490, 290)
        $txtResult.Text = $results
        $resultForm.Controls.Add($txtResult)
        
        $resultForm.ShowDialog()
        
        $btnTestSnmp.Enabled = $true
        $btnTestSnmp.Text = "Test SNMP"
    })

    # Save button handler
    $btnSave.Add_Click({
        if (Test-Path $ConfigPath) {
            $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        } else {
            [System.Windows.Forms.MessageBox]::Show("Nessuna configurazione trovata. Esegui prima l'installer.", $AppName, "OK", "Error")
            return
        }

        # Build devices array
        $devicesArray = @()
        foreach ($item in $listView.Items) {
            $devicesArray += @{
                ip = $item.Text
                community = $item.SubItems[1].Text
                name = $item.SubItems[2].Text
            }
        }

        # Update config - preserve existing settings, update devices
        $configHash = @{}
        foreach ($prop in $config.PSObject.Properties) {
            $configHash[$prop.Name] = $prop.Value
        }
        $configHash["devices"] = $devicesArray
        $configHash | ConvertTo-Json -Depth 5 | Set-Content $ConfigPath -Encoding UTF8

        $result = [System.Windows.Forms.MessageBox]::Show(
            "Configurazione salvata con $($devicesArray.Count) dispositivi.`n`nVuoi riavviare il connector per applicare le modifiche?",
            $AppName,
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )

        if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {
            # Signal to restart - set a flag file
            $restartFlag = Join-Path $ConfigDir "restart_requested"
            "1" | Set-Content $restartFlag
            $form.Close()
        } else {
            $form.Close()
        }
    })

    $form.ShowDialog()

    # Check if restart was requested
    $restartFlag = Join-Path $ConfigDir "restart_requested"
    if (Test-Path $restartFlag) {
        Remove-Item $restartFlag -Force -ErrorAction SilentlyContinue
        return $true  # Signal caller to restart connector
    }
    return $false
}

# ==================== TRAY APPLICATION ====================

function Start-TrayApp {
    [System.Windows.Forms.Application]::EnableVisualStyles()
    
    # ===== Single Instance Check: kill any previous tray_app.ps1 =====
    $currentPid = $PID
    Get-Process -Name powershell, pwsh -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Id -ne $currentPid) {
            try {
                $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
                if ($cmdLine -match "tray_app\.ps1") {
                    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
    }
    # Brief wait for old icons to clear
    Start-Sleep -Milliseconds 500
    
    # Force Windows to refresh the tray area (clears ghost icons)
    try {
        $shellTray = [System.IntPtr]::Zero
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public class TrayRefresh {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")] public static extern IntPtr FindWindowEx(IntPtr hwndParent, IntPtr hwndChildAfter, string lpszClass, string lpszWindow);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public static void Refresh() {
        IntPtr tray = FindWindow("Shell_TrayWnd", null);
        IntPtr notify = FindWindowEx(tray, IntPtr.Zero, "TrayNotifyWnd", null);
        IntPtr pager = FindWindowEx(notify, IntPtr.Zero, "SysPager", null);
        IntPtr toolbar = FindWindowEx(pager, IntPtr.Zero, "ToolbarWindow32", null);
        if (toolbar == IntPtr.Zero) toolbar = FindWindowEx(notify, IntPtr.Zero, "ToolbarWindow32", null);
        if (toolbar != IntPtr.Zero) {
            RECT r; GetClientRect(toolbar, out r);
            for (int x = 0; x < r.Right; x += 10)
                for (int y = 0; y < r.Bottom; y += 10)
                    SendMessage(toolbar, 0x0200, IntPtr.Zero, (IntPtr)((y << 16) | x));
        }
    }
}
"@ -ErrorAction SilentlyContinue
        [TrayRefresh]::Refresh()
    } catch {}
    
    $notifyIcon = New-Object System.Windows.Forms.NotifyIcon
    $notifyIcon.Icon = New-TrayIcon "stopped"
    $notifyIcon.Text = "$AppName - Avvio..."
    $notifyIcon.Visible = $true
    
    # Context Menu
    $contextMenu = New-Object System.Windows.Forms.ContextMenuStrip
    $contextMenu.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 50)
    $contextMenu.ForeColor = [System.Drawing.Color]::White
    $contextMenu.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    
    # Title item (disabled)
    $titleItem = $contextMenu.Items.Add("$AppName v$Version")
    $titleItem.Enabled = $false
    $titleItem.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $titleItem.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    
    $contextMenu.Items.Add("-") | Out-Null
    
    # Status
    $statusItem = $contextMenu.Items.Add("Stato")
    $statusItem.Add_Click({
        $text = Get-StatusText
        [System.Windows.Forms.MessageBox]::Show($text, "$AppName - Stato", 
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information)
    })
    
    # Open NOC Center
    $nocItem = $contextMenu.Items.Add("Apri NOC Center")
    $nocItem.Add_Click({
        if (Test-Path $ConfigPath) {
            $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
            if ($config.noc_center_url) {
                Start-Process $config.noc_center_url
            }
        }
    })
    
    $contextMenu.Items.Add("-") | Out-Null
    
    # Start
    $startItem = $contextMenu.Items.Add("Avvia")
    $startItem.ForeColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
    $startItem.Add_Click({
        if (Start-ConnectorViaTask) {
            $notifyIcon.Icon = New-TrayIcon "running"
            $notifyIcon.Text = "$AppName - Attivo"
            $notifyIcon.ShowBalloonTip(3000, $AppName, "Connector avviato e in ascolto", [System.Windows.Forms.ToolTipIcon]::Info)
            $startItem.Visible = $false
            $stopItem.Visible = $true
            $restartItem.Visible = $true
        } else {
            [System.Windows.Forms.MessageBox]::Show("Errore avvio. Verifica la configurazione.", $AppName,
                [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        }
    })
    
    # Stop
    $stopItem = $contextMenu.Items.Add("Ferma")
    $stopItem.ForeColor = [System.Drawing.Color]::FromArgb(239, 68, 68)
    $stopItem.Visible = $false
    $stopItem.Add_Click({
        Stop-ConnectorProcess
        $notifyIcon.Icon = New-TrayIcon "stopped"
        $notifyIcon.Text = "$AppName - Fermo"
        $notifyIcon.ShowBalloonTip(2000, $AppName, "Connector fermato", [System.Windows.Forms.ToolTipIcon]::Warning)
        $startItem.Visible = $true
        $stopItem.Visible = $false
        $restartItem.Visible = $false
    })
    
    # Restart
    $restartItem = $contextMenu.Items.Add("Riavvia")
    $restartItem.Visible = $false
    $restartItem.Add_Click({
        Stop-ConnectorProcess
        Start-Sleep -Seconds 1
        if (Start-ConnectorViaTask) {
            $notifyIcon.Icon = New-TrayIcon "running"
            $notifyIcon.Text = "$AppName - Attivo"
            $notifyIcon.ShowBalloonTip(2000, $AppName, "Connector riavviato", [System.Windows.Forms.ToolTipIcon]::Info)
        }
    })
    
    $contextMenu.Items.Add("-") | Out-Null
    
    # View Logs
    $logItem = $contextMenu.Items.Add("Visualizza Log")
    $logItem.Add_Click({
        $logFile = Join-Path (Join-Path $env:ProgramData $AppName) "logs\connector.log"
        if (Test-Path $logFile) {
            Start-Process "notepad.exe" -ArgumentList $logFile
        } else {
            [System.Windows.Forms.MessageBox]::Show("File log non ancora creato.", $AppName)
        }
    })
    
    # Edit Config
    $configItem = $contextMenu.Items.Add("Configurazione")
    $configItem.Add_Click({
        if (Test-Path $ConfigPath) {
            Start-Process "notepad.exe" -ArgumentList $ConfigPath
        } else {
            [System.Windows.Forms.MessageBox]::Show("Nessuna configurazione. Esegui install.bat", $AppName)
        }
    })

    # Manage Devices
    $devicesItem = $contextMenu.Items.Add("Gestisci Dispositivi")
    $devicesItem.ForeColor = [System.Drawing.Color]::FromArgb(96, 165, 250)
    $devicesItem.Add_Click({
        $shouldRestart = Show-DeviceManager
        if ($shouldRestart) {
            # Restart connector process
            Stop-ConnectorProcess
            Start-Sleep -Seconds 1
            if (Start-ConnectorViaTask) {
                $notifyIcon.Icon = New-TrayIcon "running"
                $notifyIcon.Text = "$AppName - Attivo (riavviato)"
                $notifyIcon.ShowBalloonTip(3000, $AppName, "Connector riavviato con nuovi dispositivi", [System.Windows.Forms.ToolTipIcon]::Info)
            }
        }
    })
    
    $contextMenu.Items.Add("-") | Out-Null

    # Informazioni / About
    $aboutItem = $contextMenu.Items.Add("Informazioni")
    $aboutItem.Add_Click({
        $aboutForm = New-Object System.Windows.Forms.Form
        $aboutForm.Text = "$AppName - Informazioni"
        $aboutForm.Size = New-Object System.Drawing.Size(420, 340)
        $aboutForm.StartPosition = "CenterScreen"
        $aboutForm.FormBorderStyle = "FixedDialog"
        $aboutForm.MaximizeBox = $false
        $aboutForm.MinimizeBox = $false
        $aboutForm.BackColor = [System.Drawing.Color]::White

        # Logo
        $logoPath = Join-Path $ScriptDir "86bit_logo.jpg"
        if (Test-Path $logoPath) {
            $picBox = New-Object System.Windows.Forms.PictureBox
            $picBox.Location = New-Object System.Drawing.Point(20, 15)
            $picBox.Size = New-Object System.Drawing.Size(80, 80)
            $picBox.SizeMode = "Zoom"
            $picBox.Image = [System.Drawing.Image]::FromFile($logoPath)
            $aboutForm.Controls.Add($picBox)
        }

        # App Name + Version
        $lblName = New-Object System.Windows.Forms.Label
        $lblName.Text = "$AppName  v$Version"
        $lblName.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
        $lblName.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 50)
        $lblName.Location = New-Object System.Drawing.Point(110, 20)
        $lblName.AutoSize = $true
        $aboutForm.Controls.Add($lblName)

        $lblDesc = New-Object System.Windows.Forms.Label
        $lblDesc.Text = "NOC Collector - SNMP Trap, Syslog, Active Polling"
        $lblDesc.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $lblDesc.ForeColor = [System.Drawing.Color]::FromArgb(100, 100, 120)
        $lblDesc.Location = New-Object System.Drawing.Point(110, 52)
        $lblDesc.AutoSize = $true
        $aboutForm.Controls.Add($lblDesc)

        # Separator
        $sep = New-Object System.Windows.Forms.Label
        $sep.BorderStyle = "Fixed3D"
        $sep.Location = New-Object System.Drawing.Point(20, 105)
        $sep.Size = New-Object System.Drawing.Size(370, 2)
        $aboutForm.Controls.Add($sep)

        # Company info
        $companyInfo = @"
86BIT srl Unipersonale

Codice Fiscale e P.Iva 04353030168
Capitale sociale EUR 30.000,00 i.v.
Reg. Imprese di Bergamo 04353030168
REA n. BG456578

Sede Operativa:
Piazza Papa Giovanni XXIII
24020 Scanzorosciate (BG)

Tel. +39 035 310 900
info@86bit.it
"@

        $lblCompany = New-Object System.Windows.Forms.Label
        $lblCompany.Text = $companyInfo
        $lblCompany.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
        $lblCompany.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
        $lblCompany.Location = New-Object System.Drawing.Point(20, 115)
        $lblCompany.Size = New-Object System.Drawing.Size(370, 170)
        $aboutForm.Controls.Add($lblCompany)

        # OK button
        $btnOk = New-Object System.Windows.Forms.Button
        $btnOk.Text = "OK"
        $btnOk.Size = New-Object System.Drawing.Size(80, 30)
        $btnOk.Location = New-Object System.Drawing.Point(310, 270)
        $btnOk.FlatStyle = "Flat"
        $btnOk.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $btnOk.ForeColor = [System.Drawing.Color]::White
        $btnOk.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
        $btnOk.Add_Click({ $aboutForm.Close() })
        $aboutForm.Controls.Add($btnOk)
        $aboutForm.AcceptButton = $btnOk

        $aboutForm.ShowDialog()
    })
    
    $contextMenu.Items.Add("-") | Out-Null
    
    # Exit
    $exitItem = $contextMenu.Items.Add("Esci")
    $exitItem.ForeColor = [System.Drawing.Color]::FromArgb(239, 68, 68)
    $exitItem.Add_Click({
        Stop-ConnectorProcess
        $notifyIcon.Visible = $false
        $notifyIcon.Icon = $null
        $notifyIcon.Dispose()
        try { [TrayRefresh]::Refresh() } catch {}
        [System.Windows.Forms.Application]::Exit()
    })
    
    $notifyIcon.ContextMenuStrip = $contextMenu
    
    # Double-click shows status
    $notifyIcon.Add_DoubleClick({
        $text = Get-StatusText
        [System.Windows.Forms.MessageBox]::Show($text, "$AppName - Stato",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information)
    })
    
    # Auto-start: controlla se il connettore gira gia' come Scheduled Task
    $existingStatus = Read-ConnectorStatus
    if ($existingStatus -and $existingStatus.status -eq "running") {
        # Il connettore gira gia' (via Task Scheduler o avvio precedente)
        $global:IsRunning = $true
        $notifyIcon.Icon = New-TrayIcon "running"
        $notifyIcon.Text = "$AppName - Attivo (Servizio)"
        $startItem.Visible = $false
        $stopItem.Visible = $true
        $restartItem.Visible = $true
        $notifyIcon.ShowBalloonTip(3000, $AppName, "Connector attivo come servizio di sistema", [System.Windows.Forms.ToolTipIcon]::Info)
    } elseif (Test-Path $ConfigPath) {
        $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($config.noc_center_url -and $config.api_key) {
            if (Start-ConnectorViaTask) {
                $notifyIcon.Icon = New-TrayIcon "running"
                $notifyIcon.Text = "$AppName - Attivo"
                $startItem.Visible = $false
                $stopItem.Visible = $true
                $restartItem.Visible = $true
                $notifyIcon.ShowBalloonTip(3000, $AppName, "Connector avviato e in ascolto", [System.Windows.Forms.ToolTipIcon]::Info)
            }
        } else {
            $notifyIcon.ShowBalloonTip(5000, $AppName, "Configurazione incompleta. Esegui install.bat", [System.Windows.Forms.ToolTipIcon]::Warning)
        }
    } else {
        $notifyIcon.ShowBalloonTip(5000, $AppName, "Prima installazione. Esegui install.bat", [System.Windows.Forms.ToolTipIcon]::Warning)
    }
    
    # Timer for tooltip update and connector health monitoring
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 15000  # 15 seconds
    $timer.Add_Tick({
        $status = Read-ConnectorStatus
        $connectorAlive = ($status -ne $null -and $status.status -eq "running")
        
        if ($global:IsRunning -and -not $connectorAlive) {
            # Connettore era attivo ma ora non risponde piu'
            $global:IsRunning = $false
            $notifyIcon.Icon = New-TrayIcon "error"
            $notifyIcon.Text = "$AppName - NON RISPONDE"
            $notifyIcon.ShowBalloonTip(5000, $AppName, "Il connector non risponde! Verificare i log.", [System.Windows.Forms.ToolTipIcon]::Error)
            $startItem.Visible = $true
            $stopItem.Visible = $false
            $restartItem.Visible = $false
        } elseif (-not $global:IsRunning -and $connectorAlive) {
            # Connettore avviato dal Task Scheduler senza passare dalla tray
            $global:IsRunning = $true
            $notifyIcon.Icon = New-TrayIcon "running"
            $notifyIcon.Text = (Get-StatusText).Replace("`n", " | ").Substring(0, [Math]::Min(127, (Get-StatusText).Length))
            $startItem.Visible = $false
            $stopItem.Visible = $true
            $restartItem.Visible = $true
        } elseif ($global:IsRunning -and $connectorAlive) {
            # Aggiorna tooltip
            $notifyIcon.Text = (Get-StatusText).Replace("`n", " | ").Substring(0, [Math]::Min(127, (Get-StatusText).Length))
        }
    })
    $timer.Start()
    
    # Run message loop
    [System.Windows.Forms.Application]::Run()
}

# Entry point
Start-TrayApp
