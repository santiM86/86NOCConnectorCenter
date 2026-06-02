"""
Audit FRESHNESS della pipeline dati ARGUS Center.
Verifica che ogni collection di telemetria abbia dati aggiornati entro
i tempi concordati (vedi tabella in PRD).
"""
import os
import sys
import asyncio
import pathlib
from datetime import datetime, timezone

ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from database import db  # noqa: E402

# Soglie (secondi)
THRESH = {
    "managed_agents.last_heartbeat_at": 300,        # 5 min
    "connector_status.last_seen":       120,        # 2 min legacy
    "device_poll_status.last_poll":     600,        # 10 min SNMP
    "device_poll_status.last_reachable_at": 300,    # 5 min ping
    "managed_devices.last_seen_at":     900,        # 15 min discovery
    "wan_probe_results.checked_at":     300,        # 5 min WAN
    "printers.last_poll_at":            900,        # 15 min stampante
    "connector_status.last_lan_scan_at": 1800,      # 30 min scanner watchdog
}

NOW = datetime.now(timezone.utc)


def _age(ts):
    if ts is None:
        return None
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (NOW - dt).total_seconds()
    except Exception:
        return None


def _fmt(secs):
    if secs is None:
        return "—"
    if secs < 60:
        return f"{int(secs)}s"
    if secs < 3600:
        return f"{int(secs/60)}m"
    if secs < 86400:
        return f"{int(secs/3600)}h"
    return f"{int(secs/86400)}d"


async def _audit_collection(name, ts_field, threshold, extra_fields=None):
    extra_fields = extra_fields or []
    proj = {"_id": 0, ts_field: 1, "client_id": 1, "hostname": 1, "device_ip": 1,
            "device_name": 1, "ip": 1, "name": 1, "target_id": 1}
    for f in extra_fields:
        proj[f] = 1
    docs = await db[name].find({}, proj).to_list(20000)
    total = len(docs)
    fresh = 0
    stale = 0
    no_ts = 0
    oldest = 0
    oldest_doc = None
    samples_stale = []
    for d in docs:
        age = _age(d.get(ts_field))
        if age is None:
            no_ts += 1
            continue
        if age <= threshold:
            fresh += 1
        else:
            stale += 1
            if len(samples_stale) < 3:
                samples_stale.append(d)
            if age > oldest:
                oldest = age
                oldest_doc = d
    return {
        "collection": name, "field": ts_field, "threshold_s": threshold,
        "total": total, "fresh": fresh, "stale": stale, "no_ts": no_ts,
        "oldest_age_s": oldest, "oldest_doc": oldest_doc,
        "samples_stale": samples_stale,
    }


async def main():
    print(f"⏱  Audit Freshness @ {NOW.isoformat()}")
    print("=" * 80)

    results = []
    results.append(await _audit_collection(
        "managed_agents", "last_heartbeat_at",
        THRESH["managed_agents.last_heartbeat_at"], ["connected", "agent_id"]))
    results.append(await _audit_collection(
        "connector_status", "last_seen",
        THRESH["connector_status.last_seen"], ["mode"]))
    results.append(await _audit_collection(
        "connector_status", "last_lan_scan_at",
        THRESH["connector_status.last_lan_scan_at"], ["mode"]))
    results.append(await _audit_collection(
        "device_poll_status", "last_poll",
        THRESH["device_poll_status.last_poll"],
        ["device_type", "reachable", "monitor_type"]))
    results.append(await _audit_collection(
        "device_poll_status", "last_reachable_at",
        THRESH["device_poll_status.last_reachable_at"]))
    results.append(await _audit_collection(
        "managed_devices", "last_seen_at",
        THRESH["managed_devices.last_seen_at"], ["source"]))
    results.append(await _audit_collection(
        "wan_probe_results", "checked_at",
        THRESH["wan_probe_results.checked_at"]))
    # printers potrebbe non esistere
    try:
        results.append(await _audit_collection(
            "printers", "last_poll_at", THRESH["printers.last_poll_at"]))
    except Exception:
        pass

    print(f"{'Collection':35s} {'Field':25s} {'Total':>7s} {'Fresh':>7s} "
          f"{'Stale':>7s} {'NoTS':>6s} {'Oldest':>10s} {'Thresh':>8s}")
    print("-" * 120)
    issues = []
    for r in results:
        key = f"{r['collection']}.{r['field']}"
        ratio = (r["stale"] / r["total"] * 100) if r["total"] else 0
        flag = "⚠️" if ratio > 50 and r["total"] > 0 else " "
        print(f"{flag} {r['collection']:33s} {r['field']:25s} {r['total']:>7d} "
              f"{r['fresh']:>7d} {r['stale']:>7d} {r['no_ts']:>6d} "
              f"{_fmt(r['oldest_age_s']):>10s} {_fmt(r['threshold_s']):>8s}")
        if r["total"] > 0 and r["fresh"] == 0 and r["stale"] > 0:
            issues.append(f"❌ {key}: 0 record freschi su {r['total']} totali")
        elif ratio > 80 and r["total"] >= 5:
            issues.append(f"⚠️  {key}: {ratio:.0f}% stale ({r['stale']}/{r['total']})")

    print()
    print("=" * 80)
    print("📋 ISSUE RILEVATI:")
    if not issues:
        print("  ✅ Tutte le pipeline hanno dati freschi nei tempi concordati")
    else:
        for i in issues:
            print(f"  {i}")

    # Dettaglio per-cliente: % device freschi
    print()
    print("=" * 80)
    print("📊 DEVICE FRESHNESS PER-CLIENTE (device_poll_status):")
    clients = await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(50)
    devices = await db.device_poll_status.find(
        {}, {"_id": 0, "client_id": 1, "last_poll": 1, "last_reachable_at": 1,
             "reachable": 1, "device_ip": 1}
    ).to_list(20000)
    by_cid = {}
    for d in devices:
        cid = d.get("client_id")
        if not cid:
            continue
        if cid not in by_cid:
            by_cid[cid] = {"total": 0, "snmp_fresh": 0, "ping_fresh": 0}
        by_cid[cid]["total"] += 1
        if _age(d.get("last_poll")) and _age(d.get("last_poll")) <= 600:
            by_cid[cid]["snmp_fresh"] += 1
        if _age(d.get("last_reachable_at")) and _age(d.get("last_reachable_at")) <= 300:
            by_cid[cid]["ping_fresh"] += 1

    for c in clients:
        s = by_cid.get(c["id"], {"total": 0, "snmp_fresh": 0, "ping_fresh": 0})
        if s["total"] == 0:
            continue
        snmp_pct = s["snmp_fresh"] / s["total"] * 100
        ping_pct = s["ping_fresh"] / s["total"] * 100
        flag = "✅" if snmp_pct > 80 or ping_pct > 80 else "⚠️ "
        print(f"  {flag} {c['name']:25s} devices={s['total']:4d}  "
              f"SNMP fresh={s['snmp_fresh']:4d} ({snmp_pct:5.1f}%)  "
              f"PING fresh={s['ping_fresh']:4d} ({ping_pct:5.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
