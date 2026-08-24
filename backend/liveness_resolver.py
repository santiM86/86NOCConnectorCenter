"""
Helper centralizzato per il calcolo dello stato "online/offline" di un device.

Risolve l'incoerenza tra Panoramica (overview.py) e lista Dispositivi
(devices.py): prima i due endpoint usavano logiche divergenti per dedurre
lo status, e con i fix v4.16.x evidence-based (FDB switch, ARP cache,
TCP fallback) la divergenza era diventata sistematica (Overview diceva
70/86 online ma la lista Dispositivi mostrava molti più offline).

Stessa filosofia di display_name.py e device_type_resolver.py: una sola
sorgente di verita' per il calcolo dello status.

Concetti chiave:
  - **Debounce anti-flap**: un singolo poll fallito NON marca offline.
    Servono ≥3 consecutive_failures E ≥5 minuti senza nessun successo.
  - **Evidence override**: se l'IP o il MAC del device sono stati visti
    negli ultimi 15 minuti tramite Scanner LAN, agent_v4 ARP, o FDB
    switch SNMP → ONLINE, qualsiasi cosa dica reachable=false.
  - **Cross-segment**: il connector Master puo' non avere visibilita'
    L3 su una VLAN remota; lo Scanner sulla VLAN giusta (o lo switch
    L2 via SNMP) sopperisce.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Mapping, Optional


# Defaults condivisi tra tutti i consumer
DEBOUNCE_MIN_FAILURES = 3      # 3 cicli consecutivi falliti
DEBOUNCE_GRACE_SECONDS = 300   # 5 minuti senza nessun successo
# A) Debounce PIU' RAPIDO per i dispositivi VITALI: allarme dopo ~2 min.
VITAL_MIN_FAILURES = 2
VITAL_GRACE_SECONDS = 120      # 2 minuti per i vitali
# C) Pre-allarme "soft": segnala il device che sta fallendo gia' dopo ~90s,
# prima dell'allarme pieno (debounce). Usato da services/pre_alarm.py.
PRE_ALARM_SECONDS = 90
EVIDENCE_WINDOW_MINUTES = 15   # quanto considerare "recente" un discovered_endpoint
# v2026-06 SPEED: l'agent invia heartbeat ogni 15s. 180s (12 beat persi) era
# troppo lento per rilevare un blackout "quasi live". 90s = 6 beat persi:
# resta robusto ai jitter ma dimezza il tempo di rilevazione offline/blackout.
AGENT_HEARTBEAT_STALE_SECONDS = 90
# Finestra di freschezza per i risultati della sonda WAN esterna. Solo i
# risultati piu' recenti di questo valore contano per decidere "WAN giu'"
# (evita che vecchi doc "online" blocchino per sempre il blackout).
WAN_PROBE_FRESHNESS_SECONDS = 180
SNMP_FRESHNESS_SECONDS = 600   # 10 minuti: SNMP poll < 10 min = device raggiungibile


def _snmp_fresh(pd: Optional[Mapping[str, Any]], seconds: int = SNMP_FRESHNESS_SECONDS) -> bool:
    """
    Ritorna True se il device ha risposto con successo a un poll SNMP
    recente (entro `seconds`, default 10 minuti).

    Permette di considerare ONLINE un apparato (es. switch HP, server Windows)
    che ha ICMP disabilitato o filtrato ma risponde correttamente a SNMP.
    """
    if not pd:
        return False
    if not pd.get("snmp_reachable"):
        return False
    at = pd.get("snmp_last_check_at") or pd.get("last_poll_at") or pd.get("last_poll")
    if not at:
        return False
    try:
        dt = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < seconds
    except Exception:
        return False


async def build_clients_without_online_agent(db) -> set:
    """
    Ritorna l'insieme dei client_id che NON hanno alcun connector con
    heartbeat fresco (entro 3 minuti).

    Usato per evitare falsi positivi "offline" durante un blackout del
    connector: se il monitor (agent) e' giu', i device su cui non puo'
    pollare non sono "offline" ma "stale" (stato incerto). Vedi
    compute_status() param `offline_clients`.

    Mitiga l'effetto cascata "connector down -> 36 device falsi offline -> card cliente
    tutta rossa" mostrato nello screenshot Galvan / ZITACSRV.

    Returns:
        set di client_id (str) i cui connector sono TUTTI offline.
    """
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=AGENT_HEARTBEAT_STALE_SECONDS)
    ).isoformat()

    clients_with_online: set = set()
    async for ag in db.managed_agents.find(
        {"last_heartbeat_at": {"$gte": cutoff}},
        {"_id": 0, "client_id": 1},
    ):
        cid = ag.get("client_id")
        if cid:
            clients_with_online.add(cid)

    clients_with_any: set = set()
    async for ag in db.managed_agents.find(
        {}, {"_id": 0, "client_id": 1},
    ):
        cid = ag.get("client_id")
        if cid:
            clients_with_any.add(cid)

    return clients_with_any - clients_with_online


async def build_wan_down_clients(db) -> set:
    """
    Ritorna l'insieme dei client_id la cui WAN e' GIU' secondo la sonda
    ESTERNA del Center (external monitor / wan_probe_results): nessun target
    del cliente e' raggiungibile.

    Questa e' l'UNICA sorgente di liveness INDIPENDENTE dall'agent on-site:
    gira dal Center, quindi resta valida anche durante un blackout totale del
    sito (quando l'agent muore). Serve a confermare un vero outage.

    v2026-06 FIX (RCA blackout Gualdi):
      - BUG#1 FRESCHEZZA: prima leggeva TUTTI i doc di wan_probe_results senza
        filtro temporale → un vecchio risultato "online" (target rimosso/rinominato
        o probe ferma) impediva per sempre la classificazione "WAN giu'". Ora
        consideriamo SOLO i risultati piu' freschi di WAN_PROBE_FRESHNESS_SECONDS.
      - BUG#2 LOGICA OR: prima `cur or reachable` → bastava UN solo target ancora
        raggiungibile (anche stantio) per tenere il cliente "su". Ora "WAN giu'"
        richiede che il cliente abbia almeno un risultato FRESCO e che NESSUN
        target sia raggiungibile (AND su tutti i target).
    """
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=WAN_PROBE_FRESHNESS_SECONDS)
    ).isoformat()
    # cid -> lista di bool "raggiungibile?" per ogni target FRESCO del cliente
    per_client: dict = {}
    try:
        async for r in db.wan_probe_results.find(
            {"checked_at": {"$gte": cutoff}},
            {"_id": 0, "client_id": 1, "status": 1, "ping": 1, "ports": 1, "checked_at": 1},
        ):
            cid = r.get("client_id")
            if not cid:
                continue
            reachable = (
                (r.get("ping") or {}).get("reachable")
                or r.get("status") in ("online", "filtered", "degraded")
                or any(p.get("open") for p in (r.get("ports") or []))
            )
            per_client.setdefault(cid, []).append(bool(reachable))
    except Exception:
        return set()
    # WAN giu' = il cliente HA risultati sonda FRESCHI e NESSUNO e' raggiungibile
    return {cid for cid, states in per_client.items() if states and not any(states)}


async def build_blackout_clients(db, offline_clients: Optional[set] = None) -> set:
    """
    Ritorna i client_id in BLACKOUT CONFERMATO: l'agent on-site e' offline
    (nessun heartbeat) E la sonda WAN esterna del Center vede l'internet del
    cliente GIU'. Due sorgenti indipendenti concordi -> il sito e' davvero giu'
    (mancanza corrente / guasto WAN a monte), non un semplice riavvio agent.

    In questo caso i device vanno mostrati OFFLINE (non solo "stale"), perche'
    abbiamo la prova indipendente (WAN) che sono irraggiungibili.
    """
    if offline_clients is None:
        offline_clients = await build_clients_without_online_agent(db)
    wan_down = await build_wan_down_clients(db)
    return set(offline_clients) & wan_down


def effective_reachable(pd: Optional[Mapping[str, Any]],
                        min_failures: int = DEBOUNCE_MIN_FAILURES,
                        grace_seconds: int = DEBOUNCE_GRACE_SECONDS) -> bool:
    """
    Decide se un device va mostrato online sulla base del solo poll
    record (device_poll_status), con debounce anti-flap. Per i VITALI si
    passa una soglia piu' bassa (grace 2 min) per un allarme piu' rapido.
    """
    if not pd:
        return False
    if pd.get("reachable"):
        return True
    # v2026-06-23 SNMP-only liveness centralizzato: se ICMP fallisce ma SNMP
    # e' fresco, il device E' raggiungibile (switch HP, server Windows, ecc.).
    if _snmp_fresh(pd):
        return True
    # reachable=False: debounce
    try:
        consec = int(pd.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        consec = 0
    last_ok = pd.get("last_reachable_at")
    if not last_ok:
        # Nessun successo registrato → fidati di reachable=false (offline)
        return False
    try:
        last_ok_dt = datetime.fromisoformat(str(last_ok).replace("Z", "+00:00"))
        secs_since = (datetime.now(timezone.utc) - last_ok_dt).total_seconds()
    except Exception:
        secs_since = 1e9
    # Offline SOLO se ENTRAMBE le condizioni sono superate
    if consec >= min_failures and secs_since >= grace_seconds:
        return False
    return True


def down_phase(pd: Optional[Mapping[str, Any]], is_vital: bool = False) -> str:
    """C) Fase di down di un device che sta fallendo (per il pre-allarme):
      - "ok"       : reachable o nessun fallimento
      - "prealarm" : sta fallendo da >= PRE_ALARM_SECONDS ma debounce non ancora scattato
      - "down"     : debounce scattato (offline confermato)
    """
    if not pd or pd.get("reachable"):
        return "ok"
    try:
        consec = int(pd.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        consec = 0
    last_ok = pd.get("last_reachable_at")
    if not last_ok:
        return "down"
    try:
        secs = (datetime.now(timezone.utc) - datetime.fromisoformat(str(last_ok).replace("Z", "+00:00"))).total_seconds()
    except Exception:
        secs = 1e9
    grace = VITAL_GRACE_SECONDS if is_vital else DEBOUNCE_GRACE_SECONDS
    minf = VITAL_MIN_FAILURES if is_vital else DEBOUNCE_MIN_FAILURES
    if consec >= minf and secs >= grace:
        return "down"
    if consec >= 1 and secs >= PRE_ALARM_SECONDS:
        return "prealarm"
    return "ok"


async def build_evidence_maps(
    db,
    client_id: Optional[str] = None,
    window_minutes: int = EVIDENCE_WINDOW_MINUTES,
) -> tuple[dict, dict]:
    """
    Costruisce le mappe `ip → evidence` e `mac → evidence` interrogando
    discovered_endpoints negli ultimi `window_minutes`.

    Source-of-truth unificato per:
      - Scanner LAN (ARP / mDNS)         → "scanner_lan"
      - Agent v4 Go (ICMP nativo / TCP)  → "agent_v4_arp"
      - FDB switch via SNMP              → "mac_table_switch"

    Args:
        db: motor AsyncIOMotorDatabase
        client_id: se fornito, restringe la query a un singolo cliente
                   (per overview multi-cliente passare None).
        window_minutes: finestra "live-seen" (default 15 min).

    Returns:
        Tuple (ip_evidence, mac_evidence) — entrambe dict.
        Le chiavi sono str (ip) o mac lowercase ":"-separato.
        I valori sono label evidence usate dalla UI ("Vivo via ...").
    """
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    ).isoformat()
    query: dict = {"last_seen_at": {"$gte": cutoff_iso}}
    if client_id:
        query["client_id"] = client_id

    ip_evidence: dict = {}
    mac_evidence: dict = {}
    try:
        async for de in db.discovered_endpoints.find(
            query,
            {
                "_id": 0, "ip": 1, "mac": 1,
                "source_connector_mode": 1, "last_seen_via": 1,
                "switch_ip": 1,
            },
        ):
            de_ip = de.get("ip")
            de_mac = (de.get("mac") or "").lower().replace("-", ":")
            mode = (de.get("source_connector_mode") or "").lower()
            seen_via = (de.get("last_seen_via") or "").lower()
            has_switch = bool(de.get("switch_ip"))
            if has_switch or seen_via == "snmp":
                evidence = "mac_table_switch"
            elif mode == "agent_v4":
                evidence = "agent_v4_arp"
            elif mode == "scanner":
                evidence = "scanner_lan"
            else:
                evidence = seen_via or mode or "scanner"
            if de_ip and de_ip not in ip_evidence:
                ip_evidence[de_ip] = evidence
            if de_mac and de_mac not in mac_evidence:
                mac_evidence[de_mac] = evidence
    except Exception:
        pass
    return ip_evidence, mac_evidence


def _poll_fresh(pd: Optional[Mapping[str, Any]], minutes: int = 15) -> bool:
    """True se l'ultimo poll attivo (ICMP/SNMP) e' recente (< minutes)."""
    if not pd:
        return False
    at = pd.get("last_poll_at") or pd.get("last_poll") or pd.get("last_ping_at")
    if not at:
        return False
    try:
        dt = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < minutes * 60
    except Exception:
        return False


def compute_status(
    pd: Optional[Mapping[str, Any]],
    md: Optional[Mapping[str, Any]],
    ip_evidence: Optional[Mapping[str, str]] = None,
    mac_evidence: Optional[Mapping[str, str]] = None,
    offline_clients: Optional[set] = None,
    blackout_clients: Optional[set] = None,
) -> tuple:
    """
    Calcolo unificato dello status di un device.

    Priorita':
      1. Evidence-based override (IP o MAC visti < 15 min)  → ONLINE
      2. effective_reachable(pd) con debounce               → ONLINE / OFFLINE
         MA: se debounce dice OFFLINE e il connector del cliente e' giu'
             (client_id in offline_clients), ritorna "stale" invece di
             "offline" — mitigazione cascata blackout connector.
      3. md.source == "connector-scanner"                   → derivato da last_seen
      4. Nessun poll  → "pending" (manuale mai polleato)

    Args:
        pd: device_poll_status doc (puo' essere None)
        md: managed_devices doc (puo' essere None)
        ip_evidence: mappa ip→label da build_evidence_maps()
        mac_evidence: mappa mac→label da build_evidence_maps()
        offline_clients: set di client_id i cui connector sono TUTTI offline
                         (da build_clients_without_online_agent()). Quando
                         un client e' in questo set, lo status calcolato come
                         "offline" per debounce viene degradato a "stale"
                         perche' lo abbiamo perso di vista, non e' certo
                         che sia un fault.

    Returns:
        Tuple (status, evidence_label).
        status ∈ {"online","offline","stale","pending","unknown"}
        evidence_label = stringa ("scanner_lan", "agent_v4_arp",
        "mac_table_switch", "ping", "tcp", ecc.) o None.
    """
    md = md or {}
    pd = pd or {}
    ip_evidence = ip_evidence or {}
    mac_evidence = mac_evidence or {}
    offline_clients = offline_clients or set()
    blackout_clients = blackout_clients or set()

    ip = md.get("ip") or md.get("ip_address") or pd.get("device_ip") or ""
    mac = (md.get("mac") or "").lower().replace("-", ":")
    cid = md.get("client_id") or pd.get("client_id") or ""

    # FIX BLACKOUT (Gualdi): se l'agent del cliente e' OFFLINE, TUTTE le evidenze
    # di liveness (scanner LAN, ARP agent_v4, FDB switch) e i poll provengono
    # DALL'AGENT STESSO -> sono dati stantii inaffidabili. Non possiamo dire
    # "online" (era il bug: blackout sito ma device mostrati online per ~15 min
    # finche' l'evidenza non scadeva).
    #   - agent giu' MA WAN ancora su (es. riavvio del PC-connector) -> "stale"
    #     (stato incerto: non e' certo che i device siano in fault).
    #   - agent giu' E WAN giu' (sonda Center indipendente) -> BLACKOUT confermato
    #     -> "offline" (rosso): abbiamo la prova indipendente che il sito e' giu'.
    agent_down = bool(cid) and cid in offline_clients
    site_blackout = bool(cid) and cid in blackout_clients

    def _down():
        return ("offline", "site_blackout") if site_blackout else ("stale", "agent_offline")

    # 1. Evidence override (solo se l'agent e' vivo: l'evidence viene dall'agent)
    ip_ev = ip_evidence.get(ip) if ip else None
    mac_ev = mac_evidence.get(mac) if mac else None
    evidence = ip_ev or mac_ev
    if evidence and not agent_down:
        return "online", evidence

    # 2. Poll-based
    if pd:
        _is_vital = bool((md or {}).get("is_vital"))
        _minf = VITAL_MIN_FAILURES if _is_vital else DEBOUNCE_MIN_FAILURES
        _grace = VITAL_GRACE_SECONDS if _is_vital else DEBOUNCE_GRACE_SECONDS
        if effective_reachable(pd, _minf, _grace) and not agent_down:
            label = (pd.get("method") or pd.get("ping_method") or "ping")
            return "online", str(label).strip() if label else "ping"
        # agent giu' → stato incerto (stale) o blackout confermato (offline)
        if agent_down:
            return _down()
        return "offline", None

    # 3. Scanner-source senza poll: deriva da last_seen_at (ma non se agent giu')
    if md.get("source") == "connector-scanner":
        if agent_down:
            return _down()
        last_seen = md.get("last_seen_at")
        if last_seen:
            try:
                last_seen_dt = datetime.fromisoformat(
                    str(last_seen).replace("Z", "+00:00")
                )
                age_s = (datetime.now(timezone.utc) - last_seen_dt).total_seconds()
                if age_s < 1800:  # 30 min
                    return "online", "scanner_lan"
                return "offline", None
            except Exception:
                pass

    # 4. Agent giu' e nessun poll → incerto/blackout; altrimenti mai polleato → pending
    if agent_down:
        return _down()
    return "pending", None
