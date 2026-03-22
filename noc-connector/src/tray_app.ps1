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

# ==================== CONNECTOR PROCESS ====================

$global:ConnectorProcess = $null
$global:IsRunning = $false

function Start-ConnectorProcess {
    if ($global:ConnectorProcess -and !$global:ConnectorProcess.HasExited) {
        return
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
    if ($global:ConnectorProcess -and !$global:ConnectorProcess.HasExited) {
        try {
            $global:ConnectorProcess.Kill()
            $global:ConnectorProcess.WaitForExit(5000)
        } catch {}
    }
    $global:IsRunning = $false
}

function Get-StatusText {
    if ($global:IsRunning -and $global:ConnectorProcess -and !$global:ConnectorProcess.HasExited) {
        $uptime = ((Get-Date) - $global:ConnectorProcess.StartTime).ToString("hh\:mm\:ss")
        $config = if (Test-Path $ConfigPath) { Get-Content $ConfigPath -Raw | ConvertFrom-Json } else { $null }
        $nocUrl = if ($config) { $config.noc_center_url } else { "N/D" }
        return "$AppName v$Version`nStato: ATTIVO`nUptime: $uptime`nNOC: $nocUrl"
    }
    return "$AppName v$Version`nStato: FERMO"
}

# ==================== DEVICE MANAGER ====================

function Show-DeviceManager {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "$AppName - Gestisci Dispositivi"
    $form.Size = New-Object System.Drawing.Size(580, 480)
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

    # Bottom buttons
    $btnRemove = New-Object System.Windows.Forms.Button
    $btnRemove.Text = "Rimuovi selezionato"
    $btnRemove.Size = New-Object System.Drawing.Size(135, 30)
    $btnRemove.Location = New-Object System.Drawing.Point(20, 380)
    $btnRemove.FlatStyle = "Flat"
    $btnRemove.BackColor = [System.Drawing.Color]::White
    $btnRemove.ForeColor = [System.Drawing.Color]::FromArgb(220, 50, 50)
    $btnRemove.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
    $btnRemove.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnRemove)

    $btnSave = New-Object System.Windows.Forms.Button
    $btnSave.Text = "Salva e Riavvia"
    $btnSave.Size = New-Object System.Drawing.Size(135, 30)
    $btnSave.Location = New-Object System.Drawing.Point(403, 380)
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
    $lblHint.Location = New-Object System.Drawing.Point(20, 420)
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

    # Remove button handler
    $btnRemove.Add_Click({
        if ($listView.SelectedItems.Count -gt 0) {
            $listView.Items.Remove($listView.SelectedItems[0])
        } else {
            [System.Windows.Forms.MessageBox]::Show("Seleziona un dispositivo dalla lista.", $AppName, "OK", "Information")
        }
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
        if (Start-ConnectorProcess) {
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
        if (Start-ConnectorProcess) {
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
            if (Start-ConnectorProcess) {
                $notifyIcon.Icon = New-TrayIcon "running"
                $notifyIcon.Text = "$AppName - Attivo (riavviato)"
                $notifyIcon.ShowBalloonTip(3000, $AppName, "Connector riavviato con nuovi dispositivi", [System.Windows.Forms.ToolTipIcon]::Info)
            }
        }
    })
    
    $contextMenu.Items.Add("-") | Out-Null
    
    # Exit
    $exitItem = $contextMenu.Items.Add("Esci")
    $exitItem.ForeColor = [System.Drawing.Color]::FromArgb(239, 68, 68)
    $exitItem.Add_Click({
        Stop-ConnectorProcess
        $notifyIcon.Visible = $false
        $notifyIcon.Dispose()
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
    
    # Auto-start connector
    if (Test-Path $ConfigPath) {
        $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($config.noc_center_url -and $config.api_key) {
            if (Start-ConnectorProcess) {
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
    
    # Timer for tooltip update
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 15000  # 15 seconds
    $timer.Add_Tick({
        if ($global:IsRunning -and $global:ConnectorProcess -and $global:ConnectorProcess.HasExited) {
            $global:IsRunning = $false
            $notifyIcon.Icon = New-TrayIcon "error"
            $notifyIcon.Text = "$AppName - ERRORE"
            $notifyIcon.ShowBalloonTip(5000, $AppName, "Il connector si e' fermato inaspettatamente!", [System.Windows.Forms.ToolTipIcon]::Error)
            $startItem.Visible = $true
            $stopItem.Visible = $false
            $restartItem.Visible = $false
        } elseif ($global:IsRunning) {
            $notifyIcon.Text = (Get-StatusText).Replace("`n", " | ").Substring(0, [Math]::Min(127, (Get-StatusText).Length))
        }
    })
    $timer.Start()
    
    # Run message loop
    [System.Windows.Forms.Application]::Run()
}

# Entry point
Start-TrayApp
