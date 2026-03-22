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
$Version = "1.0.0"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
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
