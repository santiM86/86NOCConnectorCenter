<#
.SYNOPSIS
    86NocConnector Remote Browser (RMT) — v3.4.1 HTTP TRANSPORT
    Stream frame via POST al backend, input via long-poll GET. Zero WebSocket.

.PARAMETER NocCenterUrl  es. https://argus.86bit.it
.PARAMETER Token         JWT session dal Center
.PARAMETER DeviceUrl     URL device es https://10.100.61.35/
.PARAMETER SessionId
.PARAMETER LogFile
#>
param(
    [Parameter(Mandatory)][string]$NocCenterUrl,
    [Parameter(Mandatory)][string]$Token,
    [Parameter(Mandatory)][string]$DeviceUrl,
    [Parameter(Mandatory)][string]$SessionId,
    [string]$LogFile = ""
)

$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13

function Write-RmtLog($msg, $level = "INFO") {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$level] [RMT-$SessionId] $msg"
    Write-Host $line
    if ($LogFile) { try { Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue } catch {} }
}

Write-RmtLog "=== RMT SESSION START (HTTP transport) ==="
Write-RmtLog "DeviceUrl: $DeviceUrl"
Write-RmtLog "NOC: $NocCenterUrl"

# ============ EDGE LAUNCH ============
function Find-EdgeExe {
    $candidates = @(
        "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles (x86)\Google\Chrome\Application\chrome.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

$edgeExe = Find-EdgeExe
if (-not $edgeExe) {
    Write-RmtLog "Edge/Chrome non trovato" "ERROR"
    try { Invoke-RestMethod -Uri "$NocCenterUrl/api/console-rmt/status" -Method Post -Headers @{"X-RMT-Token"=$Token} -Body (@{type="error";msg="Edge/Chrome non installato sul PC del connector"} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 10 } catch {}
    exit 2
}
Write-RmtLog "Browser: $edgeExe"

function Get-FreePort {
    for ($i = 0; $i -lt 20; $i++) {
        $p = Get-Random -Minimum 19300 -Maximum 19999
        try {
            $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
            $l.Start(); $l.Stop(); return $p
        } catch {}
    }
    return 19300
}

$cdpPort = Get-FreePort
# v3.4.3: Edge headless quando lanciato dal servizio SYSTEM richiede user-data-dir
# in C:\Windows\Temp (non %TEMP% del user profile che per SYSTEM ha problemi ACL).
# Issue noto: https://github.com/microsoft/playwright/issues/8272
$userDataBase = "C:\Windows\Temp\86Noc_rmt"
if (-not (Test-Path $userDataBase)) { New-Item -ItemType Directory -Path $userDataBase -Force | Out-Null }
$userDataDir = Join-Path $userDataBase $SessionId
if (Test-Path $userDataDir) { Remove-Item $userDataDir -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null

$edgeArgs = @(
    "--headless=new",
    "--remote-debugging-port=$cdpPort",
    "--remote-allow-origins=*",
    # v3.4.3 — flag obbligatori per Edge come servizio SYSTEM:
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu-sandbox",
    "--disable-software-rasterizer",
    # Crash resilience
    "--disable-crash-reporter",
    "--disable-breakpad",
    "--disable-component-update",
    # TLS / cert
    "--ignore-certificate-errors",
    "--ignore-ssl-errors",
    "--allow-insecure-localhost",
    "--test-type",  # abilita --ignore-certificate-errors in new headless
    # Performance / stability
    "--disable-gpu",
    "--disable-web-security",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-features=Translate,BackForwardCache,IsolateOrigins,site-per-process,VizDisplayCompositor",
    "--window-size=1600,900",
    "--user-data-dir=`"$userDataDir`"",
    "about:blank"
)

Write-RmtLog "Avvio Edge CDP=$cdpPort UserDataDir=$userDataDir (SYSTEM-compatible flags)"
$edgeProc = Start-Process -FilePath $edgeExe -ArgumentList $edgeArgs -WindowStyle Hidden -PassThru
Write-RmtLog "Edge PID=$($edgeProc.Id)"

# Wait CDP ready (fino a 30s con log diagnostico)
$cdpReady = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$cdpPort/json/version" -TimeoutSec 2 -ErrorAction Stop
        $cdpReady = $true; break
    } catch {}
    # Check if Edge process is still alive
    if ($i -eq 10 -or $i -eq 20 -or $i -eq 40) {
        try {
            $alive = Get-Process -Id $edgeProc.Id -ErrorAction SilentlyContinue
            if (-not $alive -or $alive.HasExited) {
                Write-RmtLog "Edge PID=$($edgeProc.Id) e' morto durante l'attesa CDP" "ERROR"
                break
            }
            # Check port listening
            $listening = Get-NetTCPConnection -LocalPort $cdpPort -State Listen -ErrorAction SilentlyContinue
            if ($listening) {
                Write-RmtLog "Porta $cdpPort in listen su $($listening.LocalAddress) PID=$($listening.OwningProcess), ma CDP non risponde ancora"
            } else {
                Write-RmtLog "Porta $cdpPort NON in listen dopo $(($i+1)*500)ms (Edge PID=$($edgeProc.Id) ancora vivo)"
            }
        } catch {}
    }
}
if (-not $cdpReady) {
    # Raccogli info diagnostiche
    $diag = ""
    try {
        $alive = Get-Process -Id $edgeProc.Id -ErrorAction SilentlyContinue
        $diag += " EdgeAlive=$($null -ne $alive -and -not $alive.HasExited);"
    } catch {}
    try {
        $listening = Get-NetTCPConnection -LocalPort $cdpPort -State Listen -ErrorAction SilentlyContinue
        $diag += " PortListening=$($null -ne $listening);"
    } catch {}
    $diag += " UserDataDir=$userDataDir;"
    Write-RmtLog "CDP non pronto dopo 30s.$diag" "ERROR"
    try {
        Invoke-RestMethod -Uri "$NocCenterUrl/api/console-rmt/status" -Method Post `
            -Headers @{"X-RMT-Token"=$Token} `
            -Body (@{type="error"; msg="Edge CDP non risponde dopo 30s.$diag Probabile problema Defender ASR o servizio SYSTEM senza permessi Edge."} | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 10 | Out-Null
    } catch {}
    try { Stop-Process -Id $edgeProc.Id -Force -ErrorAction SilentlyContinue } catch {}
    exit 3
}

# Create tab at device URL
$targetInfo = $null
try {
    $encUrl = [System.Net.WebUtility]::UrlEncode($DeviceUrl)
    $targetInfo = Invoke-RestMethod -Uri "http://127.0.0.1:$cdpPort/json/new?$encUrl" -Method Put -TimeoutSec 5 -ErrorAction Stop
} catch {
    try {
        $targetInfo = Invoke-RestMethod -Uri "http://127.0.0.1:$cdpPort/json/new?$encUrl" -Method Post -TimeoutSec 5 -ErrorAction Stop
    } catch {
        Write-RmtLog "Errore /json/new: $($_.Exception.Message)" "ERROR"
        try { Stop-Process -Id $edgeProc.Id -Force } catch {}
        exit 4
    }
}
$targetWsUrl = $targetInfo.webSocketDebuggerUrl
Write-RmtLog "Target creato: $($targetInfo.id)"

# Connect CDP WebSocket (localhost only, nessuna config esterna serve)
Add-Type -AssemblyName "System.Net.Http"
Add-Type -AssemblyName "System.Net.WebSockets"
$cdpWs = New-Object System.Net.WebSockets.ClientWebSocket
$cdpWs.Options.KeepAliveInterval = [timespan]::FromSeconds(30)
$cts = New-Object System.Threading.CancellationTokenSource
try { $cdpWs.ConnectAsync([Uri]$targetWsUrl, $cts.Token).Wait(5000) } catch {
    Write-RmtLog "Errore connessione CDP WS: $($_.Exception.Message)" "ERROR"
    try { Stop-Process -Id $edgeProc.Id -Force } catch {}
    exit 5
}
Write-RmtLog "CDP WS connesso"

# ============ CDP HELPERS ============
$script:CdpMsgId = 0
function Send-Cdp($method, $params = @{}) {
    $script:CdpMsgId++
    $msg = @{ id = $script:CdpMsgId; method = $method; params = $params } | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($msg)
    $seg = New-Object System.ArraySegment[byte] (,$bytes)
    $cdpWs.SendAsync($seg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).Wait(2000)
}

Send-Cdp "Page.enable"
Send-Cdp "Runtime.enable"
Send-Cdp "Page.startScreencast" @{ format = "jpeg"; quality = 60; maxWidth = 1600; maxHeight = 900; everyNthFrame = 1 }

# Notify backend ready
try {
    Invoke-RestMethod -Uri "$NocCenterUrl/api/console-rmt/status/$Token" -Method Post `
        -Body (@{type="status"; msg="Edge pronto, streaming avviato"} | ConvertTo-Json) `
        -ContentType "application/json" -TimeoutSec 10 | Out-Null
} catch {}

# ============ SHARED STATE ============
$state = [hashtable]::Synchronized(@{
    CdpWs = $cdpWs
    Active = $true
    LastActivity = (Get-Date)
    FrameCount = 0
    InputCount = 0
    NocUrl = $NocCenterUrl
    Token = $Token
    CancelToken = $cts.Token
    SessionId = $SessionId
    LogFile = $LogFile
})

# ============ CDP READER (frames) ============
$cdpReaderScript = {
    param($state)
    $buffer = New-Object byte[] 1048576
    while ($state.Active) {
        try {
            $sb = New-Object System.Text.StringBuilder
            $msgType = $null
            do {
                $seg = New-Object System.ArraySegment[byte] (,$buffer)
                $task = $state.CdpWs.ReceiveAsync($seg, $state.CancelToken)
                $task.Wait(30000)
                $result = $task.Result
                $msgType = $result.MessageType
                if ($msgType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) { $state.Active = $false; break }
                $chunk = [Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
                [void]$sb.Append($chunk)
            } while (-not $result.EndOfMessage -and $state.Active)
            if (-not $state.Active) { break }

            $obj = $null
            try { $obj = $sb.ToString() | ConvertFrom-Json -ErrorAction Stop } catch { continue }
            if ($obj.method -eq "Page.screencastFrame") {
                $state.FrameCount++
                $state.LastActivity = Get-Date
                # ACK (REQUIRED)
                $ack = @{ id = ([guid]::NewGuid().GetHashCode() -band 0x7fffffff); method="Page.screencastFrameAck"; params=@{sessionId=$obj.params.sessionId} } | ConvertTo-Json -Compress
                $ackBytes = [Text.Encoding]::UTF8.GetBytes($ack)
                $ackSeg = New-Object System.ArraySegment[byte] (,$ackBytes)
                $state.CdpWs.SendAsync($ackSeg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(1000)
                # POST frame al backend (header-auth)
                try {
                    $payload = @{
                        data = $obj.params.data
                        ts = [int][double]::Parse(((Get-Date -UFormat %s)))
                        w = $obj.params.metadata.deviceWidth
                        h = $obj.params.metadata.deviceHeight
                    } | ConvertTo-Json -Compress
                    Invoke-RestMethod -Uri "$($state.NocUrl)/api/console-rmt/frame" -Method Post -Headers @{"X-RMT-Token"=$state.Token} -Body $payload -ContentType "application/json" -TimeoutSec 5 | Out-Null
                } catch {
                    # network blip - non fatale, continua
                }
            }
        } catch { $state.Active = $false; break }
    }
}

# ============ INPUT POLLER (long-poll backend) ============
$inputPollerScript = {
    param($state)
    while ($state.Active) {
        try {
            $resp = Invoke-RestMethod -Uri "$($state.NocUrl)/api/console-rmt/poll-inputs" -Method Get -Headers @{"X-RMT-Token"=$state.Token} -TimeoutSec 30
            if ($resp.events -and $resp.events.Count -gt 0) {
                $state.LastActivity = Get-Date
                foreach ($cmd in $resp.events) {
                    $state.InputCount++
                    switch ($cmd.type) {
                        "mouse" {
                            $cdpType = switch ($cmd.event) { "down" { "mousePressed" } "up" { "mouseReleased" } "move" { "mouseMoved" } default { "mouseMoved" } }
                            $btn = if ($cmd.button) { $cmd.button } else { "none" }
                            $params = @{ type=$cdpType; x=[int]$cmd.x; y=[int]$cmd.y; button=$btn; clickCount=1 }
                            $msg = @{ id=([guid]::NewGuid().GetHashCode() -band 0x7fffffff); method="Input.dispatchMouseEvent"; params=$params } | ConvertTo-Json -Compress
                            $b = [Text.Encoding]::UTF8.GetBytes($msg)
                            $sg = New-Object System.ArraySegment[byte] (,$b)
                            $state.CdpWs.SendAsync($sg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(500)
                        }
                        "key" {
                            $cdpType = if ($cmd.event -eq "down") { "keyDown" } else { "keyUp" }
                            $modifiers = 0
                            if ($cmd.mods.alt) { $modifiers += 1 }
                            if ($cmd.mods.ctrl) { $modifiers += 2 }
                            if ($cmd.mods.meta) { $modifiers += 4 }
                            if ($cmd.mods.shift) { $modifiers += 8 }
                            $params = @{ type=$cdpType; key=$cmd.key; code=$cmd.code; modifiers=$modifiers }
                            if ($cdpType -eq "keyDown" -and $cmd.key.Length -eq 1) { $params.text = $cmd.key }
                            $msg = @{ id=([guid]::NewGuid().GetHashCode() -band 0x7fffffff); method="Input.dispatchKeyEvent"; params=$params } | ConvertTo-Json -Compress
                            $b = [Text.Encoding]::UTF8.GetBytes($msg)
                            $sg = New-Object System.ArraySegment[byte] (,$b)
                            $state.CdpWs.SendAsync($sg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(500)
                        }
                        "scroll" {
                            $params = @{ type="mouseWheel"; x=[int]($cmd.x -or 400); y=[int]($cmd.y -or 400); deltaX=[double]($cmd.dx -or 0); deltaY=[double]($cmd.dy -or 0) }
                            $msg = @{ id=([guid]::NewGuid().GetHashCode() -band 0x7fffffff); method="Input.dispatchMouseEvent"; params=$params } | ConvertTo-Json -Compress
                            $b = [Text.Encoding]::UTF8.GetBytes($msg)
                            $sg = New-Object System.ArraySegment[byte] (,$b)
                            $state.CdpWs.SendAsync($sg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(500)
                        }
                        "close" { $state.Active = $false }
                    }
                }
            }
        } catch {
            # timeout normale dopo 25s, riloopa. Errori 410/401 = sessione scaduta → termina
            if ($_.Exception.Response -and $_.Exception.Response.StatusCode -in @(410, 401)) {
                $state.Active = $false; break
            }
            Start-Sleep -Milliseconds 500
        }
    }
}

# Launch via runspaces
$pool = [runspacefactory]::CreateRunspacePool(1, 3)
$pool.Open()
$ps1 = [powershell]::Create(); $ps1.RunspacePool = $pool
[void]$ps1.AddScript($cdpReaderScript).AddArgument($state); $h1 = $ps1.BeginInvoke()
$ps2 = [powershell]::Create(); $ps2.RunspacePool = $pool
[void]$ps2.AddScript($inputPollerScript).AddArgument($state); $h2 = $ps2.BeginInvoke()

Write-RmtLog "Loops avviati"

$start = Get-Date
while ($state.Active) {
    Start-Sleep -Seconds 10
    $idle = (Get-Date) - $state.LastActivity
    $elapsed = (Get-Date) - $start
    if ($idle.TotalMinutes -ge 30) { Write-RmtLog "Idle 30min, stop" "WARN"; $state.Active = $false; break }
    if ($elapsed.TotalHours -ge 2) { Write-RmtLog "Max 2h, stop" "WARN"; $state.Active = $false; break }
    Write-RmtLog ("hb - frames: {0}, input: {1}, idle: {2:N0}s" -f $state.FrameCount, $state.InputCount, $idle.TotalSeconds) "DEBUG"
}

# Cleanup
Write-RmtLog "Shutdown"
$cts.Cancel()
try { $ps1.Stop() } catch {}
try { $ps2.Stop() } catch {}
try { $pool.Close() } catch {}
try { $cdpWs.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "end", [System.Threading.CancellationToken]::None).Wait(2000) } catch {}
try { Stop-Process -Id $edgeProc.Id -Force -ErrorAction SilentlyContinue } catch {}
Start-Sleep 1
try { Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%86Noc_rmt_$SessionId%'" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } catch {}
try { Remove-Item $userDataDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
# Cleanup vecchie dir user-data di sessioni precedenti (>1h)
try {
    $base = "C:\Windows\Temp\86Noc_rmt"
    if (Test-Path $base) {
        Get-ChildItem $base -Directory -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-1) } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
} catch {}
try {
    Invoke-RestMethod -Uri "$NocCenterUrl/api/console-rmt/status" -Method Post `
        -Headers @{"X-RMT-Token"=$Token} `
        -Body (@{type="closed"; msg="Sessione terminata"} | ConvertTo-Json) `
        -ContentType "application/json" -TimeoutSec 5 | Out-Null
} catch {}
Write-RmtLog "=== RMT END frames=$($state.FrameCount) input=$($state.InputCount) ==="
exit 0
