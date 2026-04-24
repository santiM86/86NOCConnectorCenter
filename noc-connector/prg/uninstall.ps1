<#
.SYNOPSIS
    ARGUS Connector (86NocConnector) — Disinstallazione enterprise-grade.

.DESCRIPTION
    Rimuove in modo robusto e idempotente ogni traccia del connector dalla macchina:
      - Task Scheduler (updater, watchdog, legacy pre-3.3.0, omonimi del servizio)
      - Servizio NSSM in qualsiasi stato (Running / Paused / StopPending / Disabled)
      - Processi orfani (PowerShell del connector, NSSM, tray app)
      - Menu Start (tutti gli alias storici)
      - Registro (Uninstall, Run, sia 32 che 64 bit)
      - Cartelle dati (%ProgramData%\86NocConnector)
      - Cartella installazione (C:\Program Files\86NocConnector, gestisce file in uso)

    Safe-by-design:
      - Non killa processi PowerShell generici, filtra solo quelli legati al connector (path-based).
      - Non killa il proprio PID (evita auto-suicidio).
      - Idempotente: riesecuzioni successive non generano errori.
      - Log completo in %TEMP%\argus-uninstall-<timestamp>.log

.NOTES
    Richiede Amministratore. Invocato tipicamente da uninstall.bat (shortcut Menu Start
    oppure "Pannello di Controllo > Programmi e funzionalità").
#>

param(
    [switch]$NoPause
)

$ErrorActionPreference = 'Continue'
$AppName     = "86NocConnector"
$DisplayName = "ARGUS Connector"
$SvcName     = "86NocConnectorService"
$InstallDir  = Join-Path ([Environment]::GetFolderPath("ProgramFiles")) $AppName
$ConfigDir   = Join-Path $env:ProgramData $AppName
$LegacyDir   = "C:\86NocConnector"   # path pre-v3.4.0

# === Setup log ===
$stamp   = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $env:TEMP "argus-uninstall-$stamp.log"
$script:Report = @()

function Write-UninstallLog {
    param([string]$Message, [ValidateSet('INFO','OK','WARN','ERROR','STEP')][string]$Level = 'INFO')
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    try { Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue } catch {}
    $color = switch ($Level) {
        'OK'    { 'Green' }
        'WARN'  { 'Yellow' }
        'ERROR' { 'Red' }
        'STEP'  { 'Cyan' }
        default { 'Gray' }
    }
    Write-Host $line -ForegroundColor $color
    $script:Report += [PSCustomObject]@{ Level = $Level; Message = $Message }
}

# === Admin check ===
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal   = New-Object Security.Principal.WindowsPrincipal($currentUser)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host ""
    Write-Host "  [ERRORE] Serve PowerShell come Amministratore." -ForegroundColor Red
    Write-Host "  Chiudi e riapri il collegamento 'Disinstalla ARGUS Connector' con tasto destro > Esegui come amministratore." -ForegroundColor Yellow
    Write-Host ""
    if (-not $NoPause) { Read-Host "Premi INVIO per chiudere" }
    exit 1
}

Clear-Host
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "     $DisplayName — Disinstallazione" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "  Log: $LogFile" -ForegroundColor DarkGray
Write-Host ""

Write-UninstallLog "Avvio disinstallazione $DisplayName" "INFO"
Write-UninstallLog "Utente: $($currentUser.Name) | Host: $env:COMPUTERNAME" "INFO"

# ============================================================
# STEP 1 — Rimozione Task Scheduler (PRIMA del servizio NSSM)
# ============================================================
# Ordine critico: prima i task, poi il servizio. Altrimenti il task
# in esecuzione potrebbe riavviare il servizio mentre lo stiamo eliminando.
Write-UninstallLog "STEP 1 — Rimozione Task Scheduler" "STEP"

$tasksToRemove = @(
    @{ Path = '\86BIT\';    Name = 'ArgusConnectorUpdater' },   # v3.5.0+ auto-update
    @{ Path = '\86BIT\';    Name = '86NocConnector_Watchdog' }, # v3.5.12 watchdog
    @{ Path = '\';          Name = '86NocConnector' },           # legacy <v3.3.0
    @{ Path = '\';          Name = $SvcName },                   # OMONIMO NSSM (colpevole storico restart loop GALVANSRV)
    @{ Path = '\';          Name = 'ArgusConnector' },           # alias
    @{ Path = '\86BIT\';    Name = $SvcName }                    # varianti
)

foreach ($t in $tasksToRemove) {
    try {
        $existing = Get-ScheduledTask -TaskPath $t.Path -TaskName $t.Name -ErrorAction SilentlyContinue
        if ($existing) {
            try { Stop-ScheduledTask -TaskPath $t.Path -TaskName $t.Name -ErrorAction SilentlyContinue } catch {}
            Unregister-ScheduledTask -TaskPath $t.Path -TaskName $t.Name -Confirm:$false -ErrorAction Stop
            Write-UninstallLog "Task rimosso: $($t.Path)$($t.Name)" "OK"
        }
    } catch {
        Write-UninstallLog "Task $($t.Name): $($_.Exception.Message)" "WARN"
    }
    # Fallback con schtasks.exe (per compatibilità vecchie API)
    $tn = ($t.Path.TrimStart('\').TrimEnd('\') + '\' + $t.Name).TrimStart('\')
    & schtasks.exe /End /TN $tn 2>$null | Out-Null
    & schtasks.exe /Delete /TN $tn /F 2>$null | Out-Null
}
# Prova anche a rimuovere la cartella parent \86BIT\ se ora è vuota
try {
    $root = New-Object -ComObject Schedule.Service
    $root.Connect()
    $folder = $root.GetFolder('\86BIT')
    if ($folder -and $folder.GetTasks(1).Count -eq 0) {
        $root.GetFolder('\').DeleteFolder('86BIT', 0)
        Write-UninstallLog "Cartella task '\86BIT\' rimossa (vuota)" "OK"
    }
} catch {}

# ============================================================
# STEP 2 — Stop + Delete Servizio NSSM (resistente a Paused/StopPending)
# ============================================================
Write-UninstallLog "STEP 2 — Arresto ed eliminazione servizio NSSM '$SvcName'" "STEP"

$svc = Get-Service -Name $SvcName -ErrorAction SilentlyContinue
if ($svc) {
    Write-UninstallLog "Servizio trovato, stato=$($svc.Status) startType=$($svc.StartType)" "INFO"

    # Caso 1: Paused → Resume forzato per poterlo poi stoppare (altrimenti Stop-Service si blocca)
    if ($svc.Status -eq 'Paused') {
        Write-UninstallLog "Servizio in stato Paused: tentativo Resume prima di stop..." "WARN"
        try { Resume-Service -Name $SvcName -ErrorAction SilentlyContinue } catch {}
        Start-Sleep -Seconds 1
    }

    # Caso 2: se NSSM è presente, usalo (gestisce meglio figli)
    $nssmExe = Join-Path $InstallDir "nssm.exe"
    if (Test-Path $nssmExe) {
        try {
            & $nssmExe stop $SvcName 2>&1 | Out-Null
            Write-UninstallLog "NSSM stop inviato" "OK"
        } catch {
            Write-UninstallLog "NSSM stop: $($_.Exception.Message)" "WARN"
        }
    }

    # Caso 3: sc.exe stop (sempre, cover di qualsiasi stato incluso Paused/StopPending)
    & sc.exe stop $SvcName 2>&1 | Out-Null

    # Attendi stop fino a 15s
    $waited = 0
    while ($waited -lt 15) {
        Start-Sleep -Seconds 1; $waited++
        $cur = Get-Service -Name $SvcName -ErrorAction SilentlyContinue
        if (-not $cur -or $cur.Status -eq 'Stopped') { break }
    }

    # Caso 4: servizio ancora Paused dopo 15s → kill del process child di NSSM
    $cur = Get-Service -Name $SvcName -ErrorAction SilentlyContinue
    if ($cur -and $cur.Status -ne 'Stopped') {
        Write-UninstallLog "Servizio non si ferma in 15s (stato=$($cur.Status)): kill processi in $InstallDir..." "WARN"
        Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Id -ne $PID -and $_.Path -and $_.Path -like (Join-Path $InstallDir '*')
        } | ForEach-Object {
            try {
                Write-UninstallLog "  kill $($_.Name) pid=$($_.Id) [$($_.Path)]" "INFO"
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            } catch {}
        }
        Start-Sleep -Seconds 2
    }

    # Elimina il servizio (sc.exe è canonico, non richiede NSSM)
    & sc.exe delete $SvcName 2>&1 | Out-Null
    Start-Sleep -Seconds 1
    $stillThere = Get-Service -Name $SvcName -ErrorAction SilentlyContinue
    if ($stillThere) {
        Write-UninstallLog "Servizio ancora presente — richiedo rimozione manuale del DB SCM. Reboot libererà il record." "WARN"
    } else {
        Write-UninstallLog "Servizio NSSM eliminato" "OK"
    }
} else {
    Write-UninstallLog "Servizio non presente (già rimosso)" "OK"
}

# ============================================================
# STEP 3 — Kill processi orfani (PowerShell + NSSM del connector)
# ============================================================
Write-UninstallLog "STEP 3 — Terminazione processi orfani legati al connector" "STEP"

$killedCount = 0

# 3a) nssm.exe che esegue ancora dalla install dir (se è rimasto qualcosa)
Get-Process -Name nssm -ErrorAction SilentlyContinue | Where-Object {
    $_.Id -ne $PID -and $_.Path -and $_.Path -like (Join-Path $InstallDir '*')
} | ForEach-Object {
    try {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-UninstallLog "  killed nssm.exe pid=$($_.Id)" "OK"
        $killedCount++
    } catch {}
}

# 3b) PowerShell orfano con command line che referenzia i nostri script
#     (connector.ps1, tray_app.ps1, snmp_poller.ps1, update_check.ps1)
try {
    $psScriptPatterns = @('connector.ps1', 'tray_app.ps1', 'snmp_poller.ps1', 'update_check.ps1', 'service_wrapper.ps1')
    $psProcs = Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $psProcs) {
        if ($p.ProcessId -eq $PID) { continue }  # mai killare se stesso
        $cmd = [string]$p.CommandLine
        if (-not $cmd) { continue }
        $match = $false
        foreach ($pat in $psScriptPatterns) {
            if ($cmd -like "*\$pat*" -or $cmd -like "*/$pat*") { $match = $true; break }
        }
        if ($match) {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                Write-UninstallLog "  killed PowerShell pid=$($p.ProcessId) [$([IO.Path]::GetFileName($cmd.Split()[0]))]" "OK"
                $killedCount++
            } catch {}
        }
    }
} catch {
    Write-UninstallLog "Enumerazione processi via CIM fallita: $($_.Exception.Message)" "WARN"
}

if ($killedCount -eq 0) { Write-UninstallLog "Nessun processo orfano trovato" "OK" }
Start-Sleep -Seconds 2

# ============================================================
# STEP 4 — Rimozione collegamenti Menu Start
# ============================================================
Write-UninstallLog "STEP 4 — Pulizia collegamenti Menu Start" "STEP"

$startMenuCandidates = @(
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\86BIT ArgusCenter",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\86BIT Connector",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\86NocConnector",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\ARGUS Connector",
    "$env:AppData\Microsoft\Windows\Start Menu\Programs\86BIT ArgusCenter",
    "$env:AppData\Microsoft\Windows\Start Menu\Programs\ARGUS Connector"
)
foreach ($d in $startMenuCandidates) {
    if (Test-Path $d) {
        try {
            Remove-Item $d -Recurse -Force -ErrorAction Stop
            Write-UninstallLog "Menu Start rimosso: $d" "OK"
        } catch {
            Write-UninstallLog "Menu Start $d : $($_.Exception.Message)" "WARN"
        }
    }
}

# ============================================================
# STEP 5 — Pulizia registro (Uninstall + Run, 32/64)
# ============================================================
Write-UninstallLog "STEP 5 — Pulizia chiavi di registro" "STEP"

$regKeys = @(
    'HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86BIT_ArgusCenter_Connector',
    'HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector',
    'HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\ARGUS_Connector',
    'HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\86NocConnector',
    'HKCU\Software\Microsoft\Windows\CurrentVersion\Run\86NocConnector',
    'HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ARGUS_Connector',
    'HKLM\Software\Microsoft\Windows\CurrentVersion\Run\86NocConnector'
)
foreach ($k in $regKeys) {
    & reg.exe delete $k /f /reg:64 2>$null | Out-Null
    & reg.exe delete $k /f /reg:32 2>$null | Out-Null
}
Write-UninstallLog "Chiavi registro rimosse (idempotente)" "OK"

# ============================================================
# STEP 6 — Rimozione cartella dati (%ProgramData%\86NocConnector)
# ============================================================
Write-UninstallLog "STEP 6 — Rimozione cartella dati $ConfigDir" "STEP"

if (Test-Path $ConfigDir) {
    try {
        Remove-Item $ConfigDir -Recurse -Force -ErrorAction Stop
        Write-UninstallLog "Cartella dati rimossa: $ConfigDir" "OK"
    } catch {
        Write-UninstallLog "Cartella dati $ConfigDir : $($_.Exception.Message)" "WARN"
    }
} else {
    Write-UninstallLog "Cartella dati già assente" "OK"
}

# ============================================================
# STEP 7 — Rimozione installazione (con retry + reboot fallback)
# ============================================================
Write-UninstallLog "STEP 7 — Rimozione cartella installazione $InstallDir" "STEP"

function Remove-WithRetry([string]$Path, [int]$Tries = 5) {
    if (-not (Test-Path $Path)) { return $true }
    for ($i = 1; $i -le $Tries; $i++) {
        try {
            Remove-Item $Path -Recurse -Force -ErrorAction Stop
            return $true
        } catch {
            Start-Sleep -Seconds 1
            # Al secondo tentativo, ritenta kill dei processi che potrebbero tenerla aperta
            if ($i -eq 2) {
                Get-Process -ErrorAction SilentlyContinue | Where-Object {
                    $_.Id -ne $PID -and $_.Path -and $_.Path -like (Join-Path $Path '*')
                } | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }
        }
    }
    return $false
}

$removed = $false
if (Test-Path $InstallDir) {
    $removed = Remove-WithRetry -Path $InstallDir -Tries 5
    if ($removed) {
        Write-UninstallLog "Installazione rimossa: $InstallDir" "OK"
    } else {
        # Fallback: schedule per il reboot successivo tramite MoveFileEx PendingRename
        Write-UninstallLog "File ancora in uso — programmo eliminazione al prossimo reboot" "WARN"
        try {
            $key = 'HKLM\System\CurrentControlSet\Control\Session Manager'
            $vals = @()
            Get-ChildItem -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
                $vals += "\??\$($_.FullName)"; $vals += ''
            }
            $vals += "\??\$InstallDir"; $vals += ''
            $existing = (Get-ItemProperty -Path "Registry::$key" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
            if ($existing) { $vals = $existing + $vals }
            New-ItemProperty -Path "Registry::$key" -Name PendingFileRenameOperations -PropertyType MultiString -Value $vals -Force | Out-Null
            Write-UninstallLog "PendingFileRenameOperations impostato: riavviare il server per completare la pulizia" "WARN"
        } catch {
            Write-UninstallLog "Schedule reboot cleanup fallito: $($_.Exception.Message)" "ERROR"
        }
    }
} else {
    Write-UninstallLog "Cartella installazione già assente" "OK"
    $removed = $true
}

# Legacy folder C:\86NocConnector (pre-v3.4.0)
if (Test-Path $LegacyDir) {
    try {
        Remove-Item $LegacyDir -Recurse -Force -ErrorAction Stop
        Write-UninstallLog "Cartella legacy rimossa: $LegacyDir" "OK"
    } catch {
        Write-UninstallLog "Cartella legacy $LegacyDir : $($_.Exception.Message)" "WARN"
    }
}

# ============================================================
# STEP 8 — Verifica finale (sistema vergine?)
# ============================================================
Write-UninstallLog "STEP 8 — Verifica finale" "STEP"

$problems = @()

if (Test-Path $InstallDir)  { $problems += "Cartella installazione ancora presente ($InstallDir)" }
if (Test-Path $ConfigDir)   { $problems += "Cartella dati ancora presente ($ConfigDir)" }
if (Get-Service -Name $SvcName -ErrorAction SilentlyContinue) { $problems += "Servizio $SvcName ancora registrato" }
$residualTasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.TaskName -like "*NocConnector*" -or $_.TaskName -like "*ArgusConnector*"
}
if ($residualTasks) {
    foreach ($rt in $residualTasks) {
        $problems += "Task residuo: $($rt.TaskPath)$($rt.TaskName) (stato=$($rt.State))"
    }
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
if ($problems.Count -eq 0) {
    Write-Host "     SISTEMA PULITO — disinstallazione completata" -ForegroundColor Green
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-UninstallLog "Sistema vergine: nessuna traccia residua del connector" "OK"
    $exitCode = 0
} elseif (-not $removed -and $problems.Count -eq 1) {
    Write-Host "     DISINSTALLAZIONE IN SOSPESO — richiesto reboot" -ForegroundColor Yellow
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  I file della cartella installazione sono ancora bloccati da processi di sistema." -ForegroundColor Yellow
    Write-Host "  Al prossimo riavvio di Windows verranno eliminati automaticamente." -ForegroundColor Yellow
    $exitCode = 1
} else {
    Write-Host "     DISINSTALLAZIONE PARZIALE — azioni manuali consigliate" -ForegroundColor Yellow
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
    foreach ($p in $problems) { Write-Host "  - $p" -ForegroundColor Yellow }
    Write-UninstallLog "Residui trovati: $($problems -join '; ')" "WARN"
    $exitCode = 1
}

Write-Host ""
Write-Host "  Log completo salvato in:" -ForegroundColor DarkGray
Write-Host "    $LogFile" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoPause) {
    Write-Host "  Premi INVIO per chiudere..." -ForegroundColor DarkGray
    try { [void][System.Console]::ReadLine() } catch {}
}

exit $exitCode
