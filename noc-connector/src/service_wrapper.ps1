<#
.SYNOPSIS
    Wrapper per avviare connector.ps1 come servizio.
    Cattura gli errori e li logga, poi riavvia automaticamente.
    Usato dal Scheduled Task per garantire che il connettore giri sempre.
#>

# Forza TLS 1.2
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$connectorScript = Join-Path $scriptDir "connector.ps1"
$logDir = Join-Path $env:ProgramData "86NocConnector\logs"
$serviceLog = Join-Path $logDir "service.log"

if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-ServiceLog($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Out-File -FilePath $serviceLog -Append -Encoding UTF8
    # Log rotation: max 2MB per service.log
    try {
        if (Test-Path $serviceLog) {
            $size = (Get-Item $serviceLog -ErrorAction SilentlyContinue).Length
            if ($size -and $size -gt 2097152) {
                $archive = $serviceLog -replace '\.log$', "_$(Get-Date -Format 'yyyyMMdd').log"
                Move-Item $serviceLog $archive -Force -ErrorAction SilentlyContinue
                # Tieni solo ultimi 2 archivi
                Get-ChildItem $logDir -Filter "service_*.log" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending |
                    Select-Object -Skip 2 |
                    Remove-Item -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

Write-ServiceLog "=== SERVICE WRAPPER AVVIATO ==="
Write-ServiceLog "Utente: $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)"
Write-ServiceLog "Sessione: $(if ($env:SESSIONNAME) { $env:SESSIONNAME } else { 'Session0/SYSTEM' })"
Write-ServiceLog "Script: $connectorScript"
Write-ServiceLog "PID: $PID"

# Loop infinito: se il connettore crasha, lo riavvia dopo 30 secondi
while ($true) {
    Write-ServiceLog "Avvio connector.ps1..."
    try {
        & $connectorScript 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                Write-ServiceLog "ERRORE: $_"
            }
        }
        Write-ServiceLog "connector.ps1 terminato normalmente."
    } catch {
        Write-ServiceLog "ECCEZIONE: $($_.Exception.Message)"
        if ($_.Exception.InnerException) {
            Write-ServiceLog "INNER: $($_.Exception.InnerException.Message)"
        }
    }
    
    Write-ServiceLog "Riavvio tra 30 secondi..."
    Start-Sleep -Seconds 30
}
