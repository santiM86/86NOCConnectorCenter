#!/usr/bin/env bash
# ============================================================================
# verify-prod-deploy.sh
# ============================================================================
# Script di verifica che il server PROD di NOC Center (Argus) abbia tutte le
# modifiche critiche dell'ultima sessione di sviluppo.
#
# Da lanciare SUL SERVER PROD (NON nell'ambiente preview).
#
# Path PROD atteso: /home/arslan/86NOCConnectorCenter
# Servizio backend: noc-backend.service (porta 127.0.0.1:8186)
#
# Uso:
#   chmod +x verify-prod-deploy.sh
#   ./verify-prod-deploy.sh
# ============================================================================

set -u

REPO="${REPO:-/home/arslan/86NOCConnectorCenter}"
BACKEND="$REPO/backend"
AGENT="$REPO/noc-agent"
FRONTEND="$REPO/frontend"
SERVICE="${SERVICE:-noc-backend}"
PORT="${PORT:-8186}"

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
NC="\033[0m"

OK=0
FAIL=0
WARN=0

pass() { echo -e "  ${GREEN}✓${NC} $1"; OK=$((OK+1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; WARN=$((WARN+1)); }
info() { echo -e "  ${CYAN}ℹ${NC} $1"; }

section() { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

# ────────────────────────────────────────────────────────────────────────────
section "0. Repo path e branch"
# ────────────────────────────────────────────────────────────────────────────
if [ -d "$REPO/.git" ]; then
  pass "Repo trovato: $REPO"
  cd "$REPO" || exit 1
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
  LASTCOMMIT=$(git log -1 --format="%cr · %s" 2>/dev/null || echo "?")
  info "Branch corrente : $BRANCH"
  info "HEAD commit     : $HEAD"
  info "Ultimo commit   : $LASTCOMMIT"
else
  fail "Repo NON trovato in $REPO — modifica la variabile REPO in cima allo script"
  exit 2
fi

# Controlla se siamo aggiornati col remote
git fetch --quiet origin 2>/dev/null || warn "git fetch fallito (no network o credenziali)"
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/"$BRANCH" 2>/dev/null || echo "")
if [ -n "$REMOTE" ] && [ "$LOCAL" = "$REMOTE" ]; then
  pass "Repo locale ALLINEATO con origin/$BRANCH"
elif [ -n "$REMOTE" ]; then
  fail "Repo locale NON allineato → manca un git pull. local=$LOCAL remote=$REMOTE"
  echo -e "${YELLOW}   FIX: cd $REPO && git pull origin $BRANCH${NC}"
fi

# ────────────────────────────────────────────────────────────────────────────
section "1. Backend — fix anti-flap + ARP promote + SNMP-only liveness"
# ────────────────────────────────────────────────────────────────────────────
if [ -f "$BACKEND/routes/devices.py" ]; then
  pass "backend/routes/devices.py esiste"
  grep -q "arp_alive_recent" "$BACKEND/routes/devices.py" \
    && pass "FIX ARP promote → online presente (arp_alive_recent)" \
    || fail "FIX ARP promote MANCA — il device offline pur visto da Scanner LAN"
  grep -q "snmp_alive_recent" "$BACKEND/routes/devices.py" \
    && pass "FIX SNMP-only liveness presente (snmp_alive_recent)" \
    || fail "FIX SNMP-only liveness MANCA — device ICMP-blocked appariranno offline"
  grep -q "consecutive_ping_failures" "$BACKEND/routes/devices.py" \
    && pass "Anti-flap counter presente (consecutive_ping_failures)" \
    || warn "consecutive_ping_failures non trovato in devices.py"
else
  fail "backend/routes/devices.py MANCA"
fi

if [ -f "$BACKEND/routes/agent_ws.py" ]; then
  pass "backend/routes/agent_ws.py esiste"
  grep -q "snmp_reachable" "$BACKEND/routes/agent_ws.py" \
    && pass "FIX SNMP poll non degrada offline presente (snmp_reachable)" \
    || fail "FIX SNMP poll MANCA — SNMP fallito sovrascriverà status=offline"
else
  fail "backend/routes/agent_ws.py MANCA"
fi

# ────────────────────────────────────────────────────────────────────────────
section "2. Backend — FIX vault AES-GCM (Hornetsecurity + Datto)"
# ────────────────────────────────────────────────────────────────────────────
if [ -f "$BACKEND/services/hornetsecurity_poller.py" ]; then
  grep -q "vault_mismatch" "$BACKEND/services/hornetsecurity_poller.py" \
    && pass "FIX vault_mismatch Hornetsecurity (365 backup) presente" \
    || fail "FIX Hornetsecurity 365 vault MANCA — 500 al primo poll dopo rotation"
else
  fail "backend/services/hornetsecurity_poller.py MANCA"
fi

if [ -f "$BACKEND/services/hornetsecurity_vmbackup_poller.py" ]; then
  grep -q "vault_mismatch" "$BACKEND/services/hornetsecurity_vmbackup_poller.py" \
    && pass "FIX vault_mismatch Hornetsecurity VM backup presente" \
    || fail "FIX Hornetsecurity VM backup vault MANCA — Decryption failed ogni minuto nei log"
else
  warn "backend/services/hornetsecurity_vmbackup_poller.py MANCA (modulo opzionale)"
fi

if [ -f "$BACKEND/routes/datto_rmm.py" ]; then
  grep -q "vault_mismatch" "$BACKEND/routes/datto_rmm.py" \
    && pass "FIX vault_mismatch Datto RMM presente" \
    || fail "FIX Datto vault MANCA — sync Datto fallirà dopo rotation key"
else
  fail "backend/routes/datto_rmm.py MANCA"
fi

# ────────────────────────────────────────────────────────────────────────────
section "3. Backend — endpoint /api/agent/install/setup.zip"
# ────────────────────────────────────────────────────────────────────────────
if [ -f "$BACKEND/routes/install_setup.py" ]; then
  pass "backend/routes/install_setup.py esiste (Setup .exe ZIP generator)"
  grep -q "setup.zip" "$BACKEND/routes/install_setup.py" \
    && pass "Endpoint setup.zip definito" \
    || warn "stringa 'setup.zip' non trovata in install_setup.py"
  # ROLE deve essere opzionale: viene scritto solo se passato in query
  if grep -q 'ROLE=' "$BACKEND/routes/install_setup.py"; then
    if grep -q "if.*role" "$BACKEND/routes/install_setup.py" || \
       grep -q "role and" "$BACKEND/routes/install_setup.py"; then
      pass "ROLE opzionale (installer GUI chiederà Master/Scanner)"
    else
      warn "ROLE potrebbe essere sempre baked-in — verifica manualmente"
    fi
  fi
else
  fail "backend/routes/install_setup.py MANCA — pulsante 'Setup .exe' nella UI non funzionerà"
fi

# Endpoint registrato in server.py
if [ -f "$BACKEND/server.py" ]; then
  grep -q "install_setup" "$BACKEND/server.py" \
    && pass "install_setup_router registrato in server.py" \
    || fail "install_setup_router NON registrato in server.py"
fi

# ────────────────────────────────────────────────────────────────────────────
section "4. Go Agent — Store-and-Forward (BBolt spool)"
# ────────────────────────────────────────────────────────────────────────────
if [ -d "$AGENT/internal/spool" ]; then
  pass "noc-agent/internal/spool/ directory esiste"
  [ -f "$AGENT/internal/spool/spool.go" ] && pass "spool.go presente" || fail "spool.go MANCA"
  [ -f "$AGENT/internal/spool/spool_test.go" ] && pass "spool_test.go presente" || warn "spool_test.go non trovato"
else
  fail "noc-agent/internal/spool/ MANCA — agent perderà dati durante drop di rete"
fi

if [ -f "$AGENT/go.mod" ]; then
  grep -q "go.etcd.io/bbolt" "$AGENT/go.mod" \
    && pass "Dipendenza bbolt presente in go.mod" \
    || fail "bbolt NON in go.mod — spool non compilera'"
fi

if [ -f "$AGENT/cmd/installer/main.go" ]; then
  grep -q 'v4\.0\.0' "$AGENT/cmd/installer/main.go" \
    && warn "Trovato hardcode 'v4.0.0' in installer (forse fix non applicato)" \
    || pass "Hardcode v4.0.0 rimosso da cmd/installer/main.go"
fi

# ────────────────────────────────────────────────────────────────────────────
section "5. Frontend — pulsante Setup .exe (menu a tendina Master/Scanner)"
# ────────────────────────────────────────────────────────────────────────────
if [ -f "$FRONTEND/src/pages/ClientsPage.js" ]; then
  grep -q "setup.zip" "$FRONTEND/src/pages/ClientsPage.js" \
    && pass "ClientsPage.js usa /api/agent/install/setup.zip" \
    || fail "ClientsPage.js non punta a setup.zip — bottone Setup .exe non funziona"

  # Verifica menu a tendina (master + scanner)
  ROLE_VARIANTS=$(grep -c 'role=' "$FRONTEND/src/pages/ClientsPage.js" 2>/dev/null || echo 0)
  if [ "$ROLE_VARIANTS" -ge 2 ]; then
    pass "Menu Setup .exe ha varianti master/scanner ($ROLE_VARIANTS link role=)"
  else
    warn "Solo $ROLE_VARIANTS link 'role=' trovati — verifica dropdown manualmente"
  fi
else
  fail "frontend/src/pages/ClientsPage.js MANCA"
fi

# ────────────────────────────────────────────────────────────────────────────
section "6. Servizio backend in esecuzione"
# ────────────────────────────────────────────────────────────────────────────
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet "$SERVICE"; then
    pass "Servizio $SERVICE è ATTIVO"
    UPTIME=$(systemctl show -p ActiveEnterTimestamp --value "$SERVICE" 2>/dev/null)
    info "Uptime servizio: $UPTIME"
  else
    fail "Servizio $SERVICE NON attivo — sudo systemctl start $SERVICE"
  fi
else
  warn "systemctl non disponibile — skip check servizio"
fi

# Endpoint health
if command -v curl >/dev/null 2>&1; then
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:$PORT/api/agent/install/setup.zip" 2>/dev/null || echo "000")
  case "$CODE" in
    200|400|401|403|422)
      pass "Endpoint /api/agent/install/setup.zip risponde (HTTP $CODE — token mancante atteso)"
      ;;
    404)
      fail "/api/agent/install/setup.zip → 404 → l'endpoint NON è registrato (manca git pull o restart)"
      ;;
    000)
      warn "Backend non raggiungibile su 127.0.0.1:$PORT"
      ;;
    *)
      warn "Endpoint risponde con HTTP $CODE (inatteso)"
      ;;
  esac
fi

# ────────────────────────────────────────────────────────────────────────────
section "Riepilogo"
# ────────────────────────────────────────────────────────────────────────────
echo -e "  ${GREEN}OK${NC}    : $OK"
echo -e "  ${YELLOW}WARN${NC}  : $WARN"
echo -e "  ${RED}FAIL${NC}  : $FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo -e "\n${RED}❌ DEPLOY INCOMPLETO${NC}"
  echo -e "${YELLOW}Azioni richieste sul server PROD:${NC}"
  echo -e "  cd $REPO"
  echo -e "  git pull origin $BRANCH"
  echo -e "  sudo systemctl restart $SERVICE"
  echo -e "  sudo journalctl -u $SERVICE -n 50 --no-pager   # verifica boot"
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo -e "\n${YELLOW}⚠️  Deploy OK con qualche warning (rivedi sopra)${NC}"
  exit 0
else
  echo -e "\n${GREEN}✅ DEPLOY ALLINEATO — tutti i fix sono in PROD${NC}"
  exit 0
fi
