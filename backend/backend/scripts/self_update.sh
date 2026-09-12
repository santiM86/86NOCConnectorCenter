#!/usr/bin/env bash
#
# ARGUS Center - Self-Update runner
# ==================================
# Eseguito come subprocess detached dal backend FastAPI quando l'admin
# clicca "Aggiorna Backend" nella UI. Scarica il nuovo backend, fa backup,
# rimpiazza file (preservando .env e data/), pip install, restart, health check.
# Aggiorna /tmp/argus-update-status.json a ogni fase per la UI in tempo reale.
#
# Args:
#   $1 = URL del tarball
#   $2 = path file status JSON (default /tmp/argus-update-status.json)
#   $3 = backend_dir (default /opt/argus/backend, override da env ARGUS_BACKEND_DIR)
#   $4 = enable_wg (true/false): se true, aggiunge WG_EMBEDDED_ENABLED=true al .env
#   $5 = wg_host: hostname per WG_SERVER_HOST (es. argus.86bit.it)
#

set +e   # NON usiamo exit-on-error: vogliamo gestire ogni fallimento per scrivere lo status

URL="${1:?missing URL}"
STATUS_FILE="${2:-/tmp/argus-update-status.json}"
BACKEND_DIR="${3:-${ARGUS_BACKEND_DIR:-/opt/argus/backend}}"
ENABLE_WG="${4:-false}"
WG_HOST="${5:-}"

LOG_FILE="/tmp/argus-update-runner.log"
exec >>"$LOG_FILE" 2>&1
echo "==================== self_update.sh start $(date -Iseconds) ===================="
echo "URL=$URL  BACKEND_DIR=$BACKEND_DIR  ENABLE_WG=$ENABLE_WG  WG_HOST=$WG_HOST"

write_status() {
  local phase="$1" progress="$2" message="$3" error="${4:-}"
  python3 - "$STATUS_FILE" "$phase" "$progress" "$message" "$error" <<'PYEOF'
import json, sys, os, time
status_file, phase, progress, message, error = sys.argv[1:6]
data = {
    "phase": phase,
    "progress": int(progress),
    "message": message,
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
if error:
    data["error"] = error
tmp = status_file + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f)
os.replace(tmp, status_file)
PYEOF
}

fail() {
  local msg="$1"
  echo "FAIL: $msg"
  write_status "failed" 0 "$msg" "$msg"
  exit 1
}

write_status "starting" 5 "Avvio aggiornamento..."
sleep 1   # lascia tempo all'endpoint API di rispondere 202

# -- Detect service manager --
SVC_MGR="manual"
SYSTEMD_UNIT="${ARGUS_SYSTEMD_UNIT:-argus-backend}"
SUPERVISOR_NAME="${ARGUS_SUPERVISOR_NAME:-backend}"
if systemctl list-units --type=service 2>/dev/null | grep -q "$SYSTEMD_UNIT"; then
  SVC_MGR="systemd"
elif command -v supervisorctl >/dev/null && supervisorctl status "$SUPERVISOR_NAME" >/dev/null 2>&1; then
  SVC_MGR="supervisor"
fi
echo "service_manager=$SVC_MGR"

# -- Detect virtualenv --
PIP_BIN="pip"
if [[ -n "${ARGUS_VENV_DIR:-}" && -x "$ARGUS_VENV_DIR/bin/pip" ]]; then
  PIP_BIN="$ARGUS_VENV_DIR/bin/pip"
else
  for cand in "$BACKEND_DIR/../venv" "$BACKEND_DIR/../.venv" /opt/argus/.venv /opt/argus/venv /root/.venv; do
    if [[ -x "$cand/bin/pip" ]]; then PIP_BIN="$cand/bin/pip"; break; fi
  done
fi
echo "pip=$PIP_BIN"

# -- Step 1: Download --
write_status "downloading" 15 "Scarico nuovo backend da $URL"
WORK=$(mktemp -d -t argus-selfupd-XXXXXX)
trap 'rm -rf "$WORK"' EXIT
TARBALL="$WORK/package.tar.gz"
if ! curl -fL --max-time 120 "$URL" -o "$TARBALL"; then
  fail "Download del package fallito"
fi
SIZE=$(stat -c %s "$TARBALL" 2>/dev/null || echo 0)
[[ "$SIZE" -lt 100000 ]] && fail "Tarball troppo piccolo ($SIZE bytes), URL probabilmente sbagliato"
echo "downloaded $SIZE bytes"

# -- Step 2: Estrazione --
write_status "extracting" 25 "Estraggo package..."
mkdir -p "$WORK/new"
if ! tar -xzf "$TARBALL" -C "$WORK/new"; then
  fail "Estrazione tarball fallita"
fi
if [[ -d "$WORK/new/backend" ]]; then
  NEW_DIR="$WORK/new/backend"
elif [[ -f "$WORK/new/server.py" ]]; then
  NEW_DIR="$WORK/new"
else
  fail "Struttura tarball non valida (manca server.py o cartella backend/)"
fi
[[ -f "$NEW_DIR/server.py" ]] || fail "Tarball senza server.py"
[[ -f "$NEW_DIR/requirements.txt" ]] || fail "Tarball senza requirements.txt"

# -- Step 3: Backup --
write_status "backing-up" 35 "Backup del backend corrente..."
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="${ARGUS_BACKUP_ROOT:-/opt/argus/backups}/backend-$TS"
mkdir -p "$(dirname "$BACKUP_DIR")"
if ! cp -a "$BACKEND_DIR" "$BACKUP_DIR"; then
  fail "Backup fallito (controlla permessi e disk space)"
fi
echo "backup_dir=$BACKUP_DIR"

# -- Step 4: Stop backend --
write_status "stopping" 45 "Stop backend corrente..."
case "$SVC_MGR" in
  systemd)    systemctl stop "$SYSTEMD_UNIT" ;;
  supervisor) supervisorctl stop "$SUPERVISOR_NAME" ;;
  manual)     echo "WARNING: no service manager, backend non viene fermato" ;;
esac
sleep 2

# -- Step 5: Replace files --
write_status "replacing" 55 "Sostituisco file (preservando .env e data/)..."
OLD_DIR="${BACKEND_DIR}.old.$TS"
mv "$BACKEND_DIR" "$OLD_DIR" || fail "mv backend_dir->old fallito"
cp -a "$NEW_DIR" "$BACKEND_DIR" || fail "cp nuovo backend fallito"

# Restore .env
if [[ -f "$OLD_DIR/.env" ]]; then
  cp "$OLD_DIR/.env" "$BACKEND_DIR/.env"
fi
# Restore data/
if [[ -d "$OLD_DIR/data" ]]; then
  rm -rf "$BACKEND_DIR/data"
  cp -a "$OLD_DIR/data" "$BACKEND_DIR/data"
fi

# -- Step 5b: Update .env per WireGuard se richiesto --
if [[ "$ENABLE_WG" == "true" ]]; then
  ENV_FILE="$BACKEND_DIR/.env"
  if ! grep -q "^WG_EMBEDDED_ENABLED=" "$ENV_FILE" 2>/dev/null; then
    echo "WG_EMBEDDED_ENABLED=true" >> "$ENV_FILE"
    echo "added WG_EMBEDDED_ENABLED=true to .env"
  fi
  if [[ -n "$WG_HOST" ]] && ! grep -q "^WG_SERVER_HOST=" "$ENV_FILE" 2>/dev/null; then
    echo "WG_SERVER_HOST=$WG_HOST" >> "$ENV_FILE"
    echo "added WG_SERVER_HOST=$WG_HOST to .env"
  fi
fi

# -- Step 5c: Apertura firewall UDP 51820 (best-effort, solo se ufw c'e' e siamo root) --
if [[ "$ENABLE_WG" == "true" ]] && command -v ufw >/dev/null && [[ $EUID -eq 0 ]]; then
  if ! ufw status | grep -q "51820/udp"; then
    echo "ufw allow 51820/udp"
    ufw allow 51820/udp >/dev/null 2>&1 || echo "ufw allow fallito (non bloccante)"
  fi
fi

# -- Step 6: pip install --
write_status "installing" 70 "Installo dipendenze Python..."
if ! "$PIP_BIN" install --no-input --quiet -r "$BACKEND_DIR/requirements.txt"; then
  echo "pip install fallito - rollback"
  rm -rf "$BACKEND_DIR"
  mv "$OLD_DIR" "$BACKEND_DIR"
  case "$SVC_MGR" in
    systemd)    systemctl start "$SYSTEMD_UNIT" ;;
    supervisor) supervisorctl start "$SUPERVISOR_NAME" ;;
  esac
  fail "pip install fallito - eseguito ROLLBACK alla versione precedente"
fi

# -- Step 7: Start backend --
write_status "starting-backend" 85 "Riavvio backend..."
case "$SVC_MGR" in
  systemd)    systemctl start "$SYSTEMD_UNIT" ;;
  supervisor) supervisorctl start "$SUPERVISOR_NAME" ;;
esac

# -- Step 8: Health check con retry --
write_status "health-check" 92 "Verifico che il nuovo backend risponda..."
HEALTH_URL="${ARGUS_HEALTH_URL:-http://127.0.0.1:8001/api/health}"
HEALTHY=0
for i in $(seq 1 30); do
  CODE=$(curl -s -o /dev/null --max-time 3 -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
  if [[ "$CODE" =~ ^(200|401|403|404|422)$ ]]; then
    HEALTHY=1
    break
  fi
  sleep 1
done

if [[ "$HEALTHY" != "1" ]]; then
  echo "HEALTH CHECK FALLITO - rollback automatico"
  case "$SVC_MGR" in
    systemd)    systemctl stop "$SYSTEMD_UNIT" ;;
    supervisor) supervisorctl stop "$SUPERVISOR_NAME" ;;
  esac
  rm -rf "$BACKEND_DIR"
  mv "$OLD_DIR" "$BACKEND_DIR"
  case "$SVC_MGR" in
    systemd)    systemctl start "$SYSTEMD_UNIT" ;;
    supervisor) supervisorctl start "$SUPERVISOR_NAME" ;;
  esac
  fail "Il nuovo backend non risponde - eseguito ROLLBACK alla versione precedente"
fi

# -- Step 9: Cleanup --
write_status "cleanup" 98 "Pulizia file temporanei..."
rm -rf "$OLD_DIR" 2>/dev/null

# -- Done --
write_status "done" 100 "Aggiornamento completato. Backup salvato in $BACKUP_DIR"
echo "==================== self_update.sh OK $(date -Iseconds) ===================="
