<#
.SYNOPSIS
    86NocConnector Remote Browser (RMT) — v3.4.0
    Lancia Microsoft Edge in modalità headless, si connette via Chrome DevTools Protocol (CDP),
    fa screencast JPEG al backend ARGUS e processa eventi mouse/tastiera dal Center.

.DESCRIPTION
    Flusso:
    1. Individua msedge.exe (preferito, già presente su Windows 10/11) o chrome.exe come fallback.
    2. Lancia Edge in --headless=new con --remote-debugging-port=<random>, ignore-cert-errors,
       user-data-dir isolato, window-size 1600x900.
    3. Interroga http://localhost:<port>/json/version per discover webSocketDebuggerUrl del browser.
    4. Crea una nuova tab via PUT /json/new?<deviceUrl>.
    5. Apre due WebSocket:
       a) CDP_WS → localhost:<port>/devtools/page/<targetId>
       b) ARGUS_WS → wss://<noc-center>/api/console-rmt/connector-ws/<token>
    6. Invia Page.enable, Runtime.enable, Page.startScreencast (quality=60, maxWidth=1600).
    7. Loop bidirezionale:
       - Da CDP Page.screencastFrame → {type:"frame", data:<b64>, ts} verso ARGUS_WS.
       - Da ARGUS_WS {type:"mouse|key|scroll|close"} → traduce in CDP Input.dispatchMouseEvent / Input.dispatchKeyEvent.
    8. Auto-termina Edge quando ARGUS_WS si chiude o dopo 30 min di inattività.
    9. Cleanup: kill Edge process tree + delete user-data-dir temp.

.PARAMETER NocCenterUrl
.PARAMETER Token         JWT session da /api/console-rmt/session
.PARAMETER DeviceUrl     URL completo del device (es https://10.100.61.35/)
.PARAMETER SessionId     ID sessione per log
.PARAMETER LogFile       Path log file
#>
param(
    [Parameter(Mandatory)][string]$NocCenterUrl,
    [Parameter(Mandatory)][string]$Token,
    [Parameter(Mandatory)][string]$DeviceUrl,
    [Parameter(Mandatory)][string]$SessionId,
    [string]$LogFile = ""
)

$ErrorActionPreference = "Continue"

# ============================== LOGGING ==============================
function Write-RmtLog($msg, $level = "INFO") {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$level] [RMT-$SessionId] $msg"
    Write-Host $line
    if ($LogFile) {
        try { Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue } catch {}
    }
}

Write-RmtLog "=== RMT SESSION START ==="
Write-RmtLog "DeviceUrl: $DeviceUrl"
Write-RmtLog "NOC: $NocCenterUrl"

# ============================== EDGE LAUNCH ==============================
function Find-EdgeExe {
    $candidates = @(
        "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles (x86)\Google\Chrome\Application\chrome.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

$edgeExe = Find-EdgeExe
if (-not $edgeExe) {
    Write-RmtLog "ERRORE: Microsoft Edge (o Chrome) non trovato. Installa Edge o Chrome sul PC." "ERROR"
    exit 2
}
Write-RmtLog "Browser trovato: $edgeExe"

# Pick a random free port
function Get-FreePort {
    for ($i = 0; $i -lt 20; $i++) {
        $p = Get-Random -Minimum 19300 -Maximum 19999
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
            $listener.Start(); $listener.Stop()
            return $p
        } catch {}
    }
    return 19300
}

$cdpPort = Get-FreePort
$userDataDir = Join-Path $env:TEMP "86Noc_rmt_$SessionId"
if (Test-Path $userDataDir) { Remove-Item $userDataDir -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null

$edgeArgs = @(
    "--headless=new",
    "--remote-debugging-port=$cdpPort",
    "--remote-allow-origins=*",
    "--ignore-certificate-errors",
    "--ignore-ssl-errors",
    "--allow-insecure-localhost",
    "--disable-gpu",
    "--disable-web-security",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-features=Translate,BackForwardCache,IsolateOrigins,site-per-process",
    "--window-size=1600,900",
    "--user-data-dir=`"$userDataDir`"",
    "about:blank"
)

Write-RmtLog "Avvio Edge su porta CDP=$cdpPort, UserData=$userDataDir"
$edgeProc = Start-Process -FilePath $edgeExe -ArgumentList $edgeArgs -WindowStyle Hidden -PassThru
Write-RmtLog "Edge PID=$($edgeProc.Id)"

# Wait CDP ready
$cdpReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$cdpPort/json/version" -TimeoutSec 2 -ErrorAction Stop
        $cdpReady = $true; break
    } catch {}
}
if (-not $cdpReady) {
    Write-RmtLog "ERRORE: Edge CDP non pronto entro 15s" "ERROR"
    try { Stop-Process -Id $edgeProc.Id -Force -ErrorAction SilentlyContinue } catch {}
    exit 3
}
Write-RmtLog "CDP pronto"

# Create new tab pointing to device URL
$targetInfo = $null
try {
    # Open a fresh tab at DeviceUrl via /json/new
    $encodedUrl = [System.Net.WebUtility]::UrlEncode($DeviceUrl)
    $targetInfo = Invoke-RestMethod -Uri "http://127.0.0.1:$cdpPort/json/new?$encodedUrl" -Method Put -TimeoutSec 5 -ErrorAction Stop
} catch {
    # Some Edge versions need POST
    try {
        $targetInfo = Invoke-RestMethod -Uri "http://127.0.0.1:$cdpPort/json/new?$encodedUrl" -Method Post -TimeoutSec 5 -ErrorAction Stop
    } catch {
        Write-RmtLog "ERRORE /json/new: $($_.Exception.Message)" "ERROR"
        try { Stop-Process -Id $edgeProc.Id -Force } catch {}
        exit 4
    }
}
$targetWsUrl = $targetInfo.webSocketDebuggerUrl
$targetId = $targetInfo.id
Write-RmtLog "Target creato id=$targetId, WS=$targetWsUrl"

# ============================== WEBSOCKET CLIENTS ==============================
Add-Type -AssemblyName "System.Net.Http"
Add-Type -AssemblyName "System.Net.WebSockets"

function New-WSClient {
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $ws.Options.KeepAliveInterval = [timespan]::FromSeconds(30)
    return $ws
}

$cdpWs = New-WSClient
$argusWs = New-WSClient
# Accept self-signed for ARGUS WSS (preview env)
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

$cts = New-Object System.Threading.CancellationTokenSource
$cancelToken = $cts.Token

try {
    Write-RmtLog "Connessione CDP WS..."
    $cdpWs.ConnectAsync([Uri]$targetWsUrl, $cancelToken).Wait(5000)

    $argusWsUrl = $NocCenterUrl.Replace("https://", "wss://").Replace("http://", "ws://") + "/api/console-rmt/connector-ws/$Token"
    Write-RmtLog "Connessione ARGUS WS: $argusWsUrl"
    $argusWs.ConnectAsync([Uri]$argusWsUrl, $cancelToken).Wait(10000)
} catch {
    Write-RmtLog "ERRORE connessione WS: $($_.Exception.Message)" "ERROR"
    try { Stop-Process -Id $edgeProc.Id -Force } catch {}
    exit 5
}

Write-RmtLog "Entrambe le WS connesse"

# ============================== CDP HELPERS ==============================
$script:CdpMsgId = 0
function Send-CdpMessage($ws, $method, $params = @{}) {
    $script:CdpMsgId++
    $msg = @{
        id = $script:CdpMsgId
        method = $method
        params = $params
    } | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($msg)
    $seg = New-Object System.ArraySegment[byte] (,$bytes)
    $ws.SendAsync($seg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cancelToken).Wait(2000)
}

function Send-ArgusJson($ws, $obj) {
    $msg = $obj | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($msg)
    $seg = New-Object System.ArraySegment[byte] (,$bytes)
    $ws.SendAsync($seg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $cancelToken).Wait(2000)
}

# Enable Page + Runtime + Input
Send-CdpMessage $cdpWs "Page.enable"
Send-CdpMessage $cdpWs "Runtime.enable"
Send-CdpMessage $cdpWs "Network.enable"
Send-CdpMessage $cdpWs "Page.startScreencast" @{
    format = "jpeg"
    quality = 60
    maxWidth = 1600
    maxHeight = 900
    everyNthFrame = 1
}

Send-ArgusJson $argusWs @{ type = "ready"; msg = "Edge pronto, streaming attivo" }
Write-RmtLog "Screencast avviato"

# ============================== MAIN LOOPS (2 thread) ==============================
# Thread 1: CDP → ARGUS (screencast frames)
# Thread 2: ARGUS → CDP (input events)
# Implementati come jobs (runspace) per evitare blocking

$sharedState = [hashtable]::Synchronized(@{
    CdpWs = $cdpWs
    ArgusWs = $argusWs
    Active = $true
    LastActivity = (Get-Date)
    EdgePid = $edgeProc.Id
    CancelToken = $cancelToken
    FrameCount = 0
    InputCount = 0
    LogFile = $LogFile
    SessionId = $SessionId
})

# --- Loop CDP → ARGUS ---
$cdpReaderScript = {
    param($state)
    $buffer = New-Object byte[] 1048576  # 1 MB
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
                if ($msgType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                    $state.Active = $false; break
                }
                $chunk = [Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
                [void]$sb.Append($chunk)
            } while (-not $result.EndOfMessage -and $state.Active)

            if (-not $state.Active) { break }
            $text = $sb.ToString()
            $obj = $null
            try { $obj = $text | ConvertFrom-Json -ErrorAction Stop } catch { continue }

            if ($obj.method -eq "Page.screencastFrame") {
                $state.FrameCount++
                $state.LastActivity = Get-Date
                # ACK back to CDP (REQUIRED else screencast stops after few frames)
                $ackMsg = @{
                    id = ([guid]::NewGuid().GetHashCode() -band 0x7fffffff)
                    method = "Page.screencastFrameAck"
                    params = @{ sessionId = $obj.params.sessionId }
                } | ConvertTo-Json -Compress
                $ackBytes = [Text.Encoding]::UTF8.GetBytes($ackMsg)
                $ackSeg = New-Object System.ArraySegment[byte] (,$ackBytes)
                $state.CdpWs.SendAsync($ackSeg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(1000)
                # Forward frame to ARGUS
                $frameMsg = @{
                    type = "frame"
                    data = $obj.params.data
                    ts = [int][double]::Parse(((Get-Date -UFormat %s)))
                    w = $obj.params.metadata.deviceWidth
                    h = $obj.params.metadata.deviceHeight
                } | ConvertTo-Json -Compress
                $frameBytes = [Text.Encoding]::UTF8.GetBytes($frameMsg)
                $frameSeg = New-Object System.ArraySegment[byte] (,$frameBytes)
                try {
                    $state.ArgusWs.SendAsync($frameSeg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(2000)
                } catch {
                    $state.Active = $false; break
                }
            }
        } catch {
            $state.Active = $false; break
        }
    }
}

# --- Loop ARGUS → CDP ---
$argusReaderScript = {
    param($state)
    $buffer = New-Object byte[] 65536
    while ($state.Active) {
        try {
            $sb = New-Object System.Text.StringBuilder
            do {
                $seg = New-Object System.ArraySegment[byte] (,$buffer)
                $task = $state.ArgusWs.ReceiveAsync($seg, $state.CancelToken)
                $task.Wait(60000)
                $result = $task.Result
                if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                    $state.Active = $false; break
                }
                $chunk = [Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
                [void]$sb.Append($chunk)
            } while (-not $result.EndOfMessage -and $state.Active)
            if (-not $state.Active) { break }

            $text = $sb.ToString()
            $cmd = $null
            try { $cmd = $text | ConvertFrom-Json -ErrorAction Stop } catch { continue }
            $state.LastActivity = Get-Date
            $state.InputCount++

            switch ($cmd.type) {
                "mouse" {
                    $cdpType = switch ($cmd.event) { "down" { "mousePressed" } "up" { "mouseReleased" } "move" { "mouseMoved" } default { "mouseMoved" } }
                    $btn = if ($cmd.button) { $cmd.button } else { "none" }
                    $params = @{
                        type = $cdpType
                        x = [int]$cmd.x
                        y = [int]$cmd.y
                        button = $btn
                        clickCount = 1
                    }
                    $mMsg = @{ id = ([guid]::NewGuid().GetHashCode() -band 0x7fffffff); method = "Input.dispatchMouseEvent"; params = $params } | ConvertTo-Json -Compress
                    $mBytes = [Text.Encoding]::UTF8.GetBytes($mMsg)
                    $mSeg = New-Object System.ArraySegment[byte] (,$mBytes)
                    $state.CdpWs.SendAsync($mSeg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(500)
                }
                "key" {
                    $cdpType = if ($cmd.event -eq "down") { "keyDown" } else { "keyUp" }
                    $modifiers = 0
                    if ($cmd.mods.alt) { $modifiers += 1 }
                    if ($cmd.mods.ctrl) { $modifiers += 2 }
                    if ($cmd.mods.meta) { $modifiers += 4 }
                    if ($cmd.mods.shift) { $modifiers += 8 }
                    $params = @{
                        type = $cdpType
                        key = $cmd.key
                        code = $cmd.code
                        modifiers = $modifiers
                    }
                    # For printable keys on keyDown, also send char event
                    if ($cdpType -eq "keyDown" -and $cmd.key.Length -eq 1) {
                        $params.text = $cmd.key
                    }
                    $kMsg = @{ id = ([guid]::NewGuid().GetHashCode() -band 0x7fffffff); method = "Input.dispatchKeyEvent"; params = $params } | ConvertTo-Json -Compress
                    $kBytes = [Text.Encoding]::UTF8.GetBytes($kMsg)
                    $kSeg = New-Object System.ArraySegment[byte] (,$kBytes)
                    $state.CdpWs.SendAsync($kSeg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(500)
                }
                "scroll" {
                    $wMsg = @{
                        id = ([guid]::NewGuid().GetHashCode() -band 0x7fffffff)
                        method = "Input.dispatchMouseEvent"
                        params = @{
                            type = "mouseWheel"
                            x = [int]($cmd.x -or 400)
                            y = [int]($cmd.y -or 400)
                            deltaX = [double]($cmd.dx -or 0)
                            deltaY = [double]($cmd.dy -or 0)
                        }
                    } | ConvertTo-Json -Compress
                    $wBytes = [Text.Encoding]::UTF8.GetBytes($wMsg)
                    $wSeg = New-Object System.ArraySegment[byte] (,$wBytes)
                    $state.CdpWs.SendAsync($wSeg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $state.CancelToken).Wait(500)
                }
                "close" {
                    $state.Active = $false
                }
            }
        } catch {
            $state.Active = $false; break
        }
    }
}

# Launch both loops via Runspace
$runspacePool = [runspacefactory]::CreateRunspacePool(1, 4)
$runspacePool.Open()

$cdpPs = [powershell]::Create()
$cdpPs.RunspacePool = $runspacePool
[void]$cdpPs.AddScript($cdpReaderScript).AddArgument($sharedState)
$cdpHandle = $cdpPs.BeginInvoke()

$argusPs = [powershell]::Create()
$argusPs.RunspacePool = $runspacePool
[void]$argusPs.AddScript($argusReaderScript).AddArgument($sharedState)
$argusHandle = $argusPs.BeginInvoke()

Write-RmtLog "Loops avviati (CDP+ARGUS readers)"

# Main: watchdog inattività 30 min + status
$startTime = Get-Date
while ($sharedState.Active) {
    Start-Sleep -Seconds 10
    $idle = (Get-Date) - $sharedState.LastActivity
    $elapsed = (Get-Date) - $startTime
    if ($idle.TotalMinutes -ge 30) {
        Write-RmtLog "Inattività >30 min, termino sessione" "WARN"
        $sharedState.Active = $false
        break
    }
    if ($elapsed.TotalHours -ge 2) {
        Write-RmtLog "Sessione oltre 2 ore, termino per sicurezza" "WARN"
        $sharedState.Active = $false
        break
    }
    Write-RmtLog ("heartbeat - frames: {0}, input: {1}, idle: {2:N0}s" -f $sharedState.FrameCount, $sharedState.InputCount, $idle.TotalSeconds) "DEBUG"
}

# ============================== CLEANUP ==============================
Write-RmtLog "Shutdown..."
$cts.Cancel()
try { $cdpPs.Stop() } catch {}
try { $argusPs.Stop() } catch {}
try { $runspacePool.Close() } catch {}
try { $cdpWs.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "end", [System.Threading.CancellationToken]::None).Wait(2000) } catch {}
try { $argusWs.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "end", [System.Threading.CancellationToken]::None).Wait(2000) } catch {}
try { Stop-Process -Id $edgeProc.Id -Force -ErrorAction SilentlyContinue } catch {}
Start-Sleep 1
# Kill orphan Edge children
try {
    Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%86Noc_rmt_$SessionId%'" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}
try { Remove-Item $userDataDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
Write-RmtLog "=== RMT SESSION END frames=$($sharedState.FrameCount) input=$($sharedState.InputCount) ==="
exit 0
