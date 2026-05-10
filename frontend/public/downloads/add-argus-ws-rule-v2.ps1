# =============================================================================
# add-argus-ws-rule-v2.ps1
# v2: aggiunge SOLO la rewrite rule WebSocket al web.config, NON tocca
# l'elemento <webSocket> (che fa rompere lo schema XSD se messo in posizione
# sbagliata). Il flag webSocket enabled=true viene gestito esclusivamente a
# livello applicationHost.config via appcmd.
# =============================================================================

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$WebConfig = "C:\Sites\argus.86bit.it\web.config"
$BackendBase = "http://argus.86bit.it:8188"

if (-not (Test-Path $WebConfig)) {
    Write-Host "ERRORE: $WebConfig non trovato" -ForegroundColor Red; exit 1
}

# ----- 1. WebSocket enabled=true a livello apphost (idempotente) -----
& "$env:windir\system32\inetsrv\appcmd.exe" set config "argus.86bit.it" `
    -section:system.webServer/webSocket /enabled:"True" /commit:apphost | Out-Null
Write-Host "apphost: webSocket enabled=True per argus.86bit.it" -ForegroundColor Green

# ----- 2. Backup e parsing web.config -----
$Backup = "$WebConfig.bak.add-ws-v2.$(Get-Date -Format yyyyMMddHHmmss)"
Copy-Item $WebConfig $Backup -Force
Write-Host "Backup: $Backup" -ForegroundColor Cyan

[xml]$xml = Get-Content $WebConfig

$rules = $xml.SelectSingleNode("/configuration/system.webServer/rewrite/rules")
if (-not $rules) {
    Write-Host "ERRORE: rules node non trovato" -ForegroundColor Red; exit 1
}

# Rimuovi eventuale vecchia versione della rule
$existing = $rules.SelectSingleNode("rule[@name='ArgusWebSocketAgent']")
if ($existing) { $rules.RemoveChild($existing) | Out-Null }

# Costruisci la rule (action target identico a ReverseProxyInboundRule1
# per cogliere la stessa logica di proxy + condition esplicita sull'header
# Upgrade: websocket).
$ruleXml = @"
<rule name="ArgusWebSocketAgent" stopProcessing="true">
  <match url="^api/agent/ws$" />
  <conditions logicalGrouping="MatchAll">
    <add input="{HTTP_UPGRADE}" pattern="websocket" />
  </conditions>
  <action type="Rewrite" url="$BackendBase/api/agent/ws" />
</rule>
"@

$frag = $xml.CreateDocumentFragment()
$frag.InnerXml = $ruleXml

# Inserisci come PRIMO figlio di <rules> (priorita' assoluta).
if ($rules.FirstChild) {
    $rules.InsertBefore($frag, $rules.FirstChild) | Out-Null
} else {
    $rules.AppendChild($frag) | Out-Null
}

$xml.Save($WebConfig)
Write-Host "Rule ArgusWebSocketAgent inserita in cima alle rules" -ForegroundColor Green

# ----- 3. Recycle dell'app pool (piu' leggero di iisreset) -----
& "$env:windir\system32\inetsrv\appcmd.exe" recycle apppool "argus.86bit.it" 2>$null | Out-Null
Write-Host "AppPool argus.86bit.it riciclato" -ForegroundColor Green

# ----- 4. Smoke test (12s di attesa per il caldo di IIS) -----
Start-Sleep 12
try {
    $r = Invoke-WebRequest -UseBasicParsing "https://argus.86bit.it/api/health" -TimeoutSec 8
    Write-Host "Smoke /api/health -> $($r.StatusCode) (atteso 200)" -ForegroundColor Green
} catch {
    Write-Host "Smoke ERR: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Fatto. Ora controllo WS dal preview env." -ForegroundColor Cyan
