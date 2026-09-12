"""Evidence Fusion v2 — "registro delle prove" per un device NON raggiungibile.

Ogni fonte (ping, L2, Datto, Hyper-V, iLO, porta switch, memoria porta, orario device,
flap, UPS, Nebula, SNMP, connettore) produce una PROVA con età e peso; le prove votano
ipotesi concorrenti. La confidenza è CALCOLATA: quota dell'ipotesi vincente sul totale,
limitata dal numero di fonti INDIPENDENTI concordi (1→65%, 2→82%, 3→92%, 4+→97%).
Prove forti in conflitto → verdetto "incerto" (mai una certezza falsa).
Espone anche `missing[]`: cosa manca per poter arrivare al 90%.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("evidence_fusion")

HYPOTHESES: dict[str, dict] = {
    "healthy_icmp_filtered": {"label": "Operativo (ICMP filtrato)", "up": True, "alertable": False, "severity": "none"},
    "intentional_off": {"label": "Spento volutamente", "up": False, "alertable": True, "severity": "low"},
    "hardware_down": {"label": "Spento / guasto hardware", "up": False, "alertable": True, "severity": "critical"},
    "os_hung": {"label": "Acceso ma SO bloccato", "up": False, "alertable": True, "severity": "critical"},
    "link_down": {"label": "Cavo / porta / scheda di rete", "up": False, "alertable": True, "severity": "high"},
    "power_outage": {"label": "Mancanza corrente (UPS)", "up": False, "alertable": True, "severity": "critical"},
    "monitoring_blind": {"label": "Monitoraggio cieco", "up": False, "alertable": False, "severity": "none"},
}
CAP_BY_SOURCES = {0: 55, 1: 65, 2: 82, 3: 92}
CAP_MAX = 97
SOFTMAX_K = 1.3
CONFLICT_RATIO = 0.7
SOURCE_LABELS = {
    "ping": "Ping", "l2": "Tabella MAC/ARP", "datto": "Datto RMM", "hyperv": "Host Hyper-V", "ilo": "iLO/Redfish",
    "port": "Porta switch", "port_memory": "Memoria porta", "schedule": "Orario abituale device", "flap": "Flap porta",
    "ups": "UPS", "nebula": "Zyxel Nebula", "snmp": "SNMP", "connector": "Connettore", "calendar": "Calendario",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _age_min(v) -> Optional[float]:
    d = _parse(v)
    return (_now() - d).total_seconds() / 60 if d else None


def _fresh(age: Optional[float]) -> float:
    if age is None:
        return 0.7
    if age <= 5:
        return 1.0
    if age <= 15:
        return 0.8
    if age <= 60:
        return 0.5
    return 0.25


class Ledger:
    def __init__(self):
        self.evidence: list[dict] = []
        self.missing: list[dict] = []

    def add(self, source: str, title: str, text: str, votes: dict[str, float], age_min: Optional[float] = None, weight: float = 1.0):
        f = _fresh(age_min) * weight
        self.evidence.append({"source": source, "source_label": SOURCE_LABELS.get(source, source), "title": title, "text": text,
                              "age_min": round(age_min, 1) if age_min is not None else None, "freshness": round(f, 2),
                              "votes": {h: round(w * f, 2) for h, w in votes.items()}})

    def miss(self, key: str, action: str, gain: str):
        self.missing.append({"key": key, "action": action, "gain": gain})


# ---------------------------------------------------------------------------
# raccolta prove
# ---------------------------------------------------------------------------
async def _l2_age(db, cid: str, ip: str, mac: str) -> Optional[float]:
    q: dict = {"client_id": cid, "$or": [{"ip": ip}]}
    if mac:
        q["$or"].append({"mac": {"$regex": f"^{mac}$", "$options": "i"}})
    doc = await db.discovered_endpoints.find_one(q, {"_id": 0, "last_seen_at": 1}, sort=[("last_seen_at", -1)])
    return _age_min((doc or {}).get("last_seen_at"))


async def _nebula(db, cid: str, ip: str, mac: str) -> Optional[dict]:
    q: dict = {"client_id": cid, "$or": [{"ip": ip}, {"lan_ip": ip}]}
    if mac:
        q["$or"].append({"mac": {"$regex": f"^{mac}$", "$options": "i"}})
    return await db.zyxel_devices.find_one(q, {"_id": 0, "online_status": 1, "fetched_at": 1, "updated_at": 1, "name": 1})


async def _ilo_cached(db, cid: str, ip: str) -> Optional[dict]:
    doc = await db.ilo_status.find_one({"client_id": cid, "device_ip": ip}, {"_id": 0, "power_state": 1, "timestamp": 1, "fetched_at": 1})
    if doc and doc.get("power_state"):
        return doc
    pd = await db.device_poll_status.find_one({"client_id": cid, "device_ip": ip}, {"_id": 0, "redfish.power_state": 1, "redfish.polled_at": 1})
    rf = (pd or {}).get("redfish") or {}
    return {"power_state": rf.get("power_state"), "timestamp": rf.get("polled_at")} if rf.get("power_state") else None


async def _has_ilo_cred(db, ip: str) -> bool:
    return await db.device_credentials.count_documents({"device_ip": ip, "credential_type": {"$in": ["ilo", "redfish", "idrac", "bmc"]}}) > 0


async def fuse(db, md: dict, pd: Optional[dict], s: dict, family: str, ilo_power: Optional[str] = None) -> dict:
    """md = managed device, pd = poll status, s = correlation_engine.gather_signals(...)."""
    from shutdown_diagnosis import _down_history, _port_signal, _schedule_signal, find_switch_port
    from port_memory import classify_port, is_italian_holiday

    cid = md.get("client_id")
    ip = md.get("ip") or md.get("ip_address")
    mac = (md.get("mac") or md.get("mac_address") or (pd or {}).get("primary_mac") or "").lower().replace("-", ":")
    L = Ledger()
    offline_since = _parse((pd or {}).get("unreachable_since"))
    down_min = (_now() - offline_since).total_seconds() / 60 if offline_since else None

    if s.get("ping") is True:
        return _result("healthy_icmp_filtered", 100, L, {"healthy_icmp_filtered": 1.0}, {"ping"}, override_label="Raggiungibile")

    if not s.get("connector_live"):
        L.add("connector", "Connettore offline", "Il connettore on-site non risponde: le prove locali (ping, L2, SNMP) non sono affidabili.", {"monitoring_blind": 2.0})
    else:
        L.add("ping", "Ping FAIL" + (f" da {int(down_min)} min" if down_min is not None else ""),
              "Nessuna risposta ICMP dal connettore on-site.", {"hardware_down": 0.5, "os_hung": 0.5, "intentional_off": 0.5, "link_down": 0.5},
              age_min=_age_min((pd or {}).get("last_poll_at") or (pd or {}).get("updated_at")))

    # L2
    l2_age = await _l2_age(db, cid, ip, mac)
    if s.get("l2_alive") and l2_age is not None and l2_age <= 15:
        L.add("l2", f"MAC/IP visto in rete {int(l2_age)} min fa", "Presente nella tabella MAC dello switch / ARP: la scheda di rete è alimentata e attiva.",
              {"healthy_icmp_filtered": 1.0, "os_hung": 0.6}, age_min=l2_age)
    else:
        L.add("l2", "Nessuna evidenza L2 recente" + (f" (ultima {int(l2_age)} min fa)" if l2_age is not None else ""),
              "Il MAC non compare più su switch/ARP: NIC spenta o cavo scollegato.", {"hardware_down": 0.6, "intentional_off": 0.6, "link_down": 0.5},
              age_min=min(l2_age, 5) if l2_age is not None else None)

    # Datto RMM
    if s.get("datto_matched"):
        if s.get("datto") == "online" and s.get("datto_reliable", True):
            L.add("datto", "Agente Datto ONLINE", "L'agente RMM risponde al cloud: il sistema operativo è acceso e connesso.", {"healthy_icmp_filtered": 1.2}, age_min=5)
        elif s.get("datto") == "offline":
            dm = s.get("datto_minutes")
            match = down_min is not None and dm is not None and abs(dm - down_min) <= 10
            L.add("datto", "Agente Datto OFFLINE" + (f" da {int(dm)} min" if dm else ""),
                  "L'agente RMM non risponde" + (" — coincide con l'inizio del down: spegnimento/guasto reale." if match else "."),
                  {"hardware_down": 0.7 + (0.3 if match else 0), "intentional_off": 0.7 + (0.3 if match else 0), "os_hung": 0.5}, age_min=5)
        elif not s.get("datto_reliable", True):
            L.add("datto", "Datto non affidabile ora", "Portale Datto in blackout/sync stantia: segnale scartato.", {}, weight=0)
    else:
        L.miss("datto", "Associa un agente Datto RMM a questo dispositivo", "conferma indipendente dello stato del sistema operativo")

    # Hyper-V
    hv = s.get("hyperv_state")
    if hv == "Running":
        L.add("hyperv", "VM Running sull'host Hyper-V", "L'host dichiara la VM accesa.", {"healthy_icmp_filtered": 0.8, "os_hung": 0.9}, age_min=10)
    elif hv in ("Off", "Saved", "Paused"):
        L.add("hyperv", f"VM {hv} sull'host Hyper-V", "L'host dichiara la VM spenta/sospesa: spegnimento deliberato.", {"intentional_off": 1.6}, age_min=10)

    # iLO / Redfish
    ilo = ilo_power
    ilo_age = None
    if not ilo and family == "server":
        cached = await _ilo_cached(db, cid, ip)
        if cached:
            ilo = "On" if str(cached.get("power_state", "")).lower().startswith("on") else "Off" if str(cached.get("power_state", "")).lower().startswith("off") else None
            ilo_age = _age_min(cached.get("timestamp") or cached.get("fetched_at"))
    if ilo == "Off":
        L.add("ilo", "iLO: PowerState = Off", "Il BMC conferma il server SPENTO.", {"hardware_down": 1.6, "intentional_off": 0.4}, age_min=ilo_age)
    elif ilo == "On":
        L.add("ilo", "iLO: PowerState = On", "Hardware alimentato e acceso: il problema è SO/rete, non alimentazione.", {"os_hung": 1.3, "link_down": 0.6, "healthy_icmp_filtered": 0.3}, age_min=ilo_age)
    elif family == "server" and not await _has_ilo_cred(db, ip):
        L.miss("ilo", "Aggiungi le credenziali iLO/iDRAC/Redfish nel Vault", "distinzione certa tra server spento e SO bloccato")

    # Porta switch + memoria porta + flap
    st = await db.device_status_state.find_one({"client_id": cid, "device_ip": ip}, {"_id": 0, "usual_speed_mbps": 1})
    port = await find_switch_port(db, cid, ip, mac or None)
    psig, pev = _port_signal(port, (st or {}).get("usual_speed_mbps"))
    if port and port.get("has_port_data"):
        page = _age_min(port.get("updated_at"))
        votes = {"down": {"intentional_off": 0.8, "hardware_down": 0.8, "link_down": 0.7},
                 "low_speed": {"intentional_off": 1.4},
                 "up_full": {"os_hung": 1.2, "healthy_icmp_filtered": 0.6},
                 "up_unknown_speed": {"os_hung": 0.5, "intentional_off": 0.4}}.get(psig, {})
        L.add("port", pev.get("title", "Porta switch"), f"{pev.get('where', '')}: {pev.get('text', '')}", votes, age_min=page)
        try:
            habit = await classify_port(db, cid, port["switch_ip"], port["port"], port.get("oper") == "up", 0.0)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"fusion classify_port {ip}: {e}")
            habit = {"verdict": "learning"}
        hv_ = habit.get("verdict")
        if hv_ == "habitual":
            L.add("port_memory", f"Memoria porta: {habit.get('label')}", habit.get("reason", ""), {"intentional_off": 1.2}, age_min=page)
        elif hv_ == "anomalous":
            L.add("port_memory", f"Memoria porta: {habit.get('label')}", habit.get("reason", ""), {"hardware_down": 0.6, "os_hung": 0.4, "link_down": 0.6}, age_min=page)
        elif hv_ == "standby_poe":
            L.add("port_memory", f"Memoria porta: {habit.get('label')}", habit.get("reason", ""), {"intentional_off": 1.3}, age_min=page)
        elif hv_ == "learning":
            L.miss("port_memory", f"Attendi la fine dell'apprendimento della porta ({habit.get('learning_days_left', 7)} gg)", "riconoscimento degli spegnimenti abituali")
        flaps = await db.port_flap_events.count_documents({"client_id": cid, "local_ip": port["switch_ip"], "idx": port["port"],
                                                           "ts": {"$gte": (_now() - timedelta(minutes=60)).isoformat()}})
        if flaps >= 3:
            L.add("flap", f"{flaps} flap sulla porta nell'ultima ora", "Link instabile: cavo/connettore/NIC difettosi.", {"link_down": 1.1})
    elif port:
        L.miss("port", f"Abilita SNMP (ifTable) sullo switch {port.get('switch_name')} per leggere lo stato porta", "stato link/velocità/PoE della porta del device")
    else:
        L.miss("port", "Nessuna porta switch associata: monitora via SNMP lo switch a monte o attiva lo scanner ARP dell'agent", "stato fisico del collegamento e memoria porta")

    # Orario abituale del device
    downs = await _down_history(db, cid, ip)
    ssig, sev, hist = _schedule_signal(downs, offline_since)
    if ssig == "usual":
        L.add("schedule", sev.get("title", "Orario abituale"), sev.get("text", ""), {"intentional_off": 1.0}, age_min=0)
    elif ssig == "unusual":
        L.add("schedule", sev.get("title", "Orario anomalo"), sev.get("text", ""), {"hardware_down": 0.5, "os_hung": 0.5, "link_down": 0.3}, age_min=0)
    else:
        L.miss("schedule", "Storico spegnimenti del device ancora scarso (serve ~2 settimane)", "riconoscimento degli orari di spegnimento abituali")
    hol = is_italian_holiday()
    if hol:
        L.add("calendar", f"Oggi festivo: {hol}", "Giornata di chiusura: spegnimenti attesi.", {"intentional_off": 0.4}, age_min=0)

    # UPS
    try:
        from alert_engine import _ups_power_loss
        ups_ok, ups_detail = await _ups_power_loss(db, cid, minutes=30)
    except Exception:  # noqa: BLE001
        ups_ok, ups_detail = False, ""
    if ups_ok:
        L.add("ups", "UPS su batteria", ups_detail or "Un UPS del cliente segnala assenza di rete elettrica.", {"power_outage": 1.8, "hardware_down": 0.3}, age_min=5)

    # Zyxel Nebula
    nb = await _nebula(db, cid, ip, mac)
    if nb and nb.get("online_status"):
        nage = _age_min(nb.get("fetched_at") or nb.get("updated_at"))
        if str(nb["online_status"]).upper() == "ONLINE":
            L.add("nebula", "Nebula: dispositivo ONLINE", "Il cloud Zyxel vede il device connesso.", {"healthy_icmp_filtered": 1.0}, age_min=nage)
        else:
            L.add("nebula", f"Nebula: {nb['online_status']}", "Il cloud Zyxel non vede il device.", {"hardware_down": 0.6, "link_down": 0.4}, age_min=nage)

    # SNMP diretto
    if s.get("snmp") is True:
        L.add("snmp", "SNMP risponde", "Il device risponde a SNMP: acceso, solo ICMP bloccato.", {"healthy_icmp_filtered": 1.3}, age_min=5)

    return _score(L, ip)


def _score(L: Ledger, ip: str) -> dict:
    tot: dict[str, float] = {h: 0.0 for h in HYPOTHESES}
    srcs: dict[str, set] = {h: set() for h in HYPOTHESES}
    for e in L.evidence:
        for h, w in e["votes"].items():
            tot[h] += w
            if w >= 0.4:
                srcs[h].add(e["source"])
    ranked = sorted(tot.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    # softmax (pesi = log-verosimiglianze): le prove NON discriminanti (votano più ipotesi
    # allo stesso modo) non spostano il rapporto; decidono quelle discriminanti.
    exps = {h: math.exp(SOFTMAX_K * v) for h, v in tot.items() if v > 0}
    raw = 100 * exps.get(top, 0) / (sum(exps.values()) or 1.0)
    n_src = len(srcs[top] - {"ping", "calendar"})
    cap = CAP_BY_SOURCES.get(n_src, CAP_MAX)
    conflict = top_score > 0 and second_score >= CONFLICT_RATIO * top_score
    if conflict:
        cap = min(cap, 60)
    conf = int(min(raw, cap)) if top_score > 0 else 0
    return _result(top, conf, L, tot, srcs[top], conflict=conflict)


def _result(hyp: str, conf: int, L: Ledger, scores: dict, sources: set, conflict: bool = False, override_label: str = None) -> dict:
    h = HYPOTHESES[hyp]
    sev = h["severity"]
    if conflict and hyp != "healthy_icmp_filtered":
        sev = "medium" if sev in ("critical", "high") else sev
    label = override_label or h["label"]
    n = len(sources - {"ping", "calendar"})
    reasoning = f"{label} — {n} fonti indipendenti concordi" + (" (prove in conflitto: verdetto incerto)" if conflict else "")
    return {"engine": "v2", "root_cause": hyp, "label": label, "up": h["up"], "alertable": h["alertable"], "severity": sev,
            "confidence": conf, "conflict": conflict, "reasoning": reasoning,
            "sources": sorted(sources), "scores": {k: round(v, 2) for k, v in scores.items() if v > 0},
            "evidence": L.evidence, "missing": L.missing}


# ---------------------------------------------------------------------------
# copertura (anche per device UP): quali fonti avremmo se andasse giù
# ---------------------------------------------------------------------------
async def coverage(db, md: dict, ctx_datto_matched: bool, family: str) -> dict:
    from shutdown_diagnosis import _down_history, find_switch_port
    cid = md.get("client_id")
    ip = md.get("ip") or md.get("ip_address")
    mac = (md.get("mac") or md.get("mac_address") or "").lower().replace("-", ":")
    have: list[str] = ["ping", "l2"]
    missing: list[dict] = []
    if ctx_datto_matched:
        have.append("datto")
    else:
        missing.append({"key": "datto", "action": "Associa un agente Datto RMM", "gain": "stato SO indipendente"})
    if family == "server":
        if await _has_ilo_cred(db, ip):
            have.append("ilo")
        else:
            missing.append({"key": "ilo", "action": "Aggiungi credenziali iLO/Redfish nel Vault", "gain": "server spento vs SO bloccato"})
    if md.get("hyperv_vm_name") or md.get("is_vm"):
        have.append("hyperv")
    port = await find_switch_port(db, cid, ip, mac or None)
    if port and port.get("has_port_data"):
        have.append("port")
        mem = await db.port_memory.find_one({"client_id": cid, "local_ip": port["switch_ip"], "idx": port["port"]}, {"_id": 0, "first_seen": 1, "samples": 1})
        import port_memory as _pm
        ld = await _pm.refresh_learning_days(db)
        if mem and (_age_min(mem.get("first_seen")) or 0) >= ld * 1440 and int(mem.get("samples") or 0) >= 50:
            have.append("port_memory")
        else:
            left = ld - ((_age_min((mem or {}).get("first_seen")) or 0) / 1440)
            missing.append({"key": "port_memory", "action": f"Memoria porta in apprendimento ({max(0, left):.0f} gg rimanenti)", "gain": "spegnimenti abituali"})
    elif port:
        missing.append({"key": "port", "action": f"Abilita SNMP ifTable sullo switch {port.get('switch_name')}", "gain": "stato porta"})
    else:
        missing.append({"key": "port", "action": "Nessuna porta switch associata: monitora lo switch a monte via SNMP", "gain": "stato fisico link + memoria porta"})
    if len(await _down_history(db, cid, ip)) >= 3:
        have.append("schedule")
    else:
        missing.append({"key": "schedule", "action": "Storico spegnimenti scarso (si popola da solo)", "gain": "orari abituali"})
    if await db.zyxel_devices.count_documents({"client_id": cid, "$or": [{"ip": ip}, {"lan_ip": ip}]}) > 0:
        have.append("nebula")
    n = len([h for h in have if h not in ("ping",)])
    cap = CAP_BY_SOURCES.get(min(n, 3), CAP_MAX) if n < 4 else CAP_MAX
    return {"sources": have, "sources_count": n, "max_confidence": cap, "missing": missing}
