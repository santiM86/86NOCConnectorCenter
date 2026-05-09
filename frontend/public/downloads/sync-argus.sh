#!/usr/bin/env bash
# ARGUS — sync-argus.sh
# =====================================================================
# Allinea il server di produzione (`argus.86bit.it`) con le ultime
# modifiche sviluppate in preview:
#   • backend FastAPI (con i fix _token_or_403 cascade + clients.client_id)
#   • template wizard PowerShell (installer_gui.ps1.template)
#   • binari Go Windows (nocagent.exe, nocagent-ui.exe, nocwatchdog.exe,
#     nocinstall.exe)
#   • icona Argus (.ico standalone + frontend public icons)
#
# Esegui questo script SUL SERVER `argus.86bit.it`, NON in locale.
# Richiede: bash, curl, tar, sudo, supervisorctl o systemctl.
#
# Usage:
#   curl -fsSL https://snmp-hub-noc.preview.emergentagent.com/downloads/sync-argus.sh | sudo bash
#
# oppure salva il file e:
#   sudo bash sync-argus.sh
# ---------------------------------------------------------------------
set -euo pipefail

PKG_URL="${ARGUS_PKG_URL:-https://snmp-hub-noc.preview.emergentagent.com/downloads/argus-deploy-latest.tar.gz}"
ARGUS_ROOT="${ARGUS_ROOT:-/opt/argus}"
BACKUP_DIR="${ARGUS_BACKUP_DIR:-$ARGUS_ROOT/backups}"
SVC_NAME="${ARGUS_SVC_NAME:-argus-backend}"     # systemd unit name
SUP_NAME="${ARGUS_SUP_NAME:-backend}"           # supervisor program name
FRONTEND_PUBLIC="${ARGUS_FRONTEND_PUBLIC:-$ARGUS_ROOT/frontend/public}"

ts="$(date +%Y%m%d-%H%M%S)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

log()  { printf "\033[1;36m[sync-argus]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[sync-argus]\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m[sync-argus]\033[0m %s\n" "$*" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || die "Eseguire come root (sudo)."

mkdir -p "$ARGUS_ROOT" "$BACKUP_DIR"

log "1/6  Download bundle: $PKG_URL"
curl -fsSL "$PKG_URL" -o "$work/argus-deploy.tar.gz" || die "download fallito"
tar -xzf "$work/argus-deploy.tar.gz" -C "$work"
[[ -d "$work/backend" ]] || die "bundle non valido (manca backend/)"

log "2/6  Backup corrente -> $BACKUP_DIR/argus-$ts.tar.gz"
tar -czf "$BACKUP_DIR/argus-$ts.tar.gz" \
    -C "$ARGUS_ROOT" backend noc-agent 2>/dev/null || warn "Backup parziale (alcune cartelle non esistono ancora)."

log "3/6  Sync backend (preserva .env e data/)"
mkdir -p "$ARGUS_ROOT/backend"
rsync -a --delete \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude '__pycache__' \
    "$work/backend/" "$ARGUS_ROOT/backend/"

log "4/6  Sync noc-agent (template wizard + binari Windows + ico)"
mkdir -p "$ARGUS_ROOT/noc-agent"
rsync -a "$work/noc-agent/" "$ARGUS_ROOT/noc-agent/"

log "5/6  Sync icone frontend (favicon + logo + PWA)"
if [[ -d "$FRONTEND_PUBLIC" ]]; then
    rsync -a "$work/frontend-public-icons/" "$FRONTEND_PUBLIC/"
    log "      icone copiate in $FRONTEND_PUBLIC"
else
    warn "Cartella frontend ($FRONTEND_PUBLIC) non trovata — salto sync icone."
fi

log "6/6  Restart backend"
# Auto-detect del service manager
if systemctl status "$SVC_NAME" >/dev/null 2>&1; then
    systemctl restart "$SVC_NAME" && log "      systemd: $SVC_NAME riavviato"
elif command -v supervisorctl >/dev/null 2>&1; then
    supervisorctl restart "$SUP_NAME" && log "      supervisor: $SUP_NAME riavviato"
else
    warn "Nessun service manager riconosciuto (systemctl/supervisorctl). Riavvia manualmente il backend."
fi

# Suggerimento env per i path noc-agent (idempotente: aggiunge solo se mancanti)
ENV_FILE="$ARGUS_ROOT/backend/.env"
if [[ -f "$ENV_FILE" ]]; then
    grep -q '^NOCAGENT_BUILD_DIR=' "$ENV_FILE"            || echo "NOCAGENT_BUILD_DIR=$ARGUS_ROOT/noc-agent/build/bin"      >> "$ENV_FILE"
    grep -q '^NOCAGENT_TEMPLATE_DIR=' "$ENV_FILE"         || echo "NOCAGENT_TEMPLATE_DIR=$ARGUS_ROOT/noc-agent/build"       >> "$ENV_FILE"
    grep -q '^NOCAGENT_ICO_PATH=' "$ENV_FILE"             || echo "NOCAGENT_ICO_PATH=$ARGUS_ROOT/noc-agent/cmd/nocui/argus.ico" >> "$ENV_FILE"
    # Mirror di fallback: se uno qualsiasi degli asset (template wizard,
    # binari Windows, argus.ico) non e' sul filesystem locale, il backend
    # fa redirect/fetch trasparente verso questo mirror. Cosi' il sistema
    # e' self-healing: il deploy locale puo' essere parziale e funziona
    # comunque. Lascia commentato se non vuoi questa rete di sicurezza.
    grep -q '^WIZARD_TEMPLATE_FALLBACK_URL=' "$ENV_FILE"  || echo "WIZARD_TEMPLATE_FALLBACK_URL=https://snmp-hub-noc.preview.emergentagent.com" >> "$ENV_FILE"
    grep -q '^BINARY_FALLBACK_URL=' "$ENV_FILE"           || echo "BINARY_FALLBACK_URL=https://snmp-hub-noc.preview.emergentagent.com"         >> "$ENV_FILE"
    log "      env NOCAGENT_* + *_FALLBACK_URL aggiunti a $ENV_FILE (riavvio backend nuovamente)"
    if systemctl status "$SVC_NAME" >/dev/null 2>&1; then systemctl restart "$SVC_NAME"
    elif command -v supervisorctl >/dev/null 2>&1;     then supervisorctl restart "$SUP_NAME"
    fi
fi

log "DONE — argus aggiornato (backup: $BACKUP_DIR/argus-$ts.tar.gz)"
log "Verifica:  curl -sS https://argus.86bit.it/api/agent/install/manifest?platform=windows-amd64\\&token=<API_KEY> | head"
