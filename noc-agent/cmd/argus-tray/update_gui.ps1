# AUTO-GENERATED template — embedded in argus-tray.exe
# I placeholder __XXX__ vengono sostituiti a runtime da Go con i valori
# letti da agent-ui.json. NON modificare a mano lo script generato in
# %TEMP%, modifica questo template e ricompila argus-tray.exe.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# === Configurazione iniettata da Go ===
$Token       = '__TOKEN__'
$ClientId    = '__CLIENT_ID__'
$BackendUrl  = '__BACKEND_URL__'
$ClientName  = '__CLIENT_NAME__'
$Hostname    = $env:COMPUTERNAME
$ScriptUrl   = '__SCRIPT_URL__'
$TargetVer   = ''

# === UI ===
$form = New-Object System.Windows.Forms.Form
$form.Text = "Argus Connector - Aggiornamento"
$form.Size = New-Object System.Drawing.Size(620, 480)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(248, 249, 251)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

$header = New-Object System.Windows.Forms.Panel
$header.Size = New-Object System.Drawing.Size(620, 70)
$header.Location = New-Object System.Drawing.Point(0, 0)
$header.BackColor = [System.Drawing.Color]::FromArgb(33, 41, 60)
$form.Controls.Add($header)

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "Aggiornamento Argus Connector"
$lblTitle.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 14)
$lblTitle.ForeColor = [System.Drawing.Color]::White
$lblTitle.AutoSize = $true
$lblTitle.Location = New-Object System.Drawing.Point(20, 14)
$header.Controls.Add($lblTitle)

$lblSubtitle = New-Object System.Windows.Forms.Label
$lblSubtitle.Text = "$Hostname - $ClientName"
$lblSubtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$lblSubtitle.ForeColor = [System.Drawing.Color]::FromArgb(180, 200, 230)
$lblSubtitle.AutoSize = $true
$lblSubtitle.Location = New-Object System.Drawing.Point(22, 42)
$header.Controls.Add($lblSubtitle)

$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = "Avvio aggiornamento..."
$lblStatus.AutoSize = $true
$lblStatus.Location = New-Object System.Drawing.Point(20, 90)
$lblStatus.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($lblStatus)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Location = New-Object System.Drawing.Point(20, 115)
$progress.Size = New-Object System.Drawing.Size(580, 22)
$progress.Style = 'Marquee'
$progress.MarqueeAnimationSpeed = 30
$form.Controls.Add($progress)

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true
$txtLog.ScrollBars = 'Vertical'
$txtLog.ReadOnly = $true
$txtLog.Location = New-Object System.Drawing.Point(20, 150)
$txtLog.Size = New-Object System.Drawing.Size(580, 240)
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 8.5)
$txtLog.BackColor = [System.Drawing.Color]::White
$form.Controls.Add($txtLog)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = "Chiudi"
$btnClose.Location = New-Object System.Drawing.Point(495, 400)
$btnClose.Size = New-Object System.Drawing.Size(100, 28)
$btnClose.Enabled = $false
$btnClose.FlatStyle = 'Flat'
$btnClose.BackColor = [System.Drawing.Color]::FromArgb(33, 41, 60)
$btnClose.ForeColor = [System.Drawing.Color]::White
$btnClose.FlatAppearance.BorderSize = 0
$btnClose.Add_Click({ $form.Close() })
$form.Controls.Add($btnClose)

function Append-Log {
    param([string]$Line)
    $txtLog.AppendText($Line + [Environment]::NewLine)
    [System.Windows.Forms.Application]::DoEvents()
}
function Set-Status {
    param([string]$Text)
    $lblStatus.Text = $Text
    [System.Windows.Forms.Application]::DoEvents()
}

$form.Add_Shown({
    $form.Activate()
    try {
        Set-Status "Download dello script di update..."
        Append-Log "[1/4] Download install-noc-agent.ps1 dal repo"
        $tmpScript = Join-Path $env:TEMP ("noc-update-{0}.ps1" -f ([guid]::NewGuid().ToString('N').Substring(0,8)))
        $cacheBust = [DateTimeOffset]::Now.ToUnixTimeSeconds()
        Invoke-WebRequest -Uri ($ScriptUrl + "?t=" + $cacheBust) -OutFile $tmpScript -UseBasicParsing -ErrorAction Stop
        Append-Log "      OK $tmpScript"

        Set-Status "Esecuzione dell'installer (puo' richiedere 30-90 secondi)..."
        Append-Log "[2/4] Esecuzione installer (UAC: richiesto admin)"
        $argList = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $tmpScript,
            '-Token', $Token, '-ClientId', $ClientId,
            '-BackendUrl', $BackendUrl, '-Source', 'tray', '-Quiet'
        )
        if ($TargetVer) { $argList += @('-Version', $TargetVer) }
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'powershell.exe'
        $psi.Arguments = ($argList | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $psi.Verb = 'runas'
        $psi.UseShellExecute = $true
        $psi.WindowStyle = 'Hidden'
        $proc = [System.Diagnostics.Process]::Start($psi)
        Append-Log ("      PID " + $proc.Id + " - attendere conclusione...")
        $proc.WaitForExit()
        Append-Log ("      Installer terminato exit=" + $proc.ExitCode)

        Set-Status "Verifica nuova versione installata..."
        Append-Log "[3/4] Verifica agent-ui.json post-update"
        Start-Sleep -Seconds 3
        try {
            $cfgPath = "$env:ProgramData\86NocAgent\agent-ui.json"
            if (Test-Path $cfgPath) {
                $c = Get-Content $cfgPath -Raw | ConvertFrom-Json
                Append-Log ("      Nuova versione: v" + $c.version)
            } else {
                Append-Log "      agent-ui.json non trovato"
            }
        } catch { Append-Log ("      WARN: " + $_.Exception.Message) }

        Set-Status "Aggiornamento completato con successo"
        Append-Log "[4/4] Operazione conclusa - puoi chiudere questa finestra"
        $progress.Style = 'Continuous'
        $progress.Value = 100
    } catch {
        Set-Status "ERRORE durante l'aggiornamento"
        Append-Log ("ERRORE: " + $_.Exception.Message)
        $progress.Style = 'Continuous'
        $progress.Value = 0
    } finally {
        $btnClose.Enabled = $true
    }
})

[System.Windows.Forms.Application]::Run($form)
