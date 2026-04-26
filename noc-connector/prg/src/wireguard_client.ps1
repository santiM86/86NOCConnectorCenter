<#
.SYNOPSIS
    ARGUS Connector — WireGuard runtime integration (lato cliente)

.DESCRIPTION
    Modulo dot-sourced da connector.ps1 che gestisce l'intero ciclo di vita VPN:
      1. Initialize-WireGuard         - prerequisite check (wireguard.exe + wg.exe)
      2. New-WireGuardKeyPair         - genera coppia chiavi Curve25519 via wg.exe
      3. Get-WireGuardKeys            - legge/persiste in %ProgramData%\86NocConnector\wireguard\
      4. Register-WireGuardPeer       - POST pubkey al Center, riceve config (tunnel_ip, server)
      5. Sync-WireGuardSession        - long-poll session, attiva/disattiva tunnel
      6. Start-WireGuardTunnel        - scrive .conf + wireguard.exe /installtunnelservice
      7. Stop-WireGuardTunnel         - wireguard.exe /uninstalltunnelservice

    Sicurezza:
      - Chiavi private salvate solo su disco locale con ACL ristrette (LocalSystem)
      - Nessuna chiave privata mai trasmessa al NOC
      - Tunnel creato come servizio Windows isolato (gira in kernel mode dove possibile)

    Prerequisito: WireGuard for Windows installato (https://www.wireguard.com/install/)
    Se mancante, le funzioni emettono WARN e ritornano $false; il connector continua
    a funzionare in tutte le altre feature (graceful degradation).
#>

# ============================================================
# Path / Constants
# ============================================================
$script:WG_DIR = Join-Path $env:ProgramData "86NocConnector\wireguard"
$script:WG_PRIV_KEY_FILE = Join-Path $script:WG_DIR "peer_private.key"
$script:WG_PUB_KEY_FILE = Join-Path $script:WG_DIR "peer_public.key"
$script:WG_TUNNEL_CONF = Join-Path $script:WG_DIR "argus.conf"
$script:WG_TUNNEL_NAME = "argus"   # nome del tunnel/servizio Windows
$script:WG_LAST_SESSION_ID = $null
$script:WG_LAST_POLL_AT = [DateTime]::MinValue

# Path possibili di wireguard.exe (installazione standard)
$script:WG_EXE_CANDIDATES = @(
    "${env:ProgramFiles}\WireGuard\wireguard.exe",
    "${env:ProgramFiles(x86)}\WireGuard\wireguard.exe"
)
$script:WG_TOOLS_EXE_CANDIDATES = @(
    "${env:ProgramFiles}\WireGuard\wg.exe",
    "${env:ProgramFiles(x86)}\WireGuard\wg.exe"
)

# ============================================================
# Initialize: verifica prerequisiti (chiamato 1 volta all'avvio)
# ============================================================
function Initialize-WireGuard {
    [CmdletBinding()]
    param()

    $script:WG_EXE = $null
    $script:WG_TOOLS_EXE = $null

    foreach ($p in $script:WG_EXE_CANDIDATES) {
        if (Test-Path $p) { $script:WG_EXE = $p; break }
    }
    foreach ($p in $script:WG_TOOLS_EXE_CANDIDATES) {
        if (Test-Path $p) { $script:WG_TOOLS_EXE = $p; break }
    }

    # v3.5.22: AUTO-INSTALL di WireGuard for Windows se mancante.
    # Il connector scarica l'installer ufficiale Microsoft-firmato e lo esegue
    # in silent mode. Garantisce zero-touch deployment: l'admin installa solo
    # il connector ARGUS, tutto il resto (driver kernel WinTun + tools wg.exe)
    # viene gestito automaticamente al primo avvio.
    if (-not $script:WG_EXE -or -not $script:WG_TOOLS_EXE) {
        Write-Log "WireGuard for Windows non rilevato. Tento installazione automatica..." "WARN"
        $installed = Install-WireGuardClient
        if ($installed) {
            # Re-check dopo install
            foreach ($p in $script:WG_EXE_CANDIDATES) {
                if (Test-Path $p) { $script:WG_EXE = $p; break }
            }
            foreach ($p in $script:WG_TOOLS_EXE_CANDIDATES) {
                if (Test-Path $p) { $script:WG_TOOLS_EXE = $p; break }
            }
        }
    }

    if (-not $script:WG_EXE -or -not $script:WG_TOOLS_EXE) {
        Write-Log "WireGuard non disponibile: VPN remota disabilitata. Le altre feature del connector continuano normalmente. Per abilitare manualmente: scarica https://download.wireguard.com/windows-client/wireguard-installer.exe" "WARN"
        return $false
    }

    if (-not (Test-Path $script:WG_DIR)) {
        New-Item -ItemType Directory -Path $script:WG_DIR -Force | Out-Null
    }

    Write-Log "WireGuard tools rilevati: $($script:WG_EXE)" "INFO"
    return $true
}

# ============================================================
# v3.5.22: Auto-install di WireGuard for Windows
# ============================================================
function Install-WireGuardClient {
    [CmdletBinding()]
    param()

    # URL ufficiale (firmato Microsoft, signed Authenticode da WireGuard LLC)
    $installerUrl = "https://download.wireguard.com/windows-client/wireguard-installer.exe"
    $installerPath = Join-Path $env:TEMP "wireguard-installer.exe"

    try {
        Write-Log "Download WireGuard for Windows da $installerUrl ..." "INFO"
        # TLS 1.2+ (Windows Server 2016+ supporta out-of-the-box)
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 }
        # Usa WebClient per progress + maggior compat con server vecchi
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add("User-Agent", "ARGUS-Connector/$($global:Version)")
        $wc.DownloadFile($installerUrl, $installerPath)
        if (-not (Test-Path $installerPath)) {
            Write-Log "Download fallito: file non creato" "ERROR"
            return $false
        }

        # Verifica signature Authenticode (defense-in-depth)
        try {
            $sig = Get-AuthenticodeSignature $installerPath
            if ($sig.Status -ne "Valid") {
                Write-Log "Signature WireGuard installer NON valida (status=$($sig.Status)). Install ABORTITO per sicurezza." "ERROR"
                Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
                return $false
            }
            $issuer = $sig.SignerCertificate.Subject
            if ($issuer -notmatch "WireGuard|Jason A. Donenfeld") {
                Write-Log "Signature firmataria sospetta: $issuer. Install ABORTITO." "ERROR"
                Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
                return $false
            }
            Write-Log "Signature WireGuard verificata (signed by: $issuer)" "INFO"
        } catch {
            Write-Log "Verifica signature non disponibile: $($_.Exception.Message). Procedo comunque (il file e' scaricato da HTTPS ufficiale)." "WARN"
        }

        # Esegui installer silent. WireGuard installer accetta /quiet o /S.
        # Default flag: /S (silent), no UI, install in C:\Program Files\WireGuard\
        Write-Log "Esecuzione installer WireGuard in silent mode..." "INFO"
        $proc = Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait -PassThru -NoNewWindow
        Start-Sleep -Seconds 3

        if ($proc.ExitCode -eq 0) {
            Write-Log "WireGuard for Windows installato (exit=0)" "INFO"
            # Cleanup file scaricato
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            return $true
        } else {
            Write-Log "Installer WireGuard exit code: $($proc.ExitCode). Possibile install incompleto." "WARN"
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            return $false
        }
    } catch {
        Write-Log "Errore download/install WireGuard: $($_.Exception.Message)" "ERROR"
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
        return $false
    }
}

# ============================================================
# Genera o recupera coppia chiavi Curve25519 (idempotente)
# ============================================================
function Get-WireGuardKeys {
    [CmdletBinding()]
    param()
    if (-not $script:WG_TOOLS_EXE) { return $null }

    if ((Test-Path $script:WG_PRIV_KEY_FILE) -and (Test-Path $script:WG_PUB_KEY_FILE)) {
        return @{
            private_key = (Get-Content $script:WG_PRIV_KEY_FILE -Raw).Trim()
            public_key  = (Get-Content $script:WG_PUB_KEY_FILE -Raw).Trim()
        }
    }

    # Genera nuova coppia con wg.exe
    try {
        $priv = & $script:WG_TOOLS_EXE genkey 2>$null
        if (-not $priv) { Write-Log "wg.exe genkey fallito" "ERROR"; return $null }
        $priv = $priv.Trim()
        $pub = $priv | & $script:WG_TOOLS_EXE pubkey 2>$null
        if (-not $pub) { Write-Log "wg.exe pubkey fallito" "ERROR"; return $null }
        $pub = $pub.Trim()

        # Salva con ACL ristretta (solo SYSTEM + Administrators)
        Set-Content -Path $script:WG_PRIV_KEY_FILE -Value $priv -Encoding ASCII -NoNewline
        Set-Content -Path $script:WG_PUB_KEY_FILE -Value $pub -Encoding ASCII -NoNewline

        try {
            $acl = Get-Acl $script:WG_PRIV_KEY_FILE
            $acl.SetAccessRuleProtection($true, $false)  # disable inheritance
            $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
            $rule1 = New-Object System.Security.AccessControl.FileSystemAccessRule("NT AUTHORITY\SYSTEM", "FullControl", "Allow")
            $rule2 = New-Object System.Security.AccessControl.FileSystemAccessRule("BUILTIN\Administrators", "FullControl", "Allow")
            $acl.AddAccessRule($rule1); $acl.AddAccessRule($rule2)
            Set-Acl -Path $script:WG_PRIV_KEY_FILE -AclObject $acl
        } catch {
            Write-Log "ACL su chiave WG private non applicata: $($_.Exception.Message)" "WARN"
        }

        Write-Log "Nuova coppia chiavi WireGuard generata e salvata in $script:WG_DIR" "INFO"
        return @{ private_key = $priv; public_key = $pub }
    } catch {
        Write-Log "Errore generazione chiavi WG: $($_.Exception.Message)" "ERROR"
        return $null
    }
}

# ============================================================
# Registra public key al Center, riceve config server
# ============================================================
function Register-WireGuardPeer($config, $publicKey) {
    if (-not $publicKey) { return $null }
    $url = "$($config.noc_center_url)/api/connector/wireguard/register-public-key"
    $body = @{ public_key = $publicKey } | ConvertTo-Json -Compress
    $headers = @{ "X-API-Key" = $config.api_key; "Content-Type" = "application/json" }
    try {
        $r = Invoke-RestMethod -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15 -ErrorAction Stop
        Write-Log "WG peer registrato: tunnel_ip=$($r.tunnel_ip) status=$($r.status)" "INFO"
        return $r
    } catch {
        $errMsg = $_.Exception.Message
        $isAuth = ($errMsg -match "401" -or $errMsg -match "Non autorizzato")
        if ($isAuth) {
            Write-Log "WG register-public-key 401: API Key non accettata dal NOC. VPN VPN disabilitata finche' non risolto." "WARN"
        } else {
            Write-Log "Errore WG register: $errMsg" "WARN"
        }
        return $null
    }
}

# ============================================================
# Scrivi config tunnel + attiva via wireguard.exe (privilegiato)
# ============================================================
function Start-WireGuardTunnel($peerConfig) {
    if (-not $script:WG_EXE -or -not $script:WG_TOOLS_EXE) { return $false }
    if (-not $peerConfig -or -not $peerConfig.server_public_key -or
        $peerConfig.server_public_key -like "(server-not-configured)*") {
        Write-Log "Server WireGuard non configurato lato Center: tunnel non avviabile. L'admin deve eseguire setup-wireguard-server.sh + impostare WG_SERVER_PUBKEY/WG_SERVER_ENDPOINT in .env del Center." "WARN"
        return $false
    }

    $keys = Get-WireGuardKeys
    if (-not $keys) { return $false }

    # Build .conf file
    $tunnelIp = $peerConfig.tunnel_ip
    if ($tunnelIp -notmatch '/') { $tunnelIp = "$tunnelIp/16" }
    $allowedIps = if ($peerConfig.allowed_ips) { $peerConfig.allowed_ips } else { "10.86.0.0/16" }

    # v3.5.20: Pre-Shared Key (PSK) per quantum-resistance.
    # Il PSK è opzionale (compat con peer pre-v3.5.20) ma fortemente raccomandato.
    $pskLine = ""
    if ($peerConfig.preshared_key) {
        $pskLine = "PresharedKey = $($peerConfig.preshared_key)`n"
    }

    $conf = @"
# ARGUS WireGuard tunnel — generato automaticamente
# v3.5.21 OPTIMIZED: PSK ephemeral + MTU tuned per zero fragmentation
# Non modificare manualmente. Riavvia il connector per rigenerare.

[Interface]
PrivateKey = $($keys.private_key)
Address = $tunnelIp
MTU = 1420

[Peer]
PublicKey = $($peerConfig.server_public_key)
${pskLine}Endpoint = $($peerConfig.server_endpoint)
AllowedIPs = $allowedIps
PersistentKeepalive = 25
"@
    Set-Content -Path $script:WG_TUNNEL_CONF -Value $conf -Encoding UTF8

    # Se il servizio del tunnel esiste già, ferma prima (idempotency)
    Stop-WireGuardTunnel -Quiet | Out-Null

    try {
        $proc = Start-Process -FilePath $script:WG_EXE -ArgumentList @("/installtunnelservice", $script:WG_TUNNEL_CONF) -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -eq 0) {
            $pskNote = if ($peerConfig.preshared_key) { " [PSK enabled]" } else { "" }
            Write-Log "WG tunnel '$($script:WG_TUNNEL_NAME)' attivato (peer=$($peerConfig.server_endpoint), ip=$tunnelIp)$pskNote" "INFO"
            return $true
        } else {
            Write-Log "WG tunnel install exit code: $($proc.ExitCode)" "WARN"
            return $false
        }
    } catch {
        Write-Log "Errore Start-WireGuardTunnel: $($_.Exception.Message)" "ERROR"
        return $false
    }
}

# ============================================================
# v3.5.20: Force key rotation (chiamato quando l'admin clicca "Ruota chiavi")
# ============================================================
function Invoke-WireGuardKeyRotation($config) {
    if (-not $script:WG_TOOLS_EXE) { return $false }
    Write-Log "WG: rotazione chiavi forzata in corso..." "WARN"

    # Stop tunnel attivo
    Stop-WireGuardTunnel -Quiet | Out-Null

    # Cancella chiavi esistenti per forzare rigenerazione
    Remove-Item $script:WG_PRIV_KEY_FILE -Force -ErrorAction SilentlyContinue
    Remove-Item $script:WG_PUB_KEY_FILE -Force -ErrorAction SilentlyContinue

    # Rigenera coppia
    $keys = Get-WireGuardKeys
    if (-not $keys) { return $false }

    # Re-registra al Center (riceverà anche nuovo PSK)
    $script:WG_PEER_CONFIG = Register-WireGuardPeer $config $keys.public_key
    if ($script:WG_PEER_CONFIG) {
        Write-Log "WG: nuove chiavi generate e registrate. tunnel_ip=$($script:WG_PEER_CONFIG.tunnel_ip)" "INFO"
        # Notifica al Center che la rotazione è completata
        try {
            $url = "$($config.noc_center_url)/api/admin/wireguard/peer/$($script:WG_PEER_CONFIG.client_id)/clear-rotation-flag"
            # Endpoint admin - skippiamo (lo gestisce il backend al successivo register-public-key)
        } catch {}
        $script:WG_LAST_SESSION_ID = $null  # forza riapertura tunnel se serve
        return $true
    }
    return $false
}

# ============================================================
# Disattiva tunnel
# ============================================================
function Stop-WireGuardTunnel {
    [CmdletBinding()]
    param([switch]$Quiet)
    if (-not $script:WG_EXE) { return $false }

    # Il servizio si chiama "WireGuardTunnel$<tunnelname>"
    $svcName = "WireGuardTunnel`$$($script:WG_TUNNEL_NAME)"
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if (-not $svc) {
        if (-not $Quiet) { Write-Log "WG tunnel non attivo (servizio inesistente)" "DEBUG" }
        return $true
    }

    try {
        $proc = Start-Process -FilePath $script:WG_EXE -ArgumentList @("/uninstalltunnelservice", $script:WG_TUNNEL_NAME) -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -eq 0) {
            if (-not $Quiet) { Write-Log "WG tunnel '$($script:WG_TUNNEL_NAME)' disattivato" "INFO" }
            return $true
        } else {
            if (-not $Quiet) { Write-Log "WG /uninstalltunnelservice exit=$($proc.ExitCode)" "WARN" }
            return $false
        }
    } catch {
        if (-not $Quiet) { Write-Log "Errore Stop-WireGuardTunnel: $($_.Exception.Message)" "ERROR" }
        return $false
    }
}

# ============================================================
# Long-poll: chiama il NOC per sapere se attivare/disattivare tunnel
# Chiamato dal polling loop ogni ~5 secondi.
# ============================================================
function Sync-WireGuardSession($config, $peerConfig) {
    if (-not $script:WG_EXE) { return }   # WG non installato → no-op
    if (-not $peerConfig) { return }

    # v3.5.21: polling ADATTIVO per ottimizzare performance
    #   - Sessione attiva  → poll ogni 3 sec (reattività rapida a stop session)
    #   - Idle (no session) → poll ogni 10 sec (CPU risparmiata)
    $pollInterval = if ($script:WG_LAST_SESSION_ID) { 3 } else { 10 }
    $now = Get-Date
    if (($now - $script:WG_LAST_POLL_AT).TotalSeconds -lt $pollInterval) { return }
    $script:WG_LAST_POLL_AT = $now

    # Check rotation pending (priorità massima)
    try {
        $rotUrl = "$($config.noc_center_url)/api/connector/wireguard/rotation-pending"
        $r = Invoke-RestMethod -Uri $rotUrl -Method Get -Headers @{ "X-API-Key" = $config.api_key } -TimeoutSec 5 -ErrorAction Stop
        if ($r.rotation_pending -eq $true) {
            Write-Log "WG: rotation forzata richiesta dal Center, eseguo..." "WARN"
            if (Invoke-WireGuardKeyRotation $config) {
                $peerConfig = $script:WG_PEER_CONFIG
            }
        }
    } catch { }

    $url = "$($config.noc_center_url)/api/connector/wireguard/session"
    try {
        $headers = @{ "X-API-Key" = $config.api_key }
        $r = Invoke-RestMethod -Uri $url -Method Get -Headers $headers -TimeoutSec 8 -ErrorAction Stop
    } catch {
        return
    }

    if ($r.tunnel_required -eq $true) {
        # Clona peerConfig e applica overrides per questa sessione
        $effectiveConfig = $peerConfig.PSObject.Copy()
        # Restrict mode: AllowedIPs limitati ai device registrati
        if ($r.restrict_mode -eq $true -and $r.allowed_device_ips -and $r.allowed_device_ips.Count -gt 0) {
            $effectiveConfig | Add-Member -NotePropertyName allowed_ips -NotePropertyValue ($r.allowed_device_ips -join ", ") -Force
        }
        # v3.5.21: Ephemeral PSK per questa sessione (override del PSK statico del peer)
        if ($r.ephemeral_psk) {
            $effectiveConfig | Add-Member -NotePropertyName preshared_key -NotePropertyValue $r.ephemeral_psk -Force
        }

        if ($script:WG_LAST_SESSION_ID -ne $r.session_id) {
            $restrictNote = if ($r.restrict_mode) { " [RESTRICT: $($r.allowed_device_ips.Count) device]" } else { "" }
            $pskNote = if ($r.ephemeral_psk) { " [EPHEMERAL-PSK]" } else { "" }
            Write-Log "WG session start (id=$($r.session_id), avviata da=$($r.started_by), target=$($r.target_device_ip))${restrictNote}${pskNote}" "INFO"
            $ok = Start-WireGuardTunnel $effectiveConfig
            if ($ok) {
                $script:WG_LAST_SESSION_ID = $r.session_id
            }
        }
    } else {
        if ($script:WG_LAST_SESSION_ID) {
            Write-Log "WG session end" "INFO"
            Stop-WireGuardTunnel | Out-Null
            $script:WG_LAST_SESSION_ID = $null
        }
    }
}

# ============================================================
# Cleanup all'arresto del connector
# ============================================================
function Stop-WireGuardCleanup {
    if ($script:WG_EXE -and $script:WG_LAST_SESSION_ID) {
        Stop-WireGuardTunnel | Out-Null
    }
}
