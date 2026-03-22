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
$Version = "1.0.0"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = Split-Path -Parent $ScriptDir
$ConfigDir = Join-Path $env:ProgramData $AppName
$ConfigPath = Join-Path $ConfigDir "config.json"

# ==================== WIZARD FORM ====================

function Show-InstallerWizard {
    [System.Windows.Forms.Application]::EnableVisualStyles()
    
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Installazione $AppName"
    $form.Size = New-Object System.Drawing.Size(640, 480)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
    
    # Left panel (branding)
    $leftPanel = New-Object System.Windows.Forms.Panel
    $leftPanel.Location = New-Object System.Drawing.Point(0, 0)
    $leftPanel.Size = New-Object System.Drawing.Size(200, 480)
    $leftPanel.BackColor = [System.Drawing.Color]::FromArgb(10, 10, 15)
    $form.Controls.Add($leftPanel)
    
    # Logo image
    $logoPath = Join-Path $ScriptDir "86bit_logo.jpg"
    if (Test-Path $logoPath) {
        $logoPic = New-Object System.Windows.Forms.PictureBox
        $logoPic.Location = New-Object System.Drawing.Point(35, 80)
        $logoPic.Size = New-Object System.Drawing.Size(130, 130)
        $logoPic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
        $logoPic.BackColor = [System.Drawing.Color]::Transparent
        $logoPic.Image = [System.Drawing.Image]::FromFile($logoPath)
        $leftPanel.Controls.Add($logoPic)
    }
    
    $lblApp = New-Object System.Windows.Forms.Label
    $lblApp.Text = "NocConnector"
    $lblApp.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
    $lblApp.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $lblApp.BackColor = [System.Drawing.Color]::Transparent
    $lblApp.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $lblApp.Location = New-Object System.Drawing.Point(20, 220)
    $lblApp.Size = New-Object System.Drawing.Size(160, 20)
    $leftPanel.Controls.Add($lblApp)
    
    # Company info at bottom of left panel
    $lblCompany = New-Object System.Windows.Forms.Label
    $lblCompany.Text = "86BIT srl Unipersonale`nP.Iva 04353030168`nScanzorosciate (BG)`nTel. +39 035 310 900`ninfo@86bit.it"
    $lblCompany.Font = New-Object System.Drawing.Font("Segoe UI", 7)
    $lblCompany.ForeColor = [System.Drawing.Color]::FromArgb(120, 120, 140)
    $lblCompany.BackColor = [System.Drawing.Color]::Transparent
    $lblCompany.TextAlign = [System.Drawing.ContentAlignment]::BottomCenter
    $lblCompany.Location = New-Object System.Drawing.Point(5, 360)
    $lblCompany.Size = New-Object System.Drawing.Size(190, 75)
    $leftPanel.Controls.Add($lblCompany)
    
    # Content panel
    $contentPanel = New-Object System.Windows.Forms.Panel
    $contentPanel.Location = New-Object System.Drawing.Point(200, 0)
    $contentPanel.Size = New-Object System.Drawing.Size(440, 400)
    $contentPanel.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
    $form.Controls.Add($contentPanel)
    
    # Button bar
    $btnBar = New-Object System.Windows.Forms.Panel
    $btnBar.Location = New-Object System.Drawing.Point(200, 400)
    $btnBar.Size = New-Object System.Drawing.Size(440, 50)
    $btnBar.BackColor = [System.Drawing.Color]::FromArgb(224, 224, 224)
    $form.Controls.Add($btnBar)
    
    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Text = "Annulla"
    $btnCancel.Size = New-Object System.Drawing.Size(80, 30)
    $btnCancel.Location = New-Object System.Drawing.Point(348, 10)
    $btnCancel.FlatStyle = "Flat"
    $btnCancel.BackColor = [System.Drawing.Color]::White
    $btnCancel.Add_Click({ $form.Close() })
    $btnBar.Controls.Add($btnCancel)
    
    $btnNext = New-Object System.Windows.Forms.Button
    $btnNext.Text = "Avanti >"
    $btnNext.Size = New-Object System.Drawing.Size(90, 30)
    $btnNext.Location = New-Object System.Drawing.Point(252, 10)
    $btnNext.FlatStyle = "Flat"
    $btnNext.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnNext.ForeColor = [System.Drawing.Color]::White
    $btnBar.Controls.Add($btnNext)
    
    $btnBack = New-Object System.Windows.Forms.Button
    $btnBack.Text = "< Indietro"
    $btnBack.Size = New-Object System.Drawing.Size(90, 30)
    $btnBack.Location = New-Object System.Drawing.Point(156, 10)
    $btnBack.FlatStyle = "Flat"
    $btnBack.BackColor = [System.Drawing.Color]::White
    $btnBack.Enabled = $false
    $btnBar.Controls.Add($btnBack)
    
    # Input fields
    $txtUrl = New-Object System.Windows.Forms.TextBox
    $txtApiKey = New-Object System.Windows.Forms.TextBox
    $txtSNMP = New-Object System.Windows.Forms.TextBox
    $txtSyslog = New-Object System.Windows.Forms.TextBox
    $chkAutostart = New-Object System.Windows.Forms.CheckBox
    $txtStatus = New-Object System.Windows.Forms.TextBox
    $progressBar = New-Object System.Windows.Forms.ProgressBar
    
    $currentPage = 0
    
    function Clear-Content {
        $contentPanel.Controls.Clear()
    }
    
    function Show-Page($page) {
        $script:currentPage = $page
        Clear-Content
        $btnBack.Enabled = ($page -gt 0)
        
        switch ($page) {
            0 { Show-Welcome }
            1 { Show-Config }
            2 { Show-Installing }
            3 { Show-Complete }
        }
    }
    
    function Show-Welcome {
        $btnNext.Text = "Avanti >"
        $btnNext.Enabled = $true
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Installazione di $AppName"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
        $title.Location = New-Object System.Drawing.Point(20, 15)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "Questa procedura installera' $AppName sul tuo computer.`n`n$AppName raccoglie SNMP Traps e messaggi Syslog dai`ndispositivi di rete (switch, firewall, server ILO) e li`ninoltra al NOC Center in tempo reale."
        $desc.Font = New-Object System.Drawing.Font("Segoe UI", 10)
        $desc.Location = New-Object System.Drawing.Point(20, 55)
        $desc.Size = New-Object System.Drawing.Size(400, 100)
        $contentPanel.Controls.Add($desc)
        
        $infoBox = New-Object System.Windows.Forms.GroupBox
        $infoBox.Text = "Cosa verra' installato"
        $infoBox.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $infoBox.Location = New-Object System.Drawing.Point(20, 165)
        $infoBox.Size = New-Object System.Drawing.Size(395, 150)
        $contentPanel.Controls.Add($infoBox)
        
        $items = @(
            "Servizio SNMP Trap listener (porta UDP 162)"
            "Servizio Syslog listener (porta UDP 514)"
            "Icona nella system tray per monitoraggio"
            "Regole firewall Windows"
            "Avvio automatico con Windows"
        )
        $y = 22
        foreach ($item in $items) {
            $lbl = New-Object System.Windows.Forms.Label
            $lbl.Text = [char]0x2022 + "  $item"
            $lbl.Font = New-Object System.Drawing.Font("Segoe UI", 9)
            $lbl.Location = New-Object System.Drawing.Point(15, $y)
            $lbl.AutoSize = $true
            $infoBox.Controls.Add($lbl)
            $y += 22
        }
        
        $footer = New-Object System.Windows.Forms.Label
        $footer.Text = "Clicca 'Avanti' per continuare."
        $footer.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $footer.ForeColor = [System.Drawing.Color]::Gray
        $footer.Location = New-Object System.Drawing.Point(20, 325)
        $footer.AutoSize = $true
        $contentPanel.Controls.Add($footer)
        
        # Company legal footer
        $legalFooter = New-Object System.Windows.Forms.Label
        $legalFooter.Text = "86BIT srl Unipersonale - C.F. e P.Iva 04353030168 - Cap. soc. `u{20AC} 30.000,00 i.v. - Reg. Imprese BG 04353030168`r`nREA n. BG456578 - Piazza Papa Giovanni XXIII - 24020 Scanzorosciate (BG) - Tel. +39 035 310 900 - info@86bit.it"
        $legalFooter.Font = New-Object System.Drawing.Font("Segoe UI", 6.5)
        $legalFooter.ForeColor = [System.Drawing.Color]::FromArgb(160, 160, 170)
        $legalFooter.Location = New-Object System.Drawing.Point(20, 360)
        $legalFooter.Size = New-Object System.Drawing.Size(400, 30)
        $contentPanel.Controls.Add($legalFooter)
    }
    
    function Show-Config {
        $btnNext.Text = "Installa >"
        $btnNext.Enabled = $true
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Configurazione"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
        $title.Location = New-Object System.Drawing.Point(20, 15)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "Inserisci i dati di connessione al NOC Center."
        $desc.Font = New-Object System.Drawing.Font("Segoe UI", 10)
        $desc.Location = New-Object System.Drawing.Point(20, 50)
        $desc.AutoSize = $true
        $contentPanel.Controls.Add($desc)
        
        # URL
        $lblUrl = New-Object System.Windows.Forms.Label
        $lblUrl.Text = "URL NOC Center *"
        $lblUrl.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
        $lblUrl.Location = New-Object System.Drawing.Point(20, 85)
        $lblUrl.AutoSize = $true
        $contentPanel.Controls.Add($lblUrl)
        
        $txtUrl.Location = New-Object System.Drawing.Point(20, 105)
        $txtUrl.Size = New-Object System.Drawing.Size(395, 25)
        $txtUrl.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtUrl)
        
        $lblUrlHint = New-Object System.Windows.Forms.Label
        $lblUrlHint.Text = "Es: https://noc.azienda.it"
        $lblUrlHint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $lblUrlHint.ForeColor = [System.Drawing.Color]::Gray
        $lblUrlHint.Location = New-Object System.Drawing.Point(20, 130)
        $lblUrlHint.AutoSize = $true
        $contentPanel.Controls.Add($lblUrlHint)
        
        # API Key
        $lblKey = New-Object System.Windows.Forms.Label
        $lblKey.Text = "API Key del Cliente *"
        $lblKey.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
        $lblKey.Location = New-Object System.Drawing.Point(20, 155)
        $lblKey.AutoSize = $true
        $contentPanel.Controls.Add($lblKey)
        
        $txtApiKey.Location = New-Object System.Drawing.Point(20, 175)
        $txtApiKey.Size = New-Object System.Drawing.Size(395, 25)
        $txtApiKey.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtApiKey)
        
        $lblKeyHint = New-Object System.Windows.Forms.Label
        $lblKeyHint.Text = "Copiala dalla pagina Clienti del NOC Center"
        $lblKeyHint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $lblKeyHint.ForeColor = [System.Drawing.Color]::Gray
        $lblKeyHint.Location = New-Object System.Drawing.Point(20, 200)
        $lblKeyHint.AutoSize = $true
        $contentPanel.Controls.Add($lblKeyHint)
        
        # Ports
        $lblSNMP = New-Object System.Windows.Forms.Label
        $lblSNMP.Text = "Porta SNMP"
        $lblSNMP.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $lblSNMP.Location = New-Object System.Drawing.Point(20, 235)
        $lblSNMP.AutoSize = $true
        $contentPanel.Controls.Add($lblSNMP)
        
        $txtSNMP.Text = "162"
        $txtSNMP.Location = New-Object System.Drawing.Point(100, 232)
        $txtSNMP.Size = New-Object System.Drawing.Size(60, 25)
        $txtSNMP.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtSNMP)
        
        $lblSyslog2 = New-Object System.Windows.Forms.Label
        $lblSyslog2.Text = "Porta Syslog"
        $lblSyslog2.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $lblSyslog2.Location = New-Object System.Drawing.Point(190, 235)
        $lblSyslog2.AutoSize = $true
        $contentPanel.Controls.Add($lblSyslog2)
        
        $txtSyslog.Text = "514"
        $txtSyslog.Location = New-Object System.Drawing.Point(275, 232)
        $txtSyslog.Size = New-Object System.Drawing.Size(60, 25)
        $txtSyslog.Font = New-Object System.Drawing.Font("Consolas", 10)
        $contentPanel.Controls.Add($txtSyslog)
        
        # Autostart
        $chkAutostart.Text = "Avvia automaticamente con Windows"
        $chkAutostart.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $chkAutostart.Location = New-Object System.Drawing.Point(20, 270)
        $chkAutostart.Checked = $true
        $chkAutostart.AutoSize = $true
        $contentPanel.Controls.Add($chkAutostart)
        
        # Test button
        $btnTest = New-Object System.Windows.Forms.Button
        $btnTest.Text = "Test Connessione"
        $btnTest.Size = New-Object System.Drawing.Size(130, 30)
        $btnTest.Location = New-Object System.Drawing.Point(20, 310)
        $btnTest.FlatStyle = "Flat"
        $btnTest.BackColor = [System.Drawing.Color]::White
        $btnTest.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $btnTest.Add_Click({
            $url = $txtUrl.Text.Trim().TrimEnd("/")
            $key = $txtApiKey.Text.Trim()
            if (-not $url -or -not $key) {
                [System.Windows.Forms.MessageBox]::Show("Inserisci URL e API Key", $AppName, "OK", "Warning")
                return
            }
            try {
                $r = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 10
                $body = @{ connector_version=$Version; hostname=$env:COMPUTERNAME; uptime_seconds=0; traps_received=0; syslogs_received=0 } | ConvertTo-Json
                $headers = @{ "X-API-Key" = $key; "Content-Type" = "application/json" }
                Invoke-RestMethod -Uri "$url/api/connector/heartbeat" -Method Post -Headers $headers -Body $body -TimeoutSec 10
                [System.Windows.Forms.MessageBox]::Show("Connessione riuscita! API Key valida.", $AppName, "OK", "Information")
            } catch {
                [System.Windows.Forms.MessageBox]::Show("Errore: $($_.Exception.Message)", $AppName, "OK", "Error")
            }
        })
        $contentPanel.Controls.Add($btnTest)
    }
    
    function Show-Installing {
        $url = $txtUrl.Text.Trim().TrimEnd("/")
        $key = $txtApiKey.Text.Trim()
        if (-not $url -or -not $key) {
            [System.Windows.Forms.MessageBox]::Show("URL e API Key obbligatori", $AppName, "OK", "Warning")
            Show-Page 1
            return
        }
        
        $btnNext.Enabled = $false
        $btnBack.Enabled = $false
        $btnCancel.Enabled = $false
        $btnNext.Text = "Avanti >"
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Installazione in corso..."
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
        $title.Location = New-Object System.Drawing.Point(20, 15)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $progressBar.Location = New-Object System.Drawing.Point(20, 55)
        $progressBar.Size = New-Object System.Drawing.Size(395, 25)
        $progressBar.Minimum = 0
        $progressBar.Maximum = 100
        $contentPanel.Controls.Add($progressBar)
        
        $txtStatus.Multiline = $true
        $txtStatus.ScrollBars = "Vertical"
        $txtStatus.ReadOnly = $true
        $txtStatus.Location = New-Object System.Drawing.Point(20, 90)
        $txtStatus.Size = New-Object System.Drawing.Size(395, 280)
        $txtStatus.Font = New-Object System.Drawing.Font("Consolas", 9)
        $txtStatus.BackColor = [System.Drawing.Color]::FromArgb(26, 26, 46)
        $txtStatus.ForeColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
        $contentPanel.Controls.Add($txtStatus)
        
        # Run installation
        $form.Refresh()
        
        # Step 1: Config
        $txtStatus.AppendText("> Salvataggio configurazione...`r`n")
        $progressBar.Value = 20
        if (!(Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null }
        $logsDir = Join-Path $ConfigDir "logs"
        if (!(Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir -Force | Out-Null }
        $config = @{
            noc_center_url = $url
            api_key = $key
            snmp_trap_port = [int]$txtSNMP.Text
            syslog_port = [int]$txtSyslog.Text
            heartbeat_interval_seconds = 60
            batch_interval_seconds = 3
        }
        $config | ConvertTo-Json -Depth 5 | Set-Content $ConfigPath -Encoding UTF8
        $txtStatus.AppendText("  Config: $ConfigPath`r`n")
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 2: Firewall
        $txtStatus.AppendText("> Configurazione firewall...`r`n")
        $progressBar.Value = 40
        try {
            & netsh advfirewall firewall delete rule name="86NocConnector SNMP" 2>$null
            & netsh advfirewall firewall delete rule name="86NocConnector Syslog" 2>$null
            & netsh advfirewall firewall add rule name="86NocConnector SNMP" dir=in action=allow protocol=UDP localport=$($txtSNMP.Text) 2>$null
            & netsh advfirewall firewall add rule name="86NocConnector Syslog" dir=in action=allow protocol=UDP localport=$($txtSyslog.Text) 2>$null
            $txtStatus.AppendText("  Regola SNMP UDP/$($txtSNMP.Text): OK`r`n")
            $txtStatus.AppendText("  Regola Syslog UDP/$($txtSyslog.Text): OK`r`n")
        } catch {
            $txtStatus.AppendText("  Firewall: serve Amministratore`r`n")
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 3: Autostart + Registrazione in Programmi e Funzionalita'
        $txtStatus.AppendText("> Avvio automatico e registrazione...`r`n")
        $progressBar.Value = 60
        $batPath = Join-Path $BaseDir "86NocConnector.bat"
        $uninstallBat = Join-Path $BaseDir "uninstall.bat"
        if ($chkAutostart.Checked) {
            try {
                & reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v $AppName /t REG_SZ /d "`"$batPath`"" /f 2>$null
                $txtStatus.AppendText("  Registrato avvio automatico`r`n")
            } catch {
                $txtStatus.AppendText("  Errore registro: $($_.Exception.Message)`r`n")
            }
        }
        # Registra in Installazione applicazioni / Programmi e Funzionalita'
        try {
            $regPath = "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"
            & reg add $regPath /v "DisplayName" /t REG_SZ /d "$AppName" /f 2>$null
            & reg add $regPath /v "DisplayVersion" /t REG_SZ /d "$Version" /f 2>$null
            & reg add $regPath /v "Publisher" /t REG_SZ /d "86BIT srl Unipersonale" /f 2>$null
            & reg add $regPath /v "URLInfoAbout" /t REG_SZ /d "https://www.86bit.it" /f 2>$null
            & reg add $regPath /v "HelpLink" /t REG_SZ /d "mailto:info@86bit.it" /f 2>$null
            & reg add $regPath /v "Contact" /t REG_SZ /d "info@86bit.it" /f 2>$null
            & reg add $regPath /v "UninstallString" /t REG_SZ /d "`"$uninstallBat`"" /f 2>$null
            & reg add $regPath /v "InstallLocation" /t REG_SZ /d "$BaseDir" /f 2>$null
            & reg add $regPath /v "NoModify" /t REG_DWORD /d 1 /f 2>$null
            & reg add $regPath /v "NoRepair" /t REG_DWORD /d 1 /f 2>$null
            $txtStatus.AppendText("  Registrato in Programmi e Funzionalita'`r`n")
        } catch {
            $txtStatus.AppendText("  Registro programmi: serve Amministratore`r`n")
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 4: Test
        $txtStatus.AppendText("> Test connessione...`r`n")
        $progressBar.Value = 80
        try {
            Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 10 | Out-Null
            $txtStatus.AppendText("  NOC Center raggiungibile: OK`r`n")
        } catch {
            $txtStatus.AppendText("  NOC Center: $($_.Exception.Message)`r`n")
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # Step 5: Start tray
        $txtStatus.AppendText("> Avvio 86NocConnector...`r`n")
        $progressBar.Value = 100
        $trayScript = Join-Path $ScriptDir "tray_app.ps1"
        try {
            Start-Process "powershell.exe" -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$trayScript`"" -WindowStyle Hidden
            $txtStatus.AppendText("  Icona nella system tray: ATTIVA`r`n")
        } catch {
            $txtStatus.AppendText("  Errore avvio tray: $($_.Exception.Message)`r`n")
        }
        
        $txtStatus.AppendText("`r`n> Installazione completata!`r`n")
        $form.Refresh()
        
        $btnNext.Enabled = $true
        $btnCancel.Enabled = $true
    }
    
    function Show-Complete {
        $btnNext.Text = "Fine"
        $btnBack.Enabled = $false
        $btnCancel.Enabled = $false
        
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Installazione Completata!"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(22, 163, 74)
        $title.Location = New-Object System.Drawing.Point(20, 15)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "$AppName e' stato installato e avviato.`n`nOra configura i dispositivi per inviare SNMP Traps`ne Syslog all'indirizzo IP di questo server."
        $desc.Font = New-Object System.Drawing.Font("Segoe UI", 10)
        $desc.Location = New-Object System.Drawing.Point(20, 55)
        $desc.Size = New-Object System.Drawing.Size(400, 80)
        $contentPanel.Controls.Add($desc)
        
        $infoBox = New-Object System.Windows.Forms.GroupBox
        $infoBox.Text = "Riepilogo"
        $infoBox.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $infoBox.Location = New-Object System.Drawing.Point(20, 140)
        $infoBox.Size = New-Object System.Drawing.Size(395, 155)
        $contentPanel.Controls.Add($infoBox)
        
        $items = @(
            [char]0x2713 + "  Config: $ConfigPath"
            [char]0x2713 + "  SNMP: UDP/$($txtSNMP.Text)"
            [char]0x2713 + "  Syslog: UDP/$($txtSyslog.Text)"
            [char]0x2713 + "  NOC: $($txtUrl.Text.Trim().Substring(0, [Math]::Min(45, $txtUrl.Text.Trim().Length)))"
            [char]0x2713 + "  Icona system tray: Attiva"
            [char]0x2713 + "  Avvio automatico: $(if($chkAutostart.Checked){'Si'}else{'No'})"
        )
        $y = 22
        foreach ($item in $items) {
            $lbl = New-Object System.Windows.Forms.Label
            $lbl.Text = $item
            $lbl.Font = New-Object System.Drawing.Font("Segoe UI", 9)
            $lbl.ForeColor = [System.Drawing.Color]::FromArgb(46, 125, 50)
            $lbl.Location = New-Object System.Drawing.Point(15, $y)
            $lbl.AutoSize = $true
            $infoBox.Controls.Add($lbl)
            $y += 20
        }
        
        $tip = New-Object System.Windows.Forms.Label
        $tip.Text = "Trovi l'icona di $AppName vicino all'orologio`nnella barra delle applicazioni (system tray).`nCliccaci con il tasto destro per le opzioni."
        $tip.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
        $tip.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $tip.Location = New-Object System.Drawing.Point(20, 305)
        $tip.Size = New-Object System.Drawing.Size(400, 50)
        $contentPanel.Controls.Add($tip)
        
        # Company legal footer on complete page
        $legalComplete = New-Object System.Windows.Forms.Label
        $legalComplete.Text = "86BIT srl Unipersonale - C.F. e P.Iva 04353030168 - Cap. soc. `u{20AC} 30.000,00 i.v. - Reg. Imprese BG 04353030168`r`nREA n. BG456578 - Piazza Papa Giovanni XXIII - 24020 Scanzorosciate (BG) - Tel. +39 035 310 900 - info@86bit.it"
        $legalComplete.Font = New-Object System.Drawing.Font("Segoe UI", 6.5)
        $legalComplete.ForeColor = [System.Drawing.Color]::FromArgb(160, 160, 170)
        $legalComplete.Location = New-Object System.Drawing.Point(20, 365)
        $legalComplete.Size = New-Object System.Drawing.Size(400, 30)
        $contentPanel.Controls.Add($legalComplete)
    }
    
    # Navigation
    $btnNext.Add_Click({
        if ($currentPage -eq 3) { $form.Close(); return }
        Show-Page ($currentPage + 1)
    })
    
    $btnBack.Add_Click({
        if ($currentPage -gt 0) { Show-Page ($currentPage - 1) }
    })
    
    Show-Page 0
    $form.ShowDialog()
}

Show-InstallerWizard
