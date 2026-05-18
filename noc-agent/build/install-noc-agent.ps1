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
    # GitHub unauth (60 req/h) sui PC dei clienti — il PAT viene usato
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

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red }

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
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
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
$required = @("nocagent.exe","nocwatchdog.exe","nocagent-ui.exe")
# ArgusDesktop.exe (nuova UI Wails) e' opzionale per backward compatibility
# con release vecchie che non lo includevano. Se presente lo installiamo.
$optional = @("ArgusDesktop.exe")
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
$uiProcs = @("nocagent-ui","ArgusDesktop")
foreach ($p in $uiProcs) {
    $procs = Get-Process -Name $p -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Ok "Processo $p.exe terminato ($($procs.Count) istanze)"
    }
}
Start-Sleep -Seconds 2

# ------------------------------------------------------------------- #
# 4. Pulisci stato vecchio
# ------------------------------------------------------------------- #
Write-Step "Pulizia stato precedente"
Remove-Item (Join-Path $DataDir "logs") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $DataDir "log_path.txt") -Force -ErrorAction SilentlyContinue
Write-Ok "logs/ e log_path.txt rimossi"

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
# release lo include — release pre-v4.8 non lo hanno, e va bene cosi'.
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
[System.IO.File]::WriteAllText($uiInfoPath, $uiInfo, [System.Text.Encoding]::UTF8)
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
    [System.IO.File]::WriteAllText($legacyUiPath, $uiInfo, [System.Text.Encoding]::UTF8)
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
if (Test-Path $uiExe) {
    Write-Step "Avvio UI desktop ($uiLabel)"
    $launched = $false
    # Strategia 1: Start-Process diretto. Funziona quando l'installer
    # gira nella sessione utente (PowerShell admin lanciato dall'utente
    # via UAC) — caso largamente maggioritario in produzione MSP. Il
    # processo figlio eredita il contesto interattivo e la tray icon
    # appare correttamente nella session dell'utente loggato.
    try {
        Start-Process -FilePath $uiExe -ErrorAction Stop
        Write-Ok "UI desktop avviata (Start-Process diretto)"
        $launched = $true
    } catch {
        Write-Warn2 "Start-Process diretto fallito: $($_.Exception.Message)"
    }
    # Strategia 2 (fallback per SYSTEM session, es. RMM-deployed): usa
    # schtasks CLI nativo (NON XML — l'XML schema 1.4 richiedeva
    # EndBoundary obbligatorio non gestito → errore "(7,4):EndBoundary").
    # Crea un task one-shot, lo esegue, lo elimina. /RU INTERACTIVE
    # forza l'esecuzione nella sessione utente interattivo corrente.
    if (-not $launched) {
        try {
            $taskName = "86NocAgent-UI-Launch-$([guid]::NewGuid().ToString('N').Substring(0,8))"
            & schtasks.exe /Create /TN $taskName /TR "`"$uiExe`"" /SC ONCE /ST "23:59" /SD "01/01/2030" /RU "INTERACTIVE" /RL LIMITED /F | Out-Null
            if ($LASTEXITCODE -eq 0) {
                & schtasks.exe /Run /TN $taskName | Out-Null
                Start-Sleep -Seconds 3
                & schtasks.exe /Delete /TN $taskName /F 2>$null | Out-Null
                Write-Ok "UI desktop avviata via schtasks INTERACTIVE"
                $launched = $true
            }
        } catch {
            Write-Warn2 "Launch via schtasks fallita: $($_.Exception.Message)"
        }
    }
    if (-not $launched) {
        Write-Warn2 "Impossibile avviare UI desktop automaticamente. Apri manualmente dal menu Start: '86BIT Argus Connector > Connector'."
    }
}

Write-Host "Per controllare i log in tempo reale:" -ForegroundColor Gray
Write-Host "  Get-Content `"`$((Get-Content '$markerPath' -Raw).Trim())`" -Wait -Tail 50" -ForegroundColor Gray
Write-Host ""

if (-not $Quiet) {
    Write-Host "Premi un tasto per chiudere..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
