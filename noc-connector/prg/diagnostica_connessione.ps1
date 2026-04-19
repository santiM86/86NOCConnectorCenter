<#
.SYNOPSIS
    86NocConnector - Diagnostica Connessione
.DESCRIPTION
    Esegui questo script sul server per diagnosticare problemi di connessione.
    Apri PowerShell come Amministratore e lancia:
    powershell -ExecutionPolicy Bypass -File diagnostica_connessione.ps1
#>

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  86NocConnector - Diagnostica Connessione" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verifica Scheduled Task
Write-Host "[1/6] Verifica Scheduled Task..." -ForegroundColor Yellow
try {
    $task = Get-ScheduledTask -TaskName "86NocConnectorService" -ErrorAction Stop
    Write-Host "  Task trovato: $($task.TaskName)" -ForegroundColor Green
    Write-Host "  Stato: $($task.State)" -ForegroundColor $(if($task.State -eq "Running"){"Green"}else{"Red"})
    $taskInfo = Get-ScheduledTaskInfo -TaskName "86NocConnectorService" -ErrorAction SilentlyContinue
    if ($taskInfo) {
        Write-Host "  Ultima esecuzione: $($taskInfo.LastRunTime)"
        Write-Host "  Risultato: $($taskInfo.LastTaskResult)"
    }
} catch {
    Write-Host "  Task NON trovato! Esegui install.bat per registrarlo." -ForegroundColor Red
}
Write-Host ""

# 2. Verifica processi attivi
Write-Host "[2/6] Processi connector attivi..." -ForegroundColor Yellow
$procs = Get-Process powershell, pwsh -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -match "connector\.ps1") {
        [PSCustomObject]@{ PID = $_.Id; User = (Get-Process -Id $_.Id -IncludeUserName -ErrorAction SilentlyContinue).UserName; Start = $_.StartTime; Cmd = $cmd.Substring(0, [Math]::Min(80, $cmd.Length)) }
    }
}
if ($procs) {
    $procs | Format-Table -AutoSize
} else {
    Write-Host "  Nessun processo connector.ps1 in esecuzione!" -ForegroundColor Red
}
Write-Host ""

# 3. Verifica config
Write-Host "[3/6] Verifica configurazione..." -ForegroundColor Yellow
$configPath = Join-Path $env:ProgramData "86NocConnector\config.json"
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    Write-Host "  NOC URL: $($config.noc_center_url)" -ForegroundColor Green
    Write-Host "  API Key: $($config.api_key.Substring(0,10))..." -ForegroundColor Green
    Write-Host "  Dispositivi: $($config.devices.Count)" -ForegroundColor Green
} else {
    Write-Host "  config.json NON TROVATO in $configPath!" -ForegroundColor Red
    Write-Host "  Esegui install.bat per configurare." -ForegroundColor Red
}
Write-Host ""

# 4. Verifica status file
Write-Host "[4/6] Status file (status.json)..." -ForegroundColor Yellow
$statusPath = Join-Path $env:ProgramData "86NocConnector\status.json"
if (Test-Path $statusPath) {
    $status = Get-Content $statusPath -Raw | ConvertFrom-Json
    Write-Host "  Stato: $($status.status)" -ForegroundColor $(if($status.status -eq "running"){"Green"}else{"Red"})
    Write-Host "  Versione: $($status.version)"
    Write-Host "  PID: $($status.pid)"
    Write-Host "  Uptime: $([math]::Floor($status.uptime_seconds / 3600))h $([math]::Floor(($status.uptime_seconds % 3600) / 60))m"
    Write-Host "  Ultimo aggiornamento: $($status.last_update)"
    Write-Host "  Errori: $($status.errors)"
    if ($status.last_error) { Write-Host "  Ultimo errore: $($status.last_error)" -ForegroundColor Red }
} else {
    Write-Host "  status.json non presente (connettore mai avviato o fermo)" -ForegroundColor Red
}
Write-Host ""

# 5. Test connettivita' TLS
Write-Host "[5/6] Test connettivita' verso il NOC..." -ForegroundColor Yellow
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $nocUrl = $config.noc_center_url
    
    # Force TLS 1.2
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }
    Write-Host "  TLS Protocol: $([Net.ServicePointManager]::SecurityProtocol)"
    
    # Test /api/health
    try {
        $result = Invoke-RestMethod -Uri "$nocUrl/api/health" -Method Get -TimeoutSec 10 -ErrorAction Stop
        Write-Host "  GET /api/health: OK ($($result.status))" -ForegroundColor Green
    } catch {
        Write-Host "  GET /api/health: FALLITO" -ForegroundColor Red
        Write-Host "  Errore: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.Exception.InnerException) {
            Write-Host "  Dettaglio: $($_.Exception.InnerException.Message)" -ForegroundColor Red
        }
    }
    
    # Test heartbeat
    try {
        $body = @{ hostname = $env:COMPUTERNAME; connector_version = "test"; uptime_seconds = 0; traps_received = 0; syslogs_received = 0 } | ConvertTo-Json -Compress
        $headers = @{ "X-API-Key" = $config.api_key; "Content-Type" = "application/json" }
        $result = Invoke-RestMethod -Uri "$nocUrl/api/connector/heartbeat" -Method Post -Headers $headers -Body $body -TimeoutSec 10 -ErrorAction Stop
        Write-Host "  POST /api/connector/heartbeat: OK ($($result.status))" -ForegroundColor Green
    } catch {
        Write-Host "  POST /api/connector/heartbeat: FALLITO" -ForegroundColor Red
        Write-Host "  Errore: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.Exception.InnerException) {
            Write-Host "  Dettaglio: $($_.Exception.InnerException.Message)" -ForegroundColor Red
        }
    }
} else {
    Write-Host "  Salto test (config.json mancante)" -ForegroundColor Red
}
Write-Host ""

# 6. Log recenti
Write-Host "[6/6] Ultimi log del connettore..." -ForegroundColor Yellow
$logPath = Join-Path $env:ProgramData "86NocConnector\logs\connector.log"
if (Test-Path $logPath) {
    $lastLines = Get-Content $logPath -Tail 15
    foreach ($line in $lastLines) {
        $color = "Gray"
        if ($line -match "ERROR") { $color = "Red" }
        elseif ($line -match "WARN") { $color = "Yellow" }
        elseif ($line -match "avviato|OK|running") { $color = "Green" }
        Write-Host "  $line" -ForegroundColor $color
    }
} else {
    Write-Host "  Nessun file di log trovato in $logPath" -ForegroundColor Red
}
Write-Host ""

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Diagnostica completata." -ForegroundColor Cyan
Write-Host "  Copia l'output e invialo al supporto." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
pause
