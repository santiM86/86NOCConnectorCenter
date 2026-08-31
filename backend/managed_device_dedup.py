"""Deduplica/merge dei documenti duplicati in `managed_devices`.

RADICE DEL BUG "salvo ma non mantiene / non categorizza": per lo stesso IP
possono coesistere PIU' documenti in `managed_devices`:
  - CANONICO: campo `ip` valorizzato (rispetta l'indice unico (client_id, ip)).
  - LEGACY: solo `ip_address` valorizzato, `ip` null/assente (l'indice unico lo
    tollera perche' `ip` e' null).

Le scritture (Tipo Macchina, device_type/categoria, SNMP, is_vital, silence...)
finiscono su doc diversi a seconda dell'endpoint, e la LETTURA sceglieva il doc
"con piu' segnale" → a volte pescava quello sbagliato e le impostazioni/categoria
sembravano perse.

Questo helper FONDE i duplicati in un unico doc canonico (nessuna impostazione
persa: priorita' ai valori non vuoti del canonico, i buchi riempiti dai legacy),
poi elimina i doc legacy. Idempotente: se non ci sono legacy non fa nulla.
"""
from __future__ import annotations

# Campi chiave che non vanno fusi/sovrascritti (identita' del doc).
_SKIP_KEYS = {"_id", "id", "ip", "ip_address"}


def _nonempty(v) -> bool:
    return v not in (None, "", [], {})


def merge_field_dicts(canonical: dict, legacy: dict) -> dict:
    """Ritorna i campi da settare sul canonico prendendo dai legacy SOLO i
    valori non vuoti dei campi che il canonico non ha (o ha vuoti)."""
    fill: dict = {}
    for k, v in legacy.items():
        if k in _SKIP_KEYS:
            continue
        if _nonempty(v) and not _nonempty(canonical.get(k)):
            fill[k] = v
    return fill


async def merge_duplicate_managed_devices(db, client_id: str | None = None) -> dict:
    """Fonde i doc legacy (solo `ip_address`) nel canonico (`ip`) per ogni
    (client_id, ip). Restituisce {merged_groups, deleted_docs, promoted}.
    Idempotente e sicuro da rilanciare."""
    q = {
        "$or": [{"ip": {"$in": [None, ""]}}, {"ip": {"$exists": False}}],
        "ip_address": {"$nin": [None, ""]},
    }
    if client_id:
        q["client_id"] = client_id

    # Raggruppa i legacy per (client_id, ip_address)
    legacy_docs = await db.managed_devices.find(q).to_list(100000)
    groups: dict[tuple, list] = {}
    for d in legacy_docs:
        key = (d.get("client_id"), d.get("ip_address"))
        if not key[0] or not key[1]:
            continue
        groups.setdefault(key, []).append(d)

    merged_groups = 0
    deleted_docs = 0
    promoted = 0

    for (cid, ip), legs in groups.items():
        canonical = await db.managed_devices.find_one({"client_id": cid, "ip": ip})
        if canonical:
            fill: dict = {}
            for leg in legs:
                for k, v in merge_field_dicts({**canonical, **fill}, leg).items():
                    fill[k] = v
            if fill:
                await db.managed_devices.update_one({"_id": canonical["_id"]}, {"$set": fill})
            del_ids = [leg["_id"] for leg in legs]
            if del_ids:
                res = await db.managed_devices.delete_many({"_id": {"$in": del_ids}})
                deleted_docs += res.deleted_count
            merged_groups += 1
        else:
            # Nessun canonico: promuovi il PRIMO legacy (set ip), fondi gli altri.
            keep = legs[0]
            others = legs[1:]
            fill = {"ip": ip}
            for leg in others:
                for k, v in merge_field_dicts({**keep, **fill}, leg).items():
                    fill[k] = v
            await db.managed_devices.update_one({"_id": keep["_id"]}, {"$set": fill})
            promoted += 1
            if others:
                res = await db.managed_devices.delete_many({"_id": {"$in": [o["_id"] for o in others]}})
                deleted_docs += res.deleted_count
            merged_groups += 1

    return {"merged_groups": merged_groups, "deleted_docs": deleted_docs, "promoted": promoted}
