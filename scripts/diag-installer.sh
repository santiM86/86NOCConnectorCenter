#!/usr/bin/env bash
# ============================================================================
# diag-installer.sh
# ============================================================================
# Diagnostica completa per il problema "Setup .exe → ERROR_FILE_CORRUPT 1392".
#
# Da lanciare SUL SERVER PROD (NON nell'ambiente preview).
# Verifica in ordine:
#   1. Versione installer servita da /api/agent/install/manifest
#   2. Presenza binari .exe sul filesystem locale (sorgente preferito)
#   3. Validita' del proxy /api/agent-builds/.../<file> (HEAD + 1KB sample)
#   4. SHA256 effettivo dei file scaricati vs quello calcolato in locale
#
# Uso:
#   chmod +x diag-installer.sh
#   ./diag-installer.sh                       # usa ${PUBLIC_URL} dall'env
#   PUBLIC_URL=https://argus.86bit.it ./diag-installer.sh
#
# Output esce con codice 0 se tutto OK, !=0 se un problema impedisce
# l'installazione su un nuovo cliente.
# ============================================================================

set -u

REPO="${REPO:-/home/arslan/86NOCConnectorCenter}"
PUBLIC_URL="${PUBLIC_URL:-https://argus.86bit.it}"
PLATFORM="${PLATFORM:-windows-amd64}"
BUILD_DIR="${BUILD_DIR:-$REPO/noc-agent/build/bin/$PLATFORM}"
RELEASE_DIR="${RELEASE_DIR:-$REPO/backend/static/release-bin}"

# Trova un token agent qualsiasi gia' nel DB (per testare gli endpoint senza dover crearne uno)
# Se l'utente vuole, puo' passare TOKEN=xxx
TOKEN="${TOKEN:-}"

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
NC="\033[0m"

OK=0; FAIL=0; WARN=0
pass() { echo -e "  ${GREEN}OK${NC}  $1"; OK=$((OK+1)); }
fail() { echo -e "  ${RED}FAIL${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YELLOW}WARN${NC} $1"; WARN=$((WARN+1)); }
info() { echo -e "  ${CYAN}..${NC}   $1"; }
section() { echo -e "\n${CYAN}== $1 ==${NC}"; }

# ----------------------------------------------------------------------------
section "1. Versione installer corrente nel backend"
# ----------------------------------------------------------------------------
LATEST_DIR=$(ls -1d "$RELEASE_DIR"/v*/ 2>/dev/null | sort -V | tail -1)
LATEST_VER=$(basename "$LATEST_DIR" 2>/dev/null)
if [ -n "$LATEST_VER" ]; then
  pass "latest release-bin: $LATEST_VER"
else
  fail "Nessuna release-bin trovata in $RELEASE_DIR"
fi

if [ -d "$LATEST_DIR" ]; then
  for f in nocinstall.exe nocagent.exe nocwatchdog.exe nocagent-ui.exe; do
    if [ -f "$LATEST_DIR/$f" ]; then
      size=$(stat -c%s "$LATEST_DIR/$f")
      head=$(head -c 2 "$LATEST_DIR/$f" | xxd -p 2>/dev/null)
      if [ "$head" = "4d5a" ]; then
        pass "release-bin $f: size=$size byte, PE='MZ' OK"
      else
        fail "release-bin $f: NON e' un PE valido (head=0x$head)"
      fi
    else
      warn "release-bin $f: assente in $LATEST_DIR"
    fi
  done
fi

# ----------------------------------------------------------------------------
section "2. Binari sorgente in noc-agent/build/bin/"
# ----------------------------------------------------------------------------
# Sorgente usato dal manifest agent_ws.py per calcolare gli SHA256
if [ -d "$BUILD_DIR" ]; then
  pass "Build dir trovato: $BUILD_DIR"
  for f in nocagent.exe nocwatchdog.exe nocinstall.exe nocagent-ui.exe; do
    if [ -f "$BUILD_DIR/$f" ]; then
      size=$(stat -c%s "$BUILD_DIR/$f")
      head=$(head -c 2 "$BUILD_DIR/$f" | xxd -p 2>/dev/null)
      if [ "$head" = "4d5a" ] && [ "$size" -gt 500000 ]; then
        sha=$(sha256sum "$BUILD_DIR/$f" | cut -d' ' -f1)
        pass "$f: size=$size, PE='MZ' OK, sha256=${sha:0:16}..."
      else
        fail "$f: size=$size, head=0x$head — NON valido come PE"
      fi
    else
      fail "$f: MANCA in $BUILD_DIR — il manifest NON includera' lo SHA256, l'installer scarichera' alla cieca via /api/agent-builds/"
    fi
  done
else
  fail "Build dir $BUILD_DIR NON esiste — il manifest non avra' SHA256 per nessun binario"
  echo -e "${YELLOW}   FIX: copia i binari da release-bin a build/bin/$PLATFORM/${NC}"
  echo -e "${YELLOW}   sudo mkdir -p $BUILD_DIR${NC}"
  echo -e "${YELLOW}   sudo cp $LATEST_DIR*.exe $BUILD_DIR/${NC}"
fi

# ----------------------------------------------------------------------------
section "3. Backend health"
# ----------------------------------------------------------------------------
HC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$PUBLIC_URL/api/health" 2>/dev/null || echo "000")
case "$HC" in
  200) pass "Backend health $PUBLIC_URL/api/health = 200" ;;
  *)   warn "Backend health risponde HTTP $HC (atteso 200)" ;;
esac

# ----------------------------------------------------------------------------
section "4. Test proxy /api/agent-builds/<ver>/<file>"
# ----------------------------------------------------------------------------
if [ -z "$TOKEN" ]; then
  warn "Nessun TOKEN fornito → skip test proxy. Lancia: TOKEN=<un-token> $0"
else
  for f in nocagent.exe nocwatchdog.exe; do
    URL="$PUBLIC_URL/api/agent-builds/$LATEST_VER/$f?token=$TOKEN"
    info "GET $URL"
    TMP=$(mktemp /tmp/nocdiag.XXXXXX)
    CODE=$(curl -sL -o "$TMP" -w "%{http_code}" --max-time 30 "$URL")
    if [ "$CODE" != "200" ]; then
      fail "$f: HTTP $CODE — il proxy NON serve il binario (errore upstream)"
      head -c 200 "$TMP"; echo
    else
      size=$(stat -c%s "$TMP")
      head=$(head -c 2 "$TMP" | xxd -p 2>/dev/null)
      if [ "$head" = "4d5a" ] && [ "$size" -gt 500000 ]; then
        sha=$(sha256sum "$TMP" | cut -d' ' -f1)
        pass "$f proxy: size=$size, PE='MZ' OK, sha256=${sha:0:16}..."
        # confronta con sha locale
        if [ -f "$BUILD_DIR/$f" ]; then
          lsha=$(sha256sum "$BUILD_DIR/$f" | cut -d' ' -f1)
          if [ "$sha" = "$lsha" ]; then
            pass "$f: sha256 proxy == sha256 build dir (manifest coerente)"
          else
            warn "$f: sha256 proxy DIVERSO da build dir — il proxy potrebbe puntare a una vecchia release GitHub"
          fi
        fi
      else
        fail "$f proxy: NON e' un PE (size=$size, head=0x$head) — questo causa ERROR_FILE_CORRUPT 1392"
        echo "Primi 200 byte ricevuti:"; head -c 200 "$TMP"; echo
      fi
    fi
    rm -f "$TMP"
  done
fi

# ----------------------------------------------------------------------------
section "5. Verifica env BINARY_URLS_BASE (override CDN)"
# ----------------------------------------------------------------------------
if [ -f "$REPO/backend/.env" ]; then
  BUB=$(grep -E "^BINARY_URLS_BASE=" "$REPO/backend/.env" | cut -d= -f2-)
  if [ -n "$BUB" ]; then
    info "BINARY_URLS_BASE = $BUB"
    info "→ Il manifest usa il CDN esterno, NON il proxy locale. Test direttamente con curl la URL."
  else
    pass "BINARY_URLS_BASE non settato → il manifest usa il proxy /api/agent-builds/"
  fi
fi

# ----------------------------------------------------------------------------
section "Riepilogo"
# ----------------------------------------------------------------------------
echo -e "  ${GREEN}OK${NC}    : $OK"
echo -e "  ${YELLOW}WARN${NC}  : $WARN"
echo -e "  ${RED}FAIL${NC}  : $FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo -e "\n${RED}DIAGNOSI: il problema 1392 e' confermato.${NC}"
  echo -e "${YELLOW}Manda lo stdout completo di questo script all'agente.${NC}"
  exit 1
fi
exit 0
