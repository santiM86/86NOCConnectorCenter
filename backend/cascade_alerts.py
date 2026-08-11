"""Alert di anomalia sulla cascata di switch.

Rileva quando un uplink switch<->switch (link fisico da LLDP/FDB):
  - SPARISCE  -> possibile cavo rimosso / switch spento / loop che ha isolato la tratta
  - CAMBIA PORTA -> ricablaggio (l'uplink e' stato spostato su un'altra porta)

Confronta la topologia corrente (compute_switch_cascade) con una baseline
persistente per cliente (`switch_cascade_baseline`). Debounce di 2 cicli sul
"link scomparso" per assorbire lo scanning LLDP intermittente. Auto-risoluzione
dell'alert quando il link riappare o la porta torna quella attesa.

1 solo alert ATTIVO per (client, link, tipo) via `dedup_key` in `db.alerts`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from alert_engine import _dispatch_notification, _mk_alert, get_config
from alert_filter import insert_alert_if_emit

logger = logging.getLogger("cascade_alerts")

SOURCE_TYPE = "switch_cascade"
MISS_CYCLES_BEFORE_ALERT = 2  # debounce anti-flap LLDP


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_port(p) -> str:
    return str(p or "").strip().lower()


async def _resolve_alert(db, cfg, dedup_key: str, note: str) -> None:
    active = await db.alerts.find_one({"dedup_key": dedup_key, "status": "active"}, {"_id": 0})
    if not active:
        return
    await db.alerts.update_one(
        {"id": active["id"]},
        {"$set": {"status": "resolved", "resolved_at": _now_iso(),
                  "message": f"{active.get('message', '')} — {note}"}},
    )
    try:
        rec = {**active, "status": "resolved", "resolved_at": _now_iso(),
               "title": f"[RISOLTO] {active.get('title', '')}", "message": note}
        await _dispatch_notification(db, cfg, rec)
    except Exception:  # noqa: BLE001
        pass


async def _emit_alert(db, cfg, *, client_id: str, client_name: str, device_ip: str,
                      device_name: str, dedup_key: str, severity: str,
                      title: str, message: str) -> None:
    active = await db.alerts.find_one({"dedup_key": dedup_key, "status": "active"}, {"_id": 0})
    if active:
        if active.get("message") != message or active.get("severity") != severity:
            await db.alerts.update_one(
                {"id": active["id"]},
                {"$set": {"message": message, "severity": severity, "title": title}},
            )
        return
    alert = _mk_alert(client_id, client_name, device_name, device_ip,
                      "switch", severity, SOURCE_TYPE, title, message)
    alert["dedup_key"] = dedup_key
    try:
        if await insert_alert_if_emit(db, alert):
            await _dispatch_notification(db, cfg, alert)
            logger.info("cascade alert emitted client=%s key=%s", client_id, dedup_key)
    except Exception as e:  # noqa: BLE001
        logger.debug("cascade alert emit failed key=%s err=%s", dedup_key, e)


async def evaluate_cascade_alerts(db, client_id: str) -> None:
    """Valuta le anomalie della cascata per un cliente ed emette/risolve gli alert."""
    if not client_id:
        return
    from routes.topology_diagram import compute_switch_cascade
    try:
        casc = await compute_switch_cascade(client_id)
    except Exception as e:  # noqa: BLE001
        logger.debug("compute_switch_cascade failed client=%s err=%s", client_id, e)
        return

    # mappa ip -> nome (switch + gateway)
    names = {c["ip"]: c["name"] for c in casc.get("cascade", [])}
    for g in casc.get("gateways", []):
        names.setdefault(g["ip"], g["name"])

    # link correnti: chiave canonica "a|b" (a = ip minore, coerente col grafo)
    current = {}
    for e in casc.get("edges", []):
        a, b = e.get("a"), e.get("b")
        if not a or not b:
            continue
        current[f"{a}|{b}"] = {
            "a": a, "b": b,
            "a_port": e.get("a_port") or "",
            "b_port": e.get("b_port") or "",
            "verified": bool(e.get("verified")),
        }

    doc = await db.switch_cascade_baseline.find_one({"client_id": client_id}, {"_id": 0})
    baseline = (doc or {}).get("links", {}) or {}

    cfg = await get_config(db)
    cname_doc = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    client_name = (cname_doc or {}).get("name", client_id)

    new_baseline = {}

    # 1) link presenti ORA
    for key, cur in current.items():
        a, b = cur["a"], cur["b"]
        na, nb = names.get(a, a), names.get(b, b)
        base = baseline.get(key)
        entry = {**cur, "a_name": na, "b_name": nb, "last_seen": _now_iso(), "miss_count": 0}
        dedup_missing = f"cascade:{client_id}:{key}:missing"
        dedup_port = f"cascade:{client_id}:{key}:portchange"

        if base is None:
            # nuovo link: registra in baseline, nessun alert (prima scoperta)
            new_baseline[key] = entry
            continue

        # la baseline conserva le porte ATTESE (prima scoperta): non driftano,
        # cosi' un ricablaggio resta segnalato finche' non si ripristina la porta.
        entry["a_port"] = base.get("a_port", "")
        entry["b_port"] = base.get("b_port", "")
        entry["verified"] = bool(base.get("verified")) or cur["verified"]

        # riapparso dopo assenza -> risolvi eventuale alert "scomparso"
        if base.get("miss_count", 0) > 0:
            await _resolve_alert(db, cfg, dedup_missing,
                                 f"Uplink {na} <-> {nb} tornato attivo")

        # confronto porte con la baseline attesa: se cambiate -> ricablaggio
        bp_a, bp_b = _norm_port(base.get("a_port")), _norm_port(base.get("b_port"))
        cp_a, cp_b = _norm_port(cur["a_port"]), _norm_port(cur["b_port"])
        ports_known = (bp_a or bp_b) and (cp_a or cp_b)
        if ports_known and (bp_a != cp_a or bp_b != cp_b):
            msg = (f"L'uplink tra {na} ({a}) e {nb} ({b}) e' cambiato di porta: "
                   f"prima {base.get('a_port') or '?'} <-> {base.get('b_port') or '?'}, "
                   f"ora {cur['a_port'] or '?'} <-> {cur['b_port'] or '?'}. "
                   f"Possibile ricablaggio o spostamento cavo.")
            await _emit_alert(db, cfg, client_id=client_id, client_name=client_name,
                              device_ip=a, device_name=na, dedup_key=dedup_port,
                              severity="high",
                              title=f"Uplink cambiato porta: {na} <-> {nb}", message=msg)
        else:
            # porte invariate -> risolvi eventuale alert di cambio porta
            await _resolve_alert(db, cfg, dedup_port,
                                 f"Uplink {na} <-> {nb} di nuovo sulla porta attesa")

        new_baseline[key] = entry

    # 2) link della baseline SPARITI (non piu' presenti ora)
    for key, base in baseline.items():
        if key in current:
            continue
        a, b = base.get("a"), base.get("b")
        na, nb = base.get("a_name") or names.get(a, a), base.get("b_name") or names.get(b, b)
        miss = int(base.get("miss_count", 0)) + 1
        entry = {**base, "miss_count": miss}
        new_baseline[key] = entry
        # allerta solo per link precedentemente VERIFICATI (LLDP+FDB) dopo debounce
        if miss >= MISS_CYCLES_BEFORE_ALERT and base.get("verified"):
            dedup_missing = f"cascade:{client_id}:{key}:missing"
            msg = (f"L'uplink verificato tra {na} ({a}) e {nb} ({b}) non e' piu' rilevato "
                   f"(porta attesa {base.get('a_port') or '?'} <-> {base.get('b_port') or '?'}). "
                   f"Possibile cavo scollegato, switch spento o loop che ha isolato la tratta.")
            await _emit_alert(db, cfg, client_id=client_id, client_name=client_name,
                              device_ip=a, device_name=na, dedup_key=dedup_missing,
                              severity="high",
                              title=f"Uplink scomparso: {na} <-> {nb}", message=msg)

    await db.switch_cascade_baseline.update_one(
        {"client_id": client_id},
        {"$set": {"client_id": client_id, "links": new_baseline, "updated_at": _now_iso()}},
        upsert=True,
    )
