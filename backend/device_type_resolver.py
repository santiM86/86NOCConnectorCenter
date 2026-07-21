"""
Helper centralizzato per scegliere il device_type "migliore" di un device.

Stessa filosofia di display_name.py: un'unica fonte di verita' per tutte le
classificazioni device. Prima di questo modulo:
  - routes/devices.py:    aveva regex inline (~30 righe) per dedurre dev_type
                          dal poll, e un altro path che usava md.device_type raw
  - routes/overview.py:   aveva una propria _infer_device_type() con regex
                          diverse e meno keyword
  - device_classifier.py: ottimo classifier (Printer-MIB OIDs + regex robuste)
                          ma chiamato solo all'ingestion in managed_devices

Risultato: stampante apparsa come "server" nella lista, come "printer" in
Overview, oppure non smistata sotto la card "Stampanti". Switch HP 5130 visto
come "generic" perche' device_type non era mai stato salvato in DB.

Questo helper aggrega tutto e ritorna SEMPRE un device_type canonico.

Priorita' (alto -> basso):
  1. md.device_type_user_locked == True  -> rispetta scelta admin
  2. md.device_type "specifico" (in CANONICAL_TYPES, non in GENERIC_TYPES)
  3. classify_device_type() su (sys_descr/object_id/hostname/model) - robusto
  4. OUI vendor hint single-purpose (printer/voip/tvcc/access_point)
  5. md.device_type generico se esiste
  6. "generic"

L'output e' SEMPRE normalizzato:
  printer | switch | router | firewall | nas | ups | ilo |
  server | access-point | tvcc | voip | endpoint |
  endpoint-private | iot | generic
"""

from typing import Any, Mapping, Optional

from device_classifier import classify_device_type


# Tipi "specifici" gia' validi: se md.device_type e' uno di questi, lo rispettiamo.
CANONICAL_TYPES = {
    "printer", "switch", "router", "firewall",
    "nas", "ups", "ilo", "server",
    "access-point", "tvcc", "voip",
    "endpoint", "endpoint-private",
    "workstation", "mobile", "iot",
    "generic",
}

# Tipi "generici" che vanno ri-classificati: il classifier puo' migliorare.
GENERIC_TYPES = {
    "", "?", "generic", "network", "network-device", "device", "unknown",
}

# Normalizzazione alias -> canonical
_ALIAS_MAP = {
    "ap": "access-point",
    "access_point": "access-point",
    "accesspoint": "access-point",
    "wifi-ap": "access-point",
    "wifi_ap": "access-point",
    "ip_camera": "tvcc",
    "ip-camera": "tvcc",
    "camera": "tvcc",
    "nvr": "tvcc",
    "dvr": "tvcc",
    "voip_phone": "voip",
    "voip-phone": "voip",
    "phone": "voip",
    "ipphone": "voip",
    "ip-phone": "voip",
    "stampante": "printer",
    "storage": "nas",
    "zyxel-usg": "firewall",
    "fortigate": "firewall",
    "server_oob": "ilo",
    "server-oob": "ilo",
    "bmc": "ilo",
    "idrac": "ilo",
    "drac": "ilo",
}


# Tipi "endpoint" (PC consumer / device personali): NON sono infrastruttura
# di rete/server monitorata. Vanno contati e mostrati in una sezione dedicata
# "Endpoints" cosi' un PC/laptop/smartphone offline NON influenza le statistiche
# e la salute dell'infrastruttura del cliente.
ENDPOINT_TYPES = {
    "endpoint", "endpoint-private", "workstation", "mobile", "iot",
}


def is_endpoint_type(device_type: Optional[str]) -> bool:
    """True se il device_type canonico appartiene alla categoria Endpoints
    (PC/laptop/mobile/IoT), False per l'infrastruttura di rete/server."""
    return _normalize(device_type) in ENDPOINT_TYPES


def _normalize(t: Optional[str]) -> str:
    if not t:
        return ""
    s = str(t).strip().lower()
    if not s:
        return ""
    return _ALIAS_MAP.get(s, s)


# OUI vendor single-purpose hint: alcuni vendor producono SOLO stampanti, ecc.
# Confidenza media — usato solo come fallback prima di "generic".
_OUI_VENDOR_HINTS = {
    "printer": (
        "brother", "canon", "epson", "lexmark", "kyocera", "ricoh",
        "xerox", "sharp", "oki", "konica", "konica minolta",
        "zebra", "develop", "fuji xerox", "toshiba tec",
    ),
    "voip": (
        "polycom", "yealink", "snom", "grandstream", "mitel",
        "avaya", "wildix", "fanvil", "panasonic kx",
    ),
    "tvcc": (
        "hikvision", "dahua", "axis communications", "mobotix",
        "uniview", "vivotek", "bosch security", "hanwha",
        "reolink",
    ),
    "access-point": (
        "ubiquiti", "ruckus wireless", "mist systems", "aerohive",
    ),
    "nas": (
        "synology", "qnap", "asustor", "drobo",
    ),
    "ups": (
        "american power conversion", "eaton", "cyberpower", "riello",
    ),
    "iot": (
        "raspberry", "nvidia jetson", "orange pi", "espressif",
        "particle industries", "sonoff", "shelly", "tasmota",
        "ring", "nest labs", "tuya",
    ),
    "workstation": (
        "msi", "micro-star", "elitegroup", "lcfc", "asustek",
        "dell inc", "lenovo", "gigabyte", "asrock", "acer",
        "samsung electronics co", "intel corporate", "tmc",
        "liteon", "wistron", "compal", "quanta", "inventec",
        "pegatron", "hewlett-packard", "hp inc",
        "apple, inc", "apple inc",
    ),
}


def _vendor_hint(vendor: str) -> Optional[str]:
    v = (vendor or "").lower()
    if not v:
        return None
    for dtype, hints in _OUI_VENDOR_HINTS.items():
        if any(h in v for h in hints):
            return dtype
    return None


def best_device_type(
    md: Optional[Mapping[str, Any]] = None,
    pd: Optional[Mapping[str, Any]] = None,
    name_hint: Optional[str] = None,
) -> str:
    """
    Restituisce il device_type canonico per il device.

    Args:
        md: documento managed_devices (puo' essere None).
        pd: documento device_poll_status (puo' essere None).
        name_hint: nome display gia' risolto da best_display_name(), usato
                   come ulteriore signal hostname-based.

    Returns:
        Stringa canonica (vedi CANONICAL_TYPES). Default: "generic".
    """
    md = md or {}
    pd = pd or {}

    # 1. Admin l'ha bloccato esplicitamente.
    if md.get("device_type_user_locked"):
        locked = _normalize(md.get("device_type"))
        if locked:
            return locked

    md_type = _normalize(md.get("device_type"))

    # 2. md.device_type "specifico" -> rispettalo subito (e' gia' stato classificato
    # bene a priori, magari da admin via UI).
    if md_type and md_type in CANONICAL_TYPES and md_type not in GENERIC_TYPES:
        return md_type

    # 3. Classifier robusto su segnali SNMP.
    sys_descr = pd.get("sys_descr") or md.get("sys_descr") or ""
    sys_object_id = pd.get("sys_object_id") or md.get("sys_object_id") or ""
    hostname = (
        name_hint
        or pd.get("sys_name")
        or md.get("hostname")
        or md.get("name")
        or ""
    )
    model = md.get("model") or pd.get("model") or ""

    classified = classify_device_type(
        sys_descr=sys_descr,
        sys_object_id=sys_object_id,
        hostname=hostname,
        model=model,
    )
    if classified:
        return _normalize(classified)

    # 4. OUI vendor hint single-purpose (last resort prima di "generic").
    vendor = md.get("vendor") or pd.get("vendor") or ""
    vhint = _vendor_hint(vendor)
    if vhint:
        return vhint

    # 5. MAC randomizzato -> dispositivo personale (smartphone tipico)
    # Mantengo "endpoint-private" come distinta da "mobile" (vendor noto)
    # cosi' la UI puo' differenziare "iPhone con MAC reale" da "smartphone
    # in privacy mode che vediamo solo come LAA random".
    if md.get("mac_is_random"):
        return "endpoint-private"

    # 6. md.device_type generico se esiste (meglio di niente).
    if md_type:
        return md_type

    # 7. pd.device_class come ultimo fallback (es. "snmp-router").
    pd_class = _normalize(pd.get("device_class"))
    if pd_class:
        return pd_class

    return "generic"
