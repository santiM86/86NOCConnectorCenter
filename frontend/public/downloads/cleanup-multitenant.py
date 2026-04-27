#!/usr/bin/env python3
"""
ARGUS Multi-Tenant Diagnose & Cleanup
Da eseguire sul server Linux dove gira il backend ARGUS.

Cosa fa:
  1. Si connette al MongoDB locale (legge MONGO_URL dal .env del backend)
  2. Mostra la distribuzione dei device per client_id (verifica dati sporchi)
  3. Per ogni cliente, identifica device con IP fuori dalla subnet naturale
  4. Offre cleanup interattivo: DELETE / SKIP

Uso:
    cd /path/to/argus/backend
    python3 cleanup-multitenant.py

Richiede: pymongo, python-dotenv (di solito già nel venv del backend)
"""
import os
import sys
import ipaddress
from collections import defaultdict

try:
    from pymongo import MongoClient
except ImportError:
    print("ERRORE: pymongo non installato. Esegui: pip install pymongo python-dotenv")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "noc_db")

    print(f"Connessione a {mongo_url} / DB={db_name}")
    client = MongoClient(mongo_url)
    db = client[db_name]

    # =========================================================
    # 1. Distribuzione device per client_id
    # =========================================================
    print("\n=== Distribuzione device per client_id ===")
    pipeline = [
        {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    counts = list(db.devices.aggregate(pipeline))
    for r in counts:
        cid = r["_id"]
        cid_disp = cid if cid else "(VUOTO/NULL)"
        cl = db.clients.find_one({"id": cid}, {"_id": 0, "name": 1}) if cid else None
        cl_name = cl["name"] if cl else "??? cliente non esistente"
        print(f"  {str(cid_disp)[:36]:36s}  ({cl_name}): {r['count']} device")

    # =========================================================
    # 2. Lista clienti
    # =========================================================
    print("\n=== Clienti registrati ===")
    clients = list(db.clients.find({}, {"_id": 0, "id": 1, "name": 1, "api_key": 1}))
    for i, c in enumerate(clients):
        print(f"  [{i}] {c['name']:30s}  id={c['id']}")

    # =========================================================
    # 3. Selezione cliente da analizzare
    # =========================================================
    sel = input("\nIndice cliente da analizzare [INVIO=0]: ").strip()
    idx = int(sel) if sel else 0
    if idx < 0 or idx >= len(clients):
        print("Indice non valido"); return
    target = clients[idx]
    print(f"\nCliente target: {target['name']} (id={target['id']})")

    # =========================================================
    # 4. Mostra TUTTI i device di questo cliente
    # =========================================================
    print(f"\n=== Device con client_id = {target['id'][:8]}... ===")
    devs = list(db.devices.find({"client_id": target["id"]}, {"_id": 0}))
    for d in devs:
        ip = d.get("ip_address") or d.get("ip") or "?"
        print(f"  {d.get('name','?'):35s}  ip={ip:18s}  type={d.get('device_type','?'):10s}  source={d.get('source','?')}")

    # =========================================================
    # 5. Chiedi subnet naturale del cliente
    # =========================================================
    print("\nIndica le subnet 'naturali' di questo cliente (CIDR, separate da virgola).")
    print("Esempio per Galvan: 10.100.61.0/24")
    print("Lascia vuoto per identificare automaticamente dalla maggioranza dei device.")
    sn = input("Subnet del cliente: ").strip()

    valid_subnets = []
    if sn:
        for s in sn.split(","):
            s = s.strip()
            try:
                valid_subnets.append(ipaddress.ip_network(s, strict=False))
            except ValueError:
                print(f"  Subnet non valida: {s}")
    else:
        # Auto-detect: trova la subnet /24 più popolata tra i device del cliente
        subnet_counts = defaultdict(int)
        for d in devs:
            ip_str = d.get("ip_address") or d.get("ip")
            if not ip_str: continue
            try:
                ip = ipaddress.ip_address(ip_str)
                # /24 di appartenenza
                net = ipaddress.ip_network(f"{ip}/24", strict=False)
                subnet_counts[str(net)] += 1
            except ValueError:
                continue
        if subnet_counts:
            top = sorted(subnet_counts.items(), key=lambda x: -x[1])[0]
            print(f"  Auto-detect: subnet più popolata = {top[0]} ({top[1]} device)")
            valid_subnets = [ipaddress.ip_network(top[0])]
        else:
            print("Nessuna subnet identificabile."); return

    # =========================================================
    # 6. Identifica device "estranei" (IP fuori da subnet naturali)
    # =========================================================
    estranei = []
    legittimi = []
    for d in devs:
        ip_str = d.get("ip_address") or d.get("ip")
        if not ip_str:
            estranei.append(d); continue
        try:
            ip = ipaddress.ip_address(ip_str)
            in_natural = any(ip in s for s in valid_subnets)
            # Esclusione: IP loopback (Auto-127.0.0.1) considerato estraneo
            if ip.is_loopback:
                estranei.append(d)
            elif in_natural:
                legittimi.append(d)
            else:
                estranei.append(d)
        except ValueError:
            estranei.append(d)

    print(f"\n=== RISULTATO ===")
    print(f"  Device LEGITTIMI (IP nelle subnet naturali): {len(legittimi)}")
    for d in legittimi:
        print(f"    OK  {d.get('name','?'):35s} ip={d.get('ip_address') or d.get('ip')}")
    print(f"\n  Device ESTRANEI (IP fuori dalla subnet del cliente): {len(estranei)}")
    for d in estranei:
        ip = d.get("ip_address") or d.get("ip") or "??"
        print(f"    KO  {d.get('name','?'):35s} ip={ip:18s} src={d.get('source','?')}")

    if not estranei:
        print("\nNessun device estraneo. Tutto pulito!")
        return

    # =========================================================
    # 7. Cleanup interattivo
    # =========================================================
    print("\n=== AZIONE ===")
    print("  [d] DELETE tutti gli estranei (con cascade su device_poll_status, managed_devices)")
    print("  [a] ASSEGNA tutti a un altro cliente (scegliendo dalla lista)")
    print("  [i] INTERATTIVO uno per uno")
    print("  [s] SKIP (esci senza modifiche)")
    az = input("Azione [d/a/i/s]: ").strip().lower()

    if az == "s" or not az:
        print("Skipped."); return

    def delete_device(d):
        ip = d.get("ip_address") or d.get("ip")
        db.devices.delete_one({"id": d.get("id")})
        if ip:
            db.device_poll_status.delete_many({"device_ip": ip, "client_id": target["id"]})
            db.managed_devices.delete_many({"ip": ip, "client_id": target["id"]})
        print(f"    DELETED: {d.get('name','?')} ({ip})")

    def reassign_device(d, new_client_id):
        ip = d.get("ip_address") or d.get("ip")
        db.devices.update_one({"id": d.get("id")}, {"$set": {"client_id": new_client_id}})
        if ip:
            db.device_poll_status.update_many({"device_ip": ip, "client_id": target["id"]}, {"$set": {"client_id": new_client_id}})
            db.managed_devices.update_many({"ip": ip, "client_id": target["id"]}, {"$set": {"client_id": new_client_id}})
        print(f"    REASSIGNED: {d.get('name','?')} -> {new_client_id[:8]}")

    if az == "d":
        conf = input(f"Confermi DELETE di {len(estranei)} device? [s/N]: ").strip().lower()
        if conf == "s":
            for d in estranei:
                delete_device(d)
    elif az == "a":
        print("\nClienti disponibili (escludi quello corrente):")
        others = [c for c in clients if c["id"] != target["id"]]
        for i, c in enumerate(others):
            print(f"  [{i}] {c['name']}")
        nidx = int(input("Indice nuovo cliente: "))
        new_id = others[nidx]["id"]
        for d in estranei:
            reassign_device(d, new_id)
    elif az == "i":
        for d in estranei:
            ip = d.get("ip_address") or d.get("ip") or "??"
            ans = input(f"  {d.get('name','?')} ({ip}) - [d]elete / [s]kip / [a]ssign? ").strip().lower()
            if ans == "d":
                delete_device(d)
            elif ans == "a":
                others = [c for c in clients if c["id"] != target["id"]]
                for i, c in enumerate(others):
                    print(f"    [{i}] {c['name']}")
                nidx = int(input(f"    Indice cliente per {d.get('name')}: "))
                reassign_device(d, others[nidx]["id"])

    print("\n=== Pulizia completata ===")
    print("Ricarica la pagina del cliente nel browser per vedere il risultato.")


if __name__ == "__main__":
    main()
