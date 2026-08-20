"""
Blame Engine - Attribuzione automatica del guasto di rete (chi è la colpa?).

Analizza gli hop di un traceroute (già arricchiti con geo/ASN quando disponibili)
e produce un verdetto in italiano che localizza la responsabilità del guasto:
LAN cliente / CPE-router / ultimo miglio ISP / backbone carrier / sito destinazione.

Con più trace verso ancore pubbliche diverse (multi-ancora) distingue in modo
robusto un problema del CLIENTE da un guasto dell'ISP/carrier o del sito remoto.
"""
import ipaddress
from typing import Optional


def _is_private(ip: Optional[str]) -> Optional[bool]:
    if not ip:
        return None
    try:
        o = ipaddress.ip_address(ip)
        return bool(o.is_private or o.is_loopback or o.is_link_local or o.is_reserved)
    except Exception:
        return None


def _responds(h: dict) -> bool:
    return not (h.get("timeout") or (h.get("loss_pct") or 0) >= 100)


def _hop_ip(h: dict) -> Optional[str]:
    return h.get("ip") or h.get("host")


def attribute_fault(hops: list, reached: bool, target: Optional[str] = None,
                    is_client_target: bool = False) -> dict:
    """Verdetto su un singolo trace.

    Ritorna: {zone, blame, confidence, break_hop, asn, asn_name, isp, verdict}
    zone ∈ none|lan_client|cpe|last_mile_isp|isp_backbone|destination|probe
    blame ∈ OK|Cliente|ISP|Sito destinazione|Sonda
    """
    hops = sorted([h for h in (hops or []) if h.get("hop") is not None],
                  key=lambda h: h["hop"])
    for h in hops:
        ip = _hop_ip(h)
        h["_ip"] = ip
        h["_priv"] = _is_private(ip)
        h["_resp"] = _responds(h) and bool(ip)

    responding = [h for h in hops if h["_resp"]]
    last_resp = responding[-1] if responding else None
    last_pub = None
    for h in reversed(responding):
        if h["_priv"] is False:
            last_pub = h
            break

    def _geo(h):
        g = (h or {}).get("geo") or {}
        return g.get("asn"), g.get("asn_name"), g.get("isp")

    if reached:
        return {
            "zone": "none", "blame": "OK", "confidence": "alta", "break_hop": None,
            "asn": None, "asn_name": None, "isp": None,
            "verdict": "Percorso integro: destinazione raggiunta, nessun guasto sul path.",
        }

    # break_hop = primo hop successivo all'ultimo che risponde
    break_hop = (last_resp["hop"] + 1) if last_resp else (hops[0]["hop"] if hops else 1)

    # Nessun hop risponde → problema alla sonda o alla sua rete locale
    if not responding:
        return {
            "zone": "probe", "blame": "Sonda", "confidence": "media", "break_hop": break_hop,
            "asn": None, "asn_name": None, "isp": None,
            "verdict": "Nessun hop risponde: problema sulla sonda o sulla sua rete locale/uscita.",
        }

    # L'ultimo hop che risponde è privato → non si esce dalla LAN/CPE:
    # linea (ultimo miglio) giù oppure CPE/router del cliente.
    if last_resp["_priv"]:
        return {
            "zone": "last_mile_isp", "blame": "ISP", "confidence": "media",
            "break_hop": break_hop, "asn": None, "asn_name": None, "isp": None,
            "verdict": (f"Percorso fermo all'ultimo hop privato (CPE/router, hop {last_resp['hop']} "
                        f"{last_resp['_ip']}): nessun nodo pubblico dell'operatore risponde a valle → "
                        f"linea/ultimo miglio ISP giù oppure CPE del cliente."),
        }

    # L'ultimo hop che risponde è pubblico → guasto DENTRO il carrier a valle.
    asn, asn_name, isp = _geo(last_pub or last_resp)
    who = asn_name or isp or (asn or "operatore sconosciuto")
    # Se il trace è verso l'IP del cliente e siamo quasi arrivati (mancano pochi
    # hop) è probabile che il guasto sia proprio sulla sede/destinazione.
    dest_like = is_client_target and last_pub is not None
    if dest_like:
        return {
            "zone": "destination", "blame": "Sito destinazione", "confidence": "media",
            "break_hop": break_hop, "asn": asn, "asn_name": asn_name, "isp": isp,
            "verdict": (f"Il path arriva fino alla rete dell'operatore ({who}) ma la destinazione "
                        f"non risponde: probabile CPE/linea della SEDE del cliente giù o firewall "
                        f"che scarta (dall'hop {break_hop} in poi)."),
        }
    return {
        "zone": "isp_backbone", "blame": "ISP", "confidence": "alta",
        "break_hop": break_hop, "asn": asn, "asn_name": asn_name, "isp": isp,
        "verdict": (f"Guasto nel backbone del carrier {who}"
                    + (f" ({asn})" if asn else "")
                    + f": ultimo nodo che risponde è l'hop {last_resp['hop']} ({last_resp['_ip']}), "
                      f"interruzione dall'hop {break_hop} in poi → responsabilità dell'operatore, non del cliente."),
    }


def combined_verdict(traces: list) -> dict:
    """Verdetto complessivo multi-ancora.

    `traces` = lista di dict: {target, is_client, reached, verdict{...}}
    Distingue: guasto lato CLIENTE vs carrier/uscita della SONDA vs sito remoto.
    Ritorna {blame, zone, confidence, headline, verdict}.
    """
    client = next((t for t in traces if t.get("is_client")), None)
    anchors = [t for t in traces if not t.get("is_client")]
    anchors_ok = [a for a in anchors if a.get("reached")]

    if client is None:
        # solo ancore: giudizio sull'uscita internet della sonda
        if anchors_ok:
            return {"blame": "OK", "zone": "none", "confidence": "alta",
                    "headline": "Uscita Internet OK",
                    "verdict": "La sonda naviga correttamente verso Internet."}
        return {"blame": "ISP", "zone": "isp_backbone", "confidence": "media",
                "headline": "Uscita Internet della sonda giù",
                "verdict": "Nessuna ancora pubblica raggiunta: problema sull'uscita/carrier della sonda."}

    if client.get("reached"):
        return {"blame": "OK", "zone": "none", "confidence": "alta",
                "headline": "Cliente raggiungibile",
                "verdict": "La sede del cliente è raggiungibile: nessun disservizio in corso sul path."}

    # Cliente NON raggiunto:
    if anchors_ok:
        # la sonda naviga (raggiunge 1.1.1.1 / 8.8.8.8) ma NON il cliente
        cv = (client.get("verdict") or {})
        who = cv.get("asn_name") or cv.get("isp")
        return {
            "blame": "Cliente", "zone": cv.get("zone") or "last_mile_isp", "confidence": "alta",
            "headline": "Guasto lato CLIENTE (linea/CPE del cliente)",
            "verdict": ("La sonda naviga regolarmente (raggiunge 1.1.1.1/8.8.8.8) ma la sede del "
                        "cliente è IRRAGGIUNGIBILE: il guasto è sulla LINEA o sul CPE del CLIENTE, "
                        "non sulla rete a monte."
                        + (f" Ultimo operatore visto sul path: {who}." if who else "")),
        }

    # Cliente NON raggiunto E nessuna ancora raggiunta → uscita/carrier della SONDA
    return {
        "blame": "ISP", "zone": "isp_backbone", "confidence": "alta",
        "headline": "Guasto sulla linea/carrier della SONDA (NOC)",
        "verdict": ("Nessuna destinazione raggiungibile (né il cliente né 1.1.1.1/8.8.8.8): il guasto "
                    "è sull'uscita Internet o sul carrier della TUA sonda/NOC, a monte di tutto."),
    }
