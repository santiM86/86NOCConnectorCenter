"""
Dependency Graph + Impact Analysis (Argus Center) — Fase 2 CMDB.
Costruisce le relazioni tra entita' (upstream -> downstream) dai segnali gia'
raccolti (mac_connections, lldp_neighbors, Hyper-V) e calcola l'IMPATTO di un
guasto: "se cade X, quali entita' a valle restano impattate".

Modello archi: {src_entity, dst_entity, rel_type} con semantica
"dst DIPENDE DA src" (src e' a monte). Impatto(X) = BFS sui figli (dst dove src=X).
Collezione: cmdb_relationships.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("graph_builder")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ip_to_entity(db, client_id: str) -> Dict[str, dict]:
    """Mappa ip -> entita' del cliente."""
    out: Dict[str, dict] = {}
    async for e in db.cmdb_entities.find({"client_id": client_id}, {"_id": 0}):
        if e.get("primary_ip"):
            out[e["primary_ip"]] = e
    return out


async def build_relationships(db, client_id: str) -> int:
    ip2e = await _ip_to_entity(db, client_id)

    def eid(ip):
        e = ip2e.get(ip)
        return e["entity_id"] if e else None

    edges: Dict[Tuple[str, str, str], dict] = {}

    def add(src_ip, dst_ip, rel, port=None):
        s, d = eid(src_ip), eid(dst_ip)
        if not s or not d or s == d:
            return
        edges[(s, d, rel)] = {
            "client_id": client_id, "src_entity": s, "dst_entity": d,
            "rel_type": rel, "src_ip": src_ip, "dst_ip": dst_ip,
            "via_port": port, "updated_at": _now(),
        }

    # 1) mac_connections: device (from_ip) connesso allo switch (to_ip) => switch a monte
    async for m in db.mac_connections.find({"client_id": client_id}, {"_id": 0}):
        add(m.get("to_ip"), m.get("from_ip"), "connesso_a", m.get("from_port"))

    # 2) lldp_neighbors: il vicino (remote) e' tipicamente lo switch a monte del local
    async for n in db.lldp_neighbors.find({"client_id": client_id}, {"_id": 0}):
        add(n.get("remote_ip"), n.get("local_ip"), "lldp",
            n.get("remote_port_desc") or n.get("remote_port_id"))

    # 3) Hyper-V: la VM gira sull'host => host a monte della VM
    async for md in db.managed_devices.find(
        {"client_id": client_id, "hyperv_host_hint": {"$nin": [None, ""]}}, {"_id": 0}
    ):
        host_hint = str(md.get("hyperv_host_hint") or "").strip().lower()
        vm_ip = md.get("ip")
        if not host_hint or not vm_ip:
            continue
        # trova host per nome o ip
        host_ip = None
        for ip, e in ip2e.items():
            nm = str(e.get("name") or "").strip().lower()
            if host_hint == nm or host_hint == ip:
                host_ip = ip
                break
        if host_ip:
            add(host_ip, vm_ip, "gira_su")

    # sostituzione atomica per cliente
    await db.cmdb_relationships.delete_many({"client_id": client_id})
    if edges:
        await db.cmdb_relationships.insert_many(list(edges.values()))
    return len(edges)


async def build_all(db) -> Dict[str, int]:
    try:
        await db.cmdb_relationships.create_index([("client_id", 1), ("src_entity", 1)])
        await db.cmdb_relationships.create_index([("client_id", 1), ("dst_entity", 1)])
    except Exception:  # noqa: BLE001
        pass
    out: Dict[str, int] = {}
    async for c in db.clients.find({}, {"_id": 0, "id": 1}):
        cid = c.get("id")
        if not cid:
            continue
        try:
            out[cid] = await build_relationships(db, cid)
        except Exception as e:  # noqa: BLE001
            logger.warning("build_relationships %s failed: %s", cid, e)
    return out


async def compute_impact(db, entity_id: str) -> Dict[str, Any]:
    """BFS sui figli (entita' a valle) impattati dal guasto di `entity_id`."""
    root = await db.cmdb_entities.find_one({"entity_id": entity_id}, {"_id": 0})
    if not root:
        return {"found": False}
    client_id = root.get("client_id")

    # adiacenza src -> [ (dst, rel, port) ]
    adj: Dict[str, List[dict]] = {}
    async for e in db.cmdb_relationships.find({"client_id": client_id}, {"_id": 0}):
        adj.setdefault(e["src_entity"], []).append(e)

    impacted: Dict[str, dict] = {}
    queue: List[Tuple[str, int]] = [(entity_id, 0)]
    seen: Set[str] = {entity_id}
    while queue:
        cur, depth = queue.pop(0)
        for edge in adj.get(cur, []):
            dst = edge["dst_entity"]
            if dst in seen:
                continue
            seen.add(dst)
            impacted[dst] = {"entity_id": dst, "rel_type": edge["rel_type"],
                             "via": edge.get("via_port"), "depth": depth + 1}
            queue.append((dst, depth + 1))

    # arricchisci con nome/tipo/vitalita'
    devs: List[dict] = []
    if impacted:
        async for e in db.cmdb_entities.find(
            {"entity_id": {"$in": list(impacted)}}, {"_id": 0}
        ):
            info = impacted[e["entity_id"]]
            devs.append({
                "entity_id": e["entity_id"], "name": e.get("name"),
                "primary_ip": e.get("primary_ip"), "device_type": e.get("device_type"),
                "is_vital": bool(e.get("is_vital")), "rel_type": info["rel_type"],
                "depth": info["depth"],
            })
    devs.sort(key=lambda d: (d["depth"], not d["is_vital"], d["name"] or ""))
    return {
        "found": True,
        "entity_id": entity_id,
        "name": root.get("name"),
        "client_id": client_id,
        "impacted_count": len(devs),
        "impacted_vital": sum(1 for d in devs if d["is_vital"]),
        "impacted": devs,
    }
