#!/usr/bin/env bash
# publish-connector.sh — Pubblica una nuova versione del connector in tutti i percorsi richiesti
#
# COSA FA:
#   1. Crea lo ZIP dal contenuto di /app/noc-connector/prg/
#   2. Copia lo ZIP nei DUE path richiesti:
#        - /app/connector_updates/                  (auto-update via API)
#        - /app/frontend/public/downloads/           (download manuale via browser)
#   3. Crea anche il pacchetto _install.zip (con VBS installer)
#   4. Inserisce/aggiorna il record in db.connector_updates marcandolo active
#   5. Calcola e salva il file_size nel DB
#   6. Marca come inactive tutte le versioni precedenti
#
# USO: ./publish-connector.sh <version> "<changelog>"
#   Esempio: ./publish-connector.sh 3.4.8 "v3.4.8: Fix xyz"
#
# PRE-REQUISITO: version.json in /app/noc-connector/prg/ deve essere già aggiornato alla stessa versione

set -e

VERSION="${1:?Usage: $0 <version> <changelog>}"
CHANGELOG="${2:-v$VERSION update}"

PRG_DIR="/app/noc-connector/prg"
VBS_SRC="/app/noc-connector/Installa 86NocConnector.vbs"
STORAGE_DIR="/app/connector_updates"
DOWNLOADS_DIR="/app/frontend/public/downloads"
TMP_DIR=$(mktemp -d)

echo "==========================================================================="
echo "   PUBLISH CONNECTOR v$VERSION"
echo "==========================================================================="

# Verify version.json matches
VERSION_IN_JSON=$(python3 -c "import json;print(json.load(open('$PRG_DIR/version.json'))['version'])")
if [ "$VERSION_IN_JSON" != "$VERSION" ]; then
    echo "ERRORE: version.json dice '$VERSION_IN_JSON' ma stai pubblicando '$VERSION'"
    echo "Aggiorna prima $PRG_DIR/version.json"
    exit 1
fi

# ============================================================================
# PRE-FLIGHT CHECK PowerShell encoding (introdotto in v3.5.23)
# ----------------------------------------------------------------------------
# Verifica che TUTTI i file .ps1 del connector:
#   1. Abbiano BOM UTF-8 (ef bb bf) all'inizio. Senza BOM, Windows PowerShell
#      5.1 con locale italiano usa CP-1252 e i caratteri UTF-8 multibyte
#      vengono mal-interpretati.
#   2. NON contengano caratteri tipografici Unicode "killer":
#        - em-dash '—' (U+2014, e2 80 94) -> il byte 0x94 in CP-1252 e' '"'
#          (smart quote close) e CHIUDE la stringa di Write-Log, trasformando
#          i '>' successivi in operatori di redirect e rompendo il parser.
#        - en-dash '–' (U+2013, e2 80 93) -> stesso problema (0x93 = '"' open)
#        - arrow '→' '←' (U+2192/2190) -> il byte 0x92/0x90 in CP-1252 e'
#          '''/'\u2018' che corrompe stringhe single-quoted.
#        - smart quotes ' ' " " (U+2018/2019/201C/201D) -> idem
# Se trova problemi, esce con codice 2 e indica come correggere.
# ----------------------------------------------------------------------------
echo ""
echo "   PRE-FLIGHT CHECK PowerShell encoding (BOM + Unicode killers)"
echo "   ..."

PS_FILES=$(find "$PRG_DIR" -type f -name "*.ps1")
PRECHECK_FAILED=0
PRECHECK_REPORT=""

while IFS= read -r f; do
    # 1. BOM check
    bom=$(head -c 3 "$f" | od -An -tx1 | tr -d ' \n')
    if [ "$bom" != "efbbbf" ]; then
        PRECHECK_REPORT+="    [NO BOM]   $f"$'\n'
        PRECHECK_FAILED=1
    fi
    # 2. Unicode killers — usa LC_ALL=C per byte-exact match.
    # NB: `grep -c` emette il count su stdout MA esce con codice 1 quando il
    # count e' 0. Sotto `set -e` il `$()` cattura "0" ma poi lo script fallisce.
    # Soluzione: avvolgere ogni grep in un "(... ; true)" che neutralizza
    # l'exit code preservando stdout. Cosi' $em e' SEMPRE un integer valido.
    em=$( (LC_ALL=C grep -cP $'\xe2\x80\x94' "$f" 2>/dev/null || true) | head -n1 )
    en=$( (LC_ALL=C grep -cP $'\xe2\x80\x93' "$f" 2>/dev/null || true) | head -n1 )
    arr_r=$( (LC_ALL=C grep -cP $'\xe2\x86\x92' "$f" 2>/dev/null || true) | head -n1 )
    arr_l=$( (LC_ALL=C grep -cP $'\xe2\x86\x90' "$f" 2>/dev/null || true) | head -n1 )
    sq=$( (LC_ALL=C grep -cP $'\xe2\x80[\x98\x99\x9c\x9d]' "$f" 2>/dev/null || true) | head -n1 )
    # Default a 0 se vuoto (paranoia)
    em=${em:-0}; en=${en:-0}; arr_r=${arr_r:-0}; arr_l=${arr_l:-0}; sq=${sq:-0}
    total=$((em + en + arr_r + arr_l + sq))
    if [ "$total" -gt 0 ]; then
        PRECHECK_REPORT+="    [UNICODE]  $f: em-dash=$em en-dash=$en arrow_r=$arr_r arrow_l=$arr_l smart_quotes=$sq"$'\n'
        PRECHECK_FAILED=1
    fi
done <<< "$PS_FILES"

if [ "$PRECHECK_FAILED" -eq 1 ]; then
    echo ""
    echo "   PRE-FLIGHT FAIL — pubblicazione interrotta"
    echo "==========================================================================="
    echo ""
    echo "I file PowerShell del connector hanno problemi di encoding che rompono"
    echo "Windows PowerShell 5.1 su locale italiano (CP-1252) — vedi v3.5.23 nel PRD."
    echo ""
    echo "$PRECHECK_REPORT"
    echo "FIX automatico (esegui questi 2 comandi nella shell del container):"
    echo ""
    echo "  # 1. Sostituisci caratteri tipografici Unicode con ASCII"
    echo "  for f in $PRG_DIR/src/*.ps1 $PRG_DIR/*.ps1; do"
    echo "    LC_ALL=C sed -i \$'s/\\xe2\\x80\\x94/-/g; s/\\xe2\\x80\\x93/-/g; s/\\xe2\\x86\\x92/->/g; s/\\xe2\\x86\\x90/<-/g; s/\\xe2\\x80\\x98/'\\\"'\\\"'/g; s/\\xe2\\x80\\x99/'\\\"'\\\"'/g; s/\\xe2\\x80\\x9c/\\\"/g; s/\\xe2\\x80\\x9d/\\\"/g' \"\$f\""
    echo "  done"
    echo ""
    echo "  # 2. Aggiungi BOM UTF-8 ai file che non lo hanno"
    echo "  for f in $PRG_DIR/src/*.ps1 $PRG_DIR/*.ps1; do"
    echo "    if [ \"\$(head -c 3 \"\$f\" | od -An -tx1 | tr -d ' \\n')\" != \"efbbbf\" ]; then"
    echo "      printf '\\xef\\xbb\\xbf' > \"\$f.tmp\" && cat \"\$f\" >> \"\$f.tmp\" && mv \"\$f.tmp\" \"\$f\""
    echo "    fi"
    echo "  done"
    echo ""
    echo "Poi rilancia ./publish-connector.sh $VERSION \"\$CHANGELOG\""
    exit 2
fi

PS_COUNT=$(echo "$PS_FILES" | wc -l)
echo "   PRE-FLIGHT OK ($PS_COUNT file .ps1 verificati: BOM + zero Unicode killers)"
echo ""

# Build ZIPs
mkdir -p "$TMP_DIR"
cp -r "$PRG_DIR" "$TMP_DIR/"
cp "$VBS_SRC" "$TMP_DIR/" 2>/dev/null || true

PLAIN_ZIP="86NocConnector_v${VERSION}.zip"
INSTALL_ZIP="86NocConnector_v${VERSION}_install.zip"

mkdir -p "$STORAGE_DIR" "$DOWNLOADS_DIR"

cd "$TMP_DIR"
zip -rq "$STORAGE_DIR/$PLAIN_ZIP" prg/
cp "$STORAGE_DIR/$PLAIN_ZIP" "$DOWNLOADS_DIR/$PLAIN_ZIP"
zip -rq "$DOWNLOADS_DIR/$INSTALL_ZIP" prg/ "Installa 86NocConnector.vbs"
cd - > /dev/null

FILE_SIZE=$(stat -c%s "$STORAGE_DIR/$PLAIN_ZIP")
echo "  - $STORAGE_DIR/$PLAIN_ZIP       ($FILE_SIZE bytes)"
echo "  - $DOWNLOADS_DIR/$PLAIN_ZIP     (copia download)"
echo "  - $DOWNLOADS_DIR/$INSTALL_ZIP   (con VBS installer)"

# Cleanup
rm -rf "$TMP_DIR"

# Update DB
echo ""
echo "==========================================================================="
echo "   UPDATING DATABASE"
echo "==========================================================================="
cd /app/backend
set -a; source .env; set +a
python3 << EOF
import asyncio, uuid
from datetime import datetime, timezone
from database import db

async def publish():
    # Deactivate all previous
    await db.connector_updates.update_many({'active': True}, {'\$set': {'active': False}})
    # Check if version already exists (idempotent)
    existing = await db.connector_updates.find_one({'version': '$VERSION'})
    if existing:
        await db.connector_updates.update_one(
            {'version': '$VERSION'},
            {'\$set': {
                'active': True,
                'filename': '$PLAIN_ZIP',
                'file_size': $FILE_SIZE,
                'changelog': '''$CHANGELOG''',
                'published_at': datetime.now(timezone.utc).isoformat(),
            }}
        )
        print(f'  Updated existing record for v$VERSION (active=True)')
    else:
        await db.connector_updates.insert_one({
            'id': str(uuid.uuid4()),
            'version': '$VERSION',
            'filename': '$PLAIN_ZIP',
            'file_size': $FILE_SIZE,
            'active': True,
            'published_at': datetime.now(timezone.utc).isoformat(),
            'changelog': '''$CHANGELOG''',
        })
        print(f'  Inserted new record for v$VERSION (active=True)')
    # Verify
    doc = await db.connector_updates.find_one({'active': True}, {'_id': 0})
    print()
    print(f"  ACTIVE: v{doc['version']}")
    print(f"    filename:   {doc['filename']}")
    print(f"    file_size:  {doc['file_size']} bytes")
    print(f"    published:  {doc['published_at']}")

asyncio.run(publish())
EOF

echo ""
echo "==========================================================================="
echo "   DONE - v$VERSION pubblicato con successo"
echo "==========================================================================="
echo ""
echo "Prossimi passi:"
echo "  1. I connector in campo rileveranno la nuova versione entro 5 minuti (loop automatico)"
echo "  2. O dalla UI /connectors clicca 'Forza aggiornamento' su singolo connector"
echo "  3. Oppure gli utenti possono scaricare il ZIP da:"
echo "     https://<YOUR-DOMAIN>/downloads/$INSTALL_ZIP"
