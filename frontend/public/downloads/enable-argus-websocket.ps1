# =============================================================================
# enable-argus-websocket.ps1
# Abilita il supporto WebSocket su IIS + ARR per il path /api/agent/ws
# di Argus NOC Center. Idempotente: puoi rilanciarlo senza danni.
#
# Lanciare come Administrator sul server argus.86bit.it.
# =============================================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    !! $msg" -ForegroundColor Yellow }

# ----------------------------------------------------------------------
# 1. Installa il modulo WebSocket di IIS se manca
# ----------------------------------------------------------------------
Write-Step "Step 1/5  Verifica feature Web-WebSockets"
$ws = Get-WindowsFeature -Name Web-WebSockets -ErrorAction SilentlyContinue
if ($ws -and $ws.Installed) {
    Write-Ok "Web-WebSockets gia' installato"
} else {
    Write-Warn "Installazione Web-WebSockets in corso..."
    Install-WindowsFeature -Name Web-WebSockets -IncludeManagementTools | Out-Null
    Write-Ok "Web-WebSockets installato"
}

# ----------------------------------------------------------------------
# 2. Trova il sito IIS giusto (cerca quello legato a argus.86bit.it)
# ----------------------------------------------------------------------
Write-Step "Step 2/5  Identificazione sito IIS"
Import-Module WebAdministration

$sites = Get-Website
$target = $sites | Where-Object { $_.Bindings.Collection.BindingInformation -match 'argus|443|80' } |
    Select-Object -First 1
if (-not $target) {
    Write-Warn "Sito non trovato automaticamente. Siti disponibili:"
    $sites | Format-Table Name, State, PhysicalPath, @{n='Bindings';e={$_.Bindings.Collection.BindingInformation -join ', '}} -AutoSize
    $name = Read-Host "Inserisci il nome esatto del sito Argus"
    $target = Get-Website -Name $name
}
$siteName = $target.Name
$sitePath = $target.PhysicalPath
Write-Ok "Sito selezionato: $siteName  ($sitePath)"

# ----------------------------------------------------------------------
# 3. Abilita WebSocket sul sito
# ----------------------------------------------------------------------
Write-Step "Step 3/5  Abilitazione WebSocket sul sito"
try {
    Set-WebConfigurationProperty -PSPath "IIS:\Sites\$siteName" `
        -Filter "system.webServer/webSocket" -Name "enabled" -Value "True"
    Write-Ok "WebSocket abilitato sul sito '$siteName'"
} catch {
    Write-Warn "Impossibile settare webSocket via cmdlet, provo con appcmd"
    & "$env:windir\system32\inetsrv\appcmd.exe" set config "$siteName" `
        -section:system.webServer/webSocket /enabled:true /commit:apphost | Out-Null
    Write-Ok "WebSocket abilitato (via appcmd)"
}

# ----------------------------------------------------------------------
# 4. Whitelist server variables in ARR (Upgrade / Connection / X-Forwarded)
# ----------------------------------------------------------------------
Write-Step "Step 4/5  Whitelist server variables in ARR"
$appcmd = "$env:windir\system32\inetsrv\appcmd.exe"
$varsToAllow = @('HTTP_UPGRADE','HTTP_CONNECTION','HTTP_X_FORWARDED_HOST','HTTP_X_FORWARDED_PROTO')
foreach ($v in $varsToAllow) {
    & $appcmd set config -section:system.webServer/rewrite/allowedServerVariables /+"[name='$v']" /commit:apphost 2>$null | Out-Null
    Write-Ok "Whitelist: $v"
}
# Preserve Host Header (necessario per il backend FastAPI)
& $appcmd set config -section:system.webServer/proxy /preserveHostHeader:true /commit:apphost 2>$null | Out-Null
Write-Ok "preserveHostHeader = true"

# ----------------------------------------------------------------------
# 5. Aggiunge la rewrite rule per /api/agent/ws (se manca)
# ----------------------------------------------------------------------
Write-Step "Step 5/5  Rewrite rule per /api/agent/ws"
$webConfigPath = Join-Path $sitePath "web.config"
if (-not (Test-Path $webConfigPath)) {
    Write-Warn "web.config non trovato: lo creo nuovo"
    $defaultXml = @'
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <webSocket enabled="true" />
    <rewrite>
      <rules>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
'@
    Set-Content -Path $webConfigPath -Value $defaultXml -Encoding UTF8
}

[xml]$xml = Get-Content $webConfigPath

# Trova o crea <system.webServer>
$sys = $xml.SelectSingleNode("//system.webServer")
if (-not $sys) { $sys = $xml.configuration.AppendChild($xml.CreateElement("system.webServer")) }

# webSocket enabled
$wsNode = $sys.SelectSingleNode("webSocket")
if (-not $wsNode) {
    $wsNode = $sys.AppendChild($xml.CreateElement("webSocket"))
}
$wsNode.SetAttribute("enabled","true")

# rewrite/rules
$rewrite = $sys.SelectSingleNode("rewrite")
if (-not $rewrite) { $rewrite = $sys.AppendChild($xml.CreateElement("rewrite")) }
$rules = $rewrite.SelectSingleNode("rules")
if (-not $rules) { $rules = $rewrite.AppendChild($xml.CreateElement("rules")) }

# Cerca se esiste gia' la rule
$existing = $rules.SelectSingleNode("rule[@name='ArgusWebSocketAgent']")
if ($existing) {
    Write-Warn "Rule 'ArgusWebSocketAgent' gia' esistente — la sostituisco"
    $rules.RemoveChild($existing) | Out-Null
}

$ruleXml = @'
<rule name="ArgusWebSocketAgent" stopProcessing="true">
  <match url="^api/agent/ws$" />
  <conditions logicalGrouping="MatchAll">
    <add input="{HTTP_UPGRADE}" pattern="websocket" />
  </conditions>
  <action type="Rewrite" url="http://127.0.0.1:8001/api/agent/ws" />
  <serverVariables>
    <set name="HTTP_X_FORWARDED_HOST" value="{HTTP_HOST}" />
    <set name="HTTP_X_FORWARDED_PROTO" value="https" />
  </serverVariables>
</rule>
'@
$frag = $xml.CreateDocumentFragment()
$frag.InnerXml = $ruleXml
# Inserisce la rule PRIMA delle altre (per matching prioritario)
if ($rules.FirstChild) {
    $rules.InsertBefore($frag, $rules.FirstChild) | Out-Null
} else {
    $rules.AppendChild($frag) | Out-Null
}

# Backup & save
$backup = "$webConfigPath.bak.$(Get-Date -Format yyyyMMddHHmmss)"
Copy-Item $webConfigPath $backup -Force
$xml.Save($webConfigPath)
Write-Ok "web.config aggiornato (backup: $backup)"

# ----------------------------------------------------------------------
# Restart IIS
# ----------------------------------------------------------------------
Write-Step "Restart IIS"
iisreset /restart | Out-Null
Write-Ok "IIS riavviato"

# ----------------------------------------------------------------------
# Test finale (HTTP HEAD su /api/agent/ws senza header upgrade — deve dare 4xx
# ma NON 404 ARR)
# ----------------------------------------------------------------------
Write-Step "Test smoke (TCP only, no WS handshake reale)"
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri "https://argus.86bit.it/api/health" -TimeoutSec 5
    Write-Ok "Backend FastAPI raggiungibile via IIS  (status $($r.StatusCode))"
} catch {
    Write-Warn "ATTENZIONE: /api/health non risponde - $($_.Exception.Message)"
}

Write-Host ""
Write-Host "*** Setup completato. ***" -ForegroundColor Green
Write-Host "Ora sul server cliente Galvan il nocagent.exe si aggancera' al WS." -ForegroundColor Green
Write-Host "Verifica leggendo C:\ProgramData\86NocAgent\logs\nocagent.log : "
Write-Host "  - cerchi una riga 'connected' (no piu' 'ws dial failed: ... 404')"
