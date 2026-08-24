"""
Fonte UNICA di liveness dei dispositivi (device_poll_status).

Motivo: i record di polling possono essere DUPLICATI per lo stesso dispositivo
(master vs scanner-fallback). Ogni schermata che li leggeva con regole diverse
produceva incongruenze (es. un vitale "down" sulla TV e "online" sulla scheda).

Regola canonica condivisa: per ogni (client_id, ip) tieni il record MIGLIORE →
"reachable wins", a parità il più recente. Da usare OVUNQUE (TV, scheda cliente,
dashboard, digest) per avere lo stesso identico stato.
"""
from typing import Optional


def is_online(doc: dict) -> bool:
    """Un record di polling è ONLINE se raggiungibile (ping o generico)."""
    return bool(doc.get("ping_reachable") or doc.get("reachable"))


def _ts(doc: dict) -> str:
    return (doc.get("last_seen_at") or doc.get("last_seen") or doc.get("last_reachable_at")
            or doc.get("last_poll") or doc.get("updated_at") or "")


def _key(doc: dict) -> str:
    return f"{doc.get('client_id')}:{doc.get('ip') or doc.get('device_ip')}"


def dedup_poll_records(records: list) -> list:
    """Deduplica i record di poll per (client_id, ip): reachable wins, poi più recente."""
    best: dict = {}
    for d in records or []:
        k = _key(d)
        cur = best.get(k)
        if cur is None or (is_online(d), _ts(d)) > (is_online(cur), _ts(cur)):
            best[k] = d
    return list(best.values())


async def resolve_devices(db, client_id: Optional[str] = None) -> list:
    """Ritorna i device_poll_status deduplicati (stato canonico). Filtra per cliente se dato."""
    q = {"client_id": client_id} if client_id else {}
    records = await db.device_poll_status.find(q, {"_id": 0}).to_list(5000)
    return dedup_poll_records(records)
