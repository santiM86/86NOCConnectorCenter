# ============================================================================
# bootstrap_to_v350_helper.ps1
# Chiamato da bootstrap_to_v350.cmd per operazioni complesse (crea Scheduled Task con XML)
# ============================================================================
param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [Parameter(Mandatory=$true)][string]$UpdateScript
)

$ErrorActionPreference = "Stop"

# ============================================================================
# A) REGISTRY ENTRY per "Programmi e Funzionalita'" (64-bit visibility)
# ============================================================================
try {
    Write-Host "Step A: Registry Uninstall entry (x64 visible)..."
    $regPath = "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\86BIT_ArgusCenter_Connector"
    $version = "3.5.2"
    $versionJsonPath = Join-Path $InstallDir "version.json"
    if (Test-Path $versionJsonPath) {
        try {
            $vj = Get-Content $versionJsonPath -Raw | ConvertFrom-Json
            if ($vj.version) { $version = $vj.version }
        } catch {}
    }
    $uninstallBat = Join-Path $InstallDir "uninstall.bat"
    $iconPath = Join-Path $InstallDir "src\86bit_logo.ico"
    # Clean both views
    & reg delete $regPath /f /reg:32 2>$null | Out-Null
    & reg delete $regPath /f /reg:64 2>$null | Out-Null
    # Write in x64 view
    & reg add $regPath /v "DisplayName" /t REG_SZ /d "86BIT ARGUS Center Connector" /f /reg:64 | Out-Null
    & reg add $regPath /v "DisplayVersion" /t REG_SZ /d "$version" /f /reg:64 | Out-Null
    & reg add $regPath /v "Publisher" /t REG_SZ /d "86BIT srl Unipersonale" /f /reg:64 | Out-Null
    & reg add $regPath /v "URLInfoAbout" /t REG_SZ /d "https://www.86bit.it" /f /reg:64 | Out-Null
    & reg add $regPath /v "Contact" /t REG_SZ /d "info@86bit.it" /f /reg:64 | Out-Null
    & reg add $regPath /v "UninstallString" /t REG_SZ /d "`"$uninstallBat`"" /f /reg:64 | Out-Null
    & reg add $regPath /v "InstallLocation" /t REG_SZ /d "$InstallDir" /f /reg:64 | Out-Null
    if (Test-Path $iconPath) {
        & reg add $regPath /v "DisplayIcon" /t REG_SZ /d "$iconPath" /f /reg:64 | Out-Null
    }
    & reg add $regPath /v "NoModify" /t REG_DWORD /d 1 /f /reg:64 | Out-Null
    & reg add $regPath /v "NoRepair" /t REG_DWORD /d 1 /f /reg:64 | Out-Null
    Write-Host "  OK - Registry entry scritta in x64 view"
} catch {
    Write-Host "  WARN - Registry: $($_.Exception.Message)"
}

# ============================================================================
# B) MENU START Shortcuts
# ============================================================================
try {
    Write-Host "Step B: Menu Start shortcuts..."
    $startMenuDir = Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86BIT ArgusCenter"
    if (-not (Test-Path $startMenuDir)) {
        New-Item -ItemType Directory -Path $startMenuDir -Force | Out-Null
        Start-Sleep -Milliseconds 400
    }
    if (-not (Test-Path $startMenuDir)) { throw "Cartella non creata: $startMenuDir" }
    
    # Clean old folders
    Remove-Item -Path (Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86NocConnector") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path ([Environment]::GetFolderPath("CommonStartMenu")) "Programs\86BIT Connector") -Recurse -Force -ErrorAction SilentlyContinue
    
    $iconPath = Join-Path $InstallDir "src\86bit_logo.ico"
    $iconLocation = if (Test-Path $iconPath) { "$iconPath,0" } else { "shell32.dll,13" }
    $batPath = Join-Path $InstallDir "86NocConnector.bat"
    $uninstallBat = Join-Path $InstallDir "uninstall.bat"
    $diagScript = Join-Path $InstallDir "diagnostica_connessione.ps1"
    $logDir = Join-Path $env:ProgramData "86NocConnector\logs"
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

    $shell = New-Object -ComObject WScript.Shell
    
    function New-Shortcut {
        param($Path, $Target, $Args = "", $WorkDir = "", $Desc, $Icon)
        try {
            $sc = $shell.CreateShortcut($Path)
            $sc.TargetPath = $Target
            if ($Args) { $sc.Arguments = $Args }
            if ($WorkDir -and (Test-Path $WorkDir)) { $sc.WorkingDirectory = $WorkDir }
            $sc.Description = $Desc
            if ($Icon) { $sc.IconLocation = $Icon }
            $sc.Save()
            return $true
        } catch { return $false }
    }
    
    $count = 0
    # Shortcut 1: Avvia connector
    if (Test-Path $batPath) {
        if (New-Shortcut "$startMenuDir\ARGUS Center Connector.lnk" $batPath "" $InstallDir "Avvia ARGUS Center Connector" $iconLocation) { $count++ }
    } else {
        # Fallback: powershell direct
        $connectorScript = Join-Path $InstallDir "src\connector.ps1"
        if (Test-Path $connectorScript) {
            if (New-Shortcut "$startMenuDir\ARGUS Center Connector.lnk" "powershell.exe" "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$connectorScript`"" $InstallDir "Avvia ARGUS Center Connector" $iconLocation) { $count++ }
        }
    }
    # Shortcut 2: Diagnostica
    if (Test-Path $diagScript) {
        if (New-Shortcut "$startMenuDir\Diagnostica Connessione.lnk" "powershell.exe" "-ExecutionPolicy Bypass -File `"$diagScript`"" $InstallDir "Diagnostica connessione ARGUS Center" $iconLocation) { $count++ }
    }
    # Shortcut 3: Disinstalla
    if (Test-Path $uninstallBat) {
        if (New-Shortcut "$startMenuDir\Disinstalla ARGUS Connector.lnk" $uninstallBat "" $InstallDir "Disinstalla ARGUS Center Connector" $iconLocation) { $count++ }
    }
    # Shortcut 4: Log folder
    if (New-Shortcut "$startMenuDir\Apri Cartella Log.lnk" "explorer.exe" $logDir "" "Apri cartella log connettore" $iconLocation) { $count++ }
    
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
    Write-Host "  OK - $count shortcut creati in $startMenuDir"
} catch {
    Write-Host "  WARN - Shortcut: $($_.Exception.Message)"
}

# ============================================================================
# C) SCHEDULED TASK (Microsoft-native auto-update)
# ============================================================================
Write-Host "Step C: Scheduled Task..."
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
    Write-Host "  OK - Scheduled Task creato: $fullTaskName"
} else {
    Write-Host "  Fallback /TR method..."
    $escPs = $UpdateScript -replace '"', '\"'
    $escBd = $InstallDir -replace '"', '\"'
    $taskArgs = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \`"$escPs\`" -InstallDir \`"$escBd\`""
    $result2 = & schtasks.exe /Create /TN $fullTaskName /SC MINUTE /MO 5 /TR $taskArgs /RU "SYSTEM" /RL HIGHEST /F 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK - Scheduled Task creato con fallback"
    } else {
        Write-Host "  ERROR - entrambi i metodi falliti: $result2"
        exit 1
    }
}

Write-Host ""
Write-Host "=================================================="
Write-Host "  Bootstrap OK - Registry + Menu Start + Task"
Write-Host "=================================================="
exit 0
