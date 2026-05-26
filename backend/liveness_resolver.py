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
EVIDENCE_WINDOW_MINUTES = 15   # quanto considerare "recente" un discovered_endpoint


def effective_reachable(pd: Optional[Mapping[str, Any]]) -> bool:
    """
    Decide se un device va mostrato online sulla base del solo poll
    record (device_poll_status), con debounce anti-flap.

    Returns:
        True  -> mostra ONLINE
        False -> mostra OFFLINE

    Logica:
      1. Se reachable=True               → True
      2. Se reachable=False ma debounce non scattato (consec<3 o
         last_reachable_at fresco <5min) → True (transitorio)
      3. Altrimenti                       → False
    """
    if not pd:
        return False
    if pd.get("reachable"):
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
    if consec >= DEBOUNCE_MIN_FAILURES and secs_since >= DEBOUNCE_GRACE_SECONDS:
        return False
    return True


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


def compute_status(
    pd: Optional[Mapping[str, Any]],
    md: Optional[Mapping[str, Any]],
    ip_evidence: Optional[Mapping[str, str]] = None,
    mac_evidence: Optional[Mapping[str, str]] = None,
) -> tuple[str, Optional[str]]:
    """
    Calcolo unificato dello status di un device.

    Priorita':
      1. Evidence-based override (IP o MAC visti < 15 min)  → ONLINE
      2. effective_reachable(pd) con debounce               → ONLINE / OFFLINE
      3. md.source == "connector-scanner"                   → derivato da last_seen
      4. Nessun poll  → "pending" (manuale mai polleato)

    Args:
        pd: device_poll_status doc (puo' essere None)
        md: managed_devices doc (puo' essere None)
        ip_evidence: mappa ip→label da build_evidence_maps()
        mac_evidence: mappa mac→label da build_evidence_maps()

    Returns:
        Tuple (status, evidence_label).
        status ∈ {"online","offline","pending","unknown"}
        evidence_label = stringa ("scanner_lan", "agent_v4_arp",
        "mac_table_switch", "ping", "tcp", ecc.) o None.
    """
    md = md or {}
    pd = pd or {}
    ip_evidence = ip_evidence or {}
    mac_evidence = mac_evidence or {}

    ip = md.get("ip") or md.get("ip_address") or pd.get("device_ip") or ""
    mac = (md.get("mac") or "").lower().replace("-", ":")

    # 1. Evidence override
    ip_ev = ip_evidence.get(ip) if ip else None
    mac_ev = mac_evidence.get(mac) if mac else None
    evidence = ip_ev or mac_ev
    if evidence:
        return "online", evidence

    # 2. Poll-based
    if pd:
        if effective_reachable(pd):
            label = (pd.get("method") or pd.get("ping_method") or "ping")
            return "online", str(label).strip() if label else "ping"
        # debounce dice offline
        return "offline", None

    # 3. Scanner-source senza poll: deriva da last_seen_at
    if md.get("source") == "connector-scanner":
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

    # 4. Mai polleato
    return "pending", None
