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
