# ============================================================================
# bootstrap_to_v350_helper.ps1
# Chiamato da bootstrap_to_v350.cmd per operazioni complesse (crea Scheduled Task con XML)
# ============================================================================
param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [Parameter(Mandatory=$true)][string]$UpdateScript
)

$ErrorActionPreference = "Stop"

$fullTaskName = "\86BIT\ArgusConnectorUpdater"

# Rimuovi task precedenti
& schtasks.exe /Delete /TN $fullTaskName /F 2>&1 | Out-Null
& schtasks.exe /Delete /TN "\86NocConnector\UpdateChecker" /F 2>&1 | Out-Null

# XML task completo (tutte le safety features)
$taskXml = @"
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
      <Arguments>-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$UpdateScript" -InstallDir "$InstallDir"</Arguments>
    </Exec>
  </Actions>
</Task>
"@

$tmpXml = Join-Path $env:TEMP "argus_updater_bootstrap.xml"
[System.IO.File]::WriteAllText($tmpXml, $taskXml, [System.Text.Encoding]::Unicode)

$result = & schtasks.exe /Create /TN $fullTaskName /XML $tmpXml /F 2>&1
$exitCode = $LASTEXITCODE
Remove-Item $tmpXml -Force -ErrorAction SilentlyContinue

if ($exitCode -eq 0) {
    Write-Host "OK - Scheduled Task creato: $fullTaskName"
    exit 0
} else {
    Write-Host "ERROR - schtasks /Create /XML fallito (exit $exitCode): $result"
    # Fallback /TR method
    $escPs = $UpdateScript -replace '"', '\"'
    $escBd = $InstallDir -replace '"', '\"'
    $taskArgs = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \`"$escPs\`" -InstallDir \`"$escBd\`""
    $result2 = & schtasks.exe /Create /TN $fullTaskName /SC MINUTE /MO 5 /TR $taskArgs /RU "SYSTEM" /RL HIGHEST /F 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK - Scheduled Task creato con fallback method"
        exit 0
    } else {
        Write-Host "ERROR - entrambi i metodi falliti: $result2"
        exit 1
    }
}
