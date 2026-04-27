#!/usr/bin/env bash
#
# ARGUS Center - FULL UPDATE (backend + frontend) in 1 comando
# =============================================================
# Aggiorna ENTRAMBI in una sola esecuzione, con backup e rollback automatico.
# Lo lanci 1 volta sola via SSH; dopo questo, gli update successivi
# sono 1-click dalla UI grazie al pulsante "Aggiorna Backend".
#
# Usage:
#   curl -fL https://argus.86bit.it/downloads/full-update.sh | sudo bash
# Oppure:
#   sudo bash full-update.sh
#

set +e

# Default URL (cdn pubblico del Center stesso)
HOST="${ARGUS_HOST:-argus.86bit.it}"
BACKEND_URL="https://${HOST}/downloads/argus-backend-latest.tar.gz"
FRONTEND_URL="https://${HOST}/downloads/argus-frontend-latest.tar.gz"

# Path defaults (override con env var se diversi)
BACKEND_DIR="${ARGUS_BACKEND_DIR:-}"
FRONTEND_DIR="${ARGUS_FRONTEND_DIR:-}"
BACKUP_ROOT="${ARGUS_BACKUP_ROOT:-/opt/argus/backups}"

# Logging
GREEN='\033[0;32m'; YEL='\033[1;33m'; RED='\033[0;31m'; CYN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYN}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YEL}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

cat <<'EOF'
============================================================
  ARGUS Center - FULL UPDATE (backend + frontend)
============================================================
EOF

[[ $EUID -eq 0 ]] || die "Devi essere root: rilancia con 'sudo bash $0'"

# ---- Auto-detect BACKEND_DIR ----
if [[ -z "$BACKEND_DIR" ]]; then
  for cand in /opt/argus/backend /srv/argus/backend /var/argus/backend /home/argus/backend; do
    if [[ -f "$cand/server.py" ]]; then BACKEND_DIR="$cand"; break; fi
  done
  if [[ -z "$BACKEND_DIR" ]]; then
    # Cerca dovunque
    BACKEND_DIR=$(find /opt /srv /var /home -name "server.py" -path "*backend*" 2>/dev/null | head -1 | xargs -r dirname)
  fi
fi
[[ -d "$BACKEND_DIR" ]] || die "Backend dir non trovata. Setta ARGUS_BACKEND_DIR=/path/al/backend e riprova."
ok "Backend dir: $BACKEND_DIR"

# ---- Auto-detect FRONTEND_DIR ----
if [[ -z "$FRONTEND_DIR" ]]; then
  for cand in /opt/argus/frontend/build /var/www/argus /var/www/html/argus /usr/share/nginx/html/argus /opt/argus/frontend; do
    if [[ -f "$cand/index.html" ]] && grep -q "ARGUS\|argus\|root.*react" "$cand/index.html" 2>/dev/null; then
      FRONTEND_DIR="$cand"; break;
    fi
  done
  if [[ -z "$FRONTEND_DIR" ]]; then
    # Look for any index.html that mentions ARGUS
    FRONTEND_DIR=$(grep -rl "ARGUS" /var/www /opt/argus /usr/share/nginx /srv 2>/dev/null | grep "index.html$" | head -1 | xargs -r dirname)
  fi
fi
[[ -d "$FRONTEND_DIR" && -f "$FRONTEND_DIR/index.html" ]] || die "Frontend dir non trovata. Setta ARGUS_FRONTEND_DIR=/path/al/frontend/build e riprova."
ok "Frontend dir: $FRONTEND_DIR"

# ---- Auto-detect service manager ----
SVC_MGR="manual"
SYSTEMD_UNIT="${ARGUS_SYSTEMD_UNIT:-argus-backend}"
SUPERVISOR_NAME="${ARGUS_SUPERVISOR_NAME:-backend}"
if systemctl list-units --type=service 2>/dev/null | grep -q "$SYSTEMD_UNIT"; then
  SVC_MGR="systemd"
elif command -v supervisorctl >/dev/null && supervisorctl status "$SUPERVISOR_NAME" >/dev/null 2>&1; then
  SVC_MGR="supervisor"
fi
ok "Service manager: $SVC_MGR"

# ---- Auto-detect virtualenv ----
PIP_BIN="pip3"
for cand in "${ARGUS_VENV_DIR:-}/bin/pip" "$BACKEND_DIR/../venv/bin/pip" "$BACKEND_DIR/../.venv/bin/pip" /opt/argus/.venv/bin/pip /opt/argus/venv/bin/pip /root/.venv/bin/pip; do
  if [[ -x "$cand" ]]; then PIP_BIN="$cand"; break; fi
done
ok "pip: $PIP_BIN"

# ---- Riepilogo ----
echo
echo -e "${YEL}=========================================================="
echo "  RIEPILOGO PRE-DEPLOY"
echo "=========================================================="
echo "  Backend dir:    $BACKEND_DIR"
echo "  Frontend dir:   $FRONTEND_DIR"
echo "  Service:        $SVC_MGR ($SYSTEMD_UNIT|$SUPERVISOR_NAME)"
echo "  Pip:            $PIP_BIN"
echo "  Backend pkg:    $BACKEND_URL"
echo "  Frontend pkg:   $FRONTEND_URL"
echo "  Backup root:    $BACKUP_ROOT"
echo -e "==========================================================${NC}"
echo
read -r -p "Procedo? [s/N] " ans </dev/tty || ans="s"
[[ "${ans,,}" == "s" ]] || { log "Annullato"; exit 0; }

# ---- Step 1: Download both tarballs ----
WORK=$(mktemp -d -t argus-fullupd-XXXXXX)
trap 'rm -rf "$WORK"' EXIT

log "Scarico backend tarball..."
curl -fL --max-time 120 "$BACKEND_URL" -o "$WORK/backend.tar.gz" || die "Download backend fallito"
SZ=$(stat -c %s "$WORK/backend.tar.gz")
[[ "$SZ" -gt 100000 ]] || die "Backend tarball troppo piccolo ($SZ bytes)"
ok "Backend $((SZ/1024)) KB"

log "Scarico frontend tarball..."
curl -fL --max-time 120 "$FRONTEND_URL" -o "$WORK/frontend.tar.gz" || die "Download frontend fallito"
SZ=$(stat -c %s "$WORK/frontend.tar.gz")
[[ "$SZ" -gt 100000 ]] || die "Frontend tarball troppo piccolo ($SZ bytes)"
ok "Frontend $((SZ/1024)) KB"

# ---- Step 2: Estrai entrambi ----
mkdir -p "$WORK/be" "$WORK/fe"
tar -xzf "$WORK/backend.tar.gz" -C "$WORK/be" || die "Extract backend fallito"
tar -xzf "$WORK/frontend.tar.gz" -C "$WORK/fe" || die "Extract frontend fallito"

NEW_BE="$WORK/be/backend"; [[ -d "$NEW_BE" ]] || NEW_BE="$WORK/be"
NEW_FE="$WORK/fe/build";    [[ -d "$NEW_FE" ]] || NEW_FE="$WORK/fe"
[[ -f "$NEW_BE/server.py" ]] || die "Backend tarball: manca server.py"
[[ -f "$NEW_FE/index.html" ]] || die "Frontend tarball: manca index.html"
ok "Tarball validi"

# ---- Step 3: Backup ----
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_ROOT"
log "Backup backend e frontend correnti..."
cp -a "$BACKEND_DIR" "$BACKUP_ROOT/backend-$TS"
cp -a "$FRONTEND_DIR" "$BACKUP_ROOT/frontend-$TS"
ok "Backup OK ($BACKUP_ROOT/{backend,frontend}-$TS)"

# ---- Step 4: Deploy backend (con preserve .env + data/) ----
log "Stop backend..."
case "$SVC_MGR" in
  systemd)    systemctl stop "$SYSTEMD_UNIT" ;;
  supervisor) supervisorctl stop "$SUPERVISOR_NAME" ;;
esac
sleep 2

log "Sostituisco backend (preservando .env e data/)..."
OLD_BE="${BACKEND_DIR}.old.$TS"
mv "$BACKEND_DIR" "$OLD_BE" || die "mv backend fallito"
cp -a "$NEW_BE" "$BACKEND_DIR"
[[ -f "$OLD_BE/.env" ]] && cp "$OLD_BE/.env" "$BACKEND_DIR/.env"
if [[ -d "$OLD_BE/data" ]]; then
  rm -rf "$BACKEND_DIR/data"
  cp -a "$OLD_BE/data" "$BACKEND_DIR/data"
fi

log "pip install..."
"$PIP_BIN" install --no-input --quiet -r "$BACKEND_DIR/requirements.txt" 2>&1 | tail -5

# ---- Step 5: Deploy frontend ----
log "Sostituisco frontend..."
# Salva i file 'public/' specifici (downloads, assets) che potrebbero essere servizi separati
# In realta` semplifico: cancello tutto e copio il build pulito
find "$FRONTEND_DIR" -mindepth 1 -delete 2>/dev/null
cp -a "$NEW_FE/." "$FRONTEND_DIR/"
ok "Frontend deployato"

# ---- Step 6: Start backend + health check ----
log "Start backend..."
case "$SVC_MGR" in
  systemd)    systemctl start "$SYSTEMD_UNIT" ;;
  supervisor) supervisorctl start "$SUPERVISOR_NAME" ;;
esac

log "Health check post-deploy..."
HEALTHY=0
for i in $(seq 1 30); do
  CODE=$(curl -s -o /dev/null --max-time 3 -w "%{http_code}" "http://127.0.0.1:8001/api/health" 2>/dev/null || echo "000")
  if [[ "$CODE" =~ ^(200|401|403|404|422)$ ]]; then HEALTHY=1; break; fi
  sleep 1; printf "."
done
echo

if [[ "$HEALTHY" != "1" ]]; then
  err "Backend non risponde - ROLLBACK..."
  case "$SVC_MGR" in
    systemd)    systemctl stop "$SYSTEMD_UNIT" ;;
    supervisor) supervisorctl stop "$SUPERVISOR_NAME" ;;
  esac
  rm -rf "$BACKEND_DIR" && mv "$OLD_BE" "$BACKEND_DIR"
  rm -rf "$FRONTEND_DIR"/* && cp -a "$BACKUP_ROOT/frontend-$TS/." "$FRONTEND_DIR/"
  case "$SVC_MGR" in
    systemd)    systemctl start "$SYSTEMD_UNIT" ;;
    supervisor) supervisorctl start "$SUPERVISOR_NAME" ;;
  esac
  err "Rollback completato. Backup conservato in $BACKUP_ROOT/{backend,frontend}-$TS"
  exit 2
fi

# ---- Step 7: Reload nginx (best effort) ----
nginx -s reload 2>/dev/null || systemctl reload nginx 2>/dev/null || true
ok "Backend risponde"

# ---- Cleanup ----
rm -rf "$OLD_BE" 2>/dev/null

cat <<EOF

${GREEN}============================================================
  FULL UPDATE COMPLETATO
============================================================${NC}
  Backup conservati in:
    $BACKUP_ROOT/backend-$TS
    $BACKUP_ROOT/frontend-$TS

  COSA FARE ORA:
  1) Apri il Center (e fai HARD REFRESH: Ctrl+Shift+R)
  2) Vai a Impostazioni -> WireGuard
  3) Dovresti vedere 2 banner nuovi:
     - 'Aggiorna Backend Center' (cyan)
     - 'Server WireGuard Embedded' (verde/ambra/rosso)
  4) Da qui in poi, gli aggiornamenti futuri sono 1-click dalla UI.

EOF
