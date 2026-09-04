"""Allarmi 'porta switch giù verso dispositivo vitale / uplink' con modello 1+1.

Rileva il LINK DOWN (SNMP ifOperStatus up→down, admin ancora up) solo sulle porte
CRITICHE di uno switch:
  - porte verso un DISPOSITIVO VITALE (mappa affidabile via mac_connections:
    from_ip=switch, from_port=idx, to_ip=device → managed_devices.is_vital);
  - porte UPLINK/TRUNK/LAG (euristica sul nome/descrizione della porta).
Le porte "normali" (client, porte libere) NON generano allarme, per non intasare.

Riusa la macchina 1+1 di hardware_alerts (_emit_or_update / _resolve_alert):
1 messaggio all'apertura + 1 al rientro (con durata), Telegram forzato (bypassa soglia).
"""
import logging
import re

logger = logging.getLogger("port_link_alerts")

SOURCE_TYPE = "port_link_down"

# Nomi tipici di porte di dorsale/aggregazione (uplink)
_UPLINK_RE = re.compile(
    r"(uplink|trunk|\blag\b|port-?chan|bridge-aggregation|\bpo\d|\bag\d|\beth-?trunk|"
    r"sfp|xge|ten-?gig|\b10g\b|\b25g\b|\b40g\b|\b100g\b)", re.I)

# SNMP ifOperStatus: 1=up, 2=down ; ifAdminStatus: 1=up, 2=down
_UP = 1
_DOWN = 2


def _is_uplink_name(*names) -> bool:
    for n in names:
        if n and _UPLINK_RE.search(str(n)):
            return True
    return False


async def evaluate_port_links(db, client_id: str, local_ip: str,
                              prev_by_idx: dict, ports: list) -> None:
    """Chiamata da store_switch_ports dopo aver aggiornato lo switch `local_ip`.
    `prev_by_idx`: {idx: {oper, admin, ...}} stato precedente; `ports`: nuovo stato."""
    if not ports and not prev_by_idx:
        return
    try:
        from alert_engine import get_config
        import hardware_alerts as hw

        cfg = await get_config(db)

        # Mappa idx porta -> IP dispositivi collegati (join affidabile per ifIndex)
        conns = await db.mac_connections.find(
            {"client_id": client_id, "from_ip": local_ip},
            {"_id": 0, "from_port": 1, "to_ip": 1},
        ).to_list(10000)
        idx_to_ips: dict = {}
        for c in conns:
            try:
                fp = int(c.get("from_port"))
            except (TypeError, ValueError):
                continue
            if c.get("to_ip"):
                idx_to_ips.setdefault(fp, set()).add(c["to_ip"])

        # Quali di quegli IP sono dispositivi VITALI (con nome per il messaggio)
        all_ips = {ip for s in idx_to_ips.values() for ip in s}
        vital_by_ip: dict = {}
        if all_ips:
            async for md in db.managed_devices.find(
                {"client_id": client_id, "ip": {"$in": list(all_ips)}, "is_vital": True},
                {"_id": 0, "ip": 1, "name": 1},
            ):
                vital_by_ip[md["ip"]] = md.get("name") or md["ip"]

        client_name = ""
        try:
            cl = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
            client_name = (cl or {}).get("name") or ""
        except Exception:
            pass

        for p in ports:
            try:
                idx = int(p.get("idx"))
            except (TypeError, ValueError):
                continue
            new_oper = int(p.get("oper", 0) or 0)
            new_admin = int(p.get("admin", 0) or 0)
            prev = prev_by_idx.get(idx) or {}
            prev_oper = int(prev.get("oper", 0) or 0)

            pname = p.get("name") or f"port{idx}"
            descr = p.get("descr") or ""
            alias = p.get("alias") or ""

            # È una porta critica? (verso vitale oppure uplink)
            vital_ips = [ip for ip in idx_to_ips.get(idx, set()) if ip in vital_by_ip]
            is_uplink = _is_uplink_name(pname, descr, alias)
            if not vital_ips and not is_uplink:
                continue  # porta non critica → ignora

            dedup_key = f"{client_id}:{local_ip}:portlink:{idx}"

            # Transizione UP -> DOWN (con admin up) = link caduto
            if prev_oper == _UP and new_oper == _DOWN and new_admin == _UP:
                if vital_ips:
                    targets = ", ".join(f"{vital_by_ip[ip]} ({ip})" for ip in vital_ips)
                    title = f"PORTA GIÙ verso vitale: {pname} su switch {local_ip}"
                    message = (f"La porta {pname} dello switch {local_ip} è DOWN: isolato il "
                               f"dispositivo vitale {targets}. Verificare cavo/porta/apparato.")
                    severity = "critical"
                else:
                    title = f"UPLINK GIÙ: {pname} su switch {local_ip}"
                    message = (f"La porta uplink/trunk {pname} dello switch {local_ip} è DOWN: "
                               f"possibile isolamento di un segmento di rete.")
                    severity = "critical"
                await hw._emit_or_update(
                    db, cfg, client_id=client_id, client_name=client_name,
                    device_name=f"switch {local_ip}", device_ip=local_ip,
                    device_type="switch", dedup_key=dedup_key, severity=severity,
                    title=title, message=message, source_type=SOURCE_TYPE)

            # Transizione DOWN -> UP = link ripristinato (1 messaggio di rientro)
            elif prev_oper == _DOWN and new_oper == _UP:
                if vital_ips:
                    rec = (f"Porta {pname} su switch {local_ip} di nuovo UP: "
                           f"ripristinato il collegamento verso "
                           + ", ".join(vital_by_ip[ip] for ip in vital_ips) + ".")
                else:
                    rec = f"Uplink {pname} su switch {local_ip} di nuovo UP."
                await hw._resolve_alert(db, cfg, dedup_key, rec)
    except Exception as e:
        logger.error(f"port_link_alerts error switch={local_ip}: {e}", exc_info=True)
