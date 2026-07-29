"""Rilevamento loop di rete su switch (Fase A — solo backend, nessun update agent).

Segnali usati, entrambi ricavabili dai dati che gli agent gia' inviano:

 1. MAC duplicati / MAC-flapping (segnale primario, molto affidabile):
    in condizioni normali ogni MAC vive dietro UNA sola porta. Se lo stesso MAC
    viene appreso su >=2 porte dello stesso switch, la switch sta ricevendo lo
    stesso traffico da due percorsi -> tipico loop (cavo che torna su se stesso o
    tra due porte access). Piu' MAC condivisi tra le stesse porte = loop certo.

 2. Broadcast/traffic storm (segnale secondario):
    un loop genera una tempesta di pacchetti. Una porta UP con pps molto alto e
    simmetrico (rx~tx) e' sospetta.

L'esito viene sia esposto per-porta nella pagina Porte Switch (badge UI) sia usato
per generare/risolvere automaticamente un alert lato server all'ingest.
"""
from datetime import datetime, timezone

# Un MAC su 2 porte puo' capitare (failover/mobilita' transitoria). >=3 MAC
# condivisi su una porta e' invece un segnale forte e a bassissimo falso-positivo.
LOOP_DUP_MAC_THRESHOLD = 3
# pps simmetrico oltre questa soglia su porta UP = sospetto broadcast storm.
LOOP_STORM_PPS = 15000


def _safe_int(v):
    try:
        return int(v)
    except Exception:
        return None


def compute_loop_suspects(ports, endpoints):
    """Funzione pura. Ritorna dict {idx: info} per le sole porte sospette.

    info = {reasons:[str], partners:[idx], partner_labels:[str],
            dup_mac_count:int, storm:bool}
    - ports: lista dict porta (idx, name, oper, rx_pps, tx_pps)
    - endpoints: lista dict FDB (mac, port)
    """
    # Mappa MAC -> insieme di porte (idx) su cui e' stato appreso
    mac_ports: dict[str, set] = {}
    for e in endpoints or []:
        m = (e.get("mac") or "").upper()
        pidx = _safe_int(e.get("port"))
        if m and pidx is not None:
            mac_ports.setdefault(m, set()).add(pidx)

    dup_count: dict[int, int] = {}
    partners: dict[int, set] = {}
    for _m, idxs in mac_ports.items():
        if len(idxs) >= 2:
            for i in idxs:
                dup_count[i] = dup_count.get(i, 0) + 1
                partners.setdefault(i, set()).update(x for x in idxs if x != i)

    # Mappa idx -> label porta (per messaggi leggibili)
    label_by_idx: dict[int, str] = {}
    for p in ports or []:
        idx_v = _safe_int(p.get("idx"))
        if idx_v is not None:
            label_by_idx[idx_v] = str(p.get("name") or f"port{idx_v}")

    result: dict[int, dict] = {}
    for p in ports or []:
        idx_v = _safe_int(p.get("idx"))
        if idx_v is None:
            continue
        oper = _safe_int(p.get("oper")) or 0
        rx_pps = _safe_int(p.get("rx_pps")) or 0
        tx_pps = _safe_int(p.get("tx_pps")) or 0
        dup = dup_count.get(idx_v, 0)
        storm = oper == 1 and rx_pps >= LOOP_STORM_PPS and tx_pps >= LOOP_STORM_PPS

        reasons = []
        if dup >= LOOP_DUP_MAC_THRESHOLD:
            reasons.append(
                f"{dup} MAC address visti anche su altre porte (MAC flapping / tabella FDB instabile)"
            )
        if storm:
            reasons.append(
                f"traffico simmetrico anomalo {rx_pps}/{tx_pps} pps (possibile broadcast storm)"
            )
        if not reasons:
            continue

        part_idx = sorted(partners.get(idx_v, set()))
        result[idx_v] = {
            "reasons": reasons,
            "partners": part_idx,
            "partner_labels": [label_by_idx.get(i, f"port{i}") for i in part_idx],
            "dup_mac_count": dup,
            "storm": storm,
        }
    return result


async def evaluate_and_alert(db, client_id: str, local_ip: str, ports):
    """Valuta i loop per uno switch (all'ingest) e crea/risolve l'alert relativo.

    Non solleva mai: qualunque errore viene ignorato per non rompere l'ingest.
    """
    try:
        endpoints = await db.discovered_endpoints.find(
            {"switch_ip": local_ip, "client_id": client_id},
            {"_id": 0, "mac": 1, "port": 1},
        ).to_list(5000)
        suspects = compute_loop_suspects(ports or [], endpoints)

        alert_id = f"loop-{client_id}-{local_ip}"[:200]
        now_iso = datetime.now(timezone.utc).isoformat()
        existing = await db.alerts.find_one({"id": alert_id}, {"_id": 0, "status": 1})

        if not suspects:
            # Nessun loop: risolvi l'eventuale alert attivo
            if existing and existing.get("status") != "resolved":
                await db.alerts.update_one(
                    {"id": alert_id},
                    {"$set": {"status": "resolved", "resolved_at": now_iso, "last_seen": now_iso}},
                )
            return

        # Etichette porte coinvolte
        label_by_idx = {}
        for p in ports or []:
            iv = _safe_int(p.get("idx"))
            if iv is not None:
                label_by_idx[iv] = str(p.get("name") or f"port{iv}")
        labels = [label_by_idx.get(i, f"port{i}") for i in sorted(suspects.keys())]
        md = await db.managed_devices.find_one(
            {"ip": local_ip, "client_id": client_id},
            {"_id": 0, "name": 1, "device_name": 1},
        ) or {}
        dev_name = md.get("device_name") or md.get("name") or local_ip

        msg = (
            f"Rilevato possibile loop di rete su {dev_name}: porte {', '.join(labels)} "
            f"mostrano MAC duplicati e/o traffico anomalo. Verifica il cablaggio e "
            f"lo stato Spanning-Tree su quelle porte."
        )
        import json as _json
        doc = {
            "id": alert_id,
            "client_id": client_id,
            "device_id": "",
            "device_ip": local_ip,
            "device_name": dev_name,
            "device_type": "switch",
            "severity": "high",
            "source_type": "network",
            "title": f"Possibile loop di rete · {local_ip}",
            "message": msg,
            "raw_data": _json.dumps({
                "kind": "network_loop",
                "local_ip": local_ip,
                "ports": [
                    {"idx": i, "label": label_by_idx.get(i, f"port{i}"), **v}
                    for i, v in suspects.items()
                ],
            }),
            "last_seen": now_iso,
        }
        if existing:
            if existing.get("status") == "resolved":
                doc["status"] = "active"
                doc["resolved_at"] = None
            await db.alerts.update_one({"id": alert_id}, {"$set": doc})
        else:
            doc.update({
                "status": "active", "acknowledged_by": None,
                "acknowledged_at": None, "resolved_at": None, "created_at": now_iso,
            })
            await db.alerts.insert_one(doc)
    except Exception:
        pass
