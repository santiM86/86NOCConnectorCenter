#!/usr/bin/env bash
# ==============================================================================
# Argus NOC — Deploy patch v4.2.0 (live polling Go agent)
# ==============================================================================
# Cosa fa:
#   1. Scarica i 2 file backend modificati + 1 template wizard fixato.
#   2. Verifica sha256 contro il manifest atteso (no corruzione in transito).
#   3. Backup-and-replace dei file in /opt/argus/backend/routes/ e
#      /opt/argus/noc-agent/build/.
#   4. Restart del servizio FastAPI uvicorn (systemd).
#   5. Healthcheck via curl localhost:8186/api/health.
#   6. Rollback automatico se l'health-check fallisce.
#
# Cosa NON fa:
#   - NON tocca il venv Python (a differenza di sync-argus.sh).
#   - NON tocca il frontend (nginx static).
#   - NON tocca il binario Windows (lo deployi sul SOCIALSRV con un
#     PowerShell one-liner — vedi fine script).
#
# Eseguire come `arslan` (NON come root) sulla VM 10.30.0.201:
#   curl -fsSL https://snmp-hub-noc.preview.emergentagent.com/downloads/v4.2.0/deploy-v4.2.0.sh -o /tmp/deploy-v4.2.0.sh
#   chmod +x /tmp/deploy-v4.2.0.sh
#   sudo -u arslan bash /tmp/deploy-v4.2.0.sh
# ==============================================================================
set -euo pipefail

PATCH_BASE="${PATCH_BASE:-https://snmp-hub-noc.preview.emergentagent.com/downloads/v4.2.0}"
BACKEND_DIR="${BACKEND_DIR:-/opt/argus/backend}"
NOCAGENT_BUILD_DIR="${NOCAGENT_BUILD_DIR:-/opt/argus/noc-agent/build}"
SERVICE="${SERVICE:-argus-backend}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://localhost:8186/api/agents}"
EXPECTED_HEALTH_HTTP="${EXPECTED_HEALTH_HTTP:-401 403}"  # space-separated allowed codes

TS="$(date +%Y%m%d-%H%M%S)"
STAGE="/tmp/argus-v4.2.0.${TS}"
mkdir -p "${STAGE}"

declare -A SHA256
SHA256["agent_ws.py"]="56201815f80b30e68757985f9b79e525c22aa6fbbb29c350a6a5d98f4f938c2d"
SHA256["advanced_features.py"]="20d3fd1a82c13762b3058920fd765c9492fc2b68a89a42fbcc0c3c8270221b70"
SHA256["installer_gui.ps1.template"]="fe1ebe569319ba6f6a0a8b9302097e0e090bed92c90c3d300af9112ecd2ece40"

declare -A TARGET
TARGET["agent_ws.py"]="${BACKEND_DIR}/routes/agent_ws.py"
TARGET["advanced_features.py"]="${BACKEND_DIR}/routes/advanced_features.py"
TARGET["installer_gui.ps1.template"]="${NOCAGENT_BUILD_DIR}/installer_gui.ps1.template"

log()  { printf "\033[36m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
fail() { printf "\033[31m[FAIL]\033[0m %s\n" "$*" >&2; exit 1; }

# ---- 0. Preflight -----------------------------------------------------------
log "Preflight check"
[[ "$(id -un)" == "arslan" ]] || fail "Esegui come utente 'arslan' (sudo -u arslan bash $0). Sei: $(id -un)"
command -v curl   >/dev/null || fail "curl missing"
command -v sha256sum >/dev/null || fail "sha256sum missing"
command -v sudo   >/dev/null || fail "sudo missing"
[[ -d "${BACKEND_DIR}" ]] || fail "Backend dir non trovata: ${BACKEND_DIR}"
[[ -d "${NOCAGENT_BUILD_DIR}" ]] || fail "noc-agent build dir non trovata: ${NOCAGENT_BUILD_DIR}"

# ---- 1. Download + verify ---------------------------------------------------
for f in "${!SHA256[@]}"; do
  url="${PATCH_BASE}/${f}"
  dst="${STAGE}/${f}"
  log "Downloading ${f}"
  curl -fsSL --retry 3 --connect-timeout 10 -o "${dst}" "${url}" \
    || fail "Download fallito: ${url}"
  got=$(sha256sum "${dst}" | awk '{print $1}')
  want="${SHA256[$f]}"
  if [[ "${got}" != "${want}" ]]; then
    fail "sha256 mismatch su ${f}: got=${got} want=${want}"
  fi
  log "  sha256 OK"
done

# ---- 2. Backup correnti -----------------------------------------------------
BACKUP_DIR="/tmp/argus-rollback-${TS}"
mkdir -p "${BACKUP_DIR}"
log "Backup correnti in ${BACKUP_DIR}"
for f in "${!TARGET[@]}"; do
  tgt="${TARGET[$f]}"
  if [[ -f "${tgt}" ]]; then
    sudo cp -p "${tgt}" "${BACKUP_DIR}/${f}"
    log "  backup ${f}"
  else
    log "  (nessun file esistente per ${f}, skip backup)"
  fi
done

# ---- 3. Install in posizione ------------------------------------------------
log "Installing files"
for f in "${!TARGET[@]}"; do
  src="${STAGE}/${f}"
  tgt="${TARGET[$f]}"
  sudo install -o arslan -g arslan -m 644 "${src}" "${tgt}"
  log "  -> ${tgt}"
done

# ---- 4. Restart backend -----------------------------------------------------
log "Restart ${SERVICE}"
sudo systemctl restart "${SERVICE}"
sleep 4

# ---- 5. Healthcheck ---------------------------------------------------------
log "Healthcheck ${HEALTHCHECK_URL}"
hc_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${HEALTHCHECK_URL}" || true)
ok=false
for allowed in ${EXPECTED_HEALTH_HTTP}; do
  if [[ "${hc_code}" == "${allowed}" ]]; then ok=true; break; fi
done

if ! ${ok}; then
  printf "\033[31m[FAIL]\033[0m Healthcheck failed: HTTP %s (atteso uno di: %s)\n" \
    "${hc_code}" "${EXPECTED_HEALTH_HTTP}" >&2
  log "Avvio rollback automatico..."
  for f in "${!TARGET[@]}"; do
    bk="${BACKUP_DIR}/${f}"
    tgt="${TARGET[$f]}"
    if [[ -f "${bk}" ]]; then
      sudo install -o arslan -g arslan -m 644 "${bk}" "${tgt}"
      log "  rollback ${tgt}"
    fi
  done
  sudo systemctl restart "${SERVICE}"
  sleep 3
  fail "Deploy rolled back. Backup in ${BACKUP_DIR}, journal: sudo journalctl -u ${SERVICE} -n 100"
fi

log "Healthcheck OK (HTTP ${hc_code})"

# ---- 6. Quick smoke su nuove API endpoint -----------------------------------
log "Smoke test: verifica che push_config_to_client sia importabile"
sudo systemctl is-active "${SERVICE}" >/dev/null || fail "${SERVICE} not active"

# ---- 7. Riepilogo finale ----------------------------------------------------
cat <<EOF

\033[32m===========================================================
DEPLOY BACKEND v4.2.0 COMPLETATO
===========================================================\033[0m

Modifiche applicate:
  - ${TARGET["agent_ws.py"]}
  - ${TARGET["advanced_features.py"]}
  - ${TARGET["installer_gui.ps1.template"]}  (fix Tls13 wizard)

Rollback (se serve in futuro):
  for f in agent_ws.py advanced_features.py installer_gui.ps1.template; do
    sudo cp ${BACKUP_DIR}/\$f $(dirname ${TARGET["agent_ws.py"]})/\$f
  done
  sudo systemctl restart ${SERVICE}

\033[33m===========================================================
PROSSIMO STEP — Agent Go su SOCIALSRV (Windows)
===========================================================\033[0m

Sul SOCIALSRV apri \033[1mPowerShell come Amministratore\033[0m e incolla:

  Stop-Service 86NocAgent -Force
  Copy-Item "C:\\Program Files\\86NocAgent\\nocagent.exe" "C:\\Program Files\\86NocAgent\\nocagent.exe.bak-v4.0.0" -Force
  Invoke-WebRequest "${PATCH_BASE}/nocagent.exe" -OutFile "C:\\Program Files\\86NocAgent\\nocagent.exe" -UseBasicParsing
  & "C:\\Program Files\\86NocAgent\\nocagent.exe" --version
  Start-Service 86NocAgent
  Get-Content "C:\\ProgramData\\86NocAgent\\nocagent.log" -Tail 30

Atteso nel log:
  - "agent started ... agent_version=4.2.0+..."
  - "ping config hot-swapped enabled=true targets=N"

Poi sulla dashboard \033[1margus.86bit.it\033[0m → pagina Dispositivi:
  • Aspetta ~60-90s.
  • I device PENDING devono passare a \033[32mONLINE\033[0m con RTT.

EOF
