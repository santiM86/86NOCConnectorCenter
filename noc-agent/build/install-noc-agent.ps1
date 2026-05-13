<#
.SYNOPSIS
  86bit NOC Agent — installer / updater STANDALONE (zero dipendenze backend).

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
  PAT GitHub se il repo è privato. Lasciare vuoto per repo pubblici.

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
    [string]$Repo = "santiM86/86NOCConnectorCenter",
    [string]$Version = "latest",
    [string]$GitHubToken = "",
    [string]$InstallDir = "C:\Program Files\86NocAgent",
    [string]$DataDir = "C:\ProgramData\86NocAgent",
    [switch]$Quiet
)

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
Write-Host "InstallDir:  $InstallDir"
Write-Host "DataDir:     $DataDir"

# ------------------------------------------------------------------- #
# 2. Risolvi il tag della release (latest -> tag concreto)
# ------------------------------------------------------------------- #
Write-Step "Risoluzione versione GitHub Release"

$ghHeaders = @{ "User-Agent" = "86noc-installer" }
if ($GitHubToken) { $ghHeaders["Authorization"] = "Bearer $GitHubToken" }

try {
    if ($Version -eq "latest") {
        $apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
        $rel = Invoke-RestMethod -Uri $apiUrl -Headers $ghHeaders -TimeoutSec 30
        $Version = $rel.tag_name
        Write-Ok "Latest release: $Version"
    } else {
        $apiUrl = "https://api.github.com/repos/$Repo/releases/tags/$Version"
        $rel = Invoke-RestMethod -Uri $apiUrl -Headers $ghHeaders -TimeoutSec 30
        Write-Ok "Release: $($rel.tag_name) — $($rel.name)"
    }
} catch {
    Write-Fail "Impossibile risolvere la release: $($_.Exception.Message)"
    if ($_.Exception.Response.StatusCode -eq 404) {
        Write-Fail "Verifica che '$Repo' esista, sia accessibile, e che ci sia almeno una release."
        Write-Fail "Repo privati richiedono -GitHubToken con scope 'repo' o 'public_repo'."
    }
    exit 2
}

# Map filename -> asset URL
$assetUrls = @{}
foreach ($a in $rel.assets) { $assetUrls[$a.name] = $a.browser_download_url }
$required = @("nocagent.exe","nocwatchdog.exe","nocagent-ui.exe")
foreach ($f in $required) {
    if (-not $assetUrls.ContainsKey($f)) {
        Write-Fail "Asset mancante nella release $Version: $f"
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

# ------------------------------------------------------------------- #
# 4. Pulisci stato vecchio
# ------------------------------------------------------------------- #
Write-Step "Pulizia stato precedente"
Remove-Item (Join-Path $DataDir "logs") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $DataDir "log_path.txt") -Force -ErrorAction SilentlyContinue
Write-Ok "logs/ e log_path.txt rimossi"

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
        if ($GitHubToken) {
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

# ------------------------------------------------------------------- #
# 6. Scrivi agent.yaml (preserva snmp_targets se gia' presente)
# ------------------------------------------------------------------- #
Write-Step "Scrittura agent.yaml"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$yamlPath = Join-Path $DataDir "agent.yaml"

# Estrai eventuale sezione MANAGED TARGETS esistente per preservare i targets SNMP
$managedTargets = ""
if (Test-Path $yamlPath) {
    $oldContent = Get-Content $yamlPath -Raw
    if ($oldContent -match "(?ms)^# === BEGIN MANAGED TARGETS ===.*?^# === END MANAGED TARGETS ===") {
        $managedTargets = $Matches[0]
        Write-Ok "Sezione MANAGED TARGETS esistente preservata"
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
watchdog:
  enabled: true
  stale_after: 90s
update:
  enabled: false
labels:
  role: "$Role"
"@

if ($managedTargets) {
    $yaml = "$yaml`n$managedTargets`n"
}

[System.IO.File]::WriteAllText($yamlPath, $yaml, [System.Text.Encoding]::UTF8)
Write-Ok "agent.yaml scritto in $yamlPath"

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

$ver = & $nocagentExe --version 2>&1
Write-Ok "Versione binario: $ver"

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
    Write-Warn2 "Marker log_path.txt assente — il binario potrebbe non aver inizializzato il logger"
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
Write-Host "Per controllare i log in tempo reale:" -ForegroundColor Gray
Write-Host "  Get-Content `"`$((Get-Content '$markerPath' -Raw).Trim())`" -Wait -Tail 50" -ForegroundColor Gray
Write-Host ""

if (-not $Quiet) {
    Write-Host "Premi un tasto per chiudere..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
