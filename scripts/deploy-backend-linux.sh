#!/usr/bin/env bash
#
# ARGUS Center - Backend deploy/upgrade script per Linux di produzione
# ====================================================================
# - Backup completo del backend corrente prima di toccare nulla
# - Sostituzione atomica (rename, non rm -rf) per minimizzare downtime
# - Health check post-deploy con rollback automatico se la nuova versione
#   non risponde correttamente
# - .env del backend MAI toccato (chiavi, MONGO_URL, secrets preservati)
# - Funziona con systemd o supervisor (auto-detect del service manager)
#
# Usage:
#   bash deploy-backend-linux.sh <package-url-or-local-tarball>
#
# Esempi:
#   bash deploy-backend-linux.sh https://argus.86bit.it/downloads/argus-backend-latest.tar.gz
#   bash deploy-backend-linux.sh /tmp/argus-backend-latest.tar.gz
#
# Variabili d'ambiente sovrascrivibili (con i loro default):
#   ARGUS_BACKEND_DIR            (/opt/argus/backend)
#   ARGUS_BACKUP_ROOT            (/opt/argus/backups)
#   ARGUS_VENV_DIR               (auto-detect; common: /opt/argus/.venv o /root/.venv)
#   ARGUS_HEALTH_URL             (http://127.0.0.1:8001/api/auth/login con POST dummy)
#   ARGUS_HEALTH_TIMEOUT_SEC     (30)
#   ARGUS_SERVICE_MANAGER        (auto: systemd|supervisor)
#   ARGUS_SYSTEMD_UNIT           (argus-backend)
#   ARGUS_SUPERVISOR_NAME        (backend)
#

set -euo pipefail

# ---- Config ----
PACKAGE="${1:-}"
BACKEND_DIR="${ARGUS_BACKEND_DIR:-/opt/argus/backend}"
BACKUP_ROOT="${ARGUS_BACKUP_ROOT:-/opt/argus/backups}"
HEALTH_URL_DEFAULT="http://127.0.0.1:8001/api/health"
HEALTH_URL="${ARGUS_HEALTH_URL:-$HEALTH_URL_DEFAULT}"
HEALTH_TIMEOUT="${ARGUS_HEALTH_TIMEOUT_SEC:-30}"
SVC_MGR="${ARGUS_SERVICE_MANAGER:-auto}"
SYSTEMD_UNIT="${ARGUS_SYSTEMD_UNIT:-argus-backend}"
SUPERVISOR_NAME="${ARGUS_SUPERVISOR_NAME:-backend}"

# ---- Logging helpers ----
GREEN='\033[0;32m'; YEL='\033[1;33m'; RED='\033[0;31m'; CYN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYN}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YEL}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

# ---- Banner ----
cat <<'EOF'
============================================================
  ARGUS Center — Backend Deploy / Upgrade
============================================================
EOF

[[ -z "$PACKAGE" ]] && die "Usage: $0 <package-url-or-tarball-path>"
[[ $EUID -ne 0 ]] && warn "Non sei root: alcune operazioni potrebbero fallire"

# ---- Step 0: Sanity ----
log "Verifico ambiente..."
[[ -d "$BACKEND_DIR" ]] || die "BACKEND_DIR=$BACKEND_DIR non esiste. Setta ARGUS_BACKEND_DIR=<path> e riprova."

# Auto-detect service manager
if [[ "$SVC_MGR" == "auto" ]]; then
  if systemctl list-units --type=service 2>/dev/null | grep -q "$SYSTEMD_UNIT"; then
    SVC_MGR="systemd"
  elif command -v supervisorctl >/dev/null && supervisorctl status "$SUPERVISOR_NAME" >/dev/null 2>&1; then
    SVC_MGR="supervisor"
  else
    warn "Ne' systemd unit '$SYSTEMD_UNIT' ne' supervisor program '$SUPERVISOR_NAME' rilevati."
    warn "Lo script proseguira' ma non potra' riavviare automaticamente il backend."
    SVC_MGR="manual"
  fi
fi
ok "Service manager: $SVC_MGR"

# Auto-detect virtualenv
if [[ -z "${ARGUS_VENV_DIR:-}" ]]; then
  for cand in "$BACKEND_DIR/../venv" "$BACKEND_DIR/../.venv" /opt/argus/.venv /opt/argus/venv /root/.venv; do
    if [[ -x "$cand/bin/pip" ]]; then ARGUS_VENV_DIR="$cand"; break; fi
  done
fi
if [[ -n "${ARGUS_VENV_DIR:-}" && -x "$ARGUS_VENV_DIR/bin/pip" ]]; then
  ok "Virtualenv: $ARGUS_VENV_DIR"
else
  warn "Virtualenv non rilevato - verra' usato pip di sistema"
  ARGUS_VENV_DIR=""
fi

# ---- Step 1: Download / verify package ----
WORK_DIR=$(mktemp -d -t argus-deploy-XXXXXX)
trap 'rm -rf "$WORK_DIR"' EXIT
TARBALL="$WORK_DIR/package.tar.gz"

if [[ "$PACKAGE" == http://* || "$PACKAGE" == https://* ]]; then
  log "Scarico package da $PACKAGE ..."
  curl -fL --progress-bar "$PACKAGE" -o "$TARBALL" || die "Download fallito"
elif [[ -f "$PACKAGE" ]]; then
  log "Uso tarball locale $PACKAGE"
  cp "$PACKAGE" "$TARBALL"
else
  die "Package non trovato: $PACKAGE (deve essere URL o path tar.gz)"
fi

# Verify is a valid gzip archive
file "$TARBALL" 2>/dev/null | grep -qE 'gzip|tar' || warn "File non sembra un tar.gz valido (proseguo comunque)"

# Estrai in working dir
log "Estraggo package..."
mkdir -p "$WORK_DIR/new"
tar -xzf "$TARBALL" -C "$WORK_DIR/new" || die "Estrazione fallita"

# Il tarball deve contenere una root 'backend/' o files diretti
if [[ -d "$WORK_DIR/new/backend" ]]; then
  NEW_DIR="$WORK_DIR/new/backend"
elif [[ -f "$WORK_DIR/new/server.py" ]]; then
  NEW_DIR="$WORK_DIR/new"
else
  die "Struttura tarball non riconosciuta: manca 'server.py' o cartella 'backend/'"
fi
ok "Package estratto in $NEW_DIR"

# Verifica che contenga server.py + requirements.txt + routes/
[[ -f "$NEW_DIR/server.py" ]] || die "Tarball non contiene server.py"
[[ -f "$NEW_DIR/requirements.txt" ]] || die "Tarball non contiene requirements.txt"
[[ -d "$NEW_DIR/routes" ]] || die "Tarball non contiene routes/"

# ---- Step 2: Backup attuale ----
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/backend-$TS"
mkdir -p "$BACKUP_ROOT"
log "Backup di $BACKEND_DIR -> $BACKUP_DIR ..."
cp -a "$BACKEND_DIR" "$BACKUP_DIR" || die "Backup fallito"
ok "Backup completato ($(du -sh "$BACKUP_DIR" | cut -f1))"

# ---- Step 3: Health del backend CORRENTE (per confronto) ----
log "Health check del backend corrente prima della sostituzione..."
CURRENT_HEALTH="DOWN"
if curl -sf --max-time 5 "$HEALTH_URL" -o /dev/null 2>/dev/null; then
  CURRENT_HEALTH="UP"
fi
ok "Backend corrente: $CURRENT_HEALTH"

# ---- Step 4: Conferma utente ----
echo
echo -e "${YEL}=========================================================="
echo "  RIEPILOGO PRE-DEPLOY"
echo "=========================================================="
echo "  Backend dir:        $BACKEND_DIR"
echo "  Backup creato in:   $BACKUP_DIR"
echo "  Service manager:    $SVC_MGR"
echo "  Virtualenv:         ${ARGUS_VENV_DIR:-<system pip>}"
echo "  Health endpoint:    $HEALTH_URL"
echo "  Backend corrente:   $CURRENT_HEALTH"
echo -e "==========================================================${NC}"
echo
read -r -p "Procedo con il deploy? [s/N] " ans
[[ "${ans,,}" == "s" ]] || { log "Deploy annullato"; exit 0; }

# ---- Step 5: Stop backend ----
case "$SVC_MGR" in
  systemd)
    log "Stop systemd service: $SYSTEMD_UNIT"
    systemctl stop "$SYSTEMD_UNIT" || warn "systemctl stop fallito"
    ;;
  supervisor)
    log "Stop supervisor program: $SUPERVISOR_NAME"
    supervisorctl stop "$SUPERVISOR_NAME" || warn "supervisorctl stop fallito"
    ;;
  manual)
    warn "Service manager manuale: ferma il backend manualmente prima di proseguire"
    read -r -p "Premi INVIO quando il backend e' fermo..."
    ;;
esac

# ---- Step 6: Replace files (preserva .env e data/) ----
log "Sostituisco i file del backend (preservando .env e data/) ..."
# Rinomina la dir corrente come "old" (rollback rapido se serve)
OLD_DIR="${BACKEND_DIR}.old.$TS"
mv "$BACKEND_DIR" "$OLD_DIR"

# Copia il nuovo
cp -a "$NEW_DIR" "$BACKEND_DIR"

# Restore .env e data/ dal backup
if [[ -f "$OLD_DIR/.env" ]]; then
  cp "$OLD_DIR/.env" "$BACKEND_DIR/.env"
  ok ".env preservato"
else
  warn "$OLD_DIR/.env non trovato — l'avvio del backend potrebbe fallire"
fi

if [[ -d "$OLD_DIR/data" ]]; then
  rm -rf "$BACKEND_DIR/data" 2>/dev/null || true
  cp -a "$OLD_DIR/data" "$BACKEND_DIR/data"
  ok "data/ preservato"
fi

# Mantieni eventuali keys/secrets preesistenti (es. wireguard server.key)
if [[ -d "$OLD_DIR/data/wireguard" ]]; then
  mkdir -p "$BACKEND_DIR/data/wireguard"
  cp -a "$OLD_DIR/data/wireguard/." "$BACKEND_DIR/data/wireguard/" 2>/dev/null || true
fi

# ---- Step 7: pip install ----
PIP_BIN="${ARGUS_VENV_DIR:+$ARGUS_VENV_DIR/bin/}pip"
log "Installo dipendenze (pip install -r requirements.txt) ..."
"$PIP_BIN" install --no-input --quiet --upgrade pip 2>&1 | tail -3 || true
"$PIP_BIN" install --no-input --quiet -r "$BACKEND_DIR/requirements.txt" 2>&1 | tail -10
ok "pip install completato"

# ---- Step 8: Restart backend ----
case "$SVC_MGR" in
  systemd)
    log "Start systemd: $SYSTEMD_UNIT"
    systemctl start "$SYSTEMD_UNIT"
    ;;
  supervisor)
    log "Start supervisor: $SUPERVISOR_NAME"
    supervisorctl start "$SUPERVISOR_NAME"
    ;;
  manual)
    warn "Service manager manuale: avvia ora il backend manualmente"
    read -r -p "Premi INVIO quando il backend e' partito..."
    ;;
esac

# ---- Step 9: Health check post-deploy con retry ----
log "Health check post-deploy (max ${HEALTH_TIMEOUT}s)..."
HEALTHY=0
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
  if curl -sf --max-time 3 "$HEALTH_URL" -o /dev/null 2>/dev/null; then
    HEALTHY=1
    break
  fi
  # Anche un 401/422 indica che FastAPI sta rispondendo
  CODE=$(curl -s -o /dev/null --max-time 3 -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
  if [[ "$CODE" =~ ^(200|401|403|422|404)$ ]]; then
    HEALTHY=1
    break
  fi
  sleep 1
  printf "."
done
echo

if [[ "$HEALTHY" == "1" ]]; then
  ok "Backend nuovo risponde correttamente"
else
  err "Backend nuovo NON risponde dopo ${HEALTH_TIMEOUT}s — eseguo ROLLBACK..."
  # ---- Rollback ----
  case "$SVC_MGR" in
    systemd)    systemctl stop "$SYSTEMD_UNIT" || true ;;
    supervisor) supervisorctl stop "$SUPERVISOR_NAME" || true ;;
  esac
  rm -rf "$BACKEND_DIR"
  mv "$OLD_DIR" "$BACKEND_DIR"
  case "$SVC_MGR" in
    systemd)    systemctl start "$SYSTEMD_UNIT" ;;
    supervisor) supervisorctl start "$SUPERVISOR_NAME" ;;
  esac
  err "Rollback completato. Backend ripristinato dalla versione $TS."
  err "Log da verificare: journalctl -u $SYSTEMD_UNIT  (o /var/log/supervisor/${SUPERVISOR_NAME}.err.log)"
  exit 2
fi

# ---- Step 10: Cleanup ----
log "Rimuovo old dir $OLD_DIR..."
rm -rf "$OLD_DIR" || warn "Cleanup old dir fallito (puoi rimuovere a mano)"

# ---- Done ----
cat <<EOF

${GREEN}============================================================
  DEPLOY COMPLETATO CON SUCCESSO
============================================================${NC}
  Backup precedente:  $BACKUP_DIR
  Per rollback manuale:
    sudo systemctl stop $SYSTEMD_UNIT  (o supervisorctl)
    sudo rm -rf $BACKEND_DIR
    sudo mv $BACKUP_DIR $BACKEND_DIR
    sudo systemctl start $SYSTEMD_UNIT

  Backup vecchi (>30 giorni) puoi rimuoverli con:
    find $BACKUP_ROOT -maxdepth 1 -name 'backend-*' -mtime +30 -exec rm -rf {} \;

  Per attivare il server WireGuard EMBEDDED ora:
    1) Aggiungi al file $BACKEND_DIR/.env:
         WG_EMBEDDED_ENABLED=true
         WG_SERVER_HOST=argus.86bit.it
    2) Riavvia il backend:
         sudo systemctl restart $SYSTEMD_UNIT
    3) Apri il Center -> Impostazioni -> WireGuard
       Vedrai il banner "Server WireGuard Embedded" verde con "RUNTIME ATTIVO"

EOF
