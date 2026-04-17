<#
.SYNOPSIS
    86NocConnector - Wizard di Installazione
.DESCRIPTION
    Interfaccia grafica per installazione e configurazione.
    Usa .NET Windows.Forms nativo.
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$AppName = "86NocConnector"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = Split-Path -Parent $ScriptDir
$VersionFile = Join-Path $BaseDir "version.json"
if (Test-Path $VersionFile) {
    $vInfo = Get-Content $VersionFile -Raw | ConvertFrom-Json
    $Version = $vInfo.version
} else {
    $Version = "1.0.0"
}
$ConfigDir = Join-Path $env:ProgramData $AppName
$ConfigPath = Join-Path $ConfigDir "config.json"

# ==================== WIZARD FORM ====================

function Show-InstallerWizard {
    [System.Windows.Forms.Application]::EnableVisualStyles()
    
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "$AppName - Installazione"
    $form.Size = New-Object System.Drawing.Size(750, 580)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(245, 245, 248)
    
    # Center on screen
    $form.Update()
    
    # ==================== LEFT PANEL ====================
    $leftPanel = New-Object System.Windows.Forms.Panel
    $leftPanel.Location = New-Object System.Drawing.Point(0, 0)
    $leftPanel.Size = New-Object System.Drawing.Size(220, 580)
    $leftPanel.BackColor = [System.Drawing.Color]::FromArgb(15, 15, 22)
    $leftPanel.Dock = [System.Windows.Forms.DockStyle]::Left
    $leftPanel.Width = 220
    $form.Controls.Add($leftPanel)
    
    # Logo
    $logoPath = Join-Path $ScriptDir "86bit_logo.jpg"
    if (Test-Path $logoPath) {
        $logoPic = New-Object System.Windows.Forms.PictureBox
        $logoPic.Location = New-Object System.Drawing.Point(45, 80)
        $logoPic.Size = New-Object System.Drawing.Size(130, 130)
        $logoPic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
        $logoPic.BackColor = [System.Drawing.Color]::Transparent
        $logoPic.Image = [System.Drawing.Image]::FromFile($logoPath)
        $leftPanel.Controls.Add($logoPic)
    }
    
    $lblApp = New-Object System.Windows.Forms.Label
    $lblApp.Text = "NocConnector"
    $lblApp.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
    $lblApp.ForeColor = [System.Drawing.Color]::FromArgb(120, 120, 255)
    $lblApp.BackColor = [System.Drawing.Color]::Transparent
    $lblApp.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $lblApp.Location = New-Object System.Drawing.Point(15, 222)
    $lblApp.Size = New-Object System.Drawing.Size(190, 24)
    $leftPanel.Controls.Add($lblApp)
    
    $lblVer = New-Object System.Windows.Forms.Label
    $lblVer.Text = "v$Version"
    $lblVer.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $lblVer.ForeColor = [System.Drawing.Color]::FromArgb(80, 80, 100)
    $lblVer.BackColor = [System.Drawing.Color]::Transparent
    $lblVer.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $lblVer.Location = New-Object System.Drawing.Point(15, 246)
    $lblVer.Size = New-Object System.Drawing.Size(190, 18)
    $leftPanel.Controls.Add($lblVer)

    # Company info at bottom of left panel
    $lblCompany = New-Object System.Windows.Forms.Label
    $lblCompany.Text = "86bit S.r.l."
    $lblCompany.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $lblCompany.ForeColor = [System.Drawing.Color]::FromArgb(120, 120, 255)
    $lblCompany.BackColor = [System.Drawing.Color]::Transparent
    $lblCompany.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $lblCompany.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
    $lblCompany.Location = New-Object System.Drawing.Point(10, 440)
    $lblCompany.Size = New-Object System.Drawing.Size(200, 20)
    $leftPanel.Controls.Add($lblCompany)

    $lblWeb = New-Object System.Windows.Forms.Label
    $lblWeb.Text = "www.86bit.it"
    $lblWeb.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $lblWeb.ForeColor = [System.Drawing.Color]::FromArgb(90, 90, 120)
    $lblWeb.BackColor = [System.Drawing.Color]::Transparent
    $lblWeb.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $lblWeb.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
    $lblWeb.Location = New-Object System.Drawing.Point(10, 460)
    $lblWeb.Size = New-Object System.Drawing.Size(200, 18)
    $leftPanel.Controls.Add($lblWeb)

    $lblCopy = New-Object System.Windows.Forms.Label
    $lblCopy.Text = [char]0x00A9 + " 2026 Tutti i diritti riservati"
    $lblCopy.Font = New-Object System.Drawing.Font("Segoe UI", 7)
    $lblCopy.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
    $lblCopy.BackColor = [System.Drawing.Color]::Transparent
    $lblCopy.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $lblCopy.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
    $lblCopy.Location = New-Object System.Drawing.Point(10, 478)
    $lblCopy.Size = New-Object System.Drawing.Size(200, 16)
    $leftPanel.Controls.Add($lblCopy)
    
    # ==================== CONTENT PANEL ====================
    $contentPanel = New-Object System.Windows.Forms.Panel
    $contentPanel.Location = New-Object System.Drawing.Point(220, 0)
    $contentPanel.Size = New-Object System.Drawing.Size(510, 490)
    $contentPanel.BackColor = [System.Drawing.Color]::FromArgb(245, 245, 248)
    $form.Controls.Add($contentPanel)
    
    # ==================== BUTTON BAR ====================
    $btnBar = New-Object System.Windows.Forms.Panel
    $btnBar.Location = New-Object System.Drawing.Point(220, 490)
    $btnBar.Size = New-Object System.Drawing.Size(510, 52)
    $btnBar.BackColor = [System.Drawing.Color]::FromArgb(230, 230, 235)
    $form.Controls.Add($btnBar)
    
    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Text = "Annulla"
    $btnCancel.Size = New-Object System.Drawing.Size(95, 32)
    $btnCancel.Location = New-Object System.Drawing.Point(402, 10)
    $btnCancel.FlatStyle = "Flat"
    $btnCancel.BackColor = [System.Drawing.Color]::White
    $btnCancel.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 70)
    $btnCancel.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $btnCancel.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnCancel.Add_Click({ $form.Close() })
    $btnBar.Controls.Add($btnCancel)
    
    $btnNext = New-Object System.Windows.Forms.Button
    $btnNext.Text = "Avanti >"
    $btnNext.Size = New-Object System.Drawing.Size(95, 32)
    $btnNext.Location = New-Object System.Drawing.Point(301, 10)
    $btnNext.FlatStyle = "Flat"
    $btnNext.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnNext.ForeColor = [System.Drawing.Color]::White
    $btnNext.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $btnNext.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnBar.Controls.Add($btnNext)
    
    $btnBack = New-Object System.Windows.Forms.Button
    $btnBack.Text = "< Indietro"
    $btnBack.Size = New-Object System.Drawing.Size(95, 32)
    $btnBack.Location = New-Object System.Drawing.Point(200, 10)
    $btnBack.FlatStyle = "Flat"
    $btnBack.BackColor = [System.Drawing.Color]::White
    $btnBack.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 70)
    $btnBack.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $btnBack.Enabled = $false
    $btnBack.Cursor = [System.Windows.Forms.Cursors]::Hand
    $btnBar.Controls.Add($btnBack)
    
    # ==================== INPUT FIELDS ====================
    $txtUrl = New-Object System.Windows.Forms.TextBox
    $txtApiKey = New-Object System.Windows.Forms.TextBox
    $txtSNMP = New-Object System.Windows.Forms.TextBox
    $txtSyslog = New-Object System.Windows.Forms.TextBox
    $chkAutostart = New-Object System.Windows.Forms.CheckBox
    $txtStatus = New-Object System.Windows.Forms.TextBox
    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $txtDeviceIP = New-Object System.Windows.Forms.TextBox
    $txtDeviceCommunity = New-Object System.Windows.Forms.TextBox
    $txtDeviceName = New-Object System.Windows.Forms.TextBox
    $txtPollInterval = New-Object System.Windows.Forms.TextBox
    $deviceList = New-Object System.Windows.Forms.ListView
    
    $currentPage = 0
    
    function Reset-ContentPanel { $contentPanel.Controls.Clear() }
    
    function Show-Page($page) {
        $script:currentPage = $page
        Reset-ContentPanel
        $btnBack.Enabled = ($page -gt 0)
        switch ($page) {
            0 { Show-Welcome }
            1 { Show-Config }
            2 { Show-Devices }
            3 { Show-Installing }
            4 { Show-Complete }
        }
    }
    
    # ==================== PAGE 0: WELCOME ====================
    function Show-Welcome {
        $btnNext.Text = "Avanti >"
        $btnNext.Enabled = $true
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Installazione di $AppName"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 40)
        $title.Location = New-Object System.Drawing.Point(28, 20)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "Questa procedura installera' $AppName sul computer.`n`n$AppName raccoglie SNMP Traps e messaggi Syslog dai dispositivi di rete (switch, firewall, server ILO) e li inoltra al NOC Center in tempo reale."
        $desc.Font = New-Object System.Drawing.Font("Segoe UI", 9.5)
        $desc.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
        $desc.Location = New-Object System.Drawing.Point(28, 60)
        $desc.Size = New-Object System.Drawing.Size(450, 100)
        $contentPanel.Controls.Add($desc)
        
        $infoBox = New-Object System.Windows.Forms.GroupBox
        $infoBox.Text = "Cosa verra' installato"
        $infoBox.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $infoBox.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
        $infoBox.Location = New-Object System.Drawing.Point(28, 170)
        $infoBox.Size = New-Object System.Drawing.Size(450, 180)
        $contentPanel.Controls.Add($infoBox)
        
        $items = @(
            "Servizio SNMP Trap listener (porta UDP 162)"
            "Servizio Syslog listener (porta UDP 514)"
            "Icona nella system tray per monitoraggio"
            "Collegamento nel Menu Start di Windows"
            "Regole firewall Windows"
            "Avvio automatico con Windows"
        )
        $y = 26
        foreach ($item in $items) {
            $lbl = New-Object System.Windows.Forms.Label
            $lbl.Text = [char]0x2022 + "   $item"
            $lbl.Font = New-Object System.Drawing.Font("Segoe UI", 9.5)
            $lbl.ForeColor = [System.Drawing.Color]::FromArgb(50, 50, 65)
            $lbl.Location = New-Object System.Drawing.Point(18, $y)
            $lbl.AutoSize = $true
            $infoBox.Controls.Add($lbl)
            $y += 27
        }
        
        $footer = New-Object System.Windows.Forms.Label
        $footer.Text = "Clicca 'Avanti' per continuare."
        $footer.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $footer.ForeColor = [System.Drawing.Color]::FromArgb(140, 140, 155)
        $footer.Location = New-Object System.Drawing.Point(28, 450)
        $footer.AutoSize = $true
        $contentPanel.Controls.Add($footer)
    }
    
    # ==================== PAGE 1: CONFIG ====================
    function Show-Config {
        $btnNext.Text = "Avanti >"
        $btnNext.Enabled = $true
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Configurazione"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 40)
        $title.Location = New-Object System.Drawing.Point(28, 20)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "Inserisci i dati di connessione al NOC Center."
        $desc.Font = New-Object System.Drawing.Font("Segoe UI", 9.5)
        $desc.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
        $desc.Location = New-Object System.Drawing.Point(28, 55)
        $desc.AutoSize = $true
        $contentPanel.Controls.Add($desc)
        
        # URL
        $lblUrl = New-Object System.Windows.Forms.Label
        $lblUrl.Text = "URL NOC Center *"
        $lblUrl.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
        $lblUrl.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblUrl.Location = New-Object System.Drawing.Point(28, 95)
        $lblUrl.AutoSize = $true
        $contentPanel.Controls.Add($lblUrl)
        
        $txtUrl.Location = New-Object System.Drawing.Point(28, 118)
        $txtUrl.Size = New-Object System.Drawing.Size(450, 28)
        $txtUrl.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtUrl)
        
        $hintUrl = New-Object System.Windows.Forms.Label
        $hintUrl.Text = "Es: https://noc.azienda.it"
        $hintUrl.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $hintUrl.ForeColor = [System.Drawing.Color]::FromArgb(150, 150, 165)
        $hintUrl.Location = New-Object System.Drawing.Point(28, 146)
        $hintUrl.AutoSize = $true
        $contentPanel.Controls.Add($hintUrl)
        
        # API Key
        $lblKey = New-Object System.Windows.Forms.Label
        $lblKey.Text = "API Key del Cliente *"
        $lblKey.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
        $lblKey.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblKey.Location = New-Object System.Drawing.Point(28, 175)
        $lblKey.AutoSize = $true
        $contentPanel.Controls.Add($lblKey)
        
        $txtApiKey.Location = New-Object System.Drawing.Point(28, 198)
        $txtApiKey.Size = New-Object System.Drawing.Size(450, 28)
        $txtApiKey.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtApiKey)
        
        $hintKey = New-Object System.Windows.Forms.Label
        $hintKey.Text = "Copiala dalla pagina Clienti del NOC Center"
        $hintKey.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $hintKey.ForeColor = [System.Drawing.Color]::FromArgb(150, 150, 165)
        $hintKey.Location = New-Object System.Drawing.Point(28, 226)
        $hintKey.AutoSize = $true
        $contentPanel.Controls.Add($hintKey)
        
        # Ports
        $lblSNMP = New-Object System.Windows.Forms.Label
        $lblSNMP.Text = "Porta SNMP"
        $lblSNMP.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $lblSNMP.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblSNMP.Location = New-Object System.Drawing.Point(28, 264)
        $lblSNMP.AutoSize = $true
        $contentPanel.Controls.Add($lblSNMP)
        
        $txtSNMP.Text = if ($txtSNMP.Text) { $txtSNMP.Text } else { "162" }
        $txtSNMP.Location = New-Object System.Drawing.Point(110, 261)
        $txtSNMP.Size = New-Object System.Drawing.Size(60, 28)
        $txtSNMP.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtSNMP)
        
        $lblSyslog2 = New-Object System.Windows.Forms.Label
        $lblSyslog2.Text = "Porta Syslog"
        $lblSyslog2.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $lblSyslog2.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblSyslog2.Location = New-Object System.Drawing.Point(210, 264)
        $lblSyslog2.AutoSize = $true
        $contentPanel.Controls.Add($lblSyslog2)
        
        $txtSyslog.Text = if ($txtSyslog.Text) { $txtSyslog.Text } else { "514" }
        $txtSyslog.Location = New-Object System.Drawing.Point(300, 261)
        $txtSyslog.Size = New-Object System.Drawing.Size(60, 28)
        $txtSyslog.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtSyslog)
        
        # Autostart
        $chkAutostart.Text = "Avvia automaticamente con Windows"
        $chkAutostart.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $chkAutostart.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $chkAutostart.Location = New-Object System.Drawing.Point(28, 305)
        $chkAutostart.Checked = $true
        $chkAutostart.AutoSize = $true
        $chkAutostart.BackColor = [System.Drawing.Color]::Transparent
        $contentPanel.Controls.Add($chkAutostart)
        
        # Test button
        $btnTest = New-Object System.Windows.Forms.Button
        $btnTest.Text = "Test Connessione"
        $btnTest.Size = New-Object System.Drawing.Size(140, 32)
        $btnTest.Location = New-Object System.Drawing.Point(28, 350)
        $btnTest.FlatStyle = "Flat"
        $btnTest.BackColor = [System.Drawing.Color]::White
        $btnTest.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $btnTest.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $btnTest.Cursor = [System.Windows.Forms.Cursors]::Hand
        $btnTest.Add_Click({
            $url = $txtUrl.Text.Trim().TrimEnd("/")
            $key = $txtApiKey.Text.Trim()
            if (-not $url -or -not $key) {
                [System.Windows.Forms.MessageBox]::Show("Inserisci URL e API Key.", $AppName, "OK", "Warning")
                return
            }
            try {
                $r = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 10
                $body = @{ connector_version=$Version; hostname=$env:COMPUTERNAME; uptime_seconds=0; traps_received=0; syslogs_received=0 } | ConvertTo-Json
                $headers = @{ "X-API-Key" = $key; "Content-Type" = "application/json" }
                Invoke-RestMethod -Uri "$url/api/connector/heartbeat" -Method Post -Headers $headers -Body $body -TimeoutSec 10
                [System.Windows.Forms.MessageBox]::Show("Connessione OK!`nAPI Key valida.", $AppName, "OK", "Information")
            } catch {
                [System.Windows.Forms.MessageBox]::Show("Errore: $($_.Exception.Message)", $AppName, "OK", "Error")
            }
        })
        $contentPanel.Controls.Add($btnTest)
    }
    
    # ==================== PAGE 2: DEVICES ====================
    function Show-Devices {
        $btnNext.Text = "Installa >"
        $btnNext.Enabled = $true

        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Dispositivi da Monitorare"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 40)
        $title.Location = New-Object System.Drawing.Point(28, 15)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)

        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "Aggiungi switch, firewall o server da monitorare via SNMP polling."
        $desc.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $desc.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
        $desc.Location = New-Object System.Drawing.Point(28, 48)
        $desc.AutoSize = $true
        $contentPanel.Controls.Add($desc)

        # Device input row
        $lblIP = New-Object System.Windows.Forms.Label
        $lblIP.Text = "IP Address"
        $lblIP.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $lblIP.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblIP.Location = New-Object System.Drawing.Point(28, 80)
        $lblIP.AutoSize = $true
        $contentPanel.Controls.Add($lblIP)

        $txtDeviceIP.Location = New-Object System.Drawing.Point(28, 97)
        $txtDeviceIP.Size = New-Object System.Drawing.Size(125, 24)
        $txtDeviceIP.Font = New-Object System.Drawing.Font("Consolas", 9)
        if (-not $txtDeviceIP.Text) { $txtDeviceIP.Text = "" }
        $contentPanel.Controls.Add($txtDeviceIP)

        $lblComm = New-Object System.Windows.Forms.Label
        $lblComm.Text = "Community"
        $lblComm.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $lblComm.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblComm.Location = New-Object System.Drawing.Point(160, 80)
        $lblComm.AutoSize = $true
        $contentPanel.Controls.Add($lblComm)

        $txtDeviceCommunity.Location = New-Object System.Drawing.Point(160, 97)
        $txtDeviceCommunity.Size = New-Object System.Drawing.Size(90, 24)
        $txtDeviceCommunity.Font = New-Object System.Drawing.Font("Consolas", 9)
        if (-not $txtDeviceCommunity.Text) { $txtDeviceCommunity.Text = "public" }
        $contentPanel.Controls.Add($txtDeviceCommunity)

        $lblName = New-Object System.Windows.Forms.Label
        $lblName.Text = "Nome"
        $lblName.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $lblName.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblName.Location = New-Object System.Drawing.Point(258, 80)
        $lblName.AutoSize = $true
        $contentPanel.Controls.Add($lblName)

        $txtDeviceName.Location = New-Object System.Drawing.Point(258, 97)
        $txtDeviceName.Size = New-Object System.Drawing.Size(120, 24)
        $txtDeviceName.Font = New-Object System.Drawing.Font("Consolas", 9)
        if (-not $txtDeviceName.Text) { $txtDeviceName.Text = "" }
        $contentPanel.Controls.Add($txtDeviceName)

        $btnAddDev = New-Object System.Windows.Forms.Button
        $btnAddDev.Text = "+ Aggiungi"
        $btnAddDev.Size = New-Object System.Drawing.Size(80, 24)
        $btnAddDev.Location = New-Object System.Drawing.Point(385, 97)
        $btnAddDev.FlatStyle = "Flat"
        $btnAddDev.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $btnAddDev.ForeColor = [System.Drawing.Color]::White
        $btnAddDev.Font = New-Object System.Drawing.Font("Segoe UI", 8, [System.Drawing.FontStyle]::Bold)
        $btnAddDev.Cursor = [System.Windows.Forms.Cursors]::Hand
        $contentPanel.Controls.Add($btnAddDev)

        # ListView for devices
        $deviceList.Location = New-Object System.Drawing.Point(28, 135)
        $deviceList.Size = New-Object System.Drawing.Size(437, 220)
        $deviceList.View = [System.Windows.Forms.View]::Details
        $deviceList.FullRowSelect = $true
        $deviceList.GridLines = $true
        $deviceList.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $deviceList.BackColor = [System.Drawing.Color]::White
        $deviceList.Columns.Clear()
        $null = $deviceList.Columns.Add("IP", 140)
        $null = $deviceList.Columns.Add("Community", 100)
        $null = $deviceList.Columns.Add("Nome", 190)
        $contentPanel.Controls.Add($deviceList)

        $btnRemoveDev = New-Object System.Windows.Forms.Button
        $btnRemoveDev.Text = "Rimuovi selezionato"
        $btnRemoveDev.Size = New-Object System.Drawing.Size(130, 28)
        $btnRemoveDev.Location = New-Object System.Drawing.Point(28, 362)
        $btnRemoveDev.FlatStyle = "Flat"
        $btnRemoveDev.BackColor = [System.Drawing.Color]::White
        $btnRemoveDev.ForeColor = [System.Drawing.Color]::FromArgb(220, 50, 50)
        $btnRemoveDev.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $btnRemoveDev.Cursor = [System.Windows.Forms.Cursors]::Hand
        $contentPanel.Controls.Add($btnRemoveDev)

        # Poll interval
        $lblPoll = New-Object System.Windows.Forms.Label
        $lblPoll.Text = "Intervallo polling (sec):"
        $lblPoll.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $lblPoll.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblPoll.Location = New-Object System.Drawing.Point(250, 366)
        $lblPoll.AutoSize = $true
        $contentPanel.Controls.Add($lblPoll)

        $txtPollInterval.Location = New-Object System.Drawing.Point(400, 363)
        $txtPollInterval.Size = New-Object System.Drawing.Size(65, 24)
        $txtPollInterval.Font = New-Object System.Drawing.Font("Consolas", 9)
        if (-not $txtPollInterval.Text) { $txtPollInterval.Text = "60" }
        $contentPanel.Controls.Add($txtPollInterval)

        $hint = New-Object System.Windows.Forms.Label
        $hint.Text = "Lo switch HPE 1820 non invia trap. Il polling SNMP interroga le porte ogni X secondi."
        $hint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $hint.ForeColor = [System.Drawing.Color]::FromArgb(140, 140, 155)
        $hint.Location = New-Object System.Drawing.Point(28, 430)
        $hint.Size = New-Object System.Drawing.Size(440, 40)
        $contentPanel.Controls.Add($hint)

        # Button handlers
        $btnAddDev.Add_Click({
            $ip = $txtDeviceIP.Text.Trim()
            if (-not $ip) {
                [System.Windows.Forms.MessageBox]::Show("Inserisci l'indirizzo IP.", $AppName, "OK", "Warning")
                return
            }
            $comm = if ($txtDeviceCommunity.Text.Trim()) { $txtDeviceCommunity.Text.Trim() } else { "public" }
            $devName = if ($txtDeviceName.Text.Trim()) { $txtDeviceName.Text.Trim() } else { $ip }
            $item = New-Object System.Windows.Forms.ListViewItem($ip)
            $null = $item.SubItems.Add($comm)
            $null = $item.SubItems.Add($devName)
            $deviceList.Items.Add($item)
            $txtDeviceIP.Text = ""
            $txtDeviceName.Text = ""
        })

        $btnRemoveDev.Add_Click({
            if ($deviceList.SelectedItems.Count -gt 0) {
                $deviceList.Items.Remove($deviceList.SelectedItems[0])
            }
        })
    }

    # ==================== PAGE 3: INSTALLING ====================
    function Show-Installing {
        $url = $txtUrl.Text.Trim().TrimEnd("/")
        $key = $txtApiKey.Text.Trim()
        if (-not $url -or -not $key) {
            [System.Windows.Forms.MessageBox]::Show("URL e API Key sono obbligatori.", $AppName, "OK", "Warning")
            Show-Page 1
            return
        }
        
        $btnNext.Enabled = $false
        $btnBack.Enabled = $false
        $btnCancel.Enabled = $false
        $btnNext.Text = "Avanti >"
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Installazione in corso..."
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 40)
        $title.Location = New-Object System.Drawing.Point(28, 20)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $progressBar.Location = New-Object System.Drawing.Point(28, 60)
        $progressBar.Size = New-Object System.Drawing.Size(450, 22)
        $progressBar.Minimum = 0
        $progressBar.Maximum = 100
        $contentPanel.Controls.Add($progressBar)
        
        $txtStatus.Multiline = $true
        $txtStatus.ScrollBars = "Vertical"
        $txtStatus.ReadOnly = $true
        $txtStatus.Location = New-Object System.Drawing.Point(28, 95)
        $txtStatus.Size = New-Object System.Drawing.Size(450, 370)
        $txtStatus.Font = New-Object System.Drawing.Font("Consolas", 9)
        $txtStatus.BackColor = [System.Drawing.Color]::FromArgb(20, 20, 35)
        $txtStatus.ForeColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
        $contentPanel.Controls.Add($txtStatus)
        
        $form.Refresh()
        
        # Step 1: Config
        $txtStatus.AppendText("> Salvataggio configurazione...`r`n")
        $progressBar.Value = 15
        $form.Refresh()
        if (!(Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null }
        $logsDir = Join-Path $ConfigDir "logs"
        if (!(Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir -Force | Out-Null }

        # Build devices array from ListView
        $devicesArray = @()
        foreach ($item in $deviceList.Items) {
            $devicesArray += @{
                ip = $item.Text
                community = $item.SubItems[1].Text
                name = $item.SubItems[2].Text
            }
        }
        $pollInterval = 60
        try { $pollInterval = [int]$txtPollInterval.Text } catch {}

        $config = @{
            noc_center_url = $url
            api_key = $key
            snmp_trap_port = [int]$txtSNMP.Text
            syslog_port = [int]$txtSyslog.Text
            heartbeat_interval_seconds = 60
            batch_interval_seconds = 3
            poll_interval_seconds = $pollInterval
            devices = $devicesArray
        }
        $config | ConvertTo-Json -Depth 5 | Set-Content $ConfigPath -Encoding UTF8
        $txtStatus.AppendText("  Salvato in: $ConfigPath`r`n")
        if ($devicesArray.Count -gt 0) {
            $txtStatus.AppendText("  Dispositivi da monitorare: $($devicesArray.Count)`r`n")
            foreach ($d in $devicesArray) {
                $txtStatus.AppendText("    - $($d.name) ($($d.ip))`r`n")
            }
            $txtStatus.AppendText("  Polling ogni ${pollInterval}s`r`n")
        } else {
            $txtStatus.AppendText("  Nessun dispositivo configurato per polling`r`n")
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 2: Firewall
        $txtStatus.AppendText("> Configurazione firewall...`r`n")
        $progressBar.Value = 40
        $form.Refresh()
        try {
            & netsh advfirewall firewall delete rule name="86NocConnector SNMP" 2>$null
            & netsh advfirewall firewall delete rule name="86NocConnector Syslog" 2>$null
            & netsh advfirewall firewall add rule name="86NocConnector SNMP" dir=in action=allow protocol=UDP localport=$($txtSNMP.Text) 2>$null
            & netsh advfirewall firewall add rule name="86NocConnector Syslog" dir=in action=allow protocol=UDP localport=$($txtSyslog.Text) 2>$null
            $txtStatus.AppendText("  UDP/$($txtSNMP.Text) (SNMP): OK`r`n")
            $txtStatus.AppendText("  UDP/$($txtSyslog.Text) (Syslog): OK`r`n")
        } catch {
            $txtStatus.AppendText("  Firewall: serve Amministratore`r`n")
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 3: Registra come Servizio Windows (NSSM)
        $txtStatus.AppendText("> Registrazione Servizio Windows (NSSM)...`r`n")
        $progressBar.Value = 60
        $form.Refresh()
        $batPath = Join-Path $BaseDir "86NocConnector.bat"
        $uninstallBat = Join-Path $BaseDir "uninstall.bat"
        $connectorScript = Join-Path $ScriptDir "connector.ps1"
        $nssmPath = Join-Path $BaseDir "nssm.exe"
        $svcName = "86NocConnectorService"
        
        if ($chkAutostart.Checked) {
            if (Test-Path $nssmPath) {
                try {
                    # Rimuovi servizio precedente se esiste
                    & $nssmPath stop $svcName 2>$null
                    & $nssmPath remove $svcName confirm 2>$null
                    
                    # Registra il servizio con NSSM
                    & $nssmPath install $svcName "powershell.exe" "-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$connectorScript`""
                    & $nssmPath set $svcName AppDirectory $ScriptDir
                    & $nssmPath set $svcName DisplayName "86NocConnector Service"
                    & $nssmPath set $svcName Description "86NocConnector - Raccolta SNMP/Syslog per NOC Center"
                    & $nssmPath set $svcName Start SERVICE_AUTO_START
                    & $nssmPath set $svcName ObjectName LocalSystem
                    & $nssmPath set $svcName AppStdout (Join-Path $ConfigDir "logs\service_stdout.log")
                    & $nssmPath set $svcName AppStderr (Join-Path $ConfigDir "logs\service_stderr.log")
                    & $nssmPath set $svcName AppRotateFiles 1
                    & $nssmPath set $svcName AppRotateBytes 5242880
                    & $nssmPath set $svcName AppRestartDelay 30000
                    & $nssmPath set $svcName AppThrottle 30000
                    & $nssmPath set $svcName AppExit Default Restart
                    
                    $txtStatus.AppendText("  Servizio Windows registrato (NSSM)`r`n")
                    $txtStatus.AppendText("  Modalita': LocalSystem (sopravvive a disconnessione RDP)`r`n")
                    $txtStatus.AppendText("  Riavvio automatico su crash: SI`r`n")
                    $txtStatus.AppendText("  Avvio automatico all'accensione: SI`r`n")
                    
                    # Rimuovi vecchi metodi di autostart
                    & reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v $AppName /f 2>$null
                    Unregister-ScheduledTask -TaskName $svcName -Confirm:$false -ErrorAction SilentlyContinue
                    
                } catch {
                    $txtStatus.AppendText("  NSSM: $($_.Exception.Message)`r`n")
                    $txtStatus.AppendText("  Fallback: avvio automatico via registro...`r`n")
                    try {
                        & reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v $AppName /t REG_SZ /d "`"$batPath`"" /f 2>$null
                        $txtStatus.AppendText("  Avvio automatico (registro): OK`r`n")
                    } catch {}
                }
            } else {
                $txtStatus.AppendText("  nssm.exe non trovato, uso registro di sistema...`r`n")
                try {
                    & reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v $AppName /t REG_SZ /d "`"$batPath`"" /f 2>$null
                    $txtStatus.AppendText("  Avvio automatico (registro): OK`r`n")
                } catch {}
            }
        }
        # Start Menu shortcut - Cartella "86BIT ArgusCenter"
        try {
            $startMenuDir = Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86BIT ArgusCenter"
            if (!(Test-Path $startMenuDir)) { New-Item -ItemType Directory -Path $startMenuDir -Force | Out-Null }
            # Rimuovi vecchie cartelle con nomi diversi
            $oldDir = Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86NocConnector"
            if (Test-Path $oldDir) { Remove-Item $oldDir -Recurse -Force -ErrorAction SilentlyContinue }
            $oldDir2 = Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86BIT Connector"
            if (Test-Path $oldDir2) { Remove-Item $oldDir2 -Recurse -Force -ErrorAction SilentlyContinue }
            
            $shell = New-Object -ComObject WScript.Shell
            # Collegamento Avvia ARGUS Center Connector
            $shortcut = $shell.CreateShortcut("$startMenuDir\ARGUS Center Connector.lnk")
            $shortcut.TargetPath = $batPath
            $shortcut.WorkingDirectory = $BaseDir
            $shortcut.Description = "Avvia ARGUS Center Connector - Monitoring SNMP, Syslog e Redfish"
            $shortcut.IconLocation = "shell32.dll,13"
            $shortcut.WindowStyle = 7
            $shortcut.Save()
            # Collegamento Diagnostica
            $diagScript = Join-Path $BaseDir "diagnostica_connessione.ps1"
            if (Test-Path $diagScript) {
                $diagShortcut = $shell.CreateShortcut("$startMenuDir\Diagnostica Connessione.lnk")
                $diagShortcut.TargetPath = "powershell.exe"
                $diagShortcut.Arguments = "-ExecutionPolicy Bypass -File `"$diagScript`""
                $diagShortcut.WorkingDirectory = $BaseDir
                $diagShortcut.Description = "Diagnostica connessione ARGUS Center"
                $diagShortcut.IconLocation = "shell32.dll,22"
                $diagShortcut.Save()
            }
            # Collegamento Disinstalla
            $unShortcut = $shell.CreateShortcut("$startMenuDir\Disinstalla ARGUS Connector.lnk")
            $unShortcut.TargetPath = $uninstallBat
            $unShortcut.WorkingDirectory = $BaseDir
            $unShortcut.Description = "Disinstalla ARGUS Center Connector"
            $unShortcut.IconLocation = "shell32.dll,31"
            $unShortcut.Save()
            # Collegamento Apri Cartella Log
            $logDir = Join-Path $env:ProgramData "86NocConnector\logs"
            if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
            $logShortcut = $shell.CreateShortcut("$startMenuDir\Apri Cartella Log.lnk")
            $logShortcut.TargetPath = "explorer.exe"
            $logShortcut.Arguments = $logDir
            $logShortcut.Description = "Apri la cartella dei log del connettore"
            $logShortcut.IconLocation = "shell32.dll,3"
            $logShortcut.Save()
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
            $txtStatus.AppendText("  Menu Start: OK (86BIT ArgusCenter)`r`n")
        } catch {
            $txtStatus.AppendText("  Menu Start: $($_.Exception.Message)`r`n")
        }
        try {
            $regPath = "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86BIT_ArgusCenter_Connector"
            # Rimuovi vecchia chiave con nome diverso
            & reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName" /f 2>$null
            & reg add $regPath /v "DisplayName" /t REG_SZ /d "86BIT ARGUS Center Connector" /f 2>$null
            & reg add $regPath /v "DisplayVersion" /t REG_SZ /d "$Version" /f 2>$null
            & reg add $regPath /v "Publisher" /t REG_SZ /d "86BIT srl Unipersonale" /f 2>$null
            & reg add $regPath /v "URLInfoAbout" /t REG_SZ /d "https://www.86bit.it" /f 2>$null
            & reg add $regPath /v "HelpLink" /t REG_SZ /d "mailto:info@86bit.it" /f 2>$null
            & reg add $regPath /v "Contact" /t REG_SZ /d "info@86bit.it" /f 2>$null
            & reg add $regPath /v "UninstallString" /t REG_SZ /d "`"$uninstallBat`"" /f 2>$null
            & reg add $regPath /v "InstallLocation" /t REG_SZ /d "$BaseDir" /f 2>$null
            & reg add $regPath /v "InstallDate" /t REG_SZ /d "$(Get-Date -Format 'yyyyMMdd')" /f 2>$null
            & reg add $regPath /v "EstimatedSize" /t REG_DWORD /d 1024 /f 2>$null
            & reg add $regPath /v "NoModify" /t REG_DWORD /d 1 /f 2>$null
            & reg add $regPath /v "NoRepair" /t REG_DWORD /d 1 /f 2>$null
            $txtStatus.AppendText("  Programmi e Funzionalita': OK (86BIT ARGUS Center Connector)`r`n")
        } catch {}
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 4: Test
        $txtStatus.AppendText("> Test connessione...`r`n")
        $progressBar.Value = 80
        $form.Refresh()
        try {
            Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 10 | Out-Null
            $txtStatus.AppendText("  NOC Center: raggiungibile`r`n")
        } catch {
            $txtStatus.AppendText("  NOC Center: $($_.Exception.Message)`r`n")
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 5: Start connector service + tray
        $txtStatus.AppendText("> Avvio $AppName...`r`n")
        $progressBar.Value = 100
        $form.Refresh()
        
        $nssmPath = Join-Path $BaseDir "nssm.exe"
        $svcName = "86NocConnectorService"
        
        # Avvia il servizio NSSM
        if (Test-Path $nssmPath) {
            try {
                & $nssmPath start $svcName 2>$null
                Start-Sleep -Seconds 3
                $svcStatus = & $nssmPath status $svcName 2>$null
                $txtStatus.AppendText("  Servizio connettore: $svcStatus`r`n")
                if ($svcStatus -match "RUNNING|START_PENDING") {
                    $txtStatus.AppendText("  Il connettore gira come Servizio Windows (sopravvive a disconnessione RDP)`r`n")
                }
            } catch {
                $txtStatus.AppendText("  Errore avvio servizio: $($_.Exception.Message)`r`n")
            }
        } else {
            # Fallback: avvia direttamente
            Start-Process "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $ScriptDir 'connector.ps1')`"" -WindowStyle Hidden
            $txtStatus.AppendText("  Connettore: AVVIATO (processo diretto)`r`n")
        }
        
        # Avvia la tray app per monitoraggio (opzionale, solo se in sessione interattiva)
        $trayScript = Join-Path $ScriptDir "tray_app.ps1"
        try {
            Start-Process "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$trayScript`"" -WindowStyle Hidden
            $txtStatus.AppendText("  Icona system tray: ATTIVA (solo monitoraggio)`r`n")
        } catch {
            $txtStatus.AppendText("  Tray: $($_.Exception.Message)`r`n")
        }
        
        $txtStatus.AppendText("`r`n> Installazione completata con successo!`r`n")
        $form.Refresh()
        
        $btnNext.Enabled = $true
        $btnCancel.Enabled = $true
    }
    
    # ==================== PAGE 3: COMPLETE ====================
    function Show-Complete {
        $btnNext.Text = "Fine"
        $btnBack.Enabled = $false
        $btnCancel.Enabled = $false
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Installazione Completata!"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(22, 163, 74)
        $title.Location = New-Object System.Drawing.Point(28, 20)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "$AppName e' stato installato e avviato.`n`nOra lo switch HPE verra' monitorato automaticamente.`nSe una porta cambia stato, riceverai un alert nel NOC."
        $desc.Font = New-Object System.Drawing.Font("Segoe UI", 9.5)
        $desc.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
        $desc.Location = New-Object System.Drawing.Point(28, 60)
        $desc.Size = New-Object System.Drawing.Size(450, 70)
        $contentPanel.Controls.Add($desc)
        
        $infoBox = New-Object System.Windows.Forms.GroupBox
        $infoBox.Text = "Riepilogo"
        $infoBox.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $infoBox.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 80)
        $infoBox.Location = New-Object System.Drawing.Point(28, 140)
        $infoBox.Size = New-Object System.Drawing.Size(450, 190)
        $contentPanel.Controls.Add($infoBox)
        
        $items = @(
            [char]0x2713 + "   Config: $ConfigPath"
            [char]0x2713 + "   SNMP Trap: porta UDP $($txtSNMP.Text)"
            [char]0x2713 + "   Syslog: porta UDP $($txtSyslog.Text)"
            [char]0x2713 + "   NOC Center: $($txtUrl.Text.Trim().Substring(0, [Math]::Min(42, $txtUrl.Text.Trim().Length)))"
            [char]0x2713 + "   Servizio: Windows Service (NSSM - sopravvive a disconnessione RDP)"
            [char]0x2713 + "   Menu Start: 86BIT Connector (Avvia, Disinstalla, Log)"
            [char]0x2713 + "   Avvio automatico: $(if($chkAutostart.Checked){'All avvio del server'}else{'Disabilitato'})"
            [char]0x2713 + "   Polling SNMP: $($deviceList.Items.Count) dispositivi ogni $($txtPollInterval.Text)s"
        )
        $y = 26
        foreach ($item in $items) {
            $lbl = New-Object System.Windows.Forms.Label
            $lbl.Text = $item
            $lbl.Font = New-Object System.Drawing.Font("Segoe UI", 9)
            $lbl.ForeColor = [System.Drawing.Color]::FromArgb(30, 120, 50)
            $lbl.Location = New-Object System.Drawing.Point(18, $y)
            $lbl.AutoSize = $true
            $infoBox.Controls.Add($lbl)
            $y += 22
        }
        
        $tip = New-Object System.Windows.Forms.Label
        $tip.Text = "Trovi l'icona di $AppName vicino all'orologio`nnella barra delle applicazioni (system tray).`nClicca con il tasto destro per le opzioni."
        $tip.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
        $tip.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $tip.Location = New-Object System.Drawing.Point(28, 350)
        $tip.Size = New-Object System.Drawing.Size(450, 55)
        $contentPanel.Controls.Add($tip)
    }
    
    # ==================== NAVIGATION ====================
    $btnNext.Add_Click({
        if ($script:currentPage -eq 4) { $form.Close(); return }
        Show-Page ($script:currentPage + 1)
    })
    
    $btnBack.Add_Click({
        if ($script:currentPage -gt 0 -and $script:currentPage -lt 3) { Show-Page ($script:currentPage - 1) }
    })
    
    Show-Page 0
    $form.ShowDialog()
}

Show-InstallerWizard
