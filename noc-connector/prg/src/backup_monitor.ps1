# =============================================
# 86NocConnector - Backup Monitor (Hornetsecurity VM Backup)
# Monitora lo stato dei backup Hyper-V tramite API REST locale
# =============================================

function Get-AltaroBackupStatus($config) {
    <#
    .SYNOPSIS
        Interroga l'API REST locale di Hornetsecurity VM Backup v9.1.x
        per ottenere lo stato dei backup di tutte le VM configurate.
        Combina i dati con le info di Hyper-V (Get-VM).
    #>
    
    $apiUrl = if ($config.altaro_api_url) { $config.altaro_api_url } else { "https://localhost:36013/api/rest" }
    $username = $config.altaro_username
    $password = $config.altaro_password
    
    if (-not $username -or -not $password) {
        Write-Host "[Backup Monitor] Credenziali Altaro non configurate. Skipping." -ForegroundColor Yellow
        return $null
    }
    
    # Ignora certificati self-signed (API locale Altaro)
    try {
        Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int problem) { return true; }
}
"@
        [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy
    } catch {}
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    
    $sessionToken = $null
    $result = @{
        vms = @()
        hyperv_vms = @()
        summary = @{
            total_vms = 0
            backup_ok = 0
            backup_warning = 0
            backup_failed = 0
            backup_missing = 0
            last_check = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
        }
        altaro_connected = $false
        hyperv_connected = $false
    }
    
    # ---- STEP 1: Query Hyper-V per lista VM ----
    try {
        $hypervVMs = Get-VM -ErrorAction Stop
        $result.hyperv_connected = $true
        foreach ($vm in $hypervVMs) {
            $result.hyperv_vms += @{
                name = $vm.Name
                state = $vm.State.ToString()
                cpu_usage = $vm.CPUUsage
                memory_mb = [math]::Round($vm.MemoryAssigned / 1MB, 0)
                memory_demand_mb = [math]::Round($vm.MemoryDemand / 1MB, 0)
                uptime = $vm.Uptime.ToString()
                status = $vm.Status
                generation = $vm.Generation
                version = $vm.Version
                replication_state = if ($vm.ReplicationState) { $vm.ReplicationState.ToString() } else { "None" }
                checkpoint_count = ($vm | Get-VMCheckpoint -ErrorAction SilentlyContinue | Measure-Object).Count
            }
        }
        Write-Host "[Backup Monitor] Hyper-V: $($hypervVMs.Count) VM trovate" -ForegroundColor Green
    } catch {
        Write-Host "[Backup Monitor] Hyper-V non disponibile: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    
    # ---- STEP 2: Autenticazione API Altaro ----
    try {
        Write-Host "[Backup Monitor] Connessione a Altaro API: $apiUrl"
        
        $loginBody = @{
            ServerAddress = "localhost"
            ServerPort = 36013
            Username = $username
            Password = $password
        } | ConvertTo-Json
        
        $loginResponse = Invoke-RestMethod -Uri "$apiUrl/sessions/start" -Method POST -Body $loginBody -ContentType "application/json" -ErrorAction Stop
        
        if ($loginResponse -and $loginResponse.Data) {
            $sessionToken = $loginResponse.Data
        } elseif ($loginResponse -and $loginResponse.SessionToken) {
            $sessionToken = $loginResponse.SessionToken
        } elseif ($loginResponse -is [string]) {
            $sessionToken = $loginResponse
        } else {
            # Prova formato alternativo
            $sessionToken = ($loginResponse | ConvertTo-Json | ConvertFrom-Json).Data
        }
        
        if (-not $sessionToken) {
            Write-Host "[Backup Monitor] Login fallito: nessun token ricevuto" -ForegroundColor Red
            return $result
        }
        
        Write-Host "[Backup Monitor] Login Altaro OK (token: $($sessionToken.Substring(0, 8))...)" -ForegroundColor Green
        $result.altaro_connected = $true
        
    } catch {
        Write-Host "[Backup Monitor] Errore login Altaro: $($_.Exception.Message)" -ForegroundColor Red
        
        # Fallback: prova a leggere dallo Event Log
        $result = Get-BackupStatusFromEventLog $result
        return $result
    }
    
    # ---- STEP 3: Lista VM configurate con stato backup ----
    try {
        $vmsResponse = Invoke-RestMethod -Uri "$apiUrl/vms/list/$sessionToken/1" -Method GET -ErrorAction Stop
        
        $vmsList = @()
        if ($vmsResponse.Data) {
            $vmsList = $vmsResponse.Data
        } elseif ($vmsResponse -is [array]) {
            $vmsList = $vmsResponse
        }
        
        foreach ($vm in $vmsList) {
            $vmName = if ($vm.VMName) { $vm.VMName } elseif ($vm.Name) { $vm.Name } else { "Unknown" }
            $lastBackupTime = $vm.LastBackupTime
            $lastBackupStatus = $vm.LastBackupStatus
            $lastBackupSize = $vm.LastBackupSize
            $nextBackupTime = $vm.NextBackupTime
            $backupType = $vm.BackupType
            
            # Determina stato
            $status = "unknown"
            if ($lastBackupStatus -eq "Success" -or $lastBackupStatus -eq 0 -or $lastBackupStatus -eq "Completed") {
                $status = "success"
                $result.summary.backup_ok++
            } elseif ($lastBackupStatus -eq "Warning" -or $lastBackupStatus -eq 1 -or $lastBackupStatus -eq "CompletedWithWarnings") {
                $status = "warning"
                $result.summary.backup_warning++
            } elseif ($lastBackupStatus -eq "Failed" -or $lastBackupStatus -eq 2 -or $lastBackupStatus -eq "Error") {
                $status = "failed"
                $result.summary.backup_failed++
            } else {
                # Verifica se il backup e' mancante (mai eseguito o > 24h)
                if (-not $lastBackupTime) {
                    $status = "missing"
                    $result.summary.backup_missing++
                } else {
                    try {
                        $lastTime = [DateTime]::Parse($lastBackupTime)
                        if ((Get-Date) - $lastTime -gt [TimeSpan]::FromHours(24)) {
                            $status = "missing"
                            $result.summary.backup_missing++
                        } else {
                            $status = "success"
                            $result.summary.backup_ok++
                        }
                    } catch {
                        $status = "unknown"
                    }
                }
            }
            
            # Trova info Hyper-V corrispondente
            $hypervInfo = $result.hyperv_vms | Where-Object { $_.name -eq $vmName } | Select-Object -First 1
            
            $result.vms += @{
                vm_name = $vmName
                backup_status = $status
                last_backup_time = $lastBackupTime
                last_backup_size_bytes = $lastBackupSize
                next_backup_time = $nextBackupTime
                backup_type = $backupType
                vm_state = if ($hypervInfo) { $hypervInfo.state } else { "Unknown" }
                cpu_usage = if ($hypervInfo) { $hypervInfo.cpu_usage } else { $null }
                memory_mb = if ($hypervInfo) { $hypervInfo.memory_mb } else { $null }
                checkpoint_count = if ($hypervInfo) { $hypervInfo.checkpoint_count } else { 0 }
                replication_state = if ($hypervInfo) { $hypervInfo.replication_state } else { "None" }
            }
        }
        
        $result.summary.total_vms = $result.vms.Count
        Write-Host "[Backup Monitor] Altaro: $($result.vms.Count) VM configurate (OK: $($result.summary.backup_ok), Warning: $($result.summary.backup_warning), Failed: $($result.summary.backup_failed), Missing: $($result.summary.backup_missing))" -ForegroundColor Green
        
    } catch {
        Write-Host "[Backup Monitor] Errore lettura VM: $($_.Exception.Message)" -ForegroundColor Red
    }
    
    # ---- STEP 4: Chiudi sessione ----
    try {
        Invoke-RestMethod -Uri "$apiUrl/sessions/end/$sessionToken" -Method POST -ErrorAction SilentlyContinue | Out-Null
    } catch {}
    
    return $result
}


function Get-BackupStatusFromEventLog($result) {
    <#
    .SYNOPSIS
        Fallback: legge lo stato backup dall'Event Log di Windows.
        Event ID: 5000=OK, 5001=Warning, 5002=Failed
    #>
    Write-Host "[Backup Monitor] Fallback: lettura Event Log..." -ForegroundColor Yellow
    
    try {
        $events = Get-WinEvent -FilterHashtable @{
            LogName = 'Application'
            ID = 5000, 5001, 5002, 5003, 5004, 5005, 5007
            StartTime = (Get-Date).AddDays(-1)
        } -ErrorAction SilentlyContinue
        
        if ($events) {
            $vmEvents = @{}
            foreach ($evt in $events) {
                # Prova a estrarre il nome VM dal messaggio
                $vmName = "Unknown"
                if ($evt.Message -match "VM[:\s]+(.+?)[\r\n]") {
                    $vmName = $Matches[1].Trim()
                } elseif ($evt.Message -match "virtual machine[:\s]+(.+?)[\r\n]") {
                    $vmName = $Matches[1].Trim()
                }
                
                # Prendi solo l'evento piu' recente per ogni VM
                if (-not $vmEvents.ContainsKey($vmName) -or $evt.TimeCreated -gt $vmEvents[$vmName].TimeCreated) {
                    $vmEvents[$vmName] = $evt
                }
            }
            
            foreach ($kvp in $vmEvents.GetEnumerator()) {
                $status = switch ($kvp.Value.Id) {
                    5000 { "success" }
                    5001 { "warning" }
                    5002 { "failed" }
                    5005 { "success" }
                    5007 { "failed" }
                    default { "unknown" }
                }
                
                $result.vms += @{
                    vm_name = $kvp.Key
                    backup_status = $status
                    last_backup_time = $kvp.Value.TimeCreated.ToString("yyyy-MM-ddTHH:mm:ssZ")
                    last_backup_size_bytes = $null
                    next_backup_time = $null
                    backup_type = "EventLog"
                    vm_state = "Unknown"
                    cpu_usage = $null
                    memory_mb = $null
                    checkpoint_count = 0
                    replication_state = "None"
                }
                
                switch ($status) {
                    "success" { $result.summary.backup_ok++ }
                    "warning" { $result.summary.backup_warning++ }
                    "failed"  { $result.summary.backup_failed++ }
                }
            }
            $result.summary.total_vms = $result.vms.Count
            Write-Host "[Backup Monitor] EventLog: $($result.vms.Count) VM trovate" -ForegroundColor Green
        }
    } catch {
        Write-Host "[Backup Monitor] Errore lettura EventLog: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    
    return $result
}


function Send-BackupStatus($config, $backupData) {
    <#
    .SYNOPSIS
        Invia lo stato dei backup al backend NOC.
    #>
    if (-not $backupData) { return }
    
    try {
        $payload = @{
            vms = $backupData.vms
            summary = $backupData.summary
            hyperv_vms = $backupData.hyperv_vms
            altaro_connected = $backupData.altaro_connected
            hyperv_connected = $backupData.hyperv_connected
        }
        
        $json = $payload | ConvertTo-Json -Depth 5
        $response = Invoke-RestMethod -Uri "$($config.noc_url)/api/backup/process-status" -Method POST -Body $json -ContentType "application/json" -Headers @{ "X-API-Key" = $config.api_key } -ErrorAction Stop
        
        Write-Host "[Backup Monitor] Dati inviati al NOC: $($backupData.summary.total_vms) VM" -ForegroundColor Green
    } catch {
        Write-Host "[Backup Monitor] Errore invio dati: $($_.Exception.Message)" -ForegroundColor Red
    }
}
