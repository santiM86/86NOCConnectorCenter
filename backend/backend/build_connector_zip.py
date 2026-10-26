"""
Build script per pacchettizzare il Connector ZIP a partire dai sorgenti
in /app/noc-connector/. Usato sia da CLI che dall'endpoint admin
POST /api/admin/connector/rebuild-zip.

Crea ZIP con questa struttura:
  prg/
    nssm.exe
    version.json (aggiornato con la versione passata in input)
    install.bat, installa_servizio.bat, uninstall.bat, uninstall.ps1
    86NocConnector.bat
    diagnostica_connessione.ps1
    README.md
    src/
      connector.ps1, snmp_poller.ps1, argus-scanner.ps1, ...
      installer_gui.ps1, tray_app.ps1, tray_launcher.vbs
      update_check.ps1, wireguard_client.ps1, remote_browser.ps1
      backup_monitor.ps1, switch_enrichment.ps1, printer_probe.ps1
      network_scanner.ps1, diagnostica.ps1, service_wrapper.ps1
      86bit_logo.ico, 86bit_logo.jpg, 86bit_logo_256.png
  Installa 86NocConnector.vbs   <-- al livello del root ZIP, NON dentro prg/
                                    perche' e' il file che l'utente clicca per
                                    triggerare UAC + auto-elevation senza dover
                                    sapere di "prg/install.bat".
  README_ROOT.txt (opzionale)

Returns: dict con `version`, `filename`, `path`, `size`, `sha256`.
"""

from __future__ import annotations
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SOURCE_DIR = Path("/app/noc-connector")
DEST_DIR = Path("/app/connector_updates")


# Lista ESPLICITA di file/cartelle da includere — niente glob furbo per evitare
# di pacchettizzare per sbaglio file di test o backup. Modifica questa lista se
# aggiungi nuovi sorgenti al connector.
PRG_FILES = [
    "nssm.exe",
    "version.json",  # sara' sovrascritto al volo con la versione corrente
    "install.bat",
    "installa_servizio.bat",
    "uninstall.bat",
    "uninstall.ps1",
    "86NocConnector.bat",
    "diagnostica_connessione.ps1",
    "README.md",
]
PRG_SRC_FILES = [
    "connector.ps1",
    "snmp_poller.ps1",
    "argus-scanner.ps1",
    "installer_gui.ps1",
    "tray_app.ps1",
    "tray_launcher.vbs",
    "update_check.ps1",
    "wireguard_client.ps1",
    "remote_browser.ps1",
    "backup_monitor.ps1",
    "switch_enrichment.ps1",
    "printer_probe.ps1",
    "network_scanner.ps1",
    "diagnostica.ps1",
    "service_wrapper.ps1",
    "86bit_logo.ico",
    "86bit_logo.jpg",
    "86bit_logo_256.png",
]
ROOT_FILES = [
    "Installa 86NocConnector.vbs",   # entry point user-friendly per non-tech
    # bootstrap_to_v350.cmd e helper li lasciamo fuori (legacy migrazione 3.5)
]


def build_connector_zip(version: str, changelog: str = "", uploaded_by: str = "system") -> dict:
    """Builda lo ZIP del connector con i sorgenti correnti.

    Args:
        version: stringa semver senza prefisso 'v' (es. "3.8.25")
        changelog: testo libero, salvato nel doc DB ma NON nello ZIP
        uploaded_by: nome utente / sistema che triggera la build

    Returns:
        dict { version, filename, path, size, sha256, files_included }
    """
    if not version or not all(c.isdigit() or c == "." for c in version):
        raise ValueError(f"Versione non valida: '{version}' — deve essere semver (es. 3.8.25)")

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"86NocConnector_v{version}.zip"
    out_path = DEST_DIR / filename

    # 1) Aggiorna version.json al volo (non tocchiamo il file su disco)
    version_payload = {
        "version": version,
        "changelog": changelog or f"v{version} - build automatica da rebuild-zip",
        "build_date": datetime.now(timezone.utc).isoformat(),
        "build_by": uploaded_by,
    }
    version_json_str = json.dumps(version_payload, ensure_ascii=False, indent=2)

    files_included: list[str] = []
    missing: list[str] = []

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # File a livello root (Installa.vbs)
        for rel in ROOT_FILES:
            src = SOURCE_DIR / rel
            if src.is_file():
                zf.write(src, arcname=rel)
                files_included.append(rel)
            else:
                missing.append(rel)

        # File in prg/
        prg_src = SOURCE_DIR / "prg"
        for rel in PRG_FILES:
            if rel == "version.json":
                # Iniettiamo il contenuto aggiornato (stesso path nello zip)
                zf.writestr(f"prg/{rel}", version_json_str)
                files_included.append(f"prg/{rel}")
                continue
            src = prg_src / rel
            if src.is_file():
                zf.write(src, arcname=f"prg/{rel}")
                files_included.append(f"prg/{rel}")
            else:
                missing.append(f"prg/{rel}")

        # File in prg/src/
        prg_src_dir = prg_src / "src"
        for rel in PRG_SRC_FILES:
            src = prg_src_dir / rel
            if src.is_file():
                zf.write(src, arcname=f"prg/src/{rel}")
                files_included.append(f"prg/src/{rel}")
            else:
                missing.append(f"prg/src/{rel}")

    if missing:
        # File mancanti = ZIP non valido per l'installer GUI / auto-update
        out_path.unlink(missing_ok=True)
        raise FileNotFoundError(
            f"Impossibile builder ZIP: mancano {len(missing)} file: {missing}"
        )

    size = out_path.stat().st_size
    sha256 = _sha256_of_file(out_path)
    return {
        "version": version,
        "filename": filename,
        "path": str(out_path),
        "size": size,
        "sha256": sha256,
        "files_included": files_included,
    }


def publish_to_db(db, build_info: dict, changelog: str, uploaded_by: str) -> dict:
    """Marca il nuovo ZIP come `active=True` in db.connector_updates e copia il
    file nelle cartelle pubbliche frontend per il pulsante "Scarica ZIP".

    Idempotente: se lo stesso filename esiste gia', sovrascrive.
    """
    import asyncio

    async def _async_publish():
        await db.connector_updates.update_many({}, {"$set": {"active": False}})
        doc = {
            "version": build_info["version"],
            "filename": build_info["filename"],
            "changelog": changelog or "",
            "file_size": build_info["size"],
            "sha256": build_info["sha256"],
            "active": True,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "uploaded_by": uploaded_by,
        }
        await db.connector_updates.insert_one(doc)
        # Pulisce eventuale doc duplicato (stesso filename ma vecchio)
        await db.connector_updates.delete_many({
            "filename": build_info["filename"],
            "_id": {"$ne": doc.get("_id")},
        })
        return doc

    # Se siamo gia' dentro un loop async (FastAPI), il chiamante lo invochi via await.
    # Per uso CLI standalone, gestiamo qui.
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(_async_publish())  # type: ignore[return-value]
    except RuntimeError:
        return asyncio.run(_async_publish())


def copy_to_public_dirs(zip_path: Path) -> list[str]:
    """Copia lo ZIP nelle cartelle pubbliche del frontend (per /86NocConnector.zip)."""
    copied: list[str] = []
    targets = [
        Path("/app/frontend/public/86NocConnector.zip"),
        Path("/app/frontend/public/downloads") / zip_path.name,
        Path("/app/frontend/build/86NocConnector.zip"),
        Path("/app/frontend/build/downloads") / zip_path.name,
    ]
    for dest in targets:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(zip_path, dest)
            copied.append(str(dest))
        except Exception:
            pass
    return copied


def _sha256_of_file(path: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# ============= CLI entry point =============
if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser(description="Build & publish 86NocConnector ZIP")
    parser.add_argument("--version", required=True, help="Versione semver, es. 3.8.25")
    parser.add_argument("--changelog", default="", help="Changelog testo libero")
    parser.add_argument("--by", default="cli", help="Identificativo build (default: cli)")
    parser.add_argument("--no-publish", action="store_true", help="Builda lo ZIP ma non aggiorna DB")
    args = parser.parse_args()

    print(f"=> Build connector ZIP v{args.version}")
    info = build_connector_zip(args.version, args.changelog, args.by)
    print(f"   filename: {info['filename']}")
    print(f"   size:     {info['size']:,} bytes")
    print(f"   sha256:   {info['sha256']}")
    print(f"   files:    {len(info['files_included'])}")
    if not args.no_publish:
        # Setup MONGO env from /app/backend/.env, then publish
        import os
        from motor.motor_asyncio import AsyncIOMotorClient
        env_file = Path("/app/backend/.env")
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]
        client = AsyncIOMotorClient(mongo_url)
        publish_to_db(client[db_name], info, args.changelog, args.by)
        copied = copy_to_public_dirs(Path(info["path"]))
        print(f"   published: DB updated + copied to {len(copied)} public path(s)")
    sys.exit(0)
