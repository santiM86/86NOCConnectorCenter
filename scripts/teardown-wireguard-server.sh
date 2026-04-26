#!/bin/bash
# ARGUS Center — Teardown WireGuard Server
# Disinstalla la configurazione del WireGuard server (chiavi preservate per backup).
set -euo pipefail
WG_INTERFACE="${WG_INTERFACE:-wg0}"

echo "============================================"
echo "  ARGUS — WireGuard Server Teardown"
echo "============================================"

if [ "$EUID" -ne 0 ]; then echo "[ERR] sudo richiesto"; exit 1; fi

systemctl stop wg-quick@$WG_INTERFACE 2>/dev/null || true
systemctl disable wg-quick@$WG_INTERFACE 2>/dev/null || true

if [ -f /etc/wireguard/${WG_INTERFACE}.conf ]; then
    BACKUP=/etc/wireguard/${WG_INTERFACE}.conf.bak.$(date +%Y%m%d-%H%M%S)
    mv /etc/wireguard/${WG_INTERFACE}.conf $BACKUP
    echo "  Config archiviata in $BACKUP"
fi

# Cleanup iptables NAT (best-effort)
iptables -t nat -L POSTROUTING -n --line-numbers 2>/dev/null | grep "10.86.0.0/16" | awk '{print $1}' | sort -rn | while read line; do
    iptables -t nat -D POSTROUTING $line 2>/dev/null || true
done

echo "  WireGuard server disattivato. Chiavi preservate in /etc/wireguard/server_*.key"
echo "  Per rimuoverle: rm /etc/wireguard/server_*.key"
