"""
Conftest condiviso da tutti i test del backend.

Fa due cose minimali:
1. Imposta REACT_APP_BACKEND_URL a un default valido se non e' settato
   nell'environment (i test legacy usano questa env var per costruire URL HTTP).
2. Carica /app/backend/.env in modo che MONGO_URL e DB_NAME siano disponibili
   anche quando pytest e' invocato senza wrapper "set -a; source .env; set +a".

Nessun refactoring del codice di produzione: solo allineamento degli ambienti
di test cosi' i test esistenti smettono di fallire per env vars mancanti.
"""
import os
import pathlib


def _load_env_file(path: str) -> None:
    p = pathlib.Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        # Non sovrascrivere variabili gia' presenti nel processo
        os.environ.setdefault(k, v)


# Carica backend/.env (MONGO_URL, DB_NAME, ...)
_load_env_file("/app/backend/.env")
# Carica frontend/.env (REACT_APP_BACKEND_URL e' qui)
_load_env_file("/app/frontend/.env")

# Default sicuro per i test che chiamano l'API HTTP esterna
os.environ.setdefault(
    "REACT_APP_BACKEND_URL",
    "https://device-poller-ws.preview.emergentagent.com",
)
