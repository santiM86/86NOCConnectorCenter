#!/usr/bin/env python3
"""Reset password (e opzionalmente 2FA) direttamente su MongoDB.

USO (eseguire sul server dove gira il backend, con lo stesso .env):
    cd /path/al/backend
    # reset di UN account (consigliato):
    python scripts/reset_passwords.py --email info@86bit.it --password 'NuovaPass#2026' --clear-2fa
    # reset di TUTTI gli account allo stesso temporaneo:
    python scripts/reset_passwords.py --all --password 'Temp#2026' --clear-2fa

Funziona anche se il backend HTTP e' giu' (502): parla direttamente con MongoDB
via MONGO_URL/DB_NAME dal .env. Usa lo STESSO hashing dell'app (argon2).
"""
import os
import sys
import argparse

from dotenv import load_dotenv
from argon2 import PasswordHasher
from pymongo import MongoClient

load_dotenv()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", help="email dell'account da resettare")
    ap.add_argument("--all", action="store_true", help="resetta TUTTI gli account")
    ap.add_argument("--password", required=True, help="nuova password temporanea")
    ap.add_argument("--clear-2fa", action="store_true", help="disabilita 2FA e rimuove il totp_secret")
    args = ap.parse_args()

    if not args.email and not args.all:
        sys.exit("Specifica --email <email> oppure --all")

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    ph = PasswordHasher()
    pwd_hash = ph.hash(args.password)

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=8000)
    db = client[db_name]

    query = {} if args.all else {"email": args.email}
    users = list(db.users.find(query, {"_id": 0, "id": 1, "email": 1}))
    if not users:
        sys.exit(f"Nessun utente trovato per {query}")

    update = {"password_hash": pwd_hash}
    if args.clear_2fa:
        update.update({"two_factor_enabled": False, "totp_secret": None})

    res = db.users.update_many(query, {"$set": update})

    # Sblocca eventuali account/IP (best-effort: collezioni di brute-force)
    for coll in ("failed_logins", "account_locks", "login_attempts", "blocked_ips", "security_events_lock"):
        try:
            db[coll].delete_many({} if args.all else {"email": args.email})
        except Exception:
            pass

    client.close()
    print(f"OK: password resettata per {res.modified_count} utente/i:")
    for u in users:
        print(f"  - {u.get('email')}")
    print(f"Nuova password: {args.password}")
    if args.clear_2fa:
        print("2FA disabilitato (dovrai riconfigurarlo dal profilo dopo l'accesso).")


if __name__ == "__main__":
    main()
