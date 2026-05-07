<#
.SYNOPSIS
    ARGUS Connector - System Tray Application
.DESCRIPTION
    Icona nella system tray vicino all'orologio.
    Usa .NET Windows.Forms nativo (incluso in Windows).
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# v3.7.6: Rendi il processo DPI-aware PRIMA di qualsiasi chiamata Windows.Forms.
# Senza questo, su Windows 11 con DPI 125%/150% il sistema applica "DPI
# virtualization" (bitmap scaling) che falsa le coordinate calcolate e taglia
# i controlli posizionati in pixel assoluti.
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class DpiAwareTray {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int value);
}
"@ -ErrorAction SilentlyContinue
    # 1 = Process_System_DPI_Aware. Fallback su Win7/8 con SetProcessDPIAware.
    try { [DpiAwareTray]::SetProcessDpiAwareness(1) | Out-Null } catch { [DpiAwareTray]::SetProcessDPIAware() | Out-Null }
} catch {}

# $AppName: identificatore tecnico (path ProgramData, nomi task/servizio) - NON cambiare, rompe installazioni esistenti
# $DisplayName: nome visualizzato all'utente in tutta l'UI (tooltip, form title, MessageBox, About)
$AppName = "86NocConnector"
$DisplayName = "ARGUS Connector"
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

# v3.8.8: dot-source del Network Scanner (tool standalone integrato).
# Carica le funzioni Show-NetworkScanner, NS-GetMac, NS-GetHostname, NS-GetVendor,
# NS-TestPort, NS-ListSmbShares, NS-WakeOnLan e $script:NS_OuiMap.
$networkScannerScript = Join-Path $ScriptDir "network_scanner.ps1"
if (Test-Path $networkScannerScript) {
    try { . $networkScannerScript } catch {
        Write-Host "[WARN] Errore caricamento network_scanner.ps1: $($_.Exception.Message)"
    }
}

# ==================== ICON GENERATION ====================

function New-TrayIcon([string]$status = "running", [string]$mode = "master") {
    $bmp = New-Object System.Drawing.Bitmap(32, 32)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)

    # v3.8.7: in modalita' Scanner usiamo SEMPRE l'azzurro come colore primario
    # (anche quando running) per distinguere visualmente master vs scanner nel tray.
    if ($mode -eq "scanner") {
        switch ($status) {
            "running" { $bgColor = [System.Drawing.Color]::FromArgb(56, 132, 222) }    # Sky-500 azzurro
            "error"   { $bgColor = [System.Drawing.Color]::FromArgb(239, 68, 68) }     # Red
            "stopped" { $bgColor = [System.Drawing.Color]::FromArgb(107, 114, 128) }   # Gray
            default   { $bgColor = [System.Drawing.Color]::FromArgb(56, 132, 222) }    # Sky-500 azzurro
        }
    } else {
        # Modalita' Master: schema colori originale (verde quando running)
        switch ($status) {
            "running" { $bgColor = [System.Drawing.Color]::FromArgb(34, 197, 94) }    # Green
            "error"   { $bgColor = [System.Drawing.Color]::FromArgb(239, 68, 68) }    # Red
            "stopped" { $bgColor = [System.Drawing.Color]::FromArgb(107, 114, 128) }  # Gray
            default   { $bgColor = [System.Drawing.Color]::FromArgb(99, 102, 241) }   # Purple
        }
    }

    # Draw rounded rect background
    $brush = New-Object System.Drawing.SolidBrush($bgColor)
    $g.FillRectangle($brush, 0, 0, 32, 32)

    # Draw "86" text
    $font = New-Object System.Drawing.Font("Arial", 10, [System.Drawing.FontStyle]::Bold)
    $whiteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $g.DrawString("86", $font, $whiteBrush, 2, 1)

    # v3.8.7: per scanner mostriamo "SC" invece di "NC", per master "NC" come prima
    $fontSmall = New-Object System.Drawing.Font("Arial", 7, [System.Drawing.FontStyle]::Bold)
    $bottomLabel = if ($mode -eq "scanner") { "SC" } else { "NC" }
    $g.DrawString($bottomLabel, $fontSmall, $whiteBrush, 5, 18)

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

# v3.8.7 helper: legge mode dal config (cached). Usato da tooltip, titoli finestre, icona.
function Get-ConnectorMode {
    try {
        if (Test-Path $ConfigPath) {
            $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
            if ($cfg.mode) { return $cfg.mode.ToLower() }
        }
    } catch {}
    return "master"
}

# v3.8.7 helper: nome visualizzato dipendente dalla modalita' (master vs scanner)
function Get-DisplayNameForMode {
    if ((Get-ConnectorMode) -eq "scanner") { return "Connector Scanner" }
    return $DisplayName
}

# ==================== CONNECTOR PROCESS (via Scheduled Task) ====================

$global:ConnectorProcess = $null
$global:IsRunning = $false
# v3.8.23: rinominato da "86NocConnectorService" a "86NocConnector_TrayTask"
# per evitare CONFLITTO/RACE CONDITION col servizio NSSM omonimo. Il vecchio
# nome causava il SELF-HEAL ciclico ogni 30-60 min con conseguenti restart
# dello Scanner e dispositivi che andavano OFFLINE per 2-3 min sulla UI Center.
$global:TaskName = "86NocConnector_TrayTask"
$global:LegacyTaskName = "86NocConnectorService"  # vecchio nome conflittuale, va rimosso una volta sola

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
        # v3.8.23: rimuovi PRIMA il vecchio task conflittuale (stesso nome del servizio NSSM)
        # se esiste da installazioni precedenti — sblocca la race condition definitivamente
        try {
            Unregister-ScheduledTask -TaskName $global:LegacyTaskName -Confirm:$false -ErrorAction SilentlyContinue
        } catch {}
        # Rimuovi vecchio task con nome corrente (re-registrazione idempotente)
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
        # v3.8: mostra modalita' connector (master/scanner)
        $cMode = if ($config -and $config.mode) { $config.mode.ToUpper() } else { "MASTER" }
        $cExtra = ""
        if ($cMode -eq "SCANNER" -and $config) {
            $cExtra = " | Subnet: $($config.subnet)"
            if ($config.vlan_id) { $cExtra += " VLAN $($config.vlan_id)" }
        }
        return "$DisplayName v$($status.version)`nModalita': $cMode$cExtra`nStato: ATTIVO ($mode)`nUptime: ${upH}h ${upM}m`nNOC: $nocUrl`nSNMP: $($status.snmp_received) | Syslog: $($status.syslog_received)"
    }
    return "$DisplayName v$Version`nStato: FERMO"
}

# Tooltip sintetico per la system tray (limite hard 63 char).
function Get-TooltipText {
    $status = Read-ConnectorStatus
    $config = if (Test-Path $ConfigPath) { Get-Content $ConfigPath -Raw | ConvertFrom-Json } else { $null }
    $cMode = if ($config -and $config.mode) { $config.mode.ToUpper() } else { "MASTER" }
    # v3.8.7: per scanner usiamo nome esteso "Connector Scanner" nel tooltip
    $name = if ($cMode -eq "SCANNER") { "Connector Scanner" } else { $DisplayName }
    if ($status -and $status.status -eq "running") {
        return "$name v$($status.version) | ATTIVO"
    }
    return "$name v$Version | FERMO"
}

# ==================== DEVICE MANAGER ====================

function Show-DeviceManager {
    $isScanner = (Get-ConnectorMode) -eq "scanner"
    # v3.8.9: in modalita' Scanner, "Gestisci Dispositivi" apre direttamente
    # il Network Scanner completo (no Device Manager con campi SNMP).
    if ($isScanner) {
        Show-NetworkScanner
        return $false
    }
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "$DisplayName - Gestisci Dispositivi"
    $form.Size = New-Object System.Drawing.Size(820, 580)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(245, 245, 248)
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

    # Title
    $lblTitle = New-Object System.Windows.Forms.Label
    $lblTitle.Text = "Dispositivi Monitorati (SNMP Polling)"
    $lblTitle.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 40)
    $lblTitle.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
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
    $txtName.Size = New-Object System.Drawing.Size(260, 26)
    $txtName.Font = New-Object System.Drawing.Font("Consolas", 9.5)
    $form.Controls.Add($txtName)

    $btnAdd = New-Object System.Windows.Forms.Button
    $btnAdd.Text = "Aggiungi"
    $btnAdd.Size = New-Object System.Drawing.Size(80, 26)
    $btnAdd.Location = New-Object System.Drawing.Point(538, 90)
    $btnAdd.FlatStyle = "Flat"
    $btnAdd.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $btnAdd.ForeColor = [System.Drawing.Color]::White
    $btnAdd.Font = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Bold)
    $btnAdd.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnAdd)

    # ListView
    $listView = New-Object System.Windows.Forms.ListView
    $listView.Location = New-Object System.Drawing.Point(20, 130)
    $listView.Size = New-Object System.Drawing.Size(758, 240)
    $listView.View = [System.Windows.Forms.View]::Details
    $listView.FullRowSelect = $true
    $listView.GridLines = $true
    $listView.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $listView.BackColor = [System.Drawing.Color]::White
    $null = $listView.Columns.Add("IP Address", 120)
    $null = $listView.Columns.Add("Community", 90)
    $null = $listView.Columns.Add("Nome", 220)
    $null = $listView.Columns.Add("Web UI", 315)
    $form.Controls.Add($listView)

    # Load current devices from config
    if (Test-Path $ConfigPath) {
        $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($config.devices) {
            foreach ($dev in $config.devices) {
                $item = New-Object System.Windows.Forms.ListViewItem($dev.ip)
                $null = $item.SubItems.Add($dev.community)
                $null = $item.SubItems.Add($dev.name)
                $webCell = if ($dev.web_console_url) { [string]([char]0x2713) + " " + [string]$dev.web_console_url } else { [string]([char]0x2014) }
                $null = $item.SubItems.Add([string]$webCell)
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
    $btnRemove.Size = New-Object System.Drawing.Size(135, 30)
    $btnRemove.Location = New-Object System.Drawing.Point(20, 425)
    $btnRemove.FlatStyle = "Flat"
    $btnRemove.BackColor = [System.Drawing.Color]::White
    $btnRemove.ForeColor = [System.Drawing.Color]::FromArgb(220, 50, 50)
    $btnRemove.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
    $btnRemove.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnRemove)
    $btnTestSnmp = New-Object System.Windows.Forms.Button
    $btnTestSnmp.Text = "Test SNMP"
    $btnTestSnmp.Size = New-Object System.Drawing.Size(110, 30)
    $btnTestSnmp.Location = New-Object System.Drawing.Point(165, 425)
    $btnTestSnmp.FlatStyle = "Flat"
    $btnTestSnmp.BackColor = [System.Drawing.Color]::FromArgb(59, 130, 246)
    $btnTestSnmp.ForeColor = [System.Drawing.Color]::White
    $btnTestSnmp.Font = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Bold)
    $btnTestSnmp.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnTestSnmp)

    $btnWebUI = New-Object System.Windows.Forms.Button
    $btnWebUI.Text = "Apri Web UI"
    $btnWebUI.Size = New-Object System.Drawing.Size(135, 30)
    $btnWebUI.Location = New-Object System.Drawing.Point(290, 425)
    $btnWebUI.FlatStyle = "Flat"
    $btnWebUI.BackColor = [System.Drawing.Color]::FromArgb(168, 85, 247)
    $btnWebUI.ForeColor = [System.Drawing.Color]::White
    $btnWebUI.Font = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Bold)
    $btnWebUI.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnWebUI)

    $btnTestAllWebUI = New-Object System.Windows.Forms.Button
    $btnTestAllWebUI.Text = "Test Web UI (tutti)"
    $btnTestAllWebUI.Size = New-Object System.Drawing.Size(140, 30)
    $btnTestAllWebUI.Location = New-Object System.Drawing.Point(435, 425)
    $btnTestAllWebUI.FlatStyle = "Flat"
    $btnTestAllWebUI.BackColor = [System.Drawing.Color]::White
    $btnTestAllWebUI.ForeColor = [System.Drawing.Color]::FromArgb(168, 85, 247)
    $btnTestAllWebUI.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
    $btnTestAllWebUI.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnTestAllWebUI)

    $btnSave = New-Object System.Windows.Forms.Button
    $btnSave.Text = "Salva e Riavvia"
    $btnSave.Size = New-Object System.Drawing.Size(200, 30)
    $btnSave.Location = New-Object System.Drawing.Point(590, 425)
    $btnSave.FlatStyle = "Flat"
    $btnSave.BackColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
    $btnSave.ForeColor = [System.Drawing.Color]::White
    $btnSave.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $btnSave.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($btnSave)

    $lblHint = New-Object System.Windows.Forms.Label
    $lblHint.Text = "Apri Web UI: testa http/https sul device e, se risponde, invia il link ad ARGUS Center. Salva e Riavvia applica le modifiche al servizio."
    $lblHint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $lblHint.ForeColor = [System.Drawing.Color]::FromArgb(140, 140, 155)
    $lblHint.Location = New-Object System.Drawing.Point(20, 465)
    $lblHint.Size = New-Object System.Drawing.Size(780, 35)
    $form.Controls.Add($lblHint)

    # Add button handler
    $btnAdd.Add_Click({
        $ip = $txtIP.Text.Trim()
        if (-not $ip) {
            [System.Windows.Forms.MessageBox]::Show("Inserisci un indirizzo IP.", $DisplayName, "OK", "Warning")
            return
        }
        $comm = if ($txtComm.Text.Trim()) { $txtComm.Text.Trim() } else { "public" }
        $devName = if ($txtName.Text.Trim()) { $txtName.Text.Trim() } else { $ip }

        # Check duplicate
        foreach ($existing in $listView.Items) {
            if ($existing.Text -eq $ip) {
                [System.Windows.Forms.MessageBox]::Show("IP gia' presente nella lista.", $DisplayName, "OK", "Warning")
                return
            }
        }

        $item = New-Object System.Windows.Forms.ListViewItem($ip)
        $null = $item.SubItems.Add($comm)
        $null = $item.SubItems.Add($devName)
        $null = $item.SubItems.Add([string]([char]0x2014))
        $listView.Items.Add($item)
        $txtIP.Text = ""
        $txtName.Text = ""
    })

    # Export CSV handler
    $btnExport.Add_Click({
        if ($listView.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun dispositivo da esportare.", $DisplayName, "OK", "Warning")
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
            [System.Windows.Forms.MessageBox]::Show("$($listView.Items.Count) dispositivi esportati in:`n$($saveDialog.FileName)", $DisplayName, "OK", "Information")
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
                $null = $item.SubItems.Add([string]([char]0x2014))
                $listView.Items.Add($item)
                $imported++
            }
            [System.Windows.Forms.MessageBox]::Show("$imported dispositivi importati.", $DisplayName, "OK", "Information")
        }
    })

    # Remove button handler
    $btnRemove.Add_Click({
        if ($listView.SelectedItems.Count -gt 0) {
            $listView.Items.Remove($listView.SelectedItems[0])
        } else {
            [System.Windows.Forms.MessageBox]::Show("Seleziona un dispositivo dalla lista.", $DisplayName, "OK", "Information")
        }
    })

    # Test SNMP button handler
    $btnTestSnmp.Add_Click({
        if ($listView.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun dispositivo nella lista.", $DisplayName, "OK", "Warning")
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
        $resultForm.Text = "$DisplayName - Risultati Test SNMP"
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

    # ==================== WEB UI HELPERS ====================
    # Prova le porte HTTP/HTTPS comuni su un device, ritorna oggetto con url/port/scheme/title/status, oppure $null
    function Test-DeviceWebUI([string]$ip) {
        # SSL bypass per certificati self-signed (iLO, switch, firewall)
        if (-not ("CertBypassTray" -as [type])) {
            Add-Type -TypeDefinition @"
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
public static class CertBypassTray {
    public static void Enable() {
        System.Net.ServicePointManager.ServerCertificateValidationCallback = (s, c, ch, e) => true;
    }
    public static void Disable() {
        System.Net.ServicePointManager.ServerCertificateValidationCallback = null;
    }
}
"@
        }
        try {
            [Net.ServicePointManager]::SecurityProtocol = `
                [Net.SecurityProtocolType]::Tls -bor [Net.SecurityProtocolType]::Tls11 -bor `
                [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        } catch {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        }
        [CertBypassTray]::Enable()
        try {
            # Ordine porte: iLO/firewall su HTTPS 443 -> HTTP 80 -> alternative
            $candidates = @(
                @{ port=443;  scheme="https" },
                @{ port=80;   scheme="http"  },
                @{ port=8443; scheme="https" },
                @{ port=8080; scheme="http"  },
                @{ port=4443; scheme="https" },
                @{ port=10000;scheme="https" },
                @{ port=8000; scheme="http"  },
                @{ port=8888; scheme="http"  }
            )
            foreach ($c in $candidates) {
                $url = "$($c.scheme)://${ip}:$($c.port)/"
                try {
                    $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 `
                                -MaximumRedirection 3 -UserAgent "86NocConnector/TrayWebUI" -ErrorAction Stop
                    $title = ""
                    if ($resp.Content -match '<title[^>]*>(.*?)</title>') { $title = $Matches[1].Trim() }
                    return @{
                        url=$url; port=$c.port; scheme=$c.scheme
                        title=$title; status_code=[int]$resp.StatusCode; working=$true
                    }
                } catch {
                    # Connection refused / timeout / DNS -> prova prossima porta
                    continue
                }
            }
        } finally {
            [CertBypassTray]::Disable()
        }
        return $null
    }

    function Send-WebUIToArgus([string]$ip, [string]$community, [string]$name, $detection) {
        if (-not (Test-Path $ConfigPath)) { return $false }
        try {
            $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
            $url = "$($cfg.noc_center_url.TrimEnd('/'))/api/connector/web-ui-detected"
            $payload = @{
                device_ip   = $ip
                name        = $name
                community   = $community
                url         = $detection.url
                port        = $detection.port
                scheme      = $detection.scheme
                title       = $detection.title
                status_code = $detection.status_code
                working     = $detection.working
            } | ConvertTo-Json -Compress
            $headers = @{ "X-API-Key" = $cfg.api_key; "Content-Type" = "application/json" }
            try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch {}
            $null = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $payload -TimeoutSec 10 -ErrorAction Stop
            return $true
        } catch {
            return $false
        }
    }

    # Apri Web UI (device selezionato)
    $btnWebUI.Add_Click({
        if ($listView.SelectedItems.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Seleziona un dispositivo dalla lista.", $DisplayName, "OK", "Information")
            return
        }
        $item = $listView.SelectedItems[0]
        $ip   = $item.Text
        $comm = $item.SubItems[1].Text
        $name = $item.SubItems[2].Text

        $btnWebUI.Enabled = $false
        $btnWebUI.Text = "Rilevo..."
        $form.Refresh()
        [System.Windows.Forms.Cursor]::Current = [System.Windows.Forms.Cursors]::WaitCursor

        $det = Test-DeviceWebUI $ip

        [System.Windows.Forms.Cursor]::Current = [System.Windows.Forms.Cursors]::Default
        $btnWebUI.Enabled = $true
        $btnWebUI.Text = "Apri Web UI"

        if (-not $det) {
            $item.SubItems[3].Text = [string]([char]0x2715) + " non raggiungibile"
            [System.Windows.Forms.MessageBox]::Show(
                "Nessuna Web UI raggiungibile su $ip.`n`nPorte provate: 443, 80, 8443, 8080, 4443, 10000, 8000, 8888.`nVerifica firewall / service web del device.",
                $DisplayName, "OK", "Warning") | Out-Null
            return
        }

        # Apri nel browser di sistema
        try { Start-Process $det.url | Out-Null } catch {
            [System.Windows.Forms.MessageBox]::Show("Impossibile avviare il browser: $($_.Exception.Message)", $DisplayName, "OK", "Error") | Out-Null
        }

        # Aggiorna colonna Web UI
        $item.SubItems[3].Text = [string]([char]0x2713) + " " + [string]$det.url
        $item.Tag = $det

        # Invia ad ARGUS Center
        $sent = Send-WebUIToArgus $ip $comm $name $det
        $statusMsg = if ($sent) {
            "Web UI aperta nel browser: $($det.url)`n`nInformazione registrata su ARGUS Center (device ora disponibile nella console web)."
        } else {
            "Web UI aperta nel browser: $($det.url)`n`nATTENZIONE: impossibile contattare ARGUS Center per registrare il device (verifica rete)."
        }
        [System.Windows.Forms.MessageBox]::Show($statusMsg, $DisplayName, "OK",
            (& { if ($sent) { [System.Windows.Forms.MessageBoxIcon]::Information } else { [System.Windows.Forms.MessageBoxIcon]::Warning } })) | Out-Null
    })

    # Test Web UI su tutti i device (non apre il browser, solo detection + report)
    $btnTestAllWebUI.Add_Click({
        if ($listView.Items.Count -eq 0) {
            [System.Windows.Forms.MessageBox]::Show("Nessun dispositivo nella lista.", $DisplayName, "OK", "Warning") | Out-Null
            return
        }
        $btnTestAllWebUI.Enabled = $false
        $btnTestAllWebUI.Text = "Testing..."
        [System.Windows.Forms.Cursor]::Current = [System.Windows.Forms.Cursors]::WaitCursor

        $okCount = 0; $koCount = 0; $pushed = 0
        $summary = ""
        foreach ($item in $listView.Items) {
            $ip   = $item.Text
            $comm = $item.SubItems[1].Text
            $name = $item.SubItems[2].Text
            $item.SubItems[3].Text = "..."
            $form.Refresh()

            $det = Test-DeviceWebUI $ip
            if ($det) {
                $okCount++
                $item.SubItems[3].Text = [string]([char]0x2713) + " " + [string]$det.url
                $item.Tag = $det
                if (Send-WebUIToArgus $ip $comm $name $det) { $pushed++ }
                $summary += "OK  $ip -> $($det.url)`r`n"
            } else {
                $koCount++
                $item.SubItems[3].Text = [string]([char]0x2715) + " non raggiungibile"
                $summary += "--  $ip (nessuna web UI)`r`n"
            }
        }

        [System.Windows.Forms.Cursor]::Current = [System.Windows.Forms.Cursors]::Default
        $btnTestAllWebUI.Enabled = $true
        $btnTestAllWebUI.Text = "Test Web UI (tutti)"

        [System.Windows.Forms.MessageBox]::Show(
            "Test completato.`n`nWeb UI rilevate: $okCount`nNon raggiungibili: $koCount`nInviate ad ARGUS Center: $pushed`n`n$summary",
            $DisplayName, "OK", "Information") | Out-Null
    })

    # Save button handler
    $btnSave.Add_Click({
        if (Test-Path $ConfigPath) {
            $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        } else {
            [System.Windows.Forms.MessageBox]::Show("Nessuna configurazione trovata. Esegui prima l'installer.", $DisplayName, "OK", "Error")
            return
        }

        # Build devices array
        $devicesArray = @()
        foreach ($item in $listView.Items) {
            $dev = @{
                ip = $item.Text
                community = $item.SubItems[1].Text
                name = $item.SubItems[2].Text
            }
            # Se il device ha Web UI rilevata, salvala per riuso
            if ($item.Tag -and $item.Tag.url) {
                $dev.web_console_url    = $item.Tag.url
                $dev.web_console_port   = $item.Tag.port
                $dev.web_console_scheme = $item.Tag.scheme
                $dev.web_console_title  = $item.Tag.title
            }
            $devicesArray += $dev
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
            $DisplayName,
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

# ==================== MANUAL UPDATE ====================

function Invoke-SecureUpdateCheck($config) {
    # HMAC-SHA256 signed GET to /api/connector/update-check
    try {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }
        $timestamp = [math]::Floor(([DateTimeOffset]::UtcNow).ToUnixTimeSeconds())
        $nonce = [guid]::NewGuid().ToString("N")
        $hmacSecret = "argus-hmac-k3y-2026!" + $config.api_key
        $message = "$($config.api_key)$timestamp$nonce"
        $hmac = New-Object System.Security.Cryptography.HMACSHA256
        $hmac.Key = [Text.Encoding]::UTF8.GetBytes($hmacSecret)
        $signature = [BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($message))).Replace("-","").ToLower()
        $headers = @{
            "X-API-Key"        = $config.api_key
            "X-HMAC-Signature" = $signature
            "X-Timestamp"      = $timestamp.ToString()
            "X-Nonce"          = $nonce
        }
        return Invoke-RestMethod -Uri "$($config.noc_center_url)/api/connector/update-check" -Method Get -Headers $headers -TimeoutSec 15 -ErrorAction Stop
    } catch {
        return $null
    }
}

function Invoke-ManualUpdate($notifyIcon) {
    # Verifica privilegi admin (necessari per Stop/Start del servizio Windows)
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
    if (-not $isAdmin) {
        [System.Windows.Forms.MessageBox]::Show(
            "L'aggiornamento manuale richiede privilegi di Amministratore.`n`nChiudi questa applicazione e riaprila cliccando con il tasto destro sull'icona -> `"Esegui come amministratore`".",
            "$DisplayName - Privilegi richiesti",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
        return
    }

    # Load config
    if (-not (Test-Path $ConfigPath)) {
        [System.Windows.Forms.MessageBox]::Show("Configurazione non trovata.", $DisplayName,
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        return
    }
    $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    if (-not $config.api_key -or -not $config.noc_center_url) {
        [System.Windows.Forms.MessageBox]::Show("Configurazione incompleta (api_key o noc_center_url mancante).", $DisplayName,
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        return
    }

    # Show "checking..." notification
    $notifyIcon.ShowBalloonTip(2000, $DisplayName, "Verifica aggiornamenti in corso...", [System.Windows.Forms.ToolTipIcon]::Info)

    # Check for update
    $updateInfo = Invoke-SecureUpdateCheck $config
    if (-not $updateInfo) {
        [System.Windows.Forms.MessageBox]::Show(
            "Impossibile contattare ARGUS Center.`n`nVerifica:`n- connessione internet`n- URL in configurazione: $($config.noc_center_url)",
            "$DisplayName - Errore rete",
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        return
    }

    if (-not $updateInfo.update_available -or $updateInfo.latest_version -eq $Version) {
        [System.Windows.Forms.MessageBox]::Show(
            "Sei gia' alla versione piu' recente (v$Version).",
            "$DisplayName - Nessun aggiornamento",
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        return
    }

    # Confirm update
    $msg = "E' disponibile una nuova versione.`n`n" +
           "Corrente:  v$Version`n" +
           "Nuova:     v$($updateInfo.latest_version)`n`n"
    if ($updateInfo.changelog) { $msg += "Changelog:`n$($updateInfo.changelog)`n`n" }
    $msg += "Procedere con l'aggiornamento?`n(Il connettore verra' fermato per qualche secondo e riavviato automaticamente)"

    $result = [System.Windows.Forms.MessageBox]::Show(
        $msg, "$DisplayName - Aggiornamento disponibile",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($result -ne [System.Windows.Forms.DialogResult]::Yes) { return }

    # Download zip
    try {
        $notifyIcon.ShowBalloonTip(3000, $DisplayName, "Download v$($updateInfo.latest_version) in corso...", [System.Windows.Forms.ToolTipIcon]::Info)
        $headers = @{ "X-API-Key" = $config.api_key }
        $downloadUrl = "$($config.noc_center_url)$($updateInfo.download_url)"
        $tempZip = Join-Path $env:TEMP "86NocConnector_manual_update.zip"
        $tempExtract = Join-Path $env:TEMP "86NocConnector_manual_update"
        if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force }
        Invoke-WebRequest -Uri $downloadUrl -Headers $headers -OutFile $tempZip -TimeoutSec 120 -ErrorAction Stop

        # Extract
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($tempZip, $tempExtract)

        # Launch updater (independent) and exit tray app
        # Use the NEW updater.ps1 (from the just-extracted zip)
        $newUpdater = Join-Path $tempExtract "src\updater.ps1"
        $installDir = Split-Path -Parent $ScriptDir
        $updaterPath = if (Test-Path $newUpdater) { $newUpdater } else { Join-Path $ScriptDir "updater.ps1" }
        $args = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$updaterPath`" -ExtractPath `"$tempExtract`" -InstallDir `"$installDir`" -ApiUrl `"$($config.noc_center_url)`" -ApiKey `"$($config.api_key)`""
        Start-Process "powershell.exe" -ArgumentList $args -WindowStyle Hidden

        $notifyIcon.ShowBalloonTip(5000, $DisplayName, "Aggiornamento in corso. Il servizio verra' riavviato automaticamente.", [System.Windows.Forms.ToolTipIcon]::Info)

        # Give updater 3s to kick in, then exit tray app (updater killera' gli altri processi)
        Start-Sleep -Seconds 3
        $notifyIcon.Visible = $false
        [System.Windows.Forms.Application]::Exit()
    } catch {
        [System.Windows.Forms.MessageBox]::Show(
            "Errore durante l'aggiornamento:`n`n$($_.Exception.Message)",
            "$DisplayName - Errore",
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    }
}

# ==================== TRAY APPLICATION ====================

function Set-NotifyIconTooltip($notifyIcon, $text) {
    # Windows NotifyIcon ha limite HARD di 63 caratteri per il tooltip.
    # Superare il limite lancia SetValueInvocationException che spamma in loop nel timer.
    try {
        $flat = ($text -replace "`r`n", " | ") -replace "`n", " | "
        if ($flat.Length -gt 63) {
            $flat = $flat.Substring(0, 60) + "..."
        }
        $notifyIcon.Text = $flat
    } catch {
        # Ultimo fallback: non crashare mai il timer della tray
        try { $notifyIcon.Text = $DisplayName } catch {}
    }
}

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
    $notifyIcon.Icon = New-TrayIcon "stopped" (Get-ConnectorMode)
    $notifyIcon.Text = "$DisplayName v$Version | Avvio..."
    $notifyIcon.Visible = $true
    
    # Context Menu
    $contextMenu = New-Object System.Windows.Forms.ContextMenuStrip
    $contextMenu.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 50)
    $contextMenu.ForeColor = [System.Drawing.Color]::White
    $contextMenu.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    
    # Title item (disabled)
    $titleItem = $contextMenu.Items.Add("$DisplayName v$Version")
    $titleItem.Enabled = $false
    $titleItem.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $titleItem.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    
    $contextMenu.Items.Add("-") | Out-Null
    
    # Status
    $statusItem = $contextMenu.Items.Add("Stato")
    $statusItem.Add_Click({
        $text = Get-StatusText
        [System.Windows.Forms.MessageBox]::Show($text, "$DisplayName - Stato", 
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
            $notifyIcon.Icon = New-TrayIcon "running" (Get-ConnectorMode)
            $notifyIcon.Text = "$DisplayName v$Version | Stato: ATTIVO"
            $notifyIcon.ShowBalloonTip(3000, $DisplayName, "Connector avviato e in ascolto", [System.Windows.Forms.ToolTipIcon]::Info)
            $startItem.Visible = $false
            $stopItem.Visible = $true
            $restartItem.Visible = $true
        } else {
            [System.Windows.Forms.MessageBox]::Show("Errore avvio. Verifica la configurazione.", $DisplayName,
                [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        }
    })
    
    # Stop
    $stopItem = $contextMenu.Items.Add("Ferma")
    $stopItem.ForeColor = [System.Drawing.Color]::FromArgb(239, 68, 68)
    $stopItem.Visible = $false
    $stopItem.Add_Click({
        Stop-ConnectorProcess
        $notifyIcon.Icon = New-TrayIcon "stopped" (Get-ConnectorMode)
        $notifyIcon.Text = "$DisplayName v$Version | Stato: FERMO"
        $notifyIcon.ShowBalloonTip(2000, $DisplayName, "Connector fermato", [System.Windows.Forms.ToolTipIcon]::Warning)
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
            $notifyIcon.Icon = New-TrayIcon "running" (Get-ConnectorMode)
            $notifyIcon.Text = "$DisplayName v$Version | Stato: ATTIVO"
            $notifyIcon.ShowBalloonTip(2000, $DisplayName, "Connector riavviato", [System.Windows.Forms.ToolTipIcon]::Info)
        }
    })

    # Check for Updates
    $updateItem = $contextMenu.Items.Add("Verifica aggiornamenti")
    $updateItem.ForeColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
    $updateItem.Add_Click({
        Invoke-ManualUpdate $notifyIcon
    })
    
    $contextMenu.Items.Add("-") | Out-Null
    
    # View Logs
    $logItem = $contextMenu.Items.Add("Visualizza Log")
    $logItem.Add_Click({
        $logFile = Join-Path (Join-Path $env:ProgramData $AppName) "logs\connector.log"
        if (Test-Path $logFile) {
            Start-Process "notepad.exe" -ArgumentList $logFile
        } else {
            [System.Windows.Forms.MessageBox]::Show("File log non ancora creato.", $DisplayName)
        }
    })
    
    # Edit Config
    $configItem = $contextMenu.Items.Add("Configurazione")
    $configItem.Add_Click({
        if (Test-Path $ConfigPath) {
            Start-Process "notepad.exe" -ArgumentList $ConfigPath
        } else {
            [System.Windows.Forms.MessageBox]::Show("Nessuna configurazione. Esegui install.bat", $DisplayName)
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
                $notifyIcon.Icon = New-TrayIcon "running" (Get-ConnectorMode)
                $notifyIcon.Text = "$DisplayName v$Version | Stato: ATTIVO"
                $notifyIcon.ShowBalloonTip(3000, $DisplayName, "Connector riavviato con nuovi dispositivi", [System.Windows.Forms.ToolTipIcon]::Info)
            }
        }
    })

    # v3.8.8: Network Scanner - visibile SOLO in modalita' scanner.
    # Tool standalone simile ad altri network scanner enterprise: ping sweep,
    # ARP MAC, DNS+NetBIOS hostname, OUI vendor, SMB shares, HTTP/HTTPS detection,
    # WoL, export CSV. Tutto sviluppato da zero in PowerShell+WinForms.
    if ((Get-ConnectorMode) -eq "scanner") {
        $netScanItem = $contextMenu.Items.Add("Scansione di rete")
        $netScanItem.ForeColor = [System.Drawing.Color]::FromArgb(56, 132, 222)  # azzurro
        $netScanItem.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
        $netScanItem.Add_Click({ Show-NetworkScanner })
    }

    $contextMenu.Items.Add("-") | Out-Null

    # Informazioni / About
    $aboutItem = $contextMenu.Items.Add("Informazioni")
    $aboutItem.Add_Click({
        # v3.6.19: rileggi sempre la versione corrente da version.json (post-autoupdate)
        $currentVersion = $Version
        try {
            if (Test-Path $versionFile) {
                $vInfoFresh = Get-Content $versionFile -Raw -ErrorAction Stop | ConvertFrom-Json
                if ($vInfoFresh.version) { $currentVersion = $vInfoFresh.version }
            }
        } catch {}

        $aboutForm = New-Object System.Windows.Forms.Form
        $aboutForm.Text = "$DisplayName - Informazioni"
        # v3.7.6: Layout DPI-BULLETPROOF con Dock-based containers.
        # Il bottone OK vive in $bottomPanel (Dock=Bottom) -> Windows calcola la
        # posizione in modo nativo, nessun pixel hardcoded. Abbinato a
        # SetProcessDpiAwareness(1) chiamato all'avvio del tray, questo risolve
        # definitivamente il "button cut-off" su DPI 125%/150%.
        $aboutForm.ClientSize = New-Object System.Drawing.Size(460, 500)
        $aboutForm.StartPosition = "CenterScreen"
        $aboutForm.FormBorderStyle = "FixedDialog"
        $aboutForm.MaximizeBox = $false
        $aboutForm.MinimizeBox = $false
        $aboutForm.BackColor = [System.Drawing.Color]::White
        $aboutForm.AutoScaleMode = "Dpi"
        $aboutForm.AutoScaleDimensions = New-Object System.Drawing.SizeF(96, 96)

        # ----- Bottom panel (docked) : OK button -----
        # IMPORTANTE: in Windows.Forms gli elementi DOCKED devono essere aggiunti
        # PRIMA dell'elemento Fill (l'ordine di aggiunta determina z-order: i
        # controlli aggiunti per ultimi occupano l'area "Fill" residua).
        $bottomPanel = New-Object System.Windows.Forms.Panel
        $bottomPanel.Dock = [System.Windows.Forms.DockStyle]::Bottom
        $bottomPanel.Height = 58
        $bottomPanel.BackColor = [System.Drawing.Color]::FromArgb(248, 249, 252)

        $bottomSep = New-Object System.Windows.Forms.Label
        $bottomSep.Dock = [System.Windows.Forms.DockStyle]::Top
        $bottomSep.Height = 1
        $bottomSep.BackColor = [System.Drawing.Color]::FromArgb(220, 222, 230)
        $bottomPanel.Controls.Add($bottomSep)

        $btnOk = New-Object System.Windows.Forms.Button
        $btnOk.Text = "OK"
        $btnOk.Size = New-Object System.Drawing.Size(100, 34)
        # Ancorato Bottom+Right nel bottomPanel: si sposta correttamente se il panel scala
        $btnOk.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Right
        $btnOk.Location = New-Object System.Drawing.Point(($bottomPanel.Width - 115), 12)
        $btnOk.FlatStyle = "Flat"
        $btnOk.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
        $btnOk.ForeColor = [System.Drawing.Color]::White
        $btnOk.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
        $btnOk.FlatAppearance.BorderSize = 0
        $btnOk.Add_Click({ $aboutForm.Close() })
        $bottomPanel.Controls.Add($btnOk)
        # Riposiziona il bottone alla Resize del panel (assicura allineamento destro)
        $bottomPanel.Add_Resize({ $btnOk.Location = New-Object System.Drawing.Point(($bottomPanel.Width - 115), 12) })

        # ----- Content panel (fill) -----
        $contentPanel = New-Object System.Windows.Forms.Panel
        $contentPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
        $contentPanel.BackColor = [System.Drawing.Color]::White

        # Logo
        $logoPath = Join-Path $ScriptDir "86bit_logo.jpg"
        if (Test-Path $logoPath) {
            $picBox = New-Object System.Windows.Forms.PictureBox
            $picBox.Location = New-Object System.Drawing.Point(20, 15)
            $picBox.Size = New-Object System.Drawing.Size(80, 80)
            $picBox.SizeMode = "Zoom"
            $picBox.Image = [System.Drawing.Image]::FromFile($logoPath)
            $contentPanel.Controls.Add($picBox)
        }

        # App Name + Version
        $lblName = New-Object System.Windows.Forms.Label
        $lblName.Text = "$DisplayName  v$currentVersion"
        $lblName.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
        $lblName.ForeColor = [System.Drawing.Color]::FromArgb(30, 30, 50)
        $lblName.Location = New-Object System.Drawing.Point(110, 20)
        $lblName.AutoSize = $true
        $contentPanel.Controls.Add($lblName)

        $lblDesc = New-Object System.Windows.Forms.Label
        $lblDesc.Text = "NOC Collector - SNMP Trap, Syslog, Active Polling"
        $lblDesc.Font = New-Object System.Drawing.Font("Segoe UI", 9)
        $lblDesc.ForeColor = [System.Drawing.Color]::FromArgb(100, 100, 120)
        $lblDesc.Location = New-Object System.Drawing.Point(110, 52)
        $lblDesc.AutoSize = $true
        $contentPanel.Controls.Add($lblDesc)

        # Separator
        $sep = New-Object System.Windows.Forms.Label
        $sep.BorderStyle = "Fixed3D"
        $sep.Location = New-Object System.Drawing.Point(20, 105)
        $sep.Size = New-Object System.Drawing.Size(400, 2)
        $contentPanel.Controls.Add($sep)

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
        $lblCompany.Size = New-Object System.Drawing.Size(400, 220)
        $contentPanel.Controls.Add($lblCompany)

        # ORDINE DI AGGIUNTA (critico per Dock): Bottom prima, Fill dopo.
        # In WinForms il Fill occupa lo spazio residuo al termine del layout,
        # quindi deve essere l'ULTIMO aggiunto. I docked devono essere PRIMA.
        $aboutForm.Controls.Add($bottomPanel)
        $aboutForm.Controls.Add($contentPanel)
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
        [System.Windows.Forms.MessageBox]::Show($text, "$DisplayName - Stato",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information)
    })
    
    # Auto-start: controlla se il connettore gira gia' come Scheduled Task
    $existingStatus = Read-ConnectorStatus
    if ($existingStatus -and $existingStatus.status -eq "running") {
        # Il connettore gira gia' (via Task Scheduler o avvio precedente)
        $global:IsRunning = $true
        $notifyIcon.Icon = New-TrayIcon "running" (Get-ConnectorMode)
        $notifyIcon.Text = "$DisplayName v$Version | Stato: ATTIVO"
        $startItem.Visible = $false
        $stopItem.Visible = $true
        $restartItem.Visible = $true
        $notifyIcon.ShowBalloonTip(3000, $DisplayName, "Connector attivo come servizio di sistema", [System.Windows.Forms.ToolTipIcon]::Info)
    } elseif (Test-Path $ConfigPath) {
        $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($config.noc_center_url -and $config.api_key) {
            if (Start-ConnectorViaTask) {
                $notifyIcon.Icon = New-TrayIcon "running" (Get-ConnectorMode)
                $notifyIcon.Text = "$DisplayName v$Version | Stato: ATTIVO"
                $startItem.Visible = $false
                $stopItem.Visible = $true
                $restartItem.Visible = $true
                $notifyIcon.ShowBalloonTip(3000, $DisplayName, "Connector avviato e in ascolto", [System.Windows.Forms.ToolTipIcon]::Info)
            }
        } else {
            $notifyIcon.ShowBalloonTip(5000, $DisplayName, "Configurazione incompleta. Esegui install.bat", [System.Windows.Forms.ToolTipIcon]::Warning)
        }
    } else {
        $notifyIcon.ShowBalloonTip(5000, $DisplayName, "Prima installazione. Esegui install.bat", [System.Windows.Forms.ToolTipIcon]::Warning)
    }
    
    # Timer for tooltip update and connector health monitoring
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 15000  # 15 seconds
    $timer.Add_Tick({
        # v3.7.5: Rileva richieste di riavvio dopo update e chiudi il tray.
        # Al prossimo logon Windows avvia il nuovo tray_app.ps1.
        try {
            $restartFlag = Join-Path $BaseDir "tray_restart.flag"
            if (Test-Path $restartFlag) {
                Remove-Item $restartFlag -Force -ErrorAction SilentlyContinue
                $notifyIcon.ShowBalloonTip(3000, $DisplayName,
                    "Update applicato. Tray app in chiusura per applicare la nuova versione.",
                    [System.Windows.Forms.ToolTipIcon]::Info)
                Start-Sleep -Seconds 3
                $notifyIcon.Visible = $false
                $notifyIcon.Dispose()
                [System.Windows.Forms.Application]::Exit()
                return
            }
        } catch {}

        $status = Read-ConnectorStatus
        $connectorAlive = ($status -ne $null -and $status.status -eq "running")
        
        if ($global:IsRunning -and -not $connectorAlive) {
            # Connettore era attivo ma ora non risponde piu'
            $global:IsRunning = $false
            $notifyIcon.Icon = New-TrayIcon "error" (Get-ConnectorMode)
            $notifyIcon.Text = "$DisplayName v$Version | NON RISPONDE"
            $notifyIcon.ShowBalloonTip(5000, $DisplayName, "Il connector non risponde! Verificare i log.", [System.Windows.Forms.ToolTipIcon]::Error)
            $startItem.Visible = $true
            $stopItem.Visible = $false
            $restartItem.Visible = $false
        } elseif (-not $global:IsRunning -and $connectorAlive) {
            # Connettore avviato dal Task Scheduler senza passare dalla tray
            $global:IsRunning = $true
            $notifyIcon.Icon = New-TrayIcon "running" (Get-ConnectorMode)
            Set-NotifyIconTooltip $notifyIcon (Get-TooltipText)
            $startItem.Visible = $false
            $stopItem.Visible = $true
            $restartItem.Visible = $true
        } elseif ($global:IsRunning -and $connectorAlive) {
            # Aggiorna tooltip
            Set-NotifyIconTooltip $notifyIcon (Get-TooltipText)
        }
    })
    $timer.Start()
    
    # Run message loop
    [System.Windows.Forms.Application]::Run()
}

# Entry point
Start-TrayApp
