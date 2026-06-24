<#
.SYNOPSIS
  86bit NOC Agent - installer / updater STANDALONE (zero dipendenze backend).

.DESCRIPTION
  Script PowerShell che installa o aggiorna l'agent Windows scaricando i
  binari direttamente da una GitHub Release del repo specificato.

  NON contatta il backend Linux per il download/manifest: tutto il flusso
  passa esclusivamente da github.com. Il backend interagisce solo via
  WebSocket dopo l'avvio del servizio.

  Flusso:
    1. Auto-elevate (UAC) se non admin
    2. Scarica nocagent.exe, nocwatchdog.exe, nocagent-ui.exe da GitHub
       Release ($Repo, $Version)
    3. Stop servizi esistenti, copia .exe in $InstallDir, scrivi agent.yaml
    4. Crea/aggiorna servizi 86NocAgent + 86NocWatchdog via sc.exe, con
       recovery policy aggressiva
    5. Avvia i servizi, verifica heartbeat + log marker

.PARAMETER Token
  Provisioning token del cliente (obbligatorio). Es: noc_xxxxxxxxxx

.PARAMETER ClientId
  Client UUID (obbligatorio). Es: 57cb2e2b-938c-4f6d-a1a3-df5368de00e9

.PARAMETER BackendUrl
  WebSocket URL del NOC Center. Default: wss://argus.86bit.it/api/agent/ws

.PARAMETER Role
  master | scanner. Default: master.

.PARAMETER Repo
  Repo GitHub formato owner/name. Default: santiM86/86NOCConnectorCenter.

.PARAMETER Version
  Versione tag della release (es. v4.3.0) oppure "latest". Default: latest.

.PARAMETER GitHubToken
  PAT GitHub se il repo e' privato. Lasciare vuoto per repo pubblici.

.PARAMETER InstallDir
  Cartella binari. Default: C:\Program Files\86NocAgent

.EXAMPLE
  # Repo pubblico, versione latest
  iwr "https://github.com/santiM86/86NOCConnectorCenter/releases/latest/download/install-noc-agent.ps1" -OutFile $env:TEMP\install.ps1
  & $env:TEMP\install.ps1 -Token "noc_xxx" -ClientId "57cb2e2b-..." -BackendUrl "wss://argus.86bit.it/api/agent/ws"

.EXAMPLE
  # Versione specifica
  & .\install-noc-agent.ps1 -Token "noc_xxx" -ClientId "..." -Version "v4.3.0"

.EXAMPLE
  # Repo privato
  & .\install-noc-agent.ps1 -Token "noc_xxx" -ClientId "..." -GitHubToken "ghp_xxx"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Token,
    [Parameter(Mandatory=$true)][string]$ClientId,
    [string]$BackendUrl = "wss://argus.86bit.it/api/agent/ws",
    [ValidateSet("master","scanner")][string]$Role = "master",
    # Nome leggibile del cliente (es. "86BIT_Office"). Mostrato nella
    # titolo della finestra UI ("ARGUS Connector vX.Y.Z - {ClientName}").
    # Se vuoto, lo script prova a preservarlo dal precedente
    # agent-ui.json o, in ultima istanza, lo risolve via API REST al
    # Center (https endpoint /api/agent/install/manifest?token=...).
    [string]$ClientName = "",
    [string]$Repo = "santiM86/86NOCConnectorCenter",
    [string]$Version = "latest",
    [string]$GitHubToken = "",
    # Source: "github" (default per back-compat se chiamato senza -Token o
    # senza -BackendUrl) o "center" (scarica via reverse-proxy del NOC
    # Center, endpoint /api/agent-builds/{ver}/{file}). La modalità
    # "center" è raccomandata in produzione perché evita il rate-limit
    # GitHub unauth (60 req/h) sui PC dei clienti - il PAT viene usato
    # solo lato server. Auth: stesso $Token agent.
    #
    # AUTO-FALLBACK INTELLIGENTE: se $Source è vuoto, $Token e
    # $BackendUrl sono presenti → usa "center" di default. Questo
    # permette ai VECCHI binari Go (v4.10.x e precedenti) che lanciano
    # questo script con i soli parametri base di beneficiare comunque
    # del proxy Center senza aggiornare il loro binario.
    [ValidateSet("","github","center")][string]$Source = "",
    [string]$InstallDir = "C:\Program Files\86NocAgent",
    [string]$DataDir = "C:\ProgramData\86NocAgent",
    [switch]$Quiet
)

# --- Auto-detect Source quando non specificato esplicitamente ---
if (-not $Source) {
    if ($Token -and $BackendUrl) {
        $Source = "center"
    } else {
        $Source = "github"
    }
}

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # accelera Invoke-WebRequest

# Snapshot IMMEDIATO della -Version richiesta dal Center (prima di
# qualsiasi riassegnazione successiva quando si risolve "latest" via
# GitHub/Center manifest). Cosi' nel report finale al Center sappiamo
# distinguere target (cosa l'admin ha chiesto) da resolved (cosa lo
# script ha effettivamente installato).
$script:TargetVersionRaw = if ($Version) { [string]$Version } else { "" }

# ------------------------------------------------------------------- #
# 0.PRE  LOGGING PERSISTENTE (Start-Transcript + Event Viewer fallback)
# ------------------------------------------------------------------- #
# CRITICAL: durante un update remoto triggerato dal Center, lo script
# gira come subprocess detached di nocagent.exe e *cancella* la cartella
# C:\ProgramData\86NocAgent\logs come pulizia di stato (step 4). Se lo
# script crasha tra lo stop service e il start service, l'utente NON
# trova NESSUN log da nessuna parte ("agent.log non esiste") rendendo
# impossibile la diagnosi remota.
#
# Soluzione: triplice ridondanza dei log fin dal byte 1 dell'esecuzione:
#  A) Start-Transcript in $env:TEMP\noc_upgrade.log (TEMP non viene
#     mai svuotata dallo script, sopravvive a crash, riavvio servizi,
#     remove-item recursivo, ed e' leggibile da ANY user perche' i
#     temp per SYSTEM stanno in C:\Windows\Temp).
#  B) Write-EventLog su source "86NocAgent" (visibile in Event Viewer
#     -> Application -> con filter Source=86NocAgent).
#  C) Marker file fisso "$env:TEMP\noc_upgrade_marker.txt" con
#     PID + start time + outcome - per diagnostica veloce con dir.
#
# La cartella scelta e' "$env:TEMP\86noc-upgrade-logs" cosi' non
# inquina la root temp e si auto-pulisce con la rotazione TEMP di
# Windows (90 giorni di default).

$script:UpgradeStarted = Get-Date
$script:UpgradeLogDir  = Join-Path $env:TEMP "86noc-upgrade-logs"
try { New-Item -ItemType Directory -Force -Path $script:UpgradeLogDir -ErrorAction SilentlyContinue | Out-Null } catch {}
$script:UpgradeLogTimestamp = $script:UpgradeStarted.ToString("yyyyMMdd-HHmmss")
$script:UpgradeLogFile = Join-Path $script:UpgradeLogDir "noc_upgrade_$($script:UpgradeLogTimestamp)_pid$PID.log"
$script:UpgradeLatestLog = Join-Path $script:UpgradeLogDir "noc_upgrade_latest.log"
$script:UpgradeMarker = Join-Path $script:UpgradeLogDir "noc_upgrade_marker.txt"

# Start-Transcript cattura TUTTO (Write-Host, Write-Output, Write-Error,
# Write-Warning, stderr di processi esterni come schtasks/sc) finche'
# non viene Stop-Transcript-ato. -IncludeInvocationHeader prefissa ogni
# riga col timestamp; UseMinimalHeader rende il file piu' leggibile.
try {
    Start-Transcript -Path $script:UpgradeLogFile -IncludeInvocationHeader -Force -ErrorAction Stop | Out-Null
    $script:TranscriptActive = $true
} catch {
    # Caso raro: transcript gia' attivo (es. script eseguito da padre con
    # Start-Transcript). Stop-pa quello precedente e ritenta.
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}
    try {
        Start-Transcript -Path $script:UpgradeLogFile -IncludeInvocationHeader -Force -ErrorAction Stop | Out-Null
        $script:TranscriptActive = $true
    } catch {
        $script:TranscriptActive = $false
    }
}

# Event Viewer source: registriamolo se non esiste (idempotente).
try {
    if (-not [System.Diagnostics.EventLog]::SourceExists("86NocAgent")) {
        New-EventLog -LogName "Application" -Source "86NocAgent" -ErrorAction Stop
    }
    $script:EventLogReady = $true
} catch {
    $script:EventLogReady = $false
}

function Write-UpgradeEvent {
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet("Information","Warning","Error")][string]$EntryType = "Information",
        [int]$EventId = 1000
    )
    if ($script:EventLogReady) {
        try { Write-EventLog -LogName "Application" -Source "86NocAgent" -EventId $EventId -EntryType $EntryType -Message $Message -ErrorAction Stop } catch {}
    }
}

function Update-UpgradeMarker {
    param([string]$Status, [string]$Extra = "")
    try {
        $payload = @{
            pid       = $PID
            started   = $script:UpgradeStarted.ToString("o")
            updated   = (Get-Date).ToString("o")
            status    = $Status
            log_file  = $script:UpgradeLogFile
            extra     = $Extra
        } | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($script:UpgradeMarker, $payload, [System.Text.Encoding]::UTF8)
        # Mirror "latest" per accesso rapido senza listare la cartella
        if (Test-Path $script:UpgradeLogFile) {
            try { Copy-Item -Path $script:UpgradeLogFile -Destination $script:UpgradeLatestLog -Force -ErrorAction SilentlyContinue } catch {}
        }
    } catch {}
}

Update-UpgradeMarker -Status "started" -Extra "version=$Version source=$Source"
Write-UpgradeEvent -Message "Upgrade installer started (PID=$PID, log=$script:UpgradeLogFile, version=$Version, source=$Source)" -EntryType Information -EventId 1001
# NB: l'heartbeat "started" verso il Center viene inviato DOPO la
# definizione di Send-UpgradeReport (qualche riga sotto). PowerShell
# non permette forward-reference di funzioni.

Write-Host ("=" * 78) -ForegroundColor DarkCyan
Write-Host "86NocAgent Installer/Updater" -ForegroundColor Cyan
Write-Host "  Started:    $($script:UpgradeStarted.ToString('o'))"
Write-Host "  PID:        $PID"
Write-Host "  LogFile:    $script:UpgradeLogFile"
Write-Host "  LogDir:     $script:UpgradeLogDir"
Write-Host "  Marker:     $script:UpgradeMarker"
Write-Host "  PSVersion:  $($PSVersionTable.PSVersion)"
Write-Host "  Computer:   $env:COMPUTERNAME"
Write-Host ("=" * 78) -ForegroundColor DarkCyan
Write-Host ""

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red }

# ------------------------------------------------------------------- #
# 0.UPLOAD  Send-UpgradeReport - POSTa al Center il transcript completo
# alla fine dell'upgrade (success/failed/trap). Funziona ANCHE su agent
# v4.10.x perche' lo script PowerShell vive in GitHub raw e viene
# scaricato fresh ad ogni upgrade - quindi NON serve aggiornare il
# binario per beneficiarne. Quando l'admin clicca 📜 "vedi log" nel
# Center, l'endpoint /api/agents/{id}/upgrade-log prende SEMPRE il log
# dal DB (collection agent_upgrade_logs) prima di provare il comando WS.
#
# Best-effort: errori di rete vengono ignorati per non bloccare l'upgrade.
# ------------------------------------------------------------------- #
function Send-UpgradeReport {
    param(
        [Parameter(Mandatory)][string]$Status,   # completed | failed | trap
        [string]$ErrorMsg = "",
        [string]$ResolvedVersion = ""
    )
    try {
        # Backend HTTPS dal $BackendUrl WS
        $backendHttp = $BackendUrl `
            -replace '^wss://','https://' `
            -replace '^ws://','http://' `
            -replace '/api/agent/ws$',''
        $backendHttp = $backendHttp.TrimEnd('/')
        if (-not $backendHttp) { return }

        # Tail del transcript: ultimi 256KB.
        # CRITICAL: Start-Transcript scrive in UTF-16 LE con BOM. Per
        # leggere il contenuto correttamente PRIMA dell'upload usiamo
        # ReadAllText con detection automatica BOM. In passato usavamo
        # Get-Content -Raw ma su file ancora aperti dal transcript
        # ritornava stringhe troncate / vuote per buffering. Quindi:
        #   1. Stop-Transcript subito qui (releases file handle)
        #   2. Force flush del file (giro l'handle con FileShare.Read)
        #   3. Read con .NET ReadAllText (gestisce BOM UTF-16 nativamente)
        $excerpt = ""
        # Per status "started" NON chiudiamo il transcript: l'upgrade
        # è appena iniziato e dobbiamo continuare a loggare. Per
        # completed/failed/trap invece chiudiamo e leggiamo il file.
        if ($Status -ne "started") {
        try {
            if ($script:TranscriptActive) {
                try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}
                $script:TranscriptActive = $false
            }
            if (Test-Path $script:UpgradeLogFile) {
                # Pausa più generosa per dare a Stop-Transcript tempo di
                # flushare l'IOBuffer su disco (era 250ms → su disk lenti
                # del cliente alcune volte non bastava). 1000ms costa poco
                # rispetto alla durata totale dell'upgrade (~ 30-60s).
                Start-Sleep -Milliseconds 1000
                # PRIMARIO: .NET ReadAllText con autodetect BOM (UTF-16
                # LE = default Start-Transcript). Funziona nella stragrande
                # maggioranza dei casi.
                try { $data = [System.IO.File]::ReadAllText($script:UpgradeLogFile) } catch { $data = "" }
                # FALLBACK 1: ReadAllBytes + decoding UTF-16 LE esplicito
                # (utile se il file è ancora locked da PowerShell e ReadAllText
                # ha aperto un handle corrotto).
                if ([string]::IsNullOrWhiteSpace($data)) {
                    try {
                        $raw = [System.IO.File]::ReadAllBytes($script:UpgradeLogFile)
                        if ($raw -and $raw.Length -gt 2) {
                            # UTF-16 LE BOM = FF FE
                            if ($raw[0] -eq 0xFF -and $raw[1] -eq 0xFE) {
                                $data = [System.Text.Encoding]::Unicode.GetString($raw, 2, $raw.Length - 2)
                            } elseif ($raw[0] -eq 0xFE -and $raw[1] -eq 0xFF) {
                                $data = [System.Text.Encoding]::BigEndianUnicode.GetString($raw, 2, $raw.Length - 2)
                            } elseif ($raw.Length -gt 3 -and $raw[0] -eq 0xEF -and $raw[1] -eq 0xBB -and $raw[2] -eq 0xBF) {
                                $data = [System.Text.Encoding]::UTF8.GetString($raw, 3, $raw.Length - 3)
                            } else {
                                # Default tentativo UTF-16 LE (Start-Transcript
                                # storicamente lo usa anche senza BOM su alcune
                                # versioni PS).
                                $data = [System.Text.Encoding]::Unicode.GetString($raw)
                            }
                        }
                    } catch {
                        $data = ""
                    }
                }
                if ($data) {
                    if ($data.Length -gt 262144) {
                        $excerpt = "...[truncated head]...`n" + $data.Substring($data.Length - 262144)
                    } else {
                        $excerpt = $data
                    }
                }
            }
        } catch {
            # Salviamo almeno il motivo del fallimento nel campo error
            # cosi' nella UI vediamo perche' il log e' vuoto.
            $ErrorMsg = "$ErrorMsg | log-read-failed: $($_.Exception.Message)"
        }
        } # end if Status -ne "started"

        # FALLBACK 2: se il transcript è comunque vuoto, sintetizza un
        # summary minimo dai dati che abbiamo in memoria. Cosi' la UI nel
        # Center non vede MAI un "log vuoto" privo di info. Questo
        # è il fix per i casi in cui Stop-Transcript non flusha (PS
        # constrained, antivirus che ispeziona il file, ecc.).
        # Per "started" inviamo solo un summary minimo (transcript ancora
        # aperto) cosi' la UI registra il nuovo run subito.
        if ([string]::IsNullOrWhiteSpace($excerpt)) {
            $summary = @()
            if ($Status -eq "started") {
                $summary += "[Upgrade STARTED - transcript in scrittura, il log completo arrivera' al termine]"
            } else {
                $summary += "[SUMMARY auto-generated, transcript non disponibile o vuoto]"
            }
            $summary += "PID=$PID"
            $summary += "Computer=$env:COMPUTERNAME"
            $summary += "Started=$($script:UpgradeStarted.ToString('o'))"
            $summary += "Finished=$((Get-Date).ToString('o'))"
            $summary += "TargetVersion=$($script:TargetVersionRaw)"
            $summary += "ResolvedVersion=$ResolvedVersion"
            $summary += "Status=$Status"
            $summary += "Source=$Source"
            $summary += "Role=$Role"
            $summary += "BackendUrl=$BackendUrl"
            $summary += "ClientId=$ClientId"
            if ($ErrorMsg) { $summary += "ErrorMsg=$ErrorMsg" }
            # Includi marker JSON se presente
            try {
                if (Test-Path $script:UpgradeMarker) {
                    $summary += ""
                    $summary += "[Marker $($script:UpgradeMarker)]"
                    $summary += (Get-Content $script:UpgradeMarker -Raw -ErrorAction SilentlyContinue)
                }
            } catch {}
            # Includi listing della cartella log (per diagnostica filesystem)
            try {
                $files = Get-ChildItem -Path $script:UpgradeLogDir -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 10
                if ($files) {
                    $summary += ""
                    $summary += "[Cartella $($script:UpgradeLogDir)]"
                    foreach ($f in $files) {
                        $summary += "  $($f.LastWriteTime.ToString('o'))  $([math]::Round($f.Length/1KB,1))KB  $($f.Name)"
                    }
                }
            } catch {}
            $excerpt = ($summary -join "`r`n")
        }

        # Coerce a stringhe SEMPRE (mai $null) per evitare che
        # ConvertTo-Json emetta `"target":null` (poi Pydantic lo
        # interpreta come None e f-string mostra "None"). Usiamo
        # $script:TargetVersionRaw (snapshot iniziale del -Version)
        # invece di $Version corrente che a questo punto potrebbe essere
        # stato riassegnato dalla risoluzione manifest.
        $targetVer = if ($script:TargetVersionRaw) { [string]$script:TargetVersionRaw } else { "" }
        $resVer    = if ($ResolvedVersion) { [string]$ResolvedVersion } else { [string]$Version }
        $errStr    = if ($ErrorMsg) { [string]$ErrorMsg } else { "" }
        $cid       = if ($ClientId) { [string]$ClientId } else { "" }
        $startedISO = if ($script:UpgradeStarted) { $script:UpgradeStarted.ToString('o') } else { "" }

        $body = @{
            client_id        = $cid
            hostname         = [string]$env:COMPUTERNAME
            pid              = [int]$PID
            status           = [string]$Status
            started_at       = $startedISO
            finished_at      = (Get-Date).ToString('o')
            target_version   = $targetVer
            resolved_version = $resVer
            error            = $errStr
            log_excerpt      = $excerpt
        } | ConvertTo-Json -Compress -Depth 4

        $url = "$backendHttp/api/agent/upgrade-report?token=$([Uri]::EscapeDataString($Token))"
        # Forziamo UTF-8 per il body cosi' i caratteri accentati e i
        # box-drawing dei separatori sopravvivono al transit.
        Invoke-RestMethod -Uri $url -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 30 -UseBasicParsing | Out-Null
        Write-Host "  [OK] Upgrade report uploaded to Center ($Status, $($excerpt.Length) bytes)" -ForegroundColor DarkGray
    } catch {
        # Non-fatale. Lo script ha gia' loggato tutto in $env:TEMP.
        Write-Host "  [!!] Upload upgrade report fallito (non bloccante): $($_.Exception.Message)" -ForegroundColor DarkGray
    }
}

# Heartbeat "started" verso il Center: rimpiazza eventuali report
# precedenti nella UI cosi' l'admin non vede mai un report stantio
# riferito ad un upgrade vecchio. Best-effort. La function deve essere
# gia' definita (sopra) - non possiamo forward-reference.
try { Send-UpgradeReport -Status "started" -ResolvedVersion "" } catch {}

# ------------------------------------------------------------------- #
# 0.POST  TRAP GLOBALE - cattura ogni errore terminating non gestito,
# logga lo stack trace nel transcript+EventLog, chiude pulitamente.
# DEVE essere dichiarato qui prima del body - PowerShell trap copre
# solo il codice che SEGUE la sua dichiarazione nello stesso scope.
# ------------------------------------------------------------------- #
trap {
    $errMsg = $_.Exception.Message
    $errLine = $_.InvocationInfo.ScriptLineNumber
    $errStack = $_.ScriptStackTrace
    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor Red
    Write-Host "==> ERRORE FATALE (linea $errLine):" -ForegroundColor Red
    Write-Host "    $errMsg" -ForegroundColor Red
    Write-Host ""
    Write-Host "Stack trace:" -ForegroundColor DarkGray
    Write-Host $errStack -ForegroundColor DarkGray
    Write-Host ("=" * 78) -ForegroundColor Red
    Update-UpgradeMarker -Status "failed" -Extra "line=$errLine error=$errMsg"
    Write-UpgradeEvent -Message "Upgrade FAILED line=$errLine error=$errMsg`nLogFile=$script:UpgradeLogFile`nStack:`n$errStack" -EntryType Error -EventId 1099
    # Upload best-effort al Center - Send-UpgradeReport fa internamente
    # Stop-Transcript + read flushato, quindi il transcript include
    # anche il messaggio di errore appena loggato.
    Send-UpgradeReport -Status "failed" -ErrorMsg "line=$errLine $errMsg"
    if (Test-Path $script:UpgradeLogFile) {
        try { Copy-Item -Path $script:UpgradeLogFile -Destination $script:UpgradeLatestLog -Force -ErrorAction SilentlyContinue } catch {}
    }
    exit 99
}

# ------------------------------------------------------------------- #
# 0. MAGIC TRIGGER: -Version "__uninstall__" → esegue uninstall.ps1
# ------------------------------------------------------------------- #
#
# I vecchi binari agent (v4.10.x e precedenti) non conoscono il comando
# WS "uninstall". Il Center sfrutta il comando "update" già supportato
# passando un valore magico nella -Version. Lo script qui sopra lo
# intercetta PRIMA di toccare GitHub e devia su uninstall.
#
# Funziona perché il file uninstall.ps1 è già installato in
# $InstallDir dal setup iniziale (vedi installer_gui.ps1.template).
if ($Version -eq "__uninstall__") {
    Write-Step "MAGIC TRIGGER: __uninstall__ ricevuto dal Center"
    $uninst = Join-Path $InstallDir "uninstall.ps1"
    if (Test-Path $uninst) {
        Write-Ok "Eseguo $uninst (in modalità non-interattiva)"
        & $uninst
        Write-Ok "uninstall.ps1 terminato (exit=$LASTEXITCODE)"
        exit $LASTEXITCODE
    } else {
        Write-Warn2 "$uninst non presente, fallback inline"
        try { Stop-Service '86NocAgent'    -Force -ErrorAction SilentlyContinue } catch {}
        try { Stop-Service '86NocWatchdog' -Force -ErrorAction SilentlyContinue } catch {}
        try { sc.exe delete '86NocAgent'    | Out-Null } catch {}
        try { sc.exe delete '86NocWatchdog' | Out-Null } catch {}
        try { Get-Process 'nocagent-ui' -ErrorAction SilentlyContinue | Stop-Process -Force } catch {}
        try { Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
        try { Remove-Item -Path "$env:ProgramData\86NocAgent" -Recurse -Force -ErrorAction SilentlyContinue } catch {}
        Write-Ok "Uninstall inline completato"
        exit 0
    }
}

# ------------------------------------------------------------------- #
# 1. Auto-elevazione (UAC)
# ------------------------------------------------------------------- #
# Check 1: token Administrator elevato (UAC accettato)
# Check 2: account SYSTEM (SID S-1-5-18) — usato quando lo script gira
#          via Task Scheduler /RU SYSTEM (auto-update remoto dal Center).
# Senza il check SYSTEM lo script tentava di rilanciarsi via UAC che in
# subprocess NON interattivo (Task Scheduler / service) muore silente:
# diagnosticato in v4.14.x sul flow "Aggiorna dal Center" che non si
# completava mai. Il log mostrava "Privilegi admin mancanti" e poi
# silenzio totale.
$currentIdentity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
$isSystem  = ($currentIdentity.User.Value -eq "S-1-5-18")
$isAdmin   = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not ($isSystem -or $isAdmin)) {
    Write-Warn2 "Privilegi admin mancanti, rilancio con UAC..."
    $scriptPath = $MyInvocation.MyCommand.Path
    if (-not $scriptPath) { Write-Fail "Impossibile auto-elevare: lo script deve essere salvato su disco prima."; exit 1 }
    $argList = @("-NoProfile","-ExecutionPolicy","Bypass","-File","`"$scriptPath`"")
    $PSBoundParameters.GetEnumerator() | ForEach-Object {
        if ($_.Value -is [switch]) { if ($_.Value.IsPresent) { $argList += "-$($_.Key)" } }
        else { $argList += "-$($_.Key)"; $argList += "`"$($_.Value)`"" }
    }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait
    exit $LASTEXITCODE
}
Write-Host "  Eseguo come: $($currentIdentity.Name) (SYSTEM=$isSystem Admin=$isAdmin)" -ForegroundColor DarkGray

# ------------------------------------------------------------------- #
# 1.5  Normalizzazione $BackendUrl
# ------------------------------------------------------------------- #
# REGRESSIONE v4.14.0: il binario nocagent.exe v4.14.0 fa
# `websocket.Dial(c.cfg.Backend.URL)` direttamente, SENZA appendere
# il path /api/agent/ws. Se l'installer riceve un BackendUrl "naked"
# (es. "https://argus.86bit.it" senza suffisso, come quando l'utente
# o un wrapper lo prende da agent-ui.json.backend_url che strippa il
# path), agent.yaml viene scritto con backend.url HTTPS-root e
# l'agent fallisce con: "expected handshake response status code 101
# but got 200" (riceve l'HTML del frontend invece dell'upgrade WS).
#
# Normalizziamo sempre $BackendUrl in formato wss:// + /api/agent/ws
# PRIMA di proseguire. Idempotente: se gia' completo lascia invariato.
$BackendUrlOrig = $BackendUrl
if ($BackendUrl.StartsWith("https://")) { $BackendUrl = "wss://"  + $BackendUrl.Substring(8) }
elseif ($BackendUrl.StartsWith("http://"))  { $BackendUrl = "ws://"   + $BackendUrl.Substring(7) }
if ($BackendUrl -notmatch '/api/agent/ws$') {
    $BackendUrl = $BackendUrl.TrimEnd('/') + "/api/agent/ws"
}
if ($BackendUrl -ne $BackendUrlOrig) {
    Write-Host "BackendURL normalizzato: $BackendUrlOrig -> $BackendUrl" -ForegroundColor Yellow
}

Write-Step "86NocAgent Installer (standalone, GitHub Release)"
Write-Host "Repo:        $Repo"
Write-Host "Versione:    $Version"
Write-Host "BackendURL:  $BackendUrl"
Write-Host "ClientId:    $ClientId"
Write-Host "Role:        $Role"
Write-Host "Source:      $Source"
Write-Host "InstallDir:  $InstallDir"
Write-Host "DataDir:     $DataDir"

# ------------------------------------------------------------------- #
# 2. Risolvi il tag della release (latest -> tag concreto)
# ------------------------------------------------------------------- #
Write-Step "Risoluzione versione ($Source)"

# Per Source=center, costruisco l'URL HTTPS del Center partendo dal
# BackendUrl WebSocket. Es. wss://argus.86bit.it/api/agent/ws → https://argus.86bit.it
$centerBaseUrl = ""
if ($Source -eq "center") {
    $centerBaseUrl = $BackendUrl
    if ($centerBaseUrl.StartsWith("wss://")) { $centerBaseUrl = "https://" + $centerBaseUrl.Substring(6) }
    elseif ($centerBaseUrl.StartsWith("ws://")) { $centerBaseUrl = "http://" + $centerBaseUrl.Substring(5) }
    # Strip trailing /api/agent/ws → base url
    $centerBaseUrl = $centerBaseUrl -replace "/api/agent/ws.*$", ""
    $centerBaseUrl = $centerBaseUrl.TrimEnd("/")
    Write-Host "Center proxy: $centerBaseUrl"
}

$ghHeaders = @{ "User-Agent" = "86noc-installer" }
if ($GitHubToken) { $ghHeaders["Authorization"] = "Bearer $GitHubToken" }

try {
    if ($Source -eq "center") {
        # Manifest dal Center (gia' risolve "latest" lato server)
        $manifestUrl = "$centerBaseUrl/api/agent-builds/$Version/manifest.json?token=$([Uri]::EscapeDataString($Token))"
        $rel = Invoke-RestMethod -Uri $manifestUrl -Headers @{ "User-Agent" = "86noc-installer" } -TimeoutSec 30
        $Version = $rel.version
        Write-Ok "Manifest dal Center: release $Version, $($rel.assets.Count) asset"
    } elseif ($Version -eq "latest") {
        $apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
        $rel = Invoke-RestMethod -Uri $apiUrl -Headers $ghHeaders -TimeoutSec 30
        $Version = $rel.tag_name
        Write-Ok "Latest release: $Version"
    } else {
        $apiUrl = "https://api.github.com/repos/$Repo/releases/tags/$Version"
        $rel = Invoke-RestMethod -Uri $apiUrl -Headers $ghHeaders -TimeoutSec 30
        Write-Ok "Release: $($rel.tag_name) - $($rel.name)"
    }
} catch {
    Write-Fail "Impossibile risolvere la release: $($_.Exception.Message)"
    if ($_.Exception.Response.StatusCode -eq 404) {
        Write-Fail "Verifica che '$Repo' esista, sia accessibile, e che ci sia almeno una release."
        Write-Fail "Repo privati richiedono -GitHubToken con scope 'repo' o 'public_repo'."
    }
    exit 2
}

# Map filename -> URL (cambia formato in base a Source).
# - github: usa rel.assets[].browser_download_url (https://github.com/.../download/...)
# - center: usa rel.assets[].url (relativa /api/agent-builds/...) + base URL
$assetUrls = @{}
if ($Source -eq "center") {
    foreach ($a in $rel.assets) {
        $assetUrls[$a.name] = "$centerBaseUrl$($a.url)?token=$([Uri]::EscapeDataString($Token))"
    }
} else {
    foreach ($a in $rel.assets) { $assetUrls[$a.name] = $a.browser_download_url }
}
$required = @("nocagent.exe","nocwatchdog.exe","argus-tray.exe")
# v2026-06-23 LAYOUT UNIFORME: ogni connector ha lo STESSO identico set di
# componenti → servizio + watchdog + UNICA systray nativa (argus-tray.exe).
# Le vecchie GUI (nocagent-ui.exe legacy walk, ArgusDesktop.exe Wails) NON
# vengono piu' installate e vengono RIMOSSE se presenti da installazioni
# precedenti (vedi cleanup sotto). Niente piu' mix full/minimal.
$optional = @()
$legacyToRemove = @("ArgusDesktop.exe","nocagent-ui.exe")
foreach ($f in $required) {
    if (-not $assetUrls.ContainsKey($f)) {
        Write-Fail "Asset mancante nella release ${Version}: $f"
        Write-Fail "Asset trovati: $($assetUrls.Keys -join ', ')"
        exit 3
    }
}

# ------------------------------------------------------------------- #
# 3. Stop servizi esistenti (se presenti)
# ------------------------------------------------------------------- #
Write-Step "Stop servizi esistenti"
foreach ($svc in @("86NocAgent","86NocWatchdog")) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) {
        if ($s.Status -ne "Stopped") {
            Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
            Write-Ok "Stop $svc"
        } else {
            Write-Ok "$svc gia' fermo"
        }
    } else {
        Write-Ok "$svc non installato (prima installazione)"
    }
}
Start-Sleep -Seconds 2

# Kill UI processes (tray icon + ArgusDesktop) che bloccano la sovrascrittura
# del nocagent-ui.exe / ArgusDesktop.exe nella cartella InstallDir.
# Comunemente girano nella system tray dell'utente loggato e non vengono
# fermati dal Stop-Service.
$uiProcs = @("nocagent-ui","ArgusDesktop","argus-tray")
foreach ($p in $uiProcs) {
    $procs = Get-Process -Name $p -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Ok "Processo $p.exe terminato ($($procs.Count) istanze)"
    }
}
Start-Sleep -Seconds 2

# ------------------------------------------------------------------- #
# 4. Pulizia stato vecchio (preservando il log per la diagnosi)
# ------------------------------------------------------------------- #
Write-Step "Pulizia stato precedente"
# CRITICAL: PRIMA di rimuovere logs/, salviamo agent.log nel TEMP cosi'
# se l'upgrade fallisce l'utente puo' comunque ispezionare i messaggi
# dell'agent vecchio (errori di shutdown, last heartbeat, ecc.). Senza
# questo backup il log scompariva insieme alla cartella e la diagnosi
# era impossibile.
$prevLogsDir = Join-Path $DataDir "logs"
$prevAgentLog = Join-Path $prevLogsDir "agent.log"
if (Test-Path $prevAgentLog) {
    try {
        $bakName = "agent.log.pre_upgrade_$($script:UpgradeLogTimestamp).log"
        $bakPath = Join-Path $script:UpgradeLogDir $bakName
        Copy-Item -Path $prevAgentLog -Destination $bakPath -Force -ErrorAction Stop
        $bakSize = [math]::Round((Get-Item $bakPath).Length / 1KB, 1)
        Write-Ok "agent.log precedente preservato in $bakPath ($bakSize KB)"
    } catch {
        Write-Warn2 "Backup agent.log precedente fallito: $($_.Exception.Message)"
    }
}
Remove-Item $prevLogsDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $DataDir "log_path.txt") -Force -ErrorAction SilentlyContinue
Write-Ok "logs/ e log_path.txt rimossi (backup precedente in $script:UpgradeLogDir)"

# ------------------------------------------------------------------- #
# 4.5 Eccezioni Windows Defender (Real-time + ASR + Controlled Folder)
# ------------------------------------------------------------------- #
# Windows Defender SmartScreen / ASR / Controlled Folder Access blocca
# silenziosamente nocagent.exe come "azione rischiosa" (regola
# "Use advanced protection against ransomware" - GUID c1db55ab-c21a-4637-
# bb3f-a12568109d35) perche' e' un binario Go non firmato che apre socket
# raw e modifica file in $ProgramData. Aggiungiamo le esclusioni in modo
# best-effort PRIMA del download cosi' Defender non mette in quarantena i
# .exe appena copiati. Tutti i comandi Add-MpPreference sono idempotenti.
#
# NOTA: se Defender e' gestito centralmente via GPO/Intune queste chiamate
# locali falliscono (silentemente) e bisognera' chiedere all'admin AD di
# aggiungere le esclusioni sulla policy aziendale.
Write-Step "Aggiunta esclusioni Windows Defender"
$mpAvailable = $false
try {
    $null = Get-Command Add-MpPreference -ErrorAction Stop
    $mpAvailable = $true
} catch {
    Write-Warn2 "Modulo Defender non disponibile (Server Core senza GUI o Defender disinstallato): salto esclusioni"
}

if ($mpAvailable) {
    $exclPaths = @(
        "C:\Program Files\86NocAgent",
        "C:\ProgramData\86NocAgent"
    )
    $exclProcs = @(
        "C:\Program Files\86NocAgent\nocagent.exe",
        "C:\Program Files\86NocAgent\nocwatchdog.exe",
        "C:\Program Files\86NocAgent\nocagent-ui.exe",
        "C:\Program Files\86NocAgent\ArgusDesktop.exe"
    )

    foreach ($p in $exclPaths) {
        try { Add-MpPreference -ExclusionPath $p -ErrorAction Stop } catch { }
    }
    foreach ($p in $exclProcs) {
        try { Add-MpPreference -ExclusionProcess $p -ErrorAction Stop } catch { }
        # Esclusione SPECIFICA per la regola ASR (Attack Surface Reduction)
        try { Add-MpPreference -AttackSurfaceReductionOnlyExclusions $p -ErrorAction Stop } catch { }
        # Permetti accesso anche con Controlled Folder Access attivo
        try { Add-MpPreference -ControlledFolderAccessAllowedApplications $p -ErrorAction Stop } catch { }
    }
    Write-Ok "Esclusioni Defender registrate (path + process + ASR + ControlledFolder)"
}

# ------------------------------------------------------------------- #
# 5. Scarica i binari da GitHub Release
# ------------------------------------------------------------------- #
Write-Step "Download binari da GitHub Release"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

foreach ($f in $required) {
    $dst = Join-Path $InstallDir $f
    $url = $assetUrls[$f]
    Write-Host "  $f <- $url"
    try {
        # Per asset privati l'auth bearer va passato; per pubblici e' innocua.
        $dlHeaders = @{ "User-Agent" = "86noc-installer" }
        if ($Source -eq "center") {
            # Il Center accetta il token come query string (vedi backend
            # _token_or_403), nessun header Authorization necessario qui.
        } elseif ($GitHubToken) {
            $dlHeaders["Authorization"] = "Bearer $GitHubToken"
            $dlHeaders["Accept"] = "application/octet-stream"
            # Per il download di asset privati GitHub richiede l'API URL, non browser_download_url
            $apiAsset = ($rel.assets | Where-Object { $_.name -eq $f }).url
            if ($apiAsset) { $url = $apiAsset }
        }
        Invoke-WebRequest -Uri $url -OutFile $dst -Headers $dlHeaders -TimeoutSec 180 -UseBasicParsing
        $sz = (Get-Item $dst).Length
        Write-Ok "$f scaricato: $([math]::Round($sz/1MB,2)) MB"
    } catch {
        Write-Fail "Download $f fallito: $($_.Exception.Message)"
        exit 4
    }
}

# Optional asset: ArgusDesktop.exe (nuova UI Wails). Scaricato solo se la
# release lo include - release pre-v4.8 non lo hanno, e va bene cosi'.
foreach ($f in $optional) {
    if (-not $assetUrls.ContainsKey($f)) {
        Write-Warn2 "Asset opzionale assente nella release: $f (skip)"
        continue
    }
    $dst = Join-Path $InstallDir $f
    $url = $assetUrls[$f]
    Write-Host "  $f <- $url"
    try {
        $dlHeaders = @{ "User-Agent" = "86noc-installer" }
        if ($Source -eq "center") {
            # token gia' nella query string
        } elseif ($GitHubToken) {
            $dlHeaders["Authorization"] = "Bearer $GitHubToken"
            $dlHeaders["Accept"] = "application/octet-stream"
            $apiAsset = ($rel.assets | Where-Object { $_.name -eq $f }).url
            if ($apiAsset) { $url = $apiAsset }
        }
        Invoke-WebRequest -Uri $url -OutFile $dst -Headers $dlHeaders -TimeoutSec 180 -UseBasicParsing
        $sz = (Get-Item $dst).Length
        Write-Ok "$f scaricato: $([math]::Round($sz/1MB,2)) MB"
    } catch {
        Write-Warn2 "Download $f fallito (opzionale): $($_.Exception.Message)"
    }
}

# v2026-06-23 LAYOUT UNIFORME — rimuovi GUI legacy da installazioni precedenti
# (ArgusDesktop.exe Wails + nocagent-ui.exe walk). Da ora la UNICA GUI ammessa
# e' argus-tray.exe, identica su tutti i connector. I processi sono gia' stati
# killati nello step di stop servizi; qui eliminiamo i file residui.
Write-Step "Cleanup GUI legacy (layout uniforme)"
foreach ($leg in $legacyToRemove) {
    $legPath = Join-Path $InstallDir $leg
    if (Test-Path $legPath) {
        try {
            Remove-Item -Path $legPath -Force -ErrorAction Stop
            Write-Ok "Rimosso componente legacy: $leg"
        } catch {
            Write-Warn2 "Impossibile rimuovere $leg (in uso?): $($_.Exception.Message)"
        }
    }
}


# ------------------------------------------------------------------- #
# 6. Scrivi agent.yaml (preserva snmp_targets se gia' presente)
# ------------------------------------------------------------------- #
Write-Step "Scrittura agent.yaml"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$yamlPath = Join-Path $DataDir "agent.yaml"

# Estrai i target SNMP dalla vecchia sezione MANAGED TARGETS, se presente, e
# li ri-emette indentati come 'targets:' DENTRO la sezione snmp: del nuovo
# yaml. Lo schema config Go richiede snmp.targets, NON snmp_targets top-level
# (vedi internal/config/config.go SNMPConfig.Targets yaml:"targets"). I file
# storici hanno 'snmp_targets:' top-level: quei target venivano ignorati dal
# poller v4 e i device restavano in PENDING senza ICMP/SNMP refresh.
$snmpTargetsBlock = ""
if (Test-Path $yamlPath) {
    $oldContent = Get-Content $yamlPath -Raw
    if ($oldContent -match "(?ms)^# === BEGIN MANAGED TARGETS ===\s*\r?\n(?:#[^\r\n]*\r?\n)?snmp_targets:\s*\r?\n(?<items>(?:[ \t]+[^\r\n]*\r?\n)+)# === END MANAGED TARGETS ===") {
        $rawItems = $Matches['items']
        # Aggiungo 2 spazi di indent a ogni riga non vuota (entra dentro snmp:)
        $indented = ($rawItems -split "\r?\n" | ForEach-Object {
            if ($_ -match '^\s*$') { '' } else { '  ' + $_ }
        }) -join "`n"
        $snmpTargetsBlock = "  targets:`n$indented"
        Write-Ok "Sezione MANAGED TARGETS convertita in snmp.targets (formato schema-compliant)"
    } elseif ($oldContent -match "(?ms)^# === BEGIN MANAGED TARGETS ===.*?^# === END MANAGED TARGETS ===") {
        Write-Warn2 "Sezione MANAGED TARGETS trovata ma in formato non riconosciuto (verra' scartata)"
    }
}

$yaml = @"
client_id: "$ClientId"
token: "$Token"
role: "$Role"
backend:
  url: "$BackendUrl"
heartbeat: 15s
discovery:
  enabled: true
  interval: 5m
  arp: true
  mdns: true
snmp:
  enabled: true
  interval: 60s
  communities: ["public"]
$snmpTargetsBlock
ping:
  enabled: true
  interval: 60s
watchdog:
  enabled: true
  stale_after: 90s
update:
  enabled: false
labels:
  role: "$Role"
"@

[System.IO.File]::WriteAllText($yamlPath, $yaml, [System.Text.Encoding]::UTF8)
Write-Ok "agent.yaml scritto in $yamlPath"

# Scrivi anche agent-ui.json: e' il formato preferito dalla tray UI
# (nocagent-ui.exe / ArgusDesktop.exe) per popolare i campi "Cliente",
# "Ruolo", "Backend", "Versione" senza dover ri-parsare il yaml. Quando
# manca, la UI mostra "Cliente: unknown" cosi' come visto in produzione.
$uiInfoPath = Join-Path $DataDir "agent-ui.json"
# Risalire dalla URL WS a quella HTTPS (ws:// -> http://, wss:// -> https://)
# perche' la UI usa il backend per chiamate REST self/health.
$backendHttp = $BackendUrl -replace '^wss://','https://' -replace '^ws://','http://' -replace '/api/agent/ws$',''

# Versione: usiamo il tag della release effettivamente scaricata (es. "v4.4.0"
# o "4.4.0"), stripando l'eventuale prefisso 'v' per uniformita' con i
# titoli UI (es. "ARGUS v4.4.0"). Cosi' la tray e i metadati riflettono
# SEMPRE la versione reale presente su disco, non un valore hardcoded.
$resolvedVersion = $Version
if ($rel -and $rel.tag_name) { $resolvedVersion = $rel.tag_name }
$resolvedVersion = $resolvedVersion -replace '^v',''
$buildDate = if ($rel -and $rel.published_at) { $rel.published_at } else { (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssZ') }

# Persistenza agent_id: leggiamo il file scritto dall'agent al primo run
# (internal/config/config.go:getOrCreateStableAgentID). Se non esiste
# ancora - prima installazione - il prossimo Start-Service lo creera'.
$persistedAgentId = ""
$aidPath = Join-Path $DataDir "agent_id.txt"
if (Test-Path $aidPath) {
    try { $persistedAgentId = (Get-Content $aidPath -Raw).Trim() } catch { }
}

# Risoluzione $ClientName (in cascata, primo non-vuoto vince):
#   1. Parametro -ClientName esplicito
#   2. agent-ui.json esistente (preserva tra update successivi)
#   3. agent-ui.json legacy in $InstallDir
#   4. API REST /api/agent/install/manifest?token=... sul backend
#      (best-effort, timeout 5s, fallisce silente)
#   5. fallback: usa $ClientId (UUID) - meglio "57cb..." che "unknown"
$resolvedClientName = $ClientName
if (-not $resolvedClientName) {
    foreach ($candidatePath in @($uiInfoPath, (Join-Path $InstallDir "agent-ui.json"))) {
        if (Test-Path $candidatePath) {
            try {
                $existing = Get-Content $candidatePath -Raw | ConvertFrom-Json
                if ($existing.client_name) {
                    $resolvedClientName = $existing.client_name
                    Write-Ok "client_name preservato da $candidatePath = '$resolvedClientName'"
                    break
                }
            } catch { }
        }
    }
}
if (-not $resolvedClientName) {
    # Best-effort: chiedi al Center il nome leggibile via /manifest endpoint
    try {
        $manifestUrl = "$backendHttp/api/agent/install/manifest?token=$Token"
        $manifest = Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($manifest.client_name) {
            $resolvedClientName = $manifest.client_name
            Write-Ok "client_name risolto via API = '$resolvedClientName'"
        }
    } catch {
        Write-Warn2 "client_name non risolvibile via API: $($_.Exception.Message)"
    }
}
if (-not $resolvedClientName) {
    $resolvedClientName = $ClientId
    Write-Warn2 "client_name non disponibile: uso ClientId UUID come fallback"
}

$uiInfo = [ordered]@{
    client_id   = $ClientId
    client_name = $resolvedClientName
    token       = $Token
    role        = $Role
    backend_url = $backendHttp
    install_dir = $InstallDir
    config_path = $yamlPath
    version     = $resolvedVersion
    build_date  = $buildDate
    agent_id    = $persistedAgentId
} | ConvertTo-Json -Depth 3
# UTF-8 NO BOM: Go json.Unmarshal fallisce silente sul BOM lasciando
# struct a zero-value (popup tray con campi vuoti). UTF8Encoding(false)
# = senza BOM. Vale anche per [System.IO.File]::WriteAllText sotto.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($uiInfoPath, $uiInfo, $utf8NoBom)
Write-Ok "agent-ui.json scritto (version=$resolvedVersion build_date=$buildDate)"

# Cleanup: vecchie versioni dell'installer (cmd/installer/main.go pre-v4.5)
# scrivevano agent-ui.json ANCHE in $InstallDir con version=4.0.0 hardcoded.
# Se rimane in giro la tray UI lo trova per primo nel lookup e mostra
# "ARGUS Connector v4.0.0" anche dopo aver fatto un update a v4.6.0.
# Lo eliminiamo e riscriviamo la copia "fresca" cosi' qualunque ordine di
# lookup pesca la versione corretta. -ErrorAction SilentlyContinue per non
# crashare in caso di permessi/file-lock.
$legacyUiPath = Join-Path $InstallDir "agent-ui.json"
if (Test-Path $legacyUiPath) {
    try {
        Remove-Item -Path $legacyUiPath -Force -ErrorAction Stop
        Write-Ok "Rimosso agent-ui.json legacy in $InstallDir"
    } catch {
        Write-Warn2 "Impossibile rimuovere $legacyUiPath ($($_.Exception.Message)) - provo a sovrascriverlo"
    }
}
try {
    [System.IO.File]::WriteAllText($legacyUiPath, $uiInfo, $utf8NoBom)
    Write-Ok "agent-ui.json sincronizzato anche in $InstallDir (legacy compat)"
} catch {
    Write-Warn2 "Sovrascrittura $legacyUiPath fallita: $($_.Exception.Message)"
}

# ------------------------------------------------------------------- #
# 7. Registra/aggiorna servizi via sc.exe
# ------------------------------------------------------------------- #
Write-Step "Registrazione servizi Windows"

$nocagentExe   = Join-Path $InstallDir "nocagent.exe"
$nocwatchdogExe = Join-Path $InstallDir "nocwatchdog.exe"

function Register-NocService {
    param([string]$Name, [string]$DisplayName, [string]$BinPath, [string]$Description)
    $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($existing) {
        # Aggiorna binPath (cambia se InstallDir e' cambiato)
        & sc.exe config $Name binPath= "`"$BinPath`"" | Out-Null
        & sc.exe config $Name start= auto | Out-Null
        Write-Ok "Servizio $Name aggiornato"
    } else {
        & sc.exe create $Name binPath= "`"$BinPath`"" DisplayName= "$DisplayName" start= auto | Out-Null
        & sc.exe description $Name "$Description" | Out-Null
        Write-Ok "Servizio $Name creato"
    }
    # Recovery policy: restart su crash, 60s, 5 volte
    & sc.exe failure $Name reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
}

Register-NocService -Name "86NocAgent" `
    -DisplayName "86bit NOC Agent" `
    -BinPath $nocagentExe `
    -Description "Connettore NOC 86bit verso il NOC Center (WebSocket persistente, SNMP/ICMP polling)."

Register-NocService -Name "86NocWatchdog" `
    -DisplayName "86bit NOC Watchdog" `
    -BinPath $nocwatchdogExe `
    -Description "Watchdog che riavvia 86NocAgent in caso di hang o crash."

# ------------------------------------------------------------------- #
# 8. Avvia servizi
# ------------------------------------------------------------------- #
Write-Step "Avvio servizi"
foreach ($svc in @("86NocAgent","86NocWatchdog")) {
    try {
        Start-Service -Name $svc -ErrorAction Stop
        Write-Ok "$svc avviato"
    } catch {
        Write-Fail "Avvio $svc fallito: $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 10

# ------------------------------------------------------------------- #
# 8.5  Autostart Argus Tray (Datto-style) — Scheduled Task At Logon
# ------------------------------------------------------------------- #
# argus-tray.exe e' un piccolo binario ~4MB (Win32 systray nativa) che
# vive accanto all'orologio. Lo registriamo come Scheduled Task
# 'At Logon' dell'utente INTERACTIVE (gruppo built-in che cattura
# qualunque utente sta facendo logon interattivo, indipendentemente
# da Users/Administrators). Trigger:
#
#   * Al prossimo logon  → automatico
#   * AVVIO IMMEDIATO     → Start-ScheduledTask (cosi' l'utente loggato
#                            ORA vede l'icona senza dover sloggare)
#
# CRITICAL: senza questa sezione l'icona Tray spariva ad OGNI upgrade
# automatico perche' lo Stop-Process la uccideva e niente la rilanciava
# fino al prossimo logon utente. Vedi installer_gui.ps1.template
# [10/11] per la stessa logica nell'installer GUI.
Write-Step "Autostart Argus Tray (At Logon)"
$trayExe   = Join-Path $InstallDir "argus-tray.exe"
$taskName  = "86BIT Argus Tray"
$trayArg   = ""
# v2026-06-23 LAYOUT UNIFORME: UNICA tray (argus-tray.exe), nessun fallback ad
# ArgusDesktop. argus-tray.exe e' ora un asset REQUIRED quindi e' sempre presente.
if (-not (Test-Path $trayExe)) {
    Write-Warn2 "argus-tray.exe assente, autostart UI saltato"
} else {
    # Cleanup registry-based autostart legacy (pre-v4.13.5)
    Remove-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -Name '86BITArgusTray'      -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -Name '86BITArgusConnector' -Force -ErrorAction SilentlyContinue
    try {
        if ($trayArg) {
            $action = New-ScheduledTaskAction -Execute $trayExe -Argument $trayArg
        } else {
            $action = New-ScheduledTaskAction -Execute $trayExe
        }
        $trigger   = New-ScheduledTaskTrigger -AtLogOn
        $principal = New-ScheduledTaskPrincipal -GroupId 'INTERACTIVE' -RunLevel Limited
        $settings  = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 5 -RestartInterval ([TimeSpan]::FromMinutes(1))
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings -Force -ErrorAction Stop | Out-Null
        Write-Ok "Scheduled task '$taskName' -> $([System.IO.Path]::GetFileName($trayExe)) $trayArg (At Logon)"
        # Avvio immediato nella sessione utente loggato ORA
        Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Write-Ok "Tray icon avviata nella sessione utente corrente"
    } catch {
        Write-Warn2 "Scheduled task tray non registrato: $($_.Exception.Message)"
    }
}

# ------------------------------------------------------------------- #
# 9. Verifica
# ------------------------------------------------------------------- #
Write-Step "Verifica installazione"

$svcStatus = Get-Service 86NocAgent, 86NocWatchdog | Select-Object Name, Status
$svcStatus | Format-Table -AutoSize

# Versione binario: leggiamo direttamente dalle Win32 file metadata (zero
# rischio di file lock perche' il servizio sta scrivendo / mappando il PE).
# Invocare $nocagentExe --version DOPO Start-Service falliva con "Accesso
# negato" perche' Windows non permette di rilanciare un PE gia' caricato
# come processo servizio. Usiamo il FileVersionInfo che e' read-only.
try {
    $vi = (Get-Item $nocagentExe).VersionInfo
    $sz = [math]::Round((Get-Item $nocagentExe).Length / 1MB, 2)
    if ($vi.ProductVersion) {
        Write-Ok "Versione binario: $($vi.ProductVersion) ($sz MB)"
    } else {
        Write-Ok "Binario installato: $nocagentExe ($sz MB) - version string non incorporata nei metadati"
    }
} catch {
    Write-Warn2 "Impossibile leggere metadati binario: $($_.Exception.Message)"
}

$markerPath = Join-Path $DataDir "log_path.txt"
if (Test-Path $markerPath) {
    $logPath = (Get-Content $markerPath -Raw).Trim()
    Write-Ok "Marker presente: log path = $logPath"
    if (Test-Path $logPath) {
        $logSize = (Get-Item $logPath).Length
        Write-Ok "Log file presente: $logSize byte"
        Write-Host ""
        Write-Host "--- Ultime 15 righe del log ---" -ForegroundColor Gray
        Get-Content $logPath -Tail 15
        Write-Host "--- Fine log ---" -ForegroundColor Gray
    } else {
        Write-Warn2 "Marker presente ma log file non trovato a $logPath"
    }
} else {
    Write-Warn2 "Marker log_path.txt assente - il binario potrebbe non aver inizializzato il logger"
}

$heartbeat = Join-Path $DataDir "heartbeat.tick"
if (Test-Path $heartbeat) {
    $hbAge = ((Get-Date) - (Get-Item $heartbeat).LastWriteTime).TotalSeconds
    if ($hbAge -lt 30) {
        Write-Ok "Heartbeat aggiornato $([math]::Round($hbAge,1))s fa - agent VIVO"
    } else {
        Write-Warn2 "Heartbeat stale ($([math]::Round($hbAge,1))s fa)"
    }
} else {
    Write-Warn2 "heartbeat.tick assente"
}

Write-Host ""
Write-Host "=========================================================" -ForegroundColor Green
Write-Host " Installazione 86NocAgent $Version COMPLETATA" -ForegroundColor Green
Write-Host "=========================================================" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------------- #
# 10. Rilancia la UI desktop come UTENTE LOGGATO
# ------------------------------------------------------------------- #
# nocagent-ui.exe e' una GUI Wails/Walk che gira come utente normale
# (NON come servizio Windows). Lo script l'ha killata al passo 3 per
# poter sovrascrivere il binario in $InstallDir. La rilanciamo qui
# cosi' la tray icon riappare immediatamente con la versione e il
# cliente aggiornati - senza richiedere il workaround manuale
# "Stop-Process + Start-Process" che e' stato necessario fino ad oggi.
#
# IMPORTANTE: lo script gira come Administrator (UAC), ma nocagent-ui
# deve girare nel contesto dell'utente desktop interattivo per poter
# accedere alla session dell'utente loggato (tray icon, notifiche,
# clipboard, ecc.). Usiamo `explorer.exe` come launcher: explorer
# eredita il contesto dell'utente interattivo e Start-Process tramite
# explorer lancia il figlio come quell'utente.
# Preferenza UI: usa ArgusDesktop.exe (Wails moderno, no freeze) se presente
# E se WebView2 Runtime e' installato sulla macchina. Altrimenti fallback a
# nocagent-ui.exe (walk legacy) per garantire che la UI sia comunque
# disponibile su workstation senza WebView2 (Windows pre-2021 senza Edge).
$argusDesktop = Join-Path $InstallDir "ArgusDesktop.exe"
$legacyUI     = Join-Path $InstallDir "nocagent-ui.exe"
$webview2Available = $false
try {
    # WebView2 Runtime registra un GUID stabile in HKLM. Presenza = installato.
    $wv2Key1 = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    $wv2Key2 = "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    if ((Test-Path $wv2Key1) -or (Test-Path $wv2Key2)) {
        $webview2Available = $true
    }
} catch { }
if ((Test-Path $argusDesktop) -and $webview2Available) {
    $uiExe   = $argusDesktop
    $uiLabel = "ArgusDesktop (Wails)"
} else {
    if ((Test-Path $argusDesktop) -and (-not $webview2Available)) {
        Write-Warn2 "ArgusDesktop richiede Microsoft Edge WebView2 Runtime (non installato). Uso UI legacy."
    }
    $uiExe   = $legacyUI
    $uiLabel = "nocagent-ui (legacy)"
}
# 2026-02-21 HEADLESS: il Connector non deve piu' aprire UI desktop sul
# PC client. Tutta la gestione (dispositivi SNMP, scansioni, log, update)
# avviene da NOC Center (argus.86bit.it). Skippiamo il launch della UI
# in TUTTI i casi - sia install iniziale dal wizard ZIP, sia update
# remoto (-Source center). Manteniamo solo il cleanup di processi UI
# residui per evitare conflitti di file lock sul binario aggiornato.
try {
    Get-Process -Name 'nocagent-ui'   -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name 'ArgusDesktop'  -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
} catch {}
Write-Step "Headless mode: UI desktop NON avviata. Gestione via NOC Center."

Write-Host "Per controllare i log in tempo reale:" -ForegroundColor Gray
Write-Host "  Get-Content `"`$((Get-Content '$markerPath' -Raw).Trim())`" -Wait -Tail 50" -ForegroundColor Gray
Write-Host ""

# ------------------------------------------------------------------- #
# OUTCOME / TEARDOWN - viene SEMPRE eseguito anche su errore terminating
# ------------------------------------------------------------------- #
# La logica delle eccezioni e' gestita dal $ErrorActionPreference="Stop"
# all'inizio: qualunque eccezione fa uscire lo script SUBITO. Per
# garantire che il transcript venga chiuso e che il marker rifletta
# l'esito (success/failed), usiamo `trap` (Powershell e' single-threaded
# quindi sicuro). trap esegue il blocco quando un errore terminating
# bubble-up oltre tutti i try/catch - perfetto come safety net.
#
# Note: trap viene attivato anche su Ctrl+C / kill.

# Path felice: success - marcatura finale + chiusura transcript pulita.
Update-UpgradeMarker -Status "completed" -Extra "version=$resolvedVersion"
Write-UpgradeEvent -Message "Upgrade COMPLETED version=$resolvedVersion`nLogFile=$script:UpgradeLogFile" -EntryType Information -EventId 1100

# Upload best-effort al Center: Send-UpgradeReport chiude internamente
# il transcript, attende il flush e legge il file con UTF-16/BOM-aware
# ReadAllText. Cosi' l'admin vede il transcript completo nel modale
# anche se l'agent installato e' troppo vecchio per il comando WS.
Send-UpgradeReport -Status "completed" -ResolvedVersion $resolvedVersion

# Mirror "latest" - fatto DOPO Send-UpgradeReport perche' il transcript
# e' stato chiuso dentro quella funzione.
if (Test-Path $script:UpgradeLogFile) {
    try { Copy-Item -Path $script:UpgradeLogFile -Destination $script:UpgradeLatestLog -Force -ErrorAction SilentlyContinue } catch {}
}

if (-not $Quiet) {
    Write-Host "Premi un tasto per chiudere..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
