"""
Device Type Classifier
======================
Auto-classifica un device basandosi su sys_descr, sys_object_id, hostname
e modello. Usato durante l'ingestion del connector per riempire automaticamente
`managed_devices.device_type` quando assente o generico.

Gerarchia:
1. sys_object_id prefix (piu` affidabile, vendor-firmato dal device stesso)
2. sys_descr regex (testo libero, solido per stampanti/UPS/switch noti)
3. hostname/model regex (fallback per device dietro NAT senza SNMP)
"""
import re
from typing import Optional


# === Printer-MIB enterprise OID prefixes ===
# Ogni vendor ha un OID di radice CHE FORNISCE STAMPANTI (non solo device generici).
# Quindi matchiamo prefissi specifici per stampanti/MFP, non vendor-radici generiche.
_PRINTER_OID_PREFIXES = (
    "1.3.6.1.4.1.11.2.3.9",        # HP printers (LaserJet, OfficeJet, DesignJet)
    "1.3.6.1.4.1.2435.2.3.9",      # Brother printers/MFP
    "1.3.6.1.4.1.1602.4",          # Canon imageRUNNER/imageCLASS
    "1.3.6.1.4.1.1248",            # Epson WorkForce/EcoTank/B
    "1.3.6.1.4.1.641",             # Lexmark
    "1.3.6.1.4.1.1347.41",         # Kyocera ECOSYS/TASKalfa
    "1.3.6.1.4.1.18334.1",         # Konica Minolta bizhub/AccurioPress
    "1.3.6.1.4.1.253.8.62",        # Xerox WorkCentre/VersaLink/AltaLink
    "1.3.6.1.4.1.367.1",           # Ricoh/Lanier/Savin/Gestetner
    "1.3.6.1.4.1.2385",            # Sharp MFP (MX-, BP-, AR-)
    "1.3.6.1.4.1.4884",            # OKI Data
    "1.3.6.1.4.1.297",             # Dell printers (deprecated dopo 2017)
    "1.3.6.1.4.1.236.11.5.11",     # Samsung printers (ora HP-owned)
    "1.3.6.1.4.1.6027.1.4",        # Dell rebranded printers
    "1.3.6.1.4.1.683",             # Brother (old enterprise)
)

# === Printer hostname/sys_descr patterns ===
# Modelli, serie e brand-keywords tipiche
_PRINTER_PATTERNS = re.compile(
    r"\b("
    # HP series
    r"laserjet|officejet|deskjet|designjet|pagewide|envy|smart\s?tank|color\s?laser|"
    # Brother
    r"mfc-|dcp-|hl-|brother(?:\s|-)|"
    # Sharp / Sharp MFP (MX-, BP-, AR-)
    r"sharp|mx-[a-z]?\d|bp-[a-z]?\d|ar-[a-z]?\d|"
    # Canon
    r"imagerunner|imageclass|pixma|maxify|i-?sensys|color\s?image|"
    # Epson
    r"workforce|ecotank|stylus|expression\s?premium|surecolor|"
    # Lexmark
    r"lexmark|cs[0-9]{3,}|cx[0-9]{3,}|mx[0-9]{3,}|ms[0-9]{3,}|"
    # Kyocera
    r"kyocera|ecosys|taskalfa|fs-[0-9]+|"
    # Konica Minolta
    r"konica|minolta|bizhub|accuriopress|magicolor|"
    # Xerox
    r"xerox|workcentre|versalink|altalink|primelink|phaser|"
    # Ricoh family
    r"ricoh|lanier|savin|gestetner|aficio|"
    # OKI / Samsung / Dell
    r"oki(?:data|\s)|samsung\s?(?:cl|ml|sl|mfp)|dell\s?(?:c|b|h|s)\d{3,}|"
    # MFP / Multifunction generic
    r"mfp|multifunction|all-?in-?one|"
    # Pure model series with "M" + digits common across HP/Samsung
    r"\b(pro\s?)?m[0-9]{3,}[a-z]{0,5}\b"
    r")\b",
    re.IGNORECASE,
)

# === Other device-type signals (light) ===
# Permette di evitare falsi positivi tipo "switch HP ProCurve" che potrebbe
# matchare brand-pattern ma e` chiaramente uno switch.
_SWITCH_PATTERNS = re.compile(
    r"\b(switch|comware|procurve|catalyst|ex[2-4]\d{3}|aruba\s+(?:cx|2[5-9]\d{2}|6[0-9]\d{2})|nexus|cisco\s+(?:c|wsc|ws-c)\d{3,}|"
    r"juniper\s+ex|h3c\s+5[0-9]{3}|hpe?\s+5[1-9]\d{2}|h3c\s+s\d{4}|fortiswitch|"
    r"netgear\s?(?:gs|jgs|ms|fs)[\d-]{2,}[a-z0-9-]*|d-?link\s?(?:dgs|dxs|dgsm)[\d-]{2,}[a-z0-9-]*|"
    r"tp-?link\s?(?:tl-)?sg\d{3}[a-z0-9-]*|zyxel\s?(?:gs|xgs|xs)\d{3,}[a-z0-9-]*)\b",
    re.IGNORECASE,
)
_FIREWALL_PATTERNS = re.compile(
    r"\b(fortigate|palo\s?alto|panos|sonicwall|checkpoint|sophos\s?(?:xg|sg|firewall)|fortinet\s?fg|usg-?(?:flex|pro|atp)|atp\s?\d|usg\s?\d|firewall|cisco\s?(?:asa|firepower))\b",
    re.IGNORECASE,
)
_AP_PATTERNS = re.compile(
    r"\b(unifi|access\s?point|ap\s?wi-?fi|wi-?fi\s?ap|aruba\s?ap|aruba\s?iap|cisco\s?(?:aironet|catalyst\s?9100)|engenius|tp-?link\s?eap|netgear\s?wax|"
    r"ubiquiti|mikrotik\s?cap|ruckus\s?(?:r|t|h)\d{3})\b",
    re.IGNORECASE,
)
_NAS_PATTERNS = re.compile(
    r"\b(synology|qnap|truenas|freenas|netapp|drobo|nas\s?\d)\b",
    re.IGNORECASE,
)
_UPS_PATTERNS = re.compile(
    r"\b(ups|smart-?ups|back-?ups|xanto|riello|cyberpower|eaton\s?(?:ellipse|9px|5px|9sx|5sx)|powerware|socomec|netman|netagent)\b",
    re.IGNORECASE,
)
_ILO_PATTERNS = re.compile(
    r"\b(ilo|integrated\s?lights\s?out|idrac|imm\s?[12]|bmc|cimc|xclarity|proliant|poweredge|lenovo\s?thinksystem)\b",
    re.IGNORECASE,
)


def _matches_oid_prefix(oid: str, prefixes: tuple) -> bool:
    """True se oid inizia con uno dei prefissi (con `.` di chiusura corretto)."""
    if not oid:
        return False
    oid_norm = oid.strip().rstrip(".")
    for p in prefixes:
        if oid_norm == p or oid_norm.startswith(p + "."):
            return True
    return False


def classify_device_type(
    sys_descr: Optional[str] = None,
    sys_object_id: Optional[str] = None,
    hostname: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[str]:
    """Restituisce il device_type dedotto, o None se nessuna euristica matcha.

    Ordine: sysObjectID prefix (alta affidabilita`) -> sysDescr regex -> hostname/model regex.

    Casi specifici handled (priorita` decrescente):
      - printer (Printer-MIB SNMP + brand patterns)
      - switch
      - firewall
      - access-point
      - nas
      - ups
      - ilo / server
    """
    text_parts = [t for t in (sys_descr, hostname, model) if t]
    text = " | ".join(text_parts)

    # 1. sysObjectID — prima evidenza affidabile per stampanti
    if sys_object_id and _matches_oid_prefix(sys_object_id, _PRINTER_OID_PREFIXES):
        return "printer"

    # 2. sysDescr/hostname regex — controllo stampanti per primo perche` molti MFP
    # contengono "MX-/MFC-/LaserJet" che potrebbero matchare anche pattern altri
    if text and _PRINTER_PATTERNS.search(text):
        # Filtra falsi positivi: switch HP ProCurve potrebbe matchare "M" + digits
        # ma se matcha anche pattern switch -> resta switch, non printer
        if _SWITCH_PATTERNS.search(text):
            return "switch"
        return "printer"

    if text:
        if _SWITCH_PATTERNS.search(text):
            return "switch"
        if _FIREWALL_PATTERNS.search(text):
            return "firewall"
        if _AP_PATTERNS.search(text):
            return "access-point"
        if _NAS_PATTERNS.search(text):
            return "nas"
        if _UPS_PATTERNS.search(text):
            return "ups"
        if _ILO_PATTERNS.search(text):
            return "ilo"

    return None
