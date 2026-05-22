#!/usr/bin/env bash
# ==============================================================================
# auto-deploy.sh — Auto-deploy del Center triggered da GitHub Webhook
# ==============================================================================
#
# Eseguito da: routes/github_deploy.py::_run_deploy() come subprocess.
# Working dir: $NOC_REPO_DIR (default: /home/arslan/86NOCConnectorCenter).
#
# Workflow:
#   1. git fetch + reset hard a origin/main (evita conflitti merge in
#      caso di file locali modificati per debugging)
#   2. pip install se requirements.txt è cambiato
#   3. yarn install + build se package.json o src/ è cambiato
#   4. sudo systemctl restart noc-backend.service
#   5. sudo systemctl restart noc-frontend.service (opzionale)
#
# NB: Lo script stampa ogni step su stdout/stderr — quel testo viene
# catturato dal backend Python e salvato in collection
# `github_deploy_audit` per troubleshooting via UI.
#
# Exit codes:
#   0 = success
#   1 = git pull failed
#   2 = backend dependencies install failed
#   3 = frontend build failed
#   4 = restart fallito
# ==============================================================================

set -e
set -o pipefail

REPO_DIR="${NOC_REPO_DIR:-/home/arslan/86NOCConnectorCenter}"
BRANCH="${NOC_DEPLOY_BRANCH:-main}"

ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }

echo "[$(ts)] === auto-deploy START repo=$REPO_DIR branch=$BRANCH ==="
cd "$REPO_DIR"

# -----------------------------------------------------------------------------
# 1) Git update — reset hard per evitare conflitti su file modificati
#    localmente in produzione (es. .env, lock files). Solo refs tracciati
#    vengono toccati; file untracked restano.
# -----------------------------------------------------------------------------
echo "[$(ts)] [1/5] git fetch + reset --hard origin/$BRANCH"
PREV_SHA=$(git rev-parse HEAD 2>/dev/null || echo "none")
git fetch --prune origin "$BRANCH" || { echo "[ERR] git fetch failed"; exit 1; }
git reset --hard "origin/$BRANCH" || { echo "[ERR] git reset failed"; exit 1; }
NEW_SHA=$(git rev-parse HEAD)
echo "[$(ts)]   prev=$PREV_SHA → new=$NEW_SHA"

if [ "$PREV_SHA" = "$NEW_SHA" ]; then
    echo "[$(ts)]   nessun nuovo commit, skip rebuild + restart"
    echo "[$(ts)] === auto-deploy DONE (no-op) ==="
    exit 0
fi

# Diff sommario
echo "[$(ts)]   changed files:"
git diff --name-only "$PREV_SHA" "$NEW_SHA" | head -30

# -----------------------------------------------------------------------------
# 2) Backend deps — pip install se requirements.txt è cambiato
# -----------------------------------------------------------------------------
if git diff --name-only "$PREV_SHA" "$NEW_SHA" | grep -q "^backend/requirements.txt$"; then
    echo "[$(ts)] [2/5] requirements.txt cambiato → pip install"
    cd backend
    # Usa il pip del venv del backend (path tipico systemd)
    PIP="${NOC_BACKEND_PIP:-/home/arslan/86NOCConnectorCenter/backend/venv/bin/pip}"
    if [ ! -x "$PIP" ]; then
        PIP=$(command -v pip3 || command -v pip)
    fi
    "$PIP" install -r requirements.txt --quiet || {
        echo "[ERR] pip install failed"; cd ..; exit 2;
    }
    cd ..
else
    echo "[$(ts)] [2/5] requirements.txt invariato, skip pip"
fi

# -----------------------------------------------------------------------------
# 3) Frontend rebuild — yarn build se src/ o package.json sono cambiati
# -----------------------------------------------------------------------------
if git diff --name-only "$PREV_SHA" "$NEW_SHA" | grep -qE "^frontend/(src/|package\.json|yarn\.lock)"; then
    echo "[$(ts)] [3/5] frontend cambiato → yarn install + build"
    cd frontend
    yarn install --silent --frozen-lockfile || {
        echo "[ERR] yarn install failed"; cd ..; exit 3;
    }
    # CI=false: ignora i warning come errori (CRA fa diventare errori i warning in build)
    CI=false yarn build || { echo "[ERR] yarn build failed"; cd ..; exit 3; }
    cd ..
else
    echo "[$(ts)] [3/5] frontend invariato, skip build"
fi

# -----------------------------------------------------------------------------
# 4) Restart noc-backend — sempre, anche se solo cambia agent_ws.py
# -----------------------------------------------------------------------------
echo "[$(ts)] [4/5] systemctl restart noc-backend"
sudo /bin/systemctl restart noc-backend.service || {
    echo "[ERR] restart noc-backend failed"; exit 4;
}
# Healthcheck post-restart (max 30s di attesa)
for i in $(seq 1 30); do
    sleep 1
    if curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8001/api/health 2>/dev/null; then
        echo "[$(ts)]   noc-backend healthy after ${i}s"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[ERR] noc-backend NOT healthy after 30s"
        # Non fail: lasciamo che systemd ripari, ma logghiamo l'anomalia
    fi
done

# -----------------------------------------------------------------------------
# 5) Restart noc-frontend (opzionale, solo se è un'unit systemd)
# -----------------------------------------------------------------------------
if systemctl list-unit-files 2>/dev/null | grep -q '^noc-frontend\.service'; then
    echo "[$(ts)] [5/5] systemctl restart noc-frontend"
    sudo /bin/systemctl restart noc-frontend.service || {
        echo "[WARN] restart noc-frontend failed (non-fatal)";
    }
else
    echo "[$(ts)] [5/5] noc-frontend.service non presente, skip"
fi

echo "[$(ts)] === auto-deploy DONE (commit $NEW_SHA) ==="
