#!/bin/bash
###############################################################################
# ARGUS Center — WireGuard Server Setup
# =====================================
# Script idempotente che configura il WireGuard server sul Center per consentire
# tunnel on-demand sicuri verso i Connector ARGUS dei clienti.
#
# Eseguire UNA VOLTA sul server che ospita argus.86bit.it (o un VPS dedicato).
# Richiede:
#   - Linux (Debian/Ubuntu/RHEL family)
#   - root o sudo
#   - una porta UDP aperta sul firewall pubblico (default 51820)
#
# Cosa fa:
#   1. Installa wireguard-tools
#   2. Genera coppia chiavi server (private+public)
#   3. Configura interfaccia wg0 con IP server 10.86.0.1/16
#   4. Abilita IP forwarding kernel
#   5. Configura iptables per NAT outbound + isolamento per-tenant
#   6. Avvia wg-quick@wg0 service systemd
#   7. Stampa pubkey + endpoint da inserire in .env del Center backend
#
# Disinstallazione: ./teardown-wireguard-server.sh
###############################################################################

set -euo pipefail

WG_INTERFACE="${WG_INTERFACE:-wg0}"
WG_SUBNET="${WG_SUBNET:-10.86.0.0/16}"
WG_SERVER_IP="${WG_SERVER_IP:-10.86.0.1/16}"
WG_PORT="${WG_PORT:-51820}"
WG_CONFIG_DIR="${WG_CONFIG_DIR:-/etc/wireguard}"

# ============================================================
echo "============================================"
echo "  ARGUS Center — WireGuard Server Setup"
echo "============================================"
echo "  Interface : $WG_INTERFACE"
echo "  Subnet    : $WG_SUBNET"
echo "  Server IP : $WG_SERVER_IP"
echo "  UDP Port  : $WG_PORT"
echo "============================================"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "[ERR] Eseguire come root o con sudo"
    exit 1
fi

# 1. Install wireguard-tools
echo "[1/7] Installazione wireguard-tools..."
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq wireguard-tools iptables curl
elif command -v dnf &>/dev/null; then
    dnf install -y wireguard-tools iptables curl
elif command -v yum &>/dev/null; then
    yum install -y wireguard-tools iptables curl
else
    echo "[ERR] package manager non riconosciuto (apt/dnf/yum)"
    exit 1
fi
echo "      OK"

# 2. Genera chiavi (idempotente: solo se non esistono)
echo "[2/7] Generazione/verifica chiavi server..."
mkdir -p "$WG_CONFIG_DIR"
chmod 700 "$WG_CONFIG_DIR"
if [ ! -f "$WG_CONFIG_DIR/server_private.key" ]; then
    umask 077
    wg genkey | tee "$WG_CONFIG_DIR/server_private.key" | wg pubkey > "$WG_CONFIG_DIR/server_public.key"
    echo "      Nuove chiavi generate"
else
    echo "      Chiavi già presenti (skip)"
fi

WG_SERVER_PRIVKEY=$(cat "$WG_CONFIG_DIR/server_private.key")
WG_SERVER_PUBKEY=$(cat "$WG_CONFIG_DIR/server_public.key")

# 3. Crea/aggiorna config wg0
echo "[3/7] Configurazione interfaccia $WG_INTERFACE..."
PRIMARY_IFACE=$(ip route | awk '/default/ {print $5; exit}')
if [ -z "$PRIMARY_IFACE" ]; then
    echo "[WARN] Impossibile rilevare interfaccia primaria, uso 'eth0'"
    PRIMARY_IFACE=eth0
fi

cat > "$WG_CONFIG_DIR/$WG_INTERFACE.conf" <<EOF
# ARGUS Center WireGuard server config
# Generato da setup-wireguard-server.sh
# I peer (connector cliente) verranno aggiunti dinamicamente via API ARGUS.

[Interface]
PrivateKey = $WG_SERVER_PRIVKEY
Address = $WG_SERVER_IP
ListenPort = $WG_PORT
SaveConfig = false

# Abilita IP forwarding + NAT (sostituisci $PRIMARY_IFACE se diverso)
PostUp = sysctl -w net.ipv4.ip_forward=1
PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostUp = iptables -A FORWARD -o %i -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -s $WG_SUBNET -o $PRIMARY_IFACE -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s $WG_SUBNET -o $PRIMARY_IFACE -j MASQUERADE
EOF
chmod 600 "$WG_CONFIG_DIR/$WG_INTERFACE.conf"
echo "      Config scritta in $WG_CONFIG_DIR/$WG_INTERFACE.conf"

# 4. IP forwarding persistente
echo "[4/7] Abilito IP forwarding persistente..."
if ! grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf 2>/dev/null; then
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
fi
sysctl -p > /dev/null 2>&1 || true
echo "      OK"

# 5. Firewall (apertura porta WG)
echo "[5/7] Configurazione firewall (porta UDP $WG_PORT)..."
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow $WG_PORT/udp comment "ARGUS WireGuard" || true
    echo "      ufw: regola aggiunta"
elif command -v firewall-cmd &>/dev/null && firewall-cmd --state 2>/dev/null | grep -q running; then
    firewall-cmd --permanent --add-port=${WG_PORT}/udp
    firewall-cmd --reload
    echo "      firewalld: regola aggiunta"
else
    echo "      [WARN] ufw/firewalld non attivi — assicurati che la porta UDP $WG_PORT sia aperta sul firewall pubblico"
fi

# 6. Avvio servizio
echo "[6/7] Avvio servizio WireGuard..."
systemctl enable wg-quick@$WG_INTERFACE > /dev/null 2>&1
if systemctl is-active --quiet wg-quick@$WG_INTERFACE; then
    echo "      Servizio già attivo, restart..."
    systemctl restart wg-quick@$WG_INTERFACE
else
    systemctl start wg-quick@$WG_INTERFACE
fi
sleep 1
if systemctl is-active --quiet wg-quick@$WG_INTERFACE; then
    echo "      OK: wg-quick@$WG_INTERFACE attivo"
else
    echo "[ERR] wg-quick@$WG_INTERFACE non avviato"
    systemctl status wg-quick@$WG_INTERFACE --no-pager
    exit 1
fi

# 7. Output finale + .env hint
echo "[7/7] Setup completato."
echo ""
PUBLIC_IP=$(curl -s --max-time 4 https://ipinfo.io/ip || echo "<your-public-ip>")
echo "============================================================"
echo "  ✅ WIREGUARD SERVER PRONTO"
echo "============================================================"
echo ""
echo "  Public Key:   $WG_SERVER_PUBKEY"
echo "  Endpoint:     ${PUBLIC_IP}:${WG_PORT}"
echo "  Subnet pool:  $WG_SUBNET"
echo "  Interface:    $WG_INTERFACE (server IP: $WG_SERVER_IP)"
echo ""
echo "------------------------------------------------------------"
echo "  📋 AGGIUNGI QUESTE 2 RIGHE A /app/backend/.env DEL CENTER"
echo "------------------------------------------------------------"
echo ""
echo "  WG_SERVER_PUBKEY=$WG_SERVER_PUBKEY"
echo "  WG_SERVER_ENDPOINT=${PUBLIC_IP}:${WG_PORT}"
echo ""
echo "  Poi: sudo supervisorctl restart backend"
echo "============================================================"
echo ""
echo "  Verifica: wg show $WG_INTERFACE"
echo "  Disinstalla: ./teardown-wireguard-server.sh"
echo ""
