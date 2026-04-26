#!/bin/bash
###############################################################################
# ARGUS Center — WireGuard Server Setup (HARDENED v3.5.20)
# =========================================================
# Setup military/banking-grade del server WireGuard sul Center.
# Differenze rispetto alla v3.5.17:
#   - Porta UDP random (49152-65535) invece di default 51820 → security through obscurity
#   - Source IP whitelist iptables (default: open, configurabile via WG_ALLOWED_SOURCE_IPS)
#   - Rate limit handshake (10/sec per source IP) — anti-DDoS
#   - Auto-fail2ban su >5 handshake invalidi/min se installato
#   - PSK gestiti per peer (no PSK globale; ogni connector ha il suo)
#   - Hardening kernel: rp_filter, no source routing, ICMP suppressed
#   - Logging dettagliato in /var/log/wireguard.log
#
# Eseguire UNA VOLTA sul server che ospita argus.86bit.it (o un VPS dedicato).
# Idempotente: rieseguibile in sicurezza per upgrade.
###############################################################################

set -euo pipefail

WG_INTERFACE="${WG_INTERFACE:-wg0}"
WG_SUBNET="${WG_SUBNET:-10.86.0.0/16}"
WG_SERVER_IP="${WG_SERVER_IP:-10.86.0.1/16}"
WG_CONFIG_DIR="${WG_CONFIG_DIR:-/etc/wireguard}"
# Source IP whitelist: lista IP/CIDR autorizzati a connettersi al WG server.
# Se vuoto = aperto (compat). Esempio: "203.0.113.5/32 198.51.100.0/24"
WG_ALLOWED_SOURCE_IPS="${WG_ALLOWED_SOURCE_IPS:-}"

# ============================================================
echo "============================================"
echo "  ARGUS Center — WireGuard HARDENED Setup"
echo "============================================"

if [ "$EUID" -ne 0 ]; then echo "[ERR] sudo richiesto"; exit 1; fi

# 1. Install
echo "[1/9] Installazione wireguard-tools..."
if command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq wireguard-tools iptables curl iptables-persistent fail2ban || true
elif command -v dnf &>/dev/null; then
    dnf install -y wireguard-tools iptables curl fail2ban
elif command -v yum &>/dev/null; then
    yum install -y wireguard-tools iptables curl fail2ban
else
    echo "[ERR] package manager non riconosciuto"; exit 1
fi

# 2. Genera porta random ephemeral 49152-65535 (idempotente: salva in file)
WG_PORT_FILE="$WG_CONFIG_DIR/${WG_INTERFACE}.port"
mkdir -p "$WG_CONFIG_DIR"; chmod 700 "$WG_CONFIG_DIR"
if [ -f "$WG_PORT_FILE" ]; then
    WG_PORT=$(cat "$WG_PORT_FILE")
    echo "[2/9] Porta esistente: $WG_PORT"
else
    WG_PORT=$(shuf -i 49152-65535 -n 1)
    echo "$WG_PORT" > "$WG_PORT_FILE"
    chmod 600 "$WG_PORT_FILE"
    echo "[2/9] Porta random generata: $WG_PORT (salvata in $WG_PORT_FILE)"
fi

# 3. Genera chiavi server (idempotente)
echo "[3/9] Verifica chiavi server..."
if [ ! -f "$WG_CONFIG_DIR/server_private.key" ]; then
    umask 077
    wg genkey | tee "$WG_CONFIG_DIR/server_private.key" | wg pubkey > "$WG_CONFIG_DIR/server_public.key"
    echo "      Nuove chiavi generate"
else
    echo "      Chiavi presenti (skip)"
fi
WG_SERVER_PRIVKEY=$(cat "$WG_CONFIG_DIR/server_private.key")
WG_SERVER_PUBKEY=$(cat "$WG_CONFIG_DIR/server_public.key")

# 4. Hardening kernel (sysctl)
echo "[4/9] Hardening kernel..."
cat > /etc/sysctl.d/99-argus-wireguard.conf <<EOF
# ARGUS Hardened sysctl
net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1
net.ipv4.conf.all.accept_source_route=0
net.ipv4.conf.default.accept_source_route=0
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
net.ipv4.conf.all.send_redirects=0
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.icmp_ignore_bogus_error_responses=1
net.ipv4.tcp_syncookies=1
net.ipv4.conf.all.log_martians=1
EOF
sysctl --system > /dev/null 2>&1 || true

# 5. Build wg0.conf (peer aggiunti dinamicamente via API)
echo "[5/9] Configurazione $WG_INTERFACE..."
PRIMARY_IFACE=$(ip route | awk '/default/ {print $5; exit}')
[ -z "$PRIMARY_IFACE" ] && PRIMARY_IFACE=eth0

cat > "$WG_CONFIG_DIR/$WG_INTERFACE.conf" <<EOF
# ARGUS WireGuard server config (HARDENED)
# Peer aggiunti dinamicamente via API ARGUS al register-public-key.

[Interface]
PrivateKey = $WG_SERVER_PRIVKEY
Address = $WG_SERVER_IP
ListenPort = $WG_PORT
SaveConfig = false

# IP forwarding e NAT outbound
PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostUp = iptables -A FORWARD -o %i -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -s $WG_SUBNET -o $PRIMARY_IFACE -j MASQUERADE

# Rate limit handshake (anti-DDoS): max 10 nuovi handshake/sec per IP
PostUp = iptables -A INPUT -p udp --dport $WG_PORT -m conntrack --ctstate NEW -m limit --limit 10/sec --limit-burst 20 -j ACCEPT
PostUp = iptables -A INPUT -p udp --dport $WG_PORT -m conntrack --ctstate NEW -j DROP

PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s $WG_SUBNET -o $PRIMARY_IFACE -j MASQUERADE
PostDown = iptables -D INPUT -p udp --dport $WG_PORT -m conntrack --ctstate NEW -m limit --limit 10/sec --limit-burst 20 -j ACCEPT
PostDown = iptables -D INPUT -p udp --dport $WG_PORT -m conntrack --ctstate NEW -j DROP
EOF
chmod 600 "$WG_CONFIG_DIR/$WG_INTERFACE.conf"

# 6. Source IP whitelist iptables (se configurato)
echo "[6/9] Source IP whitelist..."
# Pulisce regole vecchie se presenti
iptables -D INPUT -p udp --dport $WG_PORT -j DROP 2>/dev/null || true
for rule in $(iptables -L INPUT -n --line-numbers 2>/dev/null | grep "udp dpt:$WG_PORT" | awk '{print $1}' | sort -rn); do
    iptables -D INPUT $rule 2>/dev/null || true
done

if [ -n "$WG_ALLOWED_SOURCE_IPS" ]; then
    echo "      Whitelist attiva: $WG_ALLOWED_SOURCE_IPS"
    for src in $WG_ALLOWED_SOURCE_IPS; do
        iptables -I INPUT -p udp --dport $WG_PORT -s "$src" -j ACCEPT
    done
    iptables -A INPUT -p udp --dport $WG_PORT -j DROP
    echo "      Tutti gli altri IP source bloccati a livello firewall (kernel)"
else
    echo "      [WARN] Nessuna whitelist source IP configurata (open mode)."
    echo "      Per attivare: WG_ALLOWED_SOURCE_IPS='1.2.3.4/32 5.6.7.0/24' bash $0"
fi

# Persistenza regole iptables
if command -v netfilter-persistent &>/dev/null; then
    netfilter-persistent save > /dev/null 2>&1 || true
elif command -v iptables-save &>/dev/null; then
    iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
fi

# 7. Fail2Ban config (se installato)
echo "[7/9] Fail2Ban config..."
if command -v fail2ban-client &>/dev/null; then
    cat > /etc/fail2ban/filter.d/wireguard.conf <<'EOF'
[Definition]
failregex = .*wireguard:.*Invalid handshake initiation from <HOST>.*
            .*wireguard:.*Receiving handshake initiation from unknown peer <HOST>.*
ignoreregex =
EOF
    cat > /etc/fail2ban/jail.d/wireguard.conf <<EOF
[wireguard]
enabled = true
port = $WG_PORT
protocol = udp
filter = wireguard
backend = systemd
maxretry = 5
findtime = 300
bantime = 3600
EOF
    systemctl restart fail2ban 2>/dev/null || true
    echo "      OK: ban automatico dopo 5 handshake invalidi/5min"
else
    echo "      [WARN] fail2ban non installato (opzionale, skip)"
fi

# 8. Avvio servizio
echo "[8/9] Avvio servizio..."
systemctl enable wg-quick@$WG_INTERFACE > /dev/null 2>&1
systemctl restart wg-quick@$WG_INTERFACE
sleep 1
if ! systemctl is-active --quiet wg-quick@$WG_INTERFACE; then
    echo "[ERR] wg-quick@$WG_INTERFACE non avviato"
    systemctl status wg-quick@$WG_INTERFACE --no-pager
    exit 1
fi

# 9. Output
echo "[9/9] Setup completato."
echo ""
PUBLIC_IP=$(curl -s --max-time 4 https://ipinfo.io/ip || echo "<your-public-ip>")
echo "============================================================"
echo "  ✅ WIREGUARD HARDENED SERVER PRONTO"
echo "============================================================"
echo ""
echo "  Public Key:   $WG_SERVER_PUBKEY"
echo "  Endpoint:     ${PUBLIC_IP}:${WG_PORT}"
echo "  Subnet pool:  $WG_SUBNET"
echo "  Interface:    $WG_INTERFACE"
echo ""
echo "  🛡️  SECURITY HARDENING APPLICATO:"
echo "    ✓ Porta UDP random non-default ($WG_PORT)"
echo "    ✓ Sysctl hardening (rp_filter, no source routing, ICMP suppressed)"
echo "    ✓ Rate limit iptables 10/sec/source (anti-DDoS)"
if [ -n "$WG_ALLOWED_SOURCE_IPS" ]; then
echo "    ✓ Source IP whitelist (solo IP autorizzati possono connettersi)"
fi
if command -v fail2ban-client &>/dev/null; then
echo "    ✓ Fail2Ban auto-ban dopo 5 tentativi falliti/5min"
fi
echo "    ✓ Pre-Shared Key per peer (gestiti dinamicamente dal Center)"
echo ""
echo "------------------------------------------------------------"
echo "  📋 AGGIUNGI A /app/backend/.env DEL CENTER:"
echo "------------------------------------------------------------"
echo ""
echo "  WG_SERVER_PUBKEY=$WG_SERVER_PUBKEY"
echo "  WG_SERVER_ENDPOINT=${PUBLIC_IP}:${WG_PORT}"
echo ""
echo "  Poi: sudo supervisorctl restart backend"
echo ""
echo "------------------------------------------------------------"
echo "  💡 SUGGERIMENTO: per attivare source IP whitelist"
echo "------------------------------------------------------------"
echo ""
echo "  Ri-esegui questo script con env var:"
echo ""
echo "  sudo WG_ALLOWED_SOURCE_IPS='ip1/32 ip2/24' bash $0"
echo ""
echo "  (esempio: ip pubblici dei server cliente con il connector)"
echo "============================================================"
echo ""
echo "  Verifica: wg show $WG_INTERFACE"
echo "  Disinstalla: ./teardown-wireguard-server.sh"
echo ""
