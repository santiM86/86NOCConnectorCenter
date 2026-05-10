# =============================================================================
# add-argus-ws-rule.ps1
# Aggiunge la rewrite rule WebSocket per /api/agent/ws al web.config di IIS
# preservando integralmente le rule esistenti. Idempotente.
# =============================================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'

$WebConfig = "C:\Sites\argus.86bit.it\web.config"
$BackendUrl = "http://argus.86bit.it:8188/api/agent/ws"

if (-not (Test-Path $WebConfig)) {
    Write-Host "ERRORE: web.config non trovato: $WebConfig" -ForegroundColor Red
    exit 1
}

# Backup col timestamp
$Backup = "$WebConfig.bak.add-ws.$(Get-Date -Format yyyyMMddHHmmss)"
Copy-Item $WebConfig $Backup -Force
Write-Host "Backup: $Backup" -ForegroundColor Cyan

[xml]$xml = Get-Content $WebConfig

# Naviga /configuration/system.webServer/rewrite/rules
$rewrite = $xml.SelectSingleNode("/configuration/system.webServer/rewrite")
if (-not $rewrite) {
    Write-Host "ERRORE: nodo <rewrite> non trovato" -ForegroundColor Red
    exit 1
}
$rules = $rewrite.SelectSingleNode("rules")
if (-not $rules) {
    Write-Host "ERRORE: nodo <rules> non trovato" -ForegroundColor Red
    exit 1
}

# Se esiste gia' una rule ArgusWebSocketAgent, la rimuovo per riscriverla pulita
$existing = $rules.SelectSingleNode("rule[@name='ArgusWebSocketAgent']")
if ($existing) {
    $rules.RemoveChild($existing) | Out-Null
    Write-Host "Rimossa vecchia rule ArgusWebSocketAgent (riscrivo)" -ForegroundColor Yellow
}

# Crea la nuova rule
$ruleXml = @"
<rule name="ArgusWebSocketAgent" stopProcessing="true">
  <match url="^api/agent/ws$" />
  <conditions logicalGrouping="MatchAll">
    <add input="{HTTP_UPGRADE}" pattern="websocket" />
  </conditions>
  <action type="Rewrite" url="$BackendUrl" />
</rule>
"@

$frag = $xml.CreateDocumentFragment()
$frag.InnerXml = $ruleXml

# Inserisce la rule PRIMA di tutte le altre (per matching prioritario sulla
# rule generica ReverseProxyInboundRule1 che cattura url="(.*)").
if ($rules.FirstChild) {
    $rules.InsertBefore($frag, $rules.FirstChild) | Out-Null
} else {
    $rules.AppendChild($frag) | Out-Null
}

$xml.Save($WebConfig)
Write-Host "Rule ArgusWebSocketAgent aggiunta in cima alle rules" -ForegroundColor Green

# Ricarica IIS senza fare reset completo (basta restart del sito)
& "$env:windir\system32\inetsrv\appcmd.exe" stop site "argus.86bit.it" 2>$null | Out-Null
Start-Sleep 1
& "$env:windir\system32\inetsrv\appcmd.exe" start site "argus.86bit.it" 2>$null | Out-Null
Write-Host "Sito argus.86bit.it riavviato" -ForegroundColor Green

# Test
Start-Sleep 4
try {
    $r = Invoke-WebRequest -UseBasicParsing "https://argus.86bit.it/api/health" -TimeoutSec 5
    Write-Host "Smoke test HTTP /api/health -> $($r.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "ATTENZIONE: /api/health $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Fatto. Ora verifica dal cliente Galvan il log nocagent.log: dovrebbe agganciarsi al WS." -ForegroundColor Cyan
