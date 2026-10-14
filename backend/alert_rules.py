"""Regole Alert Engine configurabili: regole su metrica (soglia + durata) e dipendenze padre → figli.

- `alert_metric_rules`: {id, name, metric, operator, threshold, duration_min, severity, scope, client_id, device_ip, enabled}
- `metric_rule_state`: {rule_id, client_id, device_ip, breach_since, alert_id}
- `alert_dependencies`: {id, client_id, parent_ip, child_ips[], source}
- `nic_hosts`: {client_id, mac, host_ip} (host scelto manualmente per un gruppo MAC condiviso)
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from database import db
from mac_follow import norm_mac

logger = logging.getLogger("alert_rules")

METRICS = {
    "packet_loss": "Perdita pacchetti (%)",
    "latency": "Latenza ping (ms)",
    "cpu": "CPU (%)",
    "ram": "RAM (%)",
    "disk": "Disco (%)",
    "temperature": "Temperatura (°C)",
}
SEVERITIES = ("low", "medium", "high", "critical")
DOWN_SOURCE_HINTS = ("offline", "down", "unreachable", "ping", "corr_", "vital", "datto_offline", "no_response")
_VM = ("hyperv", "vmware", "vm_generic")


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _max_nested(v: Any) -> Optional[float]:
    if isinstance(v, dict):
        nums = [x for x in (_max_nested(i) for i in v.values()) if x is not None]
        return max(nums) if nums else None
    n = _num(v)
    return n if n is not None and -50 < n < 200 else None


def extract_metric(pd: dict, metric: str) -> Optional[float]:
    ps = pd.get("ping_stats") or {}
    vm = pd.get("vendor_metrics") or {}
    if metric == "packet_loss":
        return _num(ps.get("packet_loss"))
    if metric == "latency":
        return _num(ps.get("avg")) if _num(ps.get("avg")) is not None else _num(pd.get("ping_ms"))
    if metric == "cpu":
        return _num(pd.get("cpu_usage"))
    if metric == "ram":
        return _num(pd.get("memory_usage"))
    if metric == "disk":
        for k in ("disk_usage", "disk_max_pct", "disk_used_pct"):
            if _num(pd.get(k)) is not None:
                return _num(pd.get(k))
        vals = [_max_nested(v) for k, v in vm.items() if "disk" in k.lower() and ("pct" in k.lower() or "usage" in k.lower() or "used" in k.lower())]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else None
    if metric == "temperature":
        if _num(pd.get("temperature")) is not None:
            return _num(pd.get("temperature"))
        vals = [_max_nested(v) for k, v in vm.items() if "temp" in k.lower()]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else None
    return None


def _breach(value: float, op: str, threshold: float) -> bool:
    return value < threshold if op == "<" else value > threshold


def _rule_applies(rule: dict, cid: str, ip: str) -> bool:
    scope = rule.get("scope") or "all"
    if scope == "client":
        return rule.get("client_id") == cid
    if scope == "device":
        return rule.get("client_id") == cid and rule.get("device_ip") == ip
    return True


async def _resolve(alert_id: Optional[str], now: str, reason: str) -> None:
    if alert_id:
        await db.alerts.update_one({"id": alert_id, "status": {"$ne": "resolved"}},
                                   {"$set": {"status": "resolved", "resolved_at": now, "resolution_reason": reason}})


async def run_metric_rules(now_dt: Optional[datetime] = None) -> int:
    """Valuta tutte le regole attive su device_poll_status. Ritorna il numero di alert emessi."""
    rules = await db.alert_metric_rules.find({"enabled": {"$ne": False}}, {"_id": 0}).to_list(500)
    if not rules:
        return 0
    now_dt = now_dt or datetime.now(timezone.utc)
    now = now_dt.isoformat()
    polls = await db.device_poll_status.find({}, {"_id": 0, "client_id": 1, "device_ip": 1, "device_name": 1, "ping_stats": 1,
                                                  "ping_ms": 1, "cpu_usage": 1, "memory_usage": 1, "temperature": 1,
                                                  "vendor_metrics": 1, "disk_usage": 1, "disk_max_pct": 1, "disk_used_pct": 1}).to_list(20000)
    emitted = 0
    from alert_filter import insert_alert_if_emit
    states = {(x["rule_id"], x["client_id"], x["device_ip"]): x
              async for x in db.metric_rule_state.find({}, {"_id": 0})}
    for rule in rules:
        for pd in polls:
            cid, ip = pd.get("client_id"), pd.get("device_ip")
            if not cid or not ip or not _rule_applies(rule, cid, ip):
                continue
            key = {"rule_id": rule["id"], "client_id": cid, "device_ip": ip}
            st = states.get((rule["id"], cid, ip))
            val = extract_metric(pd, rule["metric"])
            if val is None or not _breach(val, rule.get("operator", ">"), float(rule["threshold"])):
                if st:
                    await _resolve(st.get("alert_id"), now, "metric_back_to_normal")
                    await db.metric_rule_state.delete_one(key)
                continue
            if not st:
                st = {**key, "breach_since": now, "alert_id": None}
                await db.metric_rule_state.insert_one(dict(st))
            since = datetime.fromisoformat(st["breach_since"])
            if st.get("alert_id") or (now_dt - since).total_seconds() < float(rule.get("duration_min") or 0) * 60:
                continue
            name = pd.get("device_name") or ip
            label = METRICS.get(rule["metric"], rule["metric"])
            alert = {
                "id": str(uuid.uuid4()), "client_id": cid, "device_ip": ip, "device_name": name, "device_type": "",
                "severity": rule.get("severity") or "medium", "source_type": "metric_rule", "rule_id": rule["id"],
                "title": f"{rule.get('name') or label}: {name} ({ip})",
                "message": f"{label} = {round(val, 1)} {rule.get('operator', '>')} {rule['threshold']} "
                           f"da almeno {rule.get('duration_min') or 0} minuti (regola '{rule.get('name') or label}').",
                "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None, "created_at": now,
            }
            if await insert_alert_if_emit(db, alert):
                emitted += 1
                await db.metric_rule_state.update_one(key, {"$set": {"alert_id": alert["id"]}})
    return emitted


# ---------------- Dipendenze padre → figli ----------------

async def parents_of(client_id: str, ip: str) -> list[str]:
    deps = await db.alert_dependencies.find({"client_id": client_id, "child_ips": ip}, {"_id": 0, "parent_ip": 1}).to_list(50)
    return [d["parent_ip"] for d in deps if d.get("parent_ip") and d["parent_ip"] != ip]


async def is_parent_down(client_id: str, parent_ip: str) -> bool:
    if await db.vital_offline_state.find_one({"client_id": client_id, "ip": parent_ip, "level": {"$gte": 1}}, {"_id": 1}):
        return True
    alerts = await db.alerts.find({"client_id": client_id, "device_ip": parent_ip, "status": "active"},
                                  {"_id": 0, "source_type": 1}).to_list(50)
    return any(any(h in (a.get("source_type") or "") for h in DOWN_SOURCE_HINTS) for a in alerts)


async def suppressed_by_parent(alert_doc: dict) -> Optional[str]:
    """Se un padre del device e' giu', registra il figlio come impattato sull'alert del padre e ritorna l'IP padre."""
    cid = alert_doc.get("client_id")
    ip = alert_doc.get("device_ip") or alert_doc.get("ip")
    if not cid or not ip or alert_doc.get("source_type") in ("metric_rule", "nic_changed", "device_recovery"):
        return None
    for pip in await parents_of(cid, ip):
        if await is_parent_down(cid, pip):
            try:
                await db.alerts.update_many(
                    {"client_id": cid, "device_ip": pip, "status": "active"},
                    {"$addToSet": {"impacted_devices": {"name": alert_doc.get("device_name") or ip, "ip": ip}}})
            except Exception as e:  # noqa: BLE001
                logger.debug("dependency impact %s->%s: %s", pip, ip, e)
            return pip
    return None


async def dependency_children_map(client_ids: Optional[set] = None) -> dict:
    """{(client_id, child_ip): [parent_ip,...]} per la soppressione nel vital watchdog."""
    q = {"client_id": {"$in": list(client_ids)}} if client_ids else {}
    out: dict = {}
    async for d in db.alert_dependencies.find(q, {"_id": 0, "client_id": 1, "parent_ip": 1, "child_ips": 1}):
        for c in d.get("child_ips") or []:
            out.setdefault((d["client_id"], c), []).append(d["parent_ip"])
    return out


# ---------------- Gruppi MAC condiviso (server host → VM) ----------------

def _propose_host(members: list[dict]) -> dict:
    phys = [m for m in members if (m.get("virtualization") or "") == "physical"]
    if phys:
        return phys[0]
    non_vm = [m for m in members if (m.get("virtualization") or "") not in _VM]
    if len(non_vm) == 1:
        return non_vm[0]
    names = Counter((m.get("name") or "").strip().upper() for m in members if m.get("name"))
    if names:
        top, n = names.most_common(1)[0]
        if n > 1:
            pool = non_vm or members
            for m in pool:
                if (m.get("name") or "").strip().upper() == top:
                    return m
    return (non_vm or members)[0]


async def nic_groups(client_id: str) -> list[dict]:
    mds = await db.managed_devices.find(
        {"client_id": client_id, "$or": [{"mac": {"$nin": [None, ""]}}, {"mac_address": {"$nin": [None, ""]}}]},
        {"_id": 0, "id": 1, "ip": 1, "ip_address": 1, "mac": 1, "mac_address": 1, "name": 1, "virtualization": 1, "device_type": 1},
    ).to_list(5000)
    by_mac: dict[str, list[dict]] = {}
    for md in mds:
        mac = norm_mac(md.get("mac") or md.get("mac_address"))
        ip = md.get("ip") or md.get("ip_address")
        if mac and ip:
            by_mac.setdefault(mac, []).append({**md, "ip": ip, "mac": mac})
    manual = {h["mac"]: h.get("host_ip") async for h in db.nic_hosts.find({"client_id": client_id}, {"_id": 0})}
    groups = []
    for mac, members in by_mac.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: m["ip"])
        host = next((m for m in members if m["ip"] == manual.get(mac)), None)
        auto = host is None
        host = host or _propose_host(members)
        groups.append({
            "mac": mac, "host_ip": host["ip"], "host_name": host.get("name") or host["ip"], "host_manual": not auto,
            "members": [{"ip": m["ip"], "name": m.get("name") or m["ip"], "virtualization": m.get("virtualization") or ""} for m in members],
            "child_ips": [m["ip"] for m in members if m["ip"] != host["ip"]],
        })
    return groups
