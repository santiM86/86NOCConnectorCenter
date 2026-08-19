"""
Situation Engine — verdetto UNICO e autorevole per dispositivo (Argus Center)
=============================================================================
Fonde TUTTI i domini (raggiungibilita' + hardware + backup + sicurezza +
performance + rete) in UNA sola situazione certa per dispositivo, con:
  - overall_state  : OK | WARNING | CRITICAL | UNKNOWN
  - primary        : la situazione dominante dichiarata (con causa radice)
  - confidence     : % di certezza del verdetto primario
  - evidence[]     : TUTTE le prove che hanno contribuito (per trasparenza)
  - recommended_action : cosa fare (runbook sintetico)

Principio: NON reimplementiamo la logica di dominio. La raggiungibilita' viene
calcolata "fresh" da correlation_engine (evidence fusion PING+L2+Datto+WAN+iLO+
SNMP+Hyper-V). Gli altri domini sono gia' valutati dai watchdog esistenti che
scrivono in `db.alerts` con source_type distinti: qui li AGGREGHIAMO e li
correliamo in un unico verdetto, deduplicando la causa radice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import correlation_engine as ce

logger = logging.getLogger("situation_engine")

SEV_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
SEV_TO_CONF = {"critical": 95, "high": 85, "medium": 65, "low": 50, "none": 100}

# Dominio dedotto dal source_type dell'alert.
_DOMAIN_RULES = [
    ("reachability", ("corr_", "site_blackout", "connector_offline", "connector_recovery",
                      "connector_watchdog", "datto_server_offline", "datto_sync_stale",
                      "external_monitor", "unreachable")),
    ("predictive", ("predictive_",)),
    ("security", ("osint_c2", "osint_exposure", "rogue_device", "security_identity_change",
                  "security_ip_mac_change", "security_mac_change", "security_mac_ip_roam",
                  "movement_anomaly")),
    ("hardware", ("hardware_snmp", "vendor_", "redfish", "threshold_temp", "threshold_cpu",
                  "threshold_memory", "threshold_port_down", "snmp")),
    ("backup", ("backup",)),
    ("performance", ("traffic_anomaly", "wan_", "external_monitor_line", "port_flap")),
    ("network", ("switch_cascade", "network", "wan_public_ip_change", "syslog")),
    ("discovery", ("new_devices_detected", "auto_promoted_vital")),
]

# Pesi di dominio (per scegliere il primario quando il device e' UP).
_DOMAIN_WEIGHT = {
    "security": 7, "predictive": 6, "reachability": 5, "hardware": 4, "backup": 3,
    "performance": 2, "network": 1, "discovery": 0,
}

# Runbook sintetico: azione consigliata per causa radice / dominio.
_ACTIONS: Dict[str, str] = {
    "server_powered_off": "Server SPENTO (iLO=Off). Riaccendi da iLO/fisicamente e verifica l'alimentazione.",
    "os_hung": "Hardware acceso ma SO bloccato. Prova reset via iLO; se non risponde, riavvio fisico e controlla i log.",
    "server_down": "Nessuna evidenza di vita. Verifica alimentazione, rete e stato fisico del server.",
    "unreachable": "Dispositivo irraggiungibile (nessuna risposta). Verifica alimentazione, cavo/porta di rete e stato del dispositivo.",
    "unresponsive_l2_present": "Presente in rete (MAC vivo) ma non risponde: verifica stack di rete/SO o riavvio in corso.",
    "site_power_down": "SITO TOTALMENTE GIU' (probabile mancanza corrente/WAN a monte). Contatta il cliente/ISP; non toccare i singoli device.",
    "site_isolated": "SITO ISOLATO (guasto uplink/rete). Verifica il collegamento a monte (firewall/uplink).",
    "isp_down": "Linea ISP GIU' (firewall raggiungibile, Internet no). Apri ticket con l'ISP.",
    "switch_down": "Switch DOWN, segmento isolato. Verifica alimentazione/uplink dello switch.",
    "firewall_mgmt_down": "IP di gestione firewall non raggiungibile (resto del sito ok). Verifica il mgmt-plane.",
    "vm_unexpected_shutdown": "VM critica SPENTA in modo inatteso sull'host Hyper-V. Riaccendi e indaga il motivo.",
    "datto_agent_issue": "Server operativo ma agent Datto KO. Riavvia/reinstalla l'agent Datto RMM.",
    "backup": "Backup fallito/mancante. Verifica il job di backup e lo spazio/destinazione.",
    "osint_c2": "Comunicazione con IP malevolo noto (C2): possibile COMPROMISSIONE. Isola il device e avvia incident response.",
    "osint_exposure": "CVE attivamente sfruttate esposte su IP pubblico. Applica patch/mitigazioni con priorita'.",
    "rogue_device": "Dispositivo sconosciuto/rogue in rete. Identifica e autorizza o blocca sulla porta.",
    "predictive_raid": "GUASTO IMMINENTE: RAID degradato/crashed. Verifica i dischi, sostituisci quello guasto e avvia la ricostruzione PRIMA di perdere ridondanza/dati.",
    "predictive_temp": "GUASTO IMMINENTE: temperatura in salita verso la soglia critica. Verifica ventole/condizionamento e pulizia filtri prima del blocco termico.",
    "predictive_ups": "GUASTO IMMINENTE: UPS in esaurimento. Verifica l'alimentazione di rete e lo stato/eta' della batteria; pianifica lo spegnimento controllato se resta su batteria.",
    "predictive": "GUASTO IMMINENTE previsto dai trend. Interveni sul componente segnalato prima del guasto.",
    "traffic_anomaly": "Anomalia di traffico rilevata. Verifica saturazione/eventi anomali sulla porta.",
    "external_monitor_line": "Linea/monitor esterno in errore: la connettivita' verso questo endpoint pubblico e' degradata o assente. Verifica linea ISP/servizio esposto.",
    "external_monitor": "Endpoint monitorato non raggiungibile dall'esterno. Verifica servizio/porta pubblica e stato linea.",
    "connector_watchdog": "Il Connettore (agent) non riporta piu' dati: verifica che il servizio agent sia attivo e connesso.",
    "connector_offline": "Connettore OFFLINE: nessuna visibilita' sul sito. Riavvia/ripristina l'agent sul posto.",
    "datto_sync_stale": "Sincronizzazione Datto RMM ferma/obsoleta: verifica la connessione Datto e l'ultimo aggiornamento.",
    "hardware": "Guasto/soglia hardware superata. Interveni sul componente segnalato (temp/PSU/ventole/RAID/disco/UPS).",
    "healthy": "Nessuna azione necessaria.",
}


# Etichette leggibili in italiano per le cause radice di raggiungibilita'.
_ROOT_LABELS = {
    "up": "Operativo", "healthy": "Operativo",
    "no_data": "Nessun dato disponibile",
    "connector_blind": "Connettore cieco (nessuna visibilita')",
    "server_powered_off": "Server spento",
    "os_hung": "Sistema operativo bloccato",
    "server_down": "Server irraggiungibile",
    "unresponsive_l2_present": "Non risponde (presente in rete)",
    "site_power_down": "Sito giu' (probabile mancanza corrente)",
    "site_isolated": "Sito isolato",
    "isp_down": "Linea ISP giu'",
    "switch_down": "Switch giu'",
    "firewall_mgmt_down": "Gestione firewall irraggiungibile",
    "vm_unexpected_shutdown": "VM spenta inaspettatamente",
    "datto_agent_issue": "Agent Datto non risponde",
    "unreachable": "Dispositivo irraggiungibile",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _classify_domain(source_type: str) -> str:
    st = (source_type or "").lower()
    best_domain, best_len = "network", -1
    for domain, prefixes in _DOMAIN_RULES:
        for p in prefixes:
            if st == p or st.startswith(p):
                if len(p) > best_len:  # longest-prefix wins (evita overlap)
                    best_domain, best_len = domain, len(p)
    return best_domain


def _state_from(severity: str, domain: str) -> str:
    r = SEV_RANK.get(severity, 0)
    if r >= 4:
        return "CRITICAL"
    if r == 3:  # high
        return "CRITICAL" if domain in ("reachability", "hardware", "security", "backup") else "WARNING"
    if r >= 1:
        return "WARNING"
    return "OK"


def _action_for(root_cause: str, domain: str) -> str:
    return _ACTIONS.get(root_cause) or _ACTIONS.get(domain) or "Verifica lo stato del dispositivo."


async def _best_poll(db, ip: str) -> Optional[dict]:
    recs = await db.device_poll_status.find({"device_ip": ip}, {"_id": 0}).to_list(50)
    if not recs:
        return None

    def key(pd):
        return (1 if pd.get("reachable") else 0, str(pd.get("last_ping_at") or pd.get("last_poll") or ""))
    return sorted(recs, key=key, reverse=True)[0]


def _liveness_evidence(md: dict, signals: dict, verdict: dict) -> Dict[str, Any]:
    """Situazione di raggiungibilita' come voce di evidence."""
    up = verdict.get("up")
    if up and not verdict.get("alertable"):
        sev = "none"
    else:
        sev = verdict.get("severity", "none")
    rc = verdict.get("root_cause")
    situation = _ROOT_LABELS.get(rc) or (rc or "").replace("_", " ").capitalize() or ("Operativo" if up else "Irraggiungibile")
    return {
        "domain": "reachability",
        "situation": situation,
        "root_cause": verdict.get("root_cause"),
        "severity": sev,
        "confidence": int(verdict.get("confidence") or 0),
        "source_type": f"corr_{verdict.get('root_cause')}",
        "up": bool(up),
        "reasoning": verdict.get("reasoning"),
        "signals": {
            "ping": signals.get("ping"),
            "l2_alive": signals.get("l2_alive"),
            "datto": signals.get("datto"),
            "connector_live": signals.get("connector_live"),
            "wan_fw_up": signals.get("fw_up"),
            "wan_rt_up": signals.get("rt_up"),
            "hyperv_state": signals.get("hyperv_state"),
            "snmp": signals.get("snmp"),
        },
    }


async def diagnose_device(
    db,
    device_ip: str,
    client_id: Optional[str] = None,
    ctx: Optional[dict] = None,
    md: Optional[dict] = None,
    cfg: Optional[dict] = None,
) -> Dict[str, Any]:
    """Verdetto unico e autorevole per un dispositivo."""
    q: Dict[str, Any] = {"ip": device_ip}
    if client_id:
        q["client_id"] = client_id
    md = md or await db.managed_devices.find_one(q, {"_id": 0})
    if not md:
        return {"found": False, "device_ip": device_ip, "client_id": client_id}

    cid = md.get("client_id") or client_id
    if cfg is None:
        try:
            from alert_engine import get_config
            cfg = await get_config(db)
        except Exception:
            cfg = {}
    if ctx is None:
        ctx = await ce.build_context(db, cfg)

    # --- 1) Verdetto liveness fresco (evidence fusion) ---
    pd = await _best_poll(db, device_ip)
    fam = ce.device_family(md)
    signals = ce.gather_signals(md, pd, ctx)
    if fam == "server":
        verdict = ce.verdict_server(signals, None)
        if not verdict["up"] and signals.get("datto") == "offline":
            try:
                from security import security_manager
                from deps import redfish_poller
                ilo = await ce.resolve_ilo_power(db, security_manager, redfish_poller, device_ip)
                if ilo:
                    verdict = ce.verdict_server(signals, ilo)
            except Exception:
                pass
    elif fam == "firewall":
        verdict = ce.verdict_firewall(signals, majority_down=False)
    elif fam == "switch":
        verdict = ce.verdict_switch(signals, children_all_down=False, has_children=False)
    else:
        verdict = ce.verdict_generic(signals)

    evidence: List[Dict[str, Any]] = [_liveness_evidence(md, signals, verdict)]

    # --- 2) Rollup degli alert ATTIVI di tutti gli altri domini ---
    # Aggancio per device_ip OPPURE per device_name (es. backup VM che portano
    # solo l'hostname/nome, non l'IP) → fusione trasversale piu' completa.
    or_clauses: List[dict] = [{"device_ip": device_ip}]
    dev_name = md.get("name") or md.get("device_name") or md.get("hostname")
    if dev_name:
        or_clauses.append({"device_name": dev_name})
    alert_q: Dict[str, Any] = {"status": "active", "$or": or_clauses}
    if cid:
        alert_q["client_id"] = cid
    async for a in db.alerts.find(alert_q, {"_id": 0}):
        st = a.get("source_type") or ""
        if st.startswith("corr_"):
            continue  # gia' rappresentato dal verdetto liveness fresco
        domain = _classify_domain(st)
        sev = a.get("severity", "medium")
        evidence.append({
            "domain": domain,
            "situation": (a.get("title") or st.replace("_", " ")).strip(),
            "root_cause": st,
            "severity": sev,
            "confidence": int(a.get("confidence") or SEV_TO_CONF.get(sev, 60)),
            "source_type": st,
            "alert_id": a.get("id"),
            "since": a.get("created_at"),
            "reasoning": a.get("message"),
        })

    # --- 3) Situazione primaria + stato complessivo ---
    live_ev = evidence[0]
    device_up = bool(verdict.get("up"))
    down_alertable = (not device_up) and verdict.get("alertable")

    others = evidence[1:]  # tutte le prove NON-liveness
    if down_alertable:
        primary = live_ev
    elif others:
        others_sorted = sorted(
            others,
            key=lambda e: (SEV_RANK.get(e["severity"], 0),
                           _DOMAIN_WEIGHT.get(e["domain"], 0),
                           e.get("confidence", 0)),
            reverse=True,
        )
        top = others_sorted[0]
        primary = top if SEV_RANK.get(top["severity"], 0) >= 2 else live_ev
    else:
        primary = live_ev

    # overall_state = peggiore tra tutte le prove (no_data/connector_blind -> UNKNOWN)
    order = {"OK": 0, "UNKNOWN": 1, "WARNING": 1, "CRITICAL": 2}
    live_unknown = live_ev.get("root_cause") in ("no_data", "connector_blind")
    overall = "UNKNOWN" if (live_unknown and not others) else "OK"
    for e in evidence:
        if e is live_ev and live_unknown:
            continue  # gia' considerato come UNKNOWN sopra
        s = _state_from(e["severity"], e["domain"])
        if order.get(s, 0) > order.get(overall, 0):
            overall = s

    root = primary.get("root_cause") or ""
    action = _action_for(root, primary.get("domain", ""))

    # Conteggio prove ANOMALE per dominio (per i badge del pannello)
    by_domain: Dict[str, int] = {}
    for e in evidence:
        if SEV_RANK.get(e.get("severity"), 0) >= 2:  # medium+
            by_domain[e["domain"]] = by_domain.get(e["domain"], 0) + 1

    return {
        "found": True,
        "device_ip": device_ip,
        "client_id": cid,
        "device_name": md.get("name") or md.get("device_name") or device_ip,
        "device_type": md.get("device_type") or fam,
        "is_vital": bool(md.get("is_vital")),
        "family": fam,
        "overall_state": overall,
        "up": device_up,
        "primary": {
            "domain": primary.get("domain"),
            "situation": primary.get("situation"),
            "root_cause": root,
            "severity": primary.get("severity"),
            "confidence": primary.get("confidence"),
            "reasoning": primary.get("reasoning"),
        },
        "recommended_action": action,
        "confidence": primary.get("confidence"),
        "evidence": evidence,
        "evidence_by_domain": by_domain,
        "evaluated_at": _now().isoformat(),
    }


async def diagnose_client(db, client_id: str, only_problems: bool = True) -> Dict[str, Any]:
    """Diagnosi unificata per tutti i dispositivi (vitali + infra) di un cliente."""
    from alert_engine import get_config
    cfg = await get_config(db)
    ctx = await ce.build_context(db, cfg)

    families = list(ce.SERVER_TYPES | ce.FIREWALL_TYPES | ce.SWITCH_TYPES)
    targets = await db.managed_devices.find(
        {"client_id": client_id,
         "$or": [{"is_vital": True}, {"device_type": {"$in": families}}]},
        {"_id": 0},
    ).to_list(10000)

    results = []
    counts = {"CRITICAL": 0, "WARNING": 0, "UNKNOWN": 0, "OK": 0}
    for md in targets:
        ip = md.get("ip") or md.get("ip_address")
        if not ip:
            continue
        try:
            d = await diagnose_device(db, ip, client_id=client_id, ctx=ctx, md=md, cfg=cfg)
        except Exception as e:
            logger.warning("diagnose_device fallita per %s: %s", ip, e)
            continue
        if not d.get("found"):
            continue
        counts[d["overall_state"]] = counts.get(d["overall_state"], 0) + 1
        if only_problems and d["overall_state"] in ("OK",):
            continue
        results.append(d)

    order = {"CRITICAL": 0, "WARNING": 1, "UNKNOWN": 2, "OK": 3}
    results.sort(key=lambda d: (order.get(d["overall_state"], 9), -(d.get("confidence") or 0)))

    # Situazioni a livello CLIENTE (alert attivi senza device_ip: backup VM,
    # sync Datto, linea/ISP, connettore) — aggregate per dominio.
    client_sits: List[Dict[str, Any]] = []
    grouped: Dict[str, Dict[str, Any]] = {}
    async for a in db.alerts.find(
        {"client_id": client_id, "status": "active",
         "$or": [{"device_ip": {"$in": ["", None]}}, {"device_ip": {"$exists": False}}]},
        {"_id": 0},
    ):
        st = a.get("source_type") or ""
        if st.startswith("corr_"):
            continue
        domain = _classify_domain(st)
        g = grouped.setdefault(st, {
            "domain": domain, "source_type": st, "count": 0,
            "severity": a.get("severity", "medium"),
            "sample_title": a.get("title"),
            "recommended_action": _action_for(st, domain),
        })
        g["count"] += 1
        if SEV_RANK.get(a.get("severity"), 0) > SEV_RANK.get(g["severity"], 0):
            g["severity"] = a.get("severity")
    for st, g in grouped.items():
        g["state"] = _state_from(g["severity"], g["domain"])
        client_sits.append(g)
    client_sits.sort(key=lambda g: (SEV_RANK.get(g["severity"], 0), g["count"]), reverse=True)

    # counts riflette gli stati dei DISPOSITIVI (scope device). Le situazioni a
    # livello cliente hanno il proprio stato in client_situations[].state e un
    # riepilogo dedicato qui sotto.
    client_counts = {"CRITICAL": 0, "WARNING": 0, "UNKNOWN": 0, "OK": 0}
    for g in client_sits:
        client_counts[g["state"]] = client_counts.get(g["state"], 0) + 1

    return {"client_id": client_id, "counts": counts, "devices": results,
            "client_situations": client_sits,
            "client_situation_counts": client_counts,
            "evaluated_at": _now().isoformat()}
