<#
.SYNOPSIS
    ARGUS Connector - Wizard di Installazione
.DESCRIPTION
    Interfaccia grafica per installazione e configurazione.
    Usa .NET Windows.Forms nativo.
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ================================================================
# ADMIN CHECK + AUTO-ELEVATION
# ================================================================
# Se non siamo admin, rilanciamo lo script via "runas" (triggera UAC prompt)
# e usciamo dal processo corrente. Il nuovo processo girera' con privilegi admin.
# ================================================================
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$currentPrincipal = New-Object System.Security.Principal.WindowsPrincipal($currentIdentity)
$isAdmin = $currentPrincipal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    try {
        $scriptPath = $MyInvocation.MyCommand.Path
        # Mostra un messaggio user-friendly (solo console, non blocca il flow)
        Write-Host "[INFO] Elevazione a privilegi amministratore richiesta. Accetta il prompt UAC..." -ForegroundColor Yellow
        
        # Rilancia lo script come admin
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
        $psi.Verb = "runas"    # questo triggera UAC
        $psi.UseShellExecute = $true
        [System.Diagnostics.Process]::Start($psi) | Out-Null
        exit 0
    } catch {
        # L'utente ha rifiutato UAC o altro errore
        [System.Windows.Forms.MessageBox]::Show(
            "Questa installazione richiede privilegi amministratore.`n`n" +
            "Per favore lancia questo file:`n" +
            "  - Tasto destro sul file 'Installa 86NocConnector.vbs'`n" +
            "  - Seleziona 'Esegui come amministratore'`n" +
            "  - Accetta il prompt UAC`n`n" +
            "Errore tecnico: $($_.Exception.Message)",
            "ARGUS Connector - Privilegi insufficienti",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        exit 1
    }
}

# $AppName: identificatore tecnico (path ProgramData, nomi servizio/task) — NON cambiare
# $DisplayName: nome visualizzato all'utente in tutta l'UI del wizard
$AppName = "86NocConnector"
$DisplayName = "ARGUS Connector"
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
    $form.Text = "$DisplayName - Installazione"
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
        $title.Text = "Installazione di $DisplayName"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 40)
        $title.Location = New-Object System.Drawing.Point(28, 20)
        $title.AutoSize = $true
        $contentPanel.Controls.Add($title)
        
        $desc = New-Object System.Windows.Forms.Label
        $desc.Text = "Questa procedura installera' $DisplayName sul computer.`n`n$DisplayName raccoglie SNMP Traps e messaggi Syslog dai dispositivi di rete (switch, firewall, server ILO) e li inoltra al NOC Center in tempo reale."
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
                [System.Windows.Forms.MessageBox]::Show("Inserisci URL e API Key.", $DisplayName, "OK", "Warning")
                return
            }
            try {
                $r = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 10
                # v3.5.16: verifica API key tramite /connector/identify (endpoint backend
                # che data la API key ritorna il client_id). Se 200 e client_id valorizzato
                # la key e' sicuramente accettata dal NOC in produzione.
                $headers = @{ "X-API-Key" = $key }
                try {
                    $identity = Invoke-RestMethod -Uri "$url/api/connector/identify" -Headers $headers -TimeoutSec 10
                    if ($identity -and $identity.client_id) {
                        # Salva il client_id in una variabile form-level per usarlo dopo
                        $script:DiscoveredClientId = $identity.client_id
                        $script:DiscoveredClientName = $identity.client_name
                        [System.Windows.Forms.MessageBox]::Show("Connessione OK! API Key valida.`r`nCliente: $($identity.client_name)`r`nClient ID: $($identity.client_id)", $DisplayName, "OK", "Information")
                        return
                    }
                } catch {
                    # Fallback legacy: prova heartbeat con solo X-API-Key (server pre-v3.5.16
                    # potrebbe non avere ancora /connector/identify ma accettare comunque X-API-Key)
                    $body = @{ connector_version=$Version; hostname=$env:COMPUTERNAME; uptime_seconds=0; traps_received=0; syslogs_received=0 } | ConvertTo-Json
                    $headers["Content-Type"] = "application/json"
                    Invoke-RestMethod -Uri "$url/api/connector/heartbeat" -Method Post -Headers $headers -Body $body -TimeoutSec 10
                    [System.Windows.Forms.MessageBox]::Show("Connessione OK!`r`nAPI Key valida (modalita' legacy: endpoint /identify non disponibile sul NOC).", $DisplayName, "OK", "Information")
                    return
                }
                [System.Windows.Forms.MessageBox]::Show("Connessione OK ma API Key NON riconosciuta dal NOC.`r`nVerifica che la key sia quella attiva nel Center UI.", $DisplayName, "OK", "Warning")
            } catch {
                [System.Windows.Forms.MessageBox]::Show("Errore: $($_.Exception.Message)", $DisplayName, "OK", "Error")
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
        $btnRemoveDev.Size = New-Object System.Drawing.Size(140, 28)
        $btnRemoveDev.Location = New-Object System.Drawing.Point(28, 362)
        $btnRemoveDev.FlatStyle = "Flat"
        $btnRemoveDev.BackColor = [System.Drawing.Color]::White
        $btnRemoveDev.ForeColor = [System.Drawing.Color]::FromArgb(220, 50, 50)
        $btnRemoveDev.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $btnRemoveDev.Cursor = [System.Windows.Forms.Cursors]::Hand
        $contentPanel.Controls.Add($btnRemoveDev)

        # Pulsante Importa CSV
        $btnImportCsv = New-Object System.Windows.Forms.Button
        $btnImportCsv.Text = "Importa CSV..."
        $btnImportCsv.Size = New-Object System.Drawing.Size(110, 28)
        $btnImportCsv.Location = New-Object System.Drawing.Point(180, 362)
        $btnImportCsv.FlatStyle = "Flat"
        $btnImportCsv.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $btnImportCsv.ForeColor = [System.Drawing.Color]::White
        $btnImportCsv.Font = New-Object System.Drawing.Font("Segoe UI", 8, [System.Drawing.FontStyle]::Bold)
        $btnImportCsv.Cursor = [System.Windows.Forms.Cursors]::Hand
        $contentPanel.Controls.Add($btnImportCsv)

        # Poll interval
        $lblPoll = New-Object System.Windows.Forms.Label
        $lblPoll.Text = "Polling (sec):"
        $lblPoll.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $lblPoll.ForeColor = [System.Drawing.Color]::FromArgb(40, 40, 55)
        $lblPoll.Location = New-Object System.Drawing.Point(310, 367)
        $lblPoll.AutoSize = $true
        $contentPanel.Controls.Add($lblPoll)

        $txtPollInterval.Location = New-Object System.Drawing.Point(400, 363)
        $txtPollInterval.Size = New-Object System.Drawing.Size(65, 24)
        $txtPollInterval.Font = New-Object System.Drawing.Font("Consolas", 9)
        if (-not $txtPollInterval.Text) { $txtPollInterval.Text = "60" }
        $contentPanel.Controls.Add($txtPollInterval)

        $hint = New-Object System.Windows.Forms.Label
        $hint.Text = "CSV: header ip, name, community, device_type, snmp_version, snmp_port" + [char]10 + "(separatore virgola, punto e virgola o tab - alias case-insensitive)."
        $hint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
        $hint.ForeColor = [System.Drawing.Color]::FromArgb(140, 140, 155)
        $hint.Location = New-Object System.Drawing.Point(28, 402)
        $hint.Size = New-Object System.Drawing.Size(440, 55)
        $contentPanel.Controls.Add($hint)

        # Button handlers
        $btnAddDev.Add_Click({
            $ip = $txtDeviceIP.Text.Trim()
            if (-not $ip) {
                [System.Windows.Forms.MessageBox]::Show("Inserisci l'indirizzo IP.", $DisplayName, "OK", "Warning")
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

        $btnImportCsv.Add_Click({
            $ofd = New-Object System.Windows.Forms.OpenFileDialog
            $ofd.Filter = "CSV Files (*.csv)|*.csv|Tutti i file (*.*)|*.*"
            $ofd.Title = "Seleziona il CSV dei dispositivi"
            if ($ofd.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }

            try {
                # Auto-detect delimiter (virgola, punto e virgola, tab)
                $firstLine = (Get-Content $ofd.FileName -TotalCount 1 -ErrorAction Stop)
                $delim = ","
                if ($firstLine -match ";") { $delim = ";" }
                elseif ($firstLine -match "`t") { $delim = "`t" }

                $rows = Import-Csv -Path $ofd.FileName -Delimiter $delim -ErrorAction Stop
                if (-not $rows -or $rows.Count -eq 0) {
                    [System.Windows.Forms.MessageBox]::Show(
                        "Il CSV e' vuoto o non leggibile.",
                        $DisplayName, [System.Windows.Forms.MessageBoxButtons]::OK,
                        [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
                    return
                }

                # Normalizza header (case-insensitive, accetta alias)
                $props = $rows[0].PSObject.Properties.Name
                function Find-Col($names) {
                    foreach ($n in $names) {
                        $match = $props | Where-Object { $_.Trim().ToLower() -eq $n.ToLower() } | Select-Object -First 1
                        if ($match) { return $match }
                    }
                    return $null
                }

                $colIp        = Find-Col @("ip", "ip_address", "indirizzo", "address", "host")
                $colName      = Find-Col @("name", "nome", "device_name", "hostname", "descrizione", "description")
                $colCommunity = Find-Col @("community", "snmp_community", "comunita")
                $colType      = Find-Col @("device_type", "type", "tipo", "categoria")
                $colVersion   = Find-Col @("snmp_version", "version", "versione")
                $colPort      = Find-Col @("port", "snmp_port", "porta")

                if (-not $colIp) {
                    [System.Windows.Forms.MessageBox]::Show(
                        "CSV non valido: manca la colonna IP (nomi accettati: ip, ip_address, indirizzo, address, host).",
                        $DisplayName, [System.Windows.Forms.MessageBoxButtons]::OK,
                        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
                    return
                }

                # Dedup contro liste esistenti
                $existingIps = @{}
                foreach ($item in $deviceList.Items) { $existingIps[$item.Text] = $true }

                $imported = 0
                $skipped = 0
                $errors = 0
                foreach ($row in $rows) {
                    $ip = ($row.$colIp).ToString().Trim()
                    if (-not $ip -or $ip -eq "") { continue }
                    # Validazione IP base (IPv4 dotted)
                    if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -and $ip -notmatch '^[a-zA-Z0-9\.\-]+$') {
                        $errors++
                        continue
                    }
                    if ($existingIps.ContainsKey($ip)) { $skipped++; continue }

                    $comm = if ($colCommunity) { ($row.$colCommunity).ToString().Trim() } else { "public" }
                    if (-not $comm) { $comm = "public" }
                    $name = if ($colName) { ($row.$colName).ToString().Trim() } else { $ip }
                    if (-not $name) { $name = $ip }

                    $item = New-Object System.Windows.Forms.ListViewItem($ip)
                    $null = $item.SubItems.Add($comm)
                    $null = $item.SubItems.Add($name)
                    # Tag con metadati extra (device_type, snmp_version, port) per uso futuro
                    $extra = @{}
                    if ($colType)    { $extra.device_type  = ($row.$colType).ToString().Trim() }
                    if ($colVersion) { $extra.snmp_version = ($row.$colVersion).ToString().Trim() }
                    if ($colPort)    { $extra.port         = ($row.$colPort).ToString().Trim() }
                    if ($extra.Count -gt 0) { $item.Tag = $extra }

                    $deviceList.Items.Add($item)
                    $existingIps[$ip] = $true
                    $imported++
                }

                [System.Windows.Forms.MessageBox]::Show(
                    "Import CSV completato.`n`nDispositivi importati: $imported`nDuplicati saltati: $skipped`nRighe non valide: $errors",
                    $DisplayName, [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
            } catch {
                [System.Windows.Forms.MessageBox]::Show(
                    "Errore durante la lettura del CSV:`n`n$($_.Exception.Message)",
                    $DisplayName, [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
            }
        })
    }

    # ==================== PAGE 3: INSTALLING ====================
    function Show-Installing {
        $url = $txtUrl.Text.Trim().TrimEnd("/")
        $key = $txtApiKey.Text.Trim()
        if (-not $url -or -not $key) {
            [System.Windows.Forms.MessageBox]::Show("URL e API Key sono obbligatori.", $DisplayName, "OK", "Warning")
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
            $d = @{
                ip = $item.Text
                community = $item.SubItems[1].Text
                name = $item.SubItems[2].Text
            }
            # Metadati extra importati da CSV (salvati in $item.Tag)
            if ($item.Tag -and $item.Tag -is [hashtable]) {
                if ($item.Tag.device_type)  { $d.device_type  = $item.Tag.device_type }
                if ($item.Tag.snmp_version) { $d.snmp_version = $item.Tag.snmp_version }
                if ($item.Tag.port)         { $d.snmp_port    = $item.Tag.port }
            }
            if (-not $d.snmp_version) { $d.snmp_version = "v2c" }
            $devicesArray += $d
        }
        $pollInterval = 60
        try { $pollInterval = [int]$txtPollInterval.Text } catch {}

        # v3.5.16: se il test connessione ha scoperto il client_id via /identify,
        # salvalo nel config (evita l'auto-discovery runtime). Se non disponibile,
        # prova a ricavarlo ora (anche se l'admin ha skippato il pulsante Test).
        $discoveredClientId = ""
        if ($script:DiscoveredClientId) {
            $discoveredClientId = $script:DiscoveredClientId
        } else {
            try {
                $_h = @{ "X-API-Key" = $key }
                $_id = Invoke-RestMethod -Uri "$url/api/connector/identify" -Headers $_h -TimeoutSec 10 -ErrorAction Stop
                if ($_id -and $_id.client_id) { $discoveredClientId = $_id.client_id }
            } catch {
                # Endpoint /identify non disponibile (NOC produzione pre-v3.5.16) o key invalida
                # → il connector runtime fara' l'auto-discovery dopo il deploy
                $discoveredClientId = ""
            }
        }

        $config = @{
            noc_center_url = $url
            api_key = $key
            client_id = $discoveredClientId
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
        
        # Step 2b: COPIA FILE in C:\Program Files\86NocConnector (evita handle sulla cartella sorgente)
        $txtStatus.AppendText("> Copia file del programma...`r`n")
        $progressBar.Value = 50
        $form.Refresh()
        $InstallPath = Join-Path ([Environment]::GetFolderPath("ProgramFiles")) $AppName
        $sourceDir = $BaseDir  # dove stanno gli script e nssm.exe (prg/ o root in installazioni legacy)
        try {
            if (!(Test-Path $InstallPath)) {
                New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
            }
            # Se la cartella sorgente E' GIA' la InstallPath (cioe' si sta reinstallando da lì), non copiare
            # NOTA: usiamo [IO.Path]::GetFullPath invece di Resolve-Path perche' quest'ultimo ritorna null
            # se il path non esiste (bug installer v3.4.x - fix in v3.5.0)
            $sourceNorm = [IO.Path]::GetFullPath($sourceDir).TrimEnd('\')
            $installNorm = [IO.Path]::GetFullPath($InstallPath).TrimEnd('\')
            if ($sourceNorm -ne $installNorm) {
                # Ferma il servizio se esiste già (evita "file in uso" durante la copia)
                & sc.exe stop "86NocConnectorService" 2>&1 | Out-Null
                Start-Sleep -Seconds 2
                
                # Copia tutti i file sorgente verso InstallPath (include src/, nssm.exe, .bat, version.json)
                Copy-Item "$sourceDir\*" -Destination $InstallPath -Recurse -Force -ErrorAction Stop
                $txtStatus.AppendText("  Copiati in: $InstallPath`r`n")
            } else {
                $txtStatus.AppendText("  Installato in: $InstallPath (in-place)`r`n")
            }
            # Da ora in poi, i percorsi del servizio puntano a InstallPath, non piu' alla cartella sorgente
            $ScriptDir = Join-Path $InstallPath "src"
            $BaseDir = $InstallPath
        } catch {
            $txtStatus.AppendText("  ERRORE copia file: $($_.Exception.Message)`r`n")
            $txtStatus.AppendText("  Installazione proseguita sui file della cartella sorgente (NON eliminare la cartella!)`r`n")
            # IMPORTANTE: se la copia fallisce, BaseDir resta la sorgente, quindi Script/Bat path devono ancora funzionare
            if (-not (Test-Path $ScriptDir)) { $ScriptDir = Join-Path $sourceDir "src" }
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 300
        $txtStatus.AppendText("> Registrazione Servizio Windows (NSSM)...`r`n")
        $progressBar.Value = 60
        $form.Refresh()
        $batPath = Join-Path $BaseDir "86NocConnector.bat"
        $uninstallBat = Join-Path $BaseDir "uninstall.bat"
        $connectorScript = Join-Path $ScriptDir "connector.ps1"
        $nssmPath = Join-Path $BaseDir "nssm.exe"
        $svcName = "86NocConnectorService"
        # v3.5.15: path assoluto a powershell.exe (evita PATH env var non definiti in NSSM LocalSystem context)
        $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        
        if ($chkAutostart.Checked) {
            if (Test-Path $nssmPath) {
                try {
                    # Rimuovi servizio precedente se esiste
                    & $nssmPath stop $svcName 2>$null
                    & $nssmPath remove $svcName confirm 2>$null

                    # === CRITICAL v3.5.12 ===
                    # Rimuovi EVENTUALI Task Scheduler residui con lo stesso nome del servizio.
                    # Nelle prime versioni (pre-v3.3.0) il connector girava come Scheduled Task
                    # chiamato "86NocConnectorService". Se l'utente aveva una vecchia installazione
                    # quel task puo' essere rimasto orfano. Ogni volta che si triggera lancia
                    # una nuova istanza di PowerShell che pollua con il servizio NSSM attuale,
                    # causando restart ciclici ogni ~60 secondi e race condition (il task killa
                    # il servizio e viceversa). Nessun polling completa mai un ciclo.
                    try {
                        $conflictTask = Get-ScheduledTask -TaskName $svcName -ErrorAction SilentlyContinue
                        if ($conflictTask) {
                            $txtStatus.AppendText("  ATTENZIONE: rilevato Task Scheduler legacy con stesso nome del servizio, rimozione...`r`n")
                            Unregister-ScheduledTask -TaskName $svcName -Confirm:$false -ErrorAction SilentlyContinue
                            # Prova anche via schtasks (alcuni task creati da versioni molto vecchie
                            # non sono visibili via Get-ScheduledTask)
                            & schtasks.exe /Delete /TN $svcName /F 2>$null | Out-Null
                            & schtasks.exe /Delete /TN "\$svcName" /F 2>$null | Out-Null
                            Start-Sleep -Milliseconds 500
                            $txtStatus.AppendText("  Task Scheduler legacy rimosso (previene restart ciclici)`r`n")
                        }
                    } catch {
                        $txtStatus.AppendText("  Warn: cleanup task legacy non critico: $($_.Exception.Message)`r`n")
                    }
                    # Kill eventuali processi PowerShell legati a connector.ps1 (orfani da task vecchi)
                    try {
                        Get-WmiObject Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
                            Where-Object { $_.CommandLine -like "*connector.ps1*" } |
                            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
                    } catch {}

                    # Registra il servizio con NSSM
                    # v3.5.15 FIX quoting: nssm install con AppParameters inline
                    # NON rispetta le virgolette su path con spazi (es. "C:\Program Files\...").
                    # Risultato pre-fix: PowerShell ricevette `-File C:\Program` come path monco
                    # → "Il file non ha estensione 'ps1'" → crash infinito ogni 60s su Program Files.
                    # Fix: install col solo eseguibile, poi AppParameters via `set` (quoting OK).
                    & $nssmPath install $svcName $psExe
                    & $nssmPath set $svcName AppParameters ('-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File "' + $connectorScript + '"')
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

                    # === Defender exclusions (v3.3.4+) ===
                    # Previene che ASR/real-time scanning blocchino updater.ps1 o killi processi legittimi
                    # del connector. Cartelle whitelist + processi whitelist.
                    try {
                        $txtStatus.AppendText("> Configurazione esclusioni Windows Defender...`r`n")
                        Add-MpPreference -ExclusionPath $BaseDir -ErrorAction SilentlyContinue
                        Add-MpPreference -ExclusionPath $ConfigDir -ErrorAction SilentlyContinue
                        Add-MpPreference -ExclusionProcess (Join-Path $BaseDir "nssm.exe") -ErrorAction SilentlyContinue
                        Add-MpPreference -ExclusionProcess (Join-Path $ScriptDir "connector.ps1") -ErrorAction SilentlyContinue
                        Add-MpPreference -ExclusionExtension ".ps1" -ErrorAction SilentlyContinue 2>$null
                        $txtStatus.AppendText("  OK: Defender exclusions aggiunte per InstallDir + ConfigDir`r`n")
                    } catch {
                        $txtStatus.AppendText("  NOTA: Defender exclusions non aggiunte: $($_.Exception.Message)`r`n")
                        $txtStatus.AppendText("  (Se l'updater ha problemi in futuro, aggiungi manualmente C:\Program Files\86NocConnector alle esclusioni Defender)`r`n")
                    }
                    
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
            # Crea la cartella con timeout di filesystem sync (a volte la creazione e' lazy)
            if (-not (Test-Path $startMenuDir)) {
                New-Item -ItemType Directory -Path $startMenuDir -Force -ErrorAction Stop | Out-Null
                Start-Sleep -Milliseconds 300  # Attendi sync filesystem
            }
            # Verifica esplicita post-creazione
            if (-not (Test-Path $startMenuDir)) {
                throw "Impossibile creare cartella $startMenuDir"
            }
            # Rimuovi vecchie cartelle con nomi diversi
            $oldDir = Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86NocConnector"
            if (Test-Path $oldDir) { Remove-Item $oldDir -Recurse -Force -ErrorAction SilentlyContinue }
            $oldDir2 = Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86BIT Connector"
            if (Test-Path $oldDir2) { Remove-Item $oldDir2 -Recurse -Force -ErrorAction SilentlyContinue }
            
            # Path del logo 86bit (icona per shortcut principali "Avvia Connector" e "Diagnostica")
            $iconPath = Join-Path $BaseDir "src\86bit_logo.ico"
            $iconLocation = if (Test-Path $iconPath) { "$iconPath,0" } else { "shell32.dll,13" }
            # Icone native Windows per shortcut "Cartella Log" e "Disinstalla":
            # - shell32.dll,3   = cartella (gialla)
            # - shell32.dll,271 = cestino / remove (rosso)
            $iconFolderNative = "$env:SystemRoot\System32\shell32.dll,3"
            $iconUninstallNative = "$env:SystemRoot\System32\shell32.dll,271"
            
            # Verifica che il batPath esista, altrimenti usa powershell.exe diretto
            $connectorTarget = $batPath
            $connectorArgs = ""
            if (-not (Test-Path $batPath)) {
                $connectorTarget = "powershell.exe"
                $connectorArgs = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$connectorScript`""
            }

            $shell = New-Object -ComObject WScript.Shell
            # Funzione helper per creare shortcut con error handling individuale
            $createShortcutSafe = {
                param($shell, $path, $target, $args, $workdir, $desc, $iconLoc, $windowStyle)
                try {
                    $sc = $shell.CreateShortcut($path)
                    $sc.TargetPath = $target
                    if ($args) { $sc.Arguments = $args }
                    if ($workdir -and (Test-Path $workdir)) { $sc.WorkingDirectory = $workdir }
                    $sc.Description = $desc
                    if ($iconLoc) { $sc.IconLocation = $iconLoc }
                    if ($windowStyle) { $sc.WindowStyle = $windowStyle }
                    $sc.Save()
                    return $true
                } catch {
                    return $false
                }
            }
            
            $shortcutResults = @()
            # Collegamento Avvia ARGUS Center Connector
            $ok = & $createShortcutSafe $shell "$startMenuDir\ARGUS Center Connector.lnk" $connectorTarget $connectorArgs $BaseDir "Avvia ARGUS Center Connector" $iconLocation 7
            $shortcutResults += @{ name = "ARGUS Center Connector"; ok = $ok }
            
            # Collegamento Diagnostica
            $diagScript = Join-Path $BaseDir "diagnostica_connessione.ps1"
            if (Test-Path $diagScript) {
                $ok = & $createShortcutSafe $shell "$startMenuDir\Diagnostica Connessione.lnk" "powershell.exe" "-ExecutionPolicy Bypass -File `"$diagScript`"" $BaseDir "Diagnostica connessione ARGUS Center" $iconLocation 1
                $shortcutResults += @{ name = "Diagnostica Connessione"; ok = $ok }
            }
            # Collegamento Disinstalla (icona nativa Windows: cestino)
            if (Test-Path $uninstallBat) {
                $ok = & $createShortcutSafe $shell "$startMenuDir\Disinstalla ARGUS Connector.lnk" $uninstallBat $null $BaseDir "Disinstalla ARGUS Center Connector" $iconUninstallNative 1
                $shortcutResults += @{ name = "Disinstalla"; ok = $ok }
            }
            # Collegamento Apri Cartella Log (icona nativa Windows: cartella)
            $logDir = Join-Path $env:ProgramData "86NocConnector\logs"
            if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
            $ok = & $createShortcutSafe $shell "$startMenuDir\Apri Cartella Log.lnk" "explorer.exe" $logDir $null "Apri la cartella dei log del connettore" $iconFolderNative 1
            $shortcutResults += @{ name = "Apri Cartella Log"; ok = $ok }
            
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
            $okCount = ($shortcutResults | Where-Object { $_.ok }).Count
            $totalCount = $shortcutResults.Count
            if ($okCount -eq $totalCount) {
                $txtStatus.AppendText("  Menu Start: OK ($okCount/$totalCount shortcut)`r`n")
            } else {
                $failedNames = ($shortcutResults | Where-Object { -not $_.ok } | ForEach-Object { $_.name }) -join ", "
                $txtStatus.AppendText("  Menu Start: parziale ($okCount/$totalCount shortcut, falliti: $failedNames)`r`n")
            }
        } catch {
            $txtStatus.AppendText("  Menu Start: $($_.Exception.Message)`r`n")
        }
        try {
            $regPath = "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86BIT_ArgusCenter_Connector"
            # Rimuovi vecchia chiave con nome diverso (da entrambe le registry view)
            & reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName" /f /reg:64 2>$null
            & reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName" /f /reg:32 2>$null
            # Rimuovi chiave vecchia con stesso nome ma eventualmente scritta in Wow6432Node
            & reg delete $regPath /f /reg:32 2>$null
            # Calcola dimensione reale installazione in KB per "EstimatedSize" (App e funzionalita')
            $estimatedSizeKB = 1024
            try {
                $sizeBytes = (Get-ChildItem -LiteralPath $BaseDir -Recurse -Force -ErrorAction SilentlyContinue |
                    Measure-Object -Property Length -Sum).Sum
                if ($sizeBytes -and $sizeBytes -gt 0) {
                    $estimatedSizeKB = [int]([Math]::Ceiling($sizeBytes / 1024))
                }
            } catch {}
            # Scrivi ESPLICITAMENTE nella 64-bit registry view (per visibilita' in "App e funzionalita'")
            & reg add $regPath /v "DisplayName" /t REG_SZ /d "ARGUS Connector" /f /reg:64 2>$null
            & reg add $regPath /v "DisplayVersion" /t REG_SZ /d "$Version" /f /reg:64 2>$null
            & reg add $regPath /v "Publisher" /t REG_SZ /d "86BIT srl Unipersonale" /f /reg:64 2>$null
            & reg add $regPath /v "URLInfoAbout" /t REG_SZ /d "https://www.86bit.it" /f /reg:64 2>$null
            & reg add $regPath /v "HelpLink" /t REG_SZ /d "mailto:info@86bit.it" /f /reg:64 2>$null
            & reg add $regPath /v "Contact" /t REG_SZ /d "info@86bit.it" /f /reg:64 2>$null
            & reg add $regPath /v "UninstallString" /t REG_SZ /d "`"$uninstallBat`"" /f /reg:64 2>$null
            & reg add $regPath /v "InstallLocation" /t REG_SZ /d "$BaseDir" /f /reg:64 2>$null
            # Logo 86bit in Programmi e Funzionalita' (invece dell'icona generica blu di Windows)
            $iconRegPath = Join-Path $BaseDir "src\86bit_logo.ico"
            if (Test-Path $iconRegPath) {
                & reg add $regPath /v "DisplayIcon" /t REG_SZ /d "$iconRegPath" /f /reg:64 2>$null
            }
            & reg add $regPath /v "InstallDate" /t REG_SZ /d "$(Get-Date -Format 'yyyyMMdd')" /f /reg:64 2>$null
            & reg add $regPath /v "EstimatedSize" /t REG_DWORD /d $estimatedSizeKB /f /reg:64 2>$null
            # Verifica lettura: deve essere visibile in x64 registry
            $verifyRead = & reg query $regPath /v "DisplayName" /reg:64 2>$null
            if ($verifyRead -and ($verifyRead -match "DisplayName")) {
                $txtStatus.AppendText("  Programmi e Funzionalita': OK (ARGUS Connector v$Version, $estimatedSizeKB KB)`r`n")
            } else {
                $txtStatus.AppendText("  Programmi e Funzionalita': scritta ma non verificata (controlla manualmente)`r`n")
            }
            & reg add $regPath /v "NoModify" /t REG_DWORD /d 1 /f /reg:64 2>$null
            & reg add $regPath /v "NoRepair" /t REG_DWORD /d 1 /f /reg:64 2>$null
        } catch {
            $txtStatus.AppendText("  Programmi e Funzionalita': errore - $($_.Exception.Message)`r`n")
        }
        $form.Refresh()
        Start-Sleep -Milliseconds 500
        
        # === Step 3b: Scheduled Task per auto-update (pattern Microsoft-native v3.5.0+) ===
        $txtStatus.AppendText("> Creazione Scheduled Task auto-update...`r`n")
        $form.Refresh()
        try {
            $taskName = "ArgusConnectorUpdater"
            $fullTaskName = "\86BIT\$taskName"
            $updateScriptPath = Join-Path $BaseDir "src\update_check.ps1"
            
            if (-not (Test-Path $updateScriptPath)) {
                throw "update_check.ps1 non trovato in $updateScriptPath"
            }
            
            # Rimuovi task preesistenti (clean state)
            & schtasks.exe /Delete /TN $fullTaskName /F 2>&1 | Out-Null
            & schtasks.exe /Delete /TN "\86NocConnector\UpdateChecker" /F 2>&1 | Out-Null
            
            # Metodo XML-first (piu' affidabile di schtasks /TR con virgolette annidate)
            # Genera un XML task completo con tutte le safety features e lo registra via /XML.
            $taskXmlContent = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>ARGUS Connector auto-update - checks NOC every 5 min</Description>
    <Author>86BIT srl</Author>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$updateScriptPath" -InstallDir "$BaseDir"</Arguments>
    </Exec>
  </Actions>
</Task>
"@
            $tmpXml = Join-Path $env:TEMP "argus_updater_task.xml"
            # IMPORTANTE: schtasks /XML richiede Unicode UTF-16 LE con BOM
            [System.IO.File]::WriteAllText($tmpXml, $taskXmlContent, [System.Text.Encoding]::Unicode)
            
            $createOutput = & schtasks.exe /Create /TN $fullTaskName /XML $tmpXml /F 2>&1
            $createExit = $LASTEXITCODE
            Remove-Item $tmpXml -Force -ErrorAction SilentlyContinue
            
            if ($createExit -eq 0) {
                $txtStatus.AppendText("  Scheduled Task: OK ($fullTaskName ogni 5 min, XML method)`r`n")
            } else {
                # Fallback: metodo /TR string-based con escape doppio manuale
                $txtStatus.AppendText("  XML method exit=$createExit : fallback /TR method...`r`n")
                $escPs = $updateScriptPath -replace '"', '\"'
                $escBd = $BaseDir -replace '"', '\"'
                $taskActionFallback = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \`"$escPs\`" -InstallDir \`"$escBd\`""
                $fallbackOutput = & schtasks.exe /Create /TN $fullTaskName /SC MINUTE /MO 5 /TR $taskActionFallback /RU "SYSTEM" /RL HIGHEST /F 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $txtStatus.AppendText("  Scheduled Task: OK ($fullTaskName, fallback method)`r`n")
                } else {
                    throw "Entrambi i metodi falliti (XML exit=$createExit, fallback exit=$LASTEXITCODE). Output: $fallbackOutput"
                }
            }
        } catch {
            $txtStatus.AppendText("  Scheduled Task: ERRORE - $($_.Exception.Message)`r`n")
            $txtStatus.AppendText("  (auto-update non funzionera'; puoi riprovare lanciando bootstrap_to_v350.cmd come admin)`r`n")
        }
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
        $txtStatus.AppendText("> Avvio $DisplayName...`r`n")
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

        # Verifica che nessun riferimento punti ancora alla cartella sorgente
        if ($sourceDir -and $sourceNorm -and $installNorm -and ($sourceNorm -ne $installNorm)) {
            $txtStatus.AppendText("`r`n> Verifica integrita' installazione...`r`n")
            $allOk = $true
            try {
                $svcExe = (& sc.exe qc "86NocConnectorService" 2>$null | Out-String)
                if ($svcExe -match [regex]::Escape($sourceNorm)) {
                    $txtStatus.AppendText("  ATTENZIONE: servizio punta ancora a $sourceNorm`r`n")
                    $allOk = $false
                }
            } catch {}
            if ($allOk) {
                $txtStatus.AppendText("  Nessun riferimento alla cartella sorgente: OK`r`n")
                $txtStatus.AppendText("  -> La cartella di installazione originale puo' ora essere eliminata.`r`n")
            }
        }

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
        $desc.Text = "$DisplayName e' stato installato e avviato.`n`nOra lo switch HPE verra' monitorato automaticamente.`nSe una porta cambia stato, riceverai un alert nel NOC."
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
        $tip.Text = "Trovi l'icona di $DisplayName vicino all'orologio`nnella barra delle applicazioni (system tray).`nClicca con il tasto destro per le opzioni."
        $tip.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
        $tip.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $tip.Location = New-Object System.Drawing.Point(28, 340)
        $tip.Size = New-Object System.Drawing.Size(450, 55)
        $contentPanel.Controls.Add($tip)

        # Avviso: la cartella di installazione puo' essere eliminata
        $cleanupTip = New-Object System.Windows.Forms.Label
        $cleanupTip.Text = [char]0x1F5D1 + " La cartella usata per l'installazione puo' essere eliminata in sicurezza. Il servizio gira da Program Files e non ha piu' alcuna dipendenza dalla cartella originale."
        $cleanupTip.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Italic)
        $cleanupTip.ForeColor = [System.Drawing.Color]::FromArgb(22, 163, 74)
        $cleanupTip.Location = New-Object System.Drawing.Point(28, 400)
        $cleanupTip.Size = New-Object System.Drawing.Size(450, 40)
        $contentPanel.Controls.Add($cleanupTip)
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
