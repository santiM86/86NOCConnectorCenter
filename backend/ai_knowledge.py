"""Base di conoscenza vendor (HPE/Aruba/Comware, Cisco, Zyxel, Hyper-V, PoE…) + memoria dei casi risolti.

Recupero "lightweight RAG" per parole chiave: nessun embedding, deterministico, zero costi.
- BUILTIN_KB: voci curate (codici IML/SEL, eventi iLO, problemi porta/PoE, best practice).
- db.ai_knowledge: voci aggiunte dall'utente (title, vendor, tags[], content).
- case_memory(): alert risolti con nota tecnico sullo stesso device/porta + feedback sulle analisi AI (db.ai_feedback).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

_STOP = {"il", "lo", "la", "le", "gli", "di", "da", "in", "un", "una", "del", "della", "dei", "con", "per", "the", "and", "for",
         "is", "on", "of", "to", "a", "e", "che", "non", "su", "porta", "port", "device", "server", "switch", "min", "fa"}

BUILTIN_KB: list[dict] = [
    # ---- HPE ProLiant / iLO / IML ----
    {"id": "hpe-iml-memory-corr", "vendor": "HPE", "tags": ["iml", "memory", "dimm", "correctable", "ecc", "corrected"],
     "title": "IML: Corrected Memory Error Threshold Exceeded (DIMM)",
     "content": "Il DIMM indicato (Processor N, DIMM N) ha superato la soglia di errori ECC correggibili. Non è ancora un guasto ma è predittivo: "
                "HPE lo copre in garanzia come Pre-Failure. Azione: ordinare/sostituire il DIMM alla prossima finestra, verificare firmware/BIOS aggiornati, "
                "controllare che AMP (Advanced Memory Protection) sia attivo. Se ricorre su DIMM diversi dello stesso canale → sospettare il socket/CPU."},
    {"id": "hpe-iml-memory-uncorr", "vendor": "HPE", "tags": ["iml", "memory", "uncorrectable", "dimm", "fatal", "machine", "check"],
     "title": "IML: Uncorrectable Memory Error / Machine Check Exception",
     "content": "Errore memoria non correggibile: il server si è quasi certamente riavviato (ASR) o bloccato. Azione SUBITO: sostituire il DIMM indicato; "
                "se non indicato usare iLO → Memory per il DIMM in stato Degraded. Aggiornare System ROM. Verificare nel SO (Event ID 41/1001) l'orario del crash."},
    {"id": "hpe-iml-psu", "vendor": "HPE", "tags": ["iml", "power", "supply", "psu", "redundancy", "lost", "ac", "input"],
     "title": "IML: Power Supply Failure / Redundancy Lost / AC power loss",
     "content": "Una PSU è guasta o ha perso l'alimentazione in ingresso. Distinguere: 'Redundancy Lost' con 'AC power loss' = problema a monte (UPS, ciabatta, presa) "
                "→ verificare cavo/UPS prima di sostituire; 'Power Supply Failure' senza AC loss = PSU guasta → sostituzione hot-swap. Controllare UPS del cliente negli stessi minuti."},
    {"id": "hpe-iml-fan", "vendor": "HPE", "tags": ["iml", "fan", "ventola", "degraded", "failed", "thermal"],
     "title": "IML: Fan Failure / Fan Degraded",
     "content": "Ventola guasta o degradata: le altre compensano ma la temperatura sale e il rumore aumenta. Sostituire la ventola (hot-plug su quasi tutti i Gen9/10/11). "
                "Se più ventole degradano insieme → controllare filtri/polvere e temperatura ambiente del rack."},
    {"id": "hpe-iml-thermal", "vendor": "HPE", "tags": ["iml", "temperature", "temperatura", "thermal", "caution", "critical", "inlet", "ambient"],
     "title": "IML: Temperature Caution/Critical (Inlet Ambient / CPU / Memory)",
     "content": "Inlet Ambient sopra soglia = problema di sala/rack (aria condizionata, flusso aria ostruito), non del server. Sensori interni alti con inlet normale = "
                "dissipatore/ventola/pasta termica o ventole in throttling. Azione: verificare clima sala, spazio davanti al server, ventole, poi firmware iLO/ROM."},
    {"id": "hpe-iml-drive", "vendor": "HPE", "tags": ["iml", "drive", "disk", "disco", "smart", "predictive", "failure", "array", "raid", "bay", "logical"],
     "title": "IML: Drive Predictive Failure / Physical Drive Failed / Logical Drive Degraded",
     "content": "SMART predictive = sostituire il disco (bay indicato) alla prossima finestra, prima che fallisca; la garanzia HPE lo copre. Physical Drive Failed = "
                "sostituire subito e verificare che il rebuild parta (Smart Array/SSA). Logical Drive Degraded = ridondanza persa: sostituire subito, nessun secondo guasto è tollerato. "
                "Controllare presenza di spare e stato batteria/cache (FBWC)."},
    {"id": "hpe-iml-cache", "vendor": "HPE", "tags": ["iml", "cache", "battery", "fbwc", "capacitor", "smart", "array", "controller", "write"],
     "title": "IML: Smart Array cache/battery (FBWC) failed or disabled",
     "content": "Cache write-back disabilitata → calo di prestazioni disco marcato (specie Hyper-V/SQL). Sostituire il modulo capacitor/battery; nel frattempo le VM possono risultare lente. "
                "Se il controller riporta 'Controller Failure' → sostituzione controller, verificare backup prima."},
    {"id": "hpe-iml-asr", "vendor": "HPE", "tags": ["iml", "asr", "reset", "watchdog", "lockup", "blue", "screen", "bsod", "reboot", "riavvio"],
     "title": "IML: ASR Detected by System ROM / Automatic Server Recovery",
     "content": "Il SO non ha risposto al watchdog per 10 min e iLO ha riavviato il server: crash del sistema operativo o hang hardware. Correlare con eventi memoria/CPU nello stesso orario; "
                "controllare Event Viewer (Kernel-Power 41, BugCheck 1001) e memory dump. Se ricorrente senza eventi hardware → driver/storage; con eventi memoria → DIMM."},
    {"id": "hpe-iml-nic", "vendor": "HPE", "tags": ["iml", "network", "adapter", "nic", "link", "down", "ethernet", "port", "flapping"],
     "title": "IML: Network Adapter Link Down / Port Failure",
     "content": "Link giù sulla NIC del server: verificare porta switch a monte (stato, velocità, errori CRC), cavo, teaming (se team, verificare che l'altro membro sia attivo). "
                "Se avviene a orari fissi → salvataggio energetico dello switch o riavvio programmato."},
    {"id": "hpe-ilo-selftest", "vendor": "HPE", "tags": ["ilo", "self", "test", "firmware", "degraded", "nvram", "eeprom"],
     "title": "iLO Self-Test failure / iLO Degraded",
     "content": "Il BMC stesso ha un problema (NVRAM, firmware, EEPROM). Aggiornare iLO all'ultima release; se persiste, reset iLO (senza spegnere il server) e in ultima istanza sostituzione scheda madre. "
                "Non impatta il SO ma toglie visibilità hardware e IML."},
    {"id": "hpe-ilo-security", "vendor": "HPE", "tags": ["ilo", "login", "failed", "authentication", "security", "brute", "force", "unauthorized", "accesso"],
     "title": "iLO: ripetuti Login Failure / Security log",
     "content": "Tentativi di accesso falliti ripetuti su iLO: possibile scansione/brute force dalla LAN o credenziali cambiate su uno strumento di monitoraggio. Verificare sorgente IP, "
                "isolare iLO su VLAN management, abilitare account lockout, aggiornare firmware (CVE iLO 4/5 note)."},
    {"id": "hpe-fw-baseline", "vendor": "HPE", "tags": ["firmware", "spp", "service", "pack", "rom", "update", "aggiornamento", "ilo5", "ilo6", "gen10", "gen11"],
     "title": "Best practice HPE: firmware baseline (SPP) e iLO",
     "content": "Molti eventi IML spuri (falsi thermal, fan, memory) spariscono con SPP recente. Aggiornare iLO + System ROM + Smart Array insieme (SPP), in finestra di manutenzione, "
                "dopo aver verificato backup e stato array. Gen9: iLO4 ≥2.8x; Gen10: iLO5 ≥3.x; Gen11: iLO6."},
    # ---- Switch / porte / PoE ----
    {"id": "net-port-100m", "vendor": "Networking", "tags": ["speed", "100", "mbps", "velocità", "negoziazione", "autoneg", "cavo", "cable", "gigabit"],
     "title": "Porta gigabit negoziata a 100 Mbps",
     "content": "Quasi sempre cavo: coppia interrotta (pin 4-5/7-8), crimpatura errata, cavo Cat5 vecchio o troppo lungo, presa a muro difettosa. Raramente NIC in risparmio energetico (Green Ethernet / EEE). "
                "Azione: test cavo (TDR se lo switch lo supporta: 'Vista cavo'), sostituire patch, verificare autoneg su entrambi i lati; se PC → disabilitare EEE nel driver."},
    {"id": "net-port-flap", "vendor": "Networking", "tags": ["flap", "flapping", "up", "down", "link", "instabile", "intermittente", "crc", "errors"],
     "title": "Porta in flap (up/down ripetuti)",
     "content": "Cause in ordine di probabilità: cavo/connettore difettoso, dispositivo che va in sospensione/riavvio ciclico, PoE insufficiente (AP/telefono si riavviano), loop STP, NIC guasta. "
                "Azione: guardare CRC/errors sulla porta, budget PoE, orari (se ogni N minuti → dispositivo; casuale → cavo). Sostituire patch prima di tutto."},
    {"id": "net-poe-standby", "vendor": "Networking", "tags": ["poe", "standby", "watt", "power", "alimentato", "link", "down"],
     "title": "Link giù ma PoE assorbe potenza",
     "content": "Il dispositivo è alimentato ma non ha link: telefono/AP in standby, riavvio in corso, o boot bloccato. Se dura > 10 min con PoE stabile → dispositivo bloccato: power-cycle della porta PoE via SNMP/CLI. "
                "Non è un guasto di cavo (il PoE passa sugli stessi fili)."},
    {"id": "net-poe-budget", "vendor": "Networking", "tags": ["poe", "budget", "overload", "denied", "power", "insufficient", "802.3at", "802.3bt"],
     "title": "PoE budget esaurito / porta PoE negata",
     "content": "Lo switch ha raggiunto il budget PoE: le porte a priorità bassa vengono spente. Sintomo: AP/telefoni si spengono quando se ne accende un altro. Azione: verificare budget totale vs richiesto, "
                "impostare priorità PoE sulle porte critiche, spostare dispositivi su altro switch o aggiungere injector."},
    {"id": "net-unused-ports", "vendor": "Networking", "tags": ["unused", "inutilizzata", "disable", "shutdown", "security", "sicurezza", "port-security", "802.1x"],
     "title": "Porte mai usate: disabilitarle (sicurezza)",
     "content": "Porte attive senza dispositivo da 30+ giorni sono un rischio (accesso fisico non autorizzato, loop accidentali). Best practice: shutdown amministrativo o VLAN black-hole, "
                "descrizione 'LIBERA'; abilitare port-security/802.1X sulle porte utente; BPDU guard sulle access."},
    {"id": "net-unknown-device", "vendor": "Networking", "tags": ["sconosciuto", "unknown", "nuovo", "cambiato", "mac", "estraneo", "rogue", "device", "changed"],
     "title": "Dispositivo sconosciuto o cambiato su una porta",
     "content": "Un MAC diverso dall'abituale su una porta utente: nuovo PC (verificare con RMM/Datto), laptop di un consulente, oppure dispositivo estraneo. Verificare OUI (vendor), hostname, "
                "se appare in Datto/inventario; se sconosciuto e fuori orario → possibile rogue: bloccare porta e verificare fisicamente."},
    {"id": "net-night-activity", "vendor": "Networking", "tags": ["notte", "night", "fuori", "orario", "festivo", "weekend", "attività", "anomala", "sospetta"],
     "title": "Attività su porta ufficio fuori orario/festivi",
     "content": "Porta 'a orario ufficio' attiva di notte o nei festivi: PC lasciato acceso (aggiornamenti WSUS/Datto), pulizie che accendono, telelavoro, o accesso non autorizzato. "
                "Correlare con Datto (utente loggato?), badge/allarme, e con la memoria porte (prima volta o abitudine?)."},
    {"id": "hpe-aruba-cli", "vendor": "HPE Aruba/Comware", "tags": ["aruba", "comware", "procurve", "officeconnect", "cli", "show", "interface", "display", "poe", "reset"],
     "title": "Comandi utili HPE Aruba (ArubaOS-Switch) e Comware",
     "content": "ArubaOS-Switch: 'show interfaces brief', 'show interfaces <p>' (errori/CRC), 'show power-over-ethernet brief', 'show mac-address <p>', 'show cable-diagnostics <p>', "
                "'interface <p> disable/enable', 'interface <p> power-over-ethernet' (toggle). Comware (1920/5130/5140): 'display interface brief', 'display interface GigabitEthernet1/0/N', "
                "'display poe interface', 'display mac-address interface GigabitEthernet1/0/N', 'shutdown/undo shutdown', 'undo poe enable / poe enable' per power-cycle."},
    {"id": "cisco-cli", "vendor": "Cisco", "tags": ["cisco", "ios", "catalyst", "show", "interface", "errdisable", "err-disabled", "bpduguard"],
     "title": "Cisco IOS: porta err-disabled e diagnostica",
     "content": "'show interfaces status err-disabled' → causa (bpduguard, psecure-violation, link-flap). Recupero: 'shutdown / no shutdown' o 'errdisable recovery cause X'. "
                "'show interfaces Gi1/0/N' per CRC/input errors; 'test cable-diagnostics tdr interface Gi1/0/N' + 'show cable-diagnostics tdr'."},
    {"id": "zyxel-nebula", "vendor": "Zyxel", "tags": ["zyxel", "nebula", "gs1920", "gs2210", "xgs", "offline", "cloud"],
     "title": "Zyxel Nebula: device offline nel cloud ma raggiungibile in LAN",
     "content": "Nebula richiede DNS e uscita TCP 443/4335 verso il cloud: se il device è pingabile in LAN ma OFFLINE in Nebula → firewall/DNS/NTP del cliente, non lo switch. "
                "Se offline in entrambi → alimentazione o uplink. Verificare 'Nebula Connectivity' e ora corretta."},
    # ---- Virtualizzazione / SO ----
    {"id": "hyperv-vm-off", "vendor": "Microsoft", "tags": ["hyper-v", "hyperv", "vm", "off", "saved", "paused", "host", "running"],
     "title": "VM Hyper-V Off/Saved/Paused",
     "content": "Off/Saved = spegnimento deliberato o host riavviato senza auto-start (verificare 'Automatic Start Action'). Paused = spazio disco esaurito sul volume delle VM (Hyper-V mette in pausa critica) → liberare spazio SUBITO. "
                "Running ma non pingabile = SO bloccato o rete VM (vSwitch/VLAN) → console da host."},
    {"id": "os-hung-l2", "vendor": "OS", "tags": ["so", "bloccato", "hung", "frozen", "mac", "arp", "vivo", "ping", "no", "response"],
     "title": "MAC vivo in rete ma niente ping/agente: SO bloccato",
     "content": "La NIC risponde a L2 (ARP/FDB) ma il SO non risponde: kernel panic/BSOD, disco pieno, storage staccato, o firewall ICMP appena attivato. Se anche l'agente RMM è offline → SO bloccato: "
                "power-cycle via iLO/host. Se Datto online e SNMP ok → solo ICMP filtrato: non è un guasto."},
    {"id": "datto-offline", "vendor": "Datto RMM", "tags": ["datto", "rmm", "agente", "offline", "last", "seen", "ultimo", "contatto"],
     "title": "Agente Datto offline: come usarlo per la diagnosi",
     "content": "Se l'ultimo contatto Datto coincide (±10 min) con l'inizio del down → spegnimento/crash reale. Se Datto è online mentre il ping fallisce → device acceso, ICMP bloccato o problema di rete tra connettore e device. "
                "Datto offline da giorni con porta switch giù a orari regolari → PC spento dall'utente."},
]

VENDOR_HINTS = {"hpe": "HPE", "hewlett": "HPE", "proliant": "HPE", "ilo": "HPE", "aruba": "HPE Aruba/Comware", "comware": "HPE Aruba/Comware",
                "cisco": "Cisco", "zyxel": "Zyxel", "hyper-v": "Microsoft", "hyperv": "Microsoft", "datto": "Datto RMM"}


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-zà-ú0-9][a-zà-ú0-9\-\.]{1,}", (text or "").lower()) if t not in _STOP and len(t) > 1}


def _score(entry: dict, toks: set, vendor: Optional[str]) -> float:
    tags = {t.lower() for t in entry.get("tags") or []}
    title_t = _tokens(entry.get("title", ""))
    body_t = _tokens(entry.get("content", ""))
    s = 3.0 * len(toks & tags) + 2.0 * len(toks & title_t) + 0.3 * len(toks & body_t)
    if vendor and (entry.get("vendor") or "").lower().startswith(vendor.lower()[:4]):
        s += 1.5
    return s


async def search_kb(db, text: str, vendor: Optional[str] = None, limit: int = 6) -> list[dict]:
    """Voci KB (builtin + utente) più pertinenti al testo (log, contesto porta, alert)."""
    toks = _tokens(text)
    if not vendor:
        for k, v in VENDOR_HINTS.items():
            if k in (text or "").lower():
                vendor = v
                break
    user = [{**d, "source": "user"} async for d in db.ai_knowledge.find({"enabled": {"$ne": False}}, {"_id": 0})]
    scored = [(s, e) for e in BUILTIN_KB + user if (s := _score(e, toks, vendor)) >= 3.0]
    scored.sort(key=lambda x: -x[0])
    return [{"id": e.get("id"), "vendor": e.get("vendor"), "title": e.get("title"), "content": e.get("content"),
             "source": e.get("source", "builtin"), "score": round(s, 1)} for s, e in scored[:limit]]


async def case_memory(db, client_id: str, device_ip: str, port_name: Optional[str] = None, limit: int = 8) -> list[dict]:
    """Casi passati sullo stesso device/porta: alert risolti con nota + feedback dell'utente sulle analisi AI."""
    out: list[dict] = []
    q: dict = {"client_id": client_id, "device_ip": device_ip, "status": "resolved",
               "$or": [{"resolution_note": {"$nin": [None, ""]}}, {"resolution_reason": {"$in": ["false_positive", "maintenance", "fixed", "manual"]}}]}
    if port_name:
        q["$and"] = [{"$or": [{"message": {"$regex": re.escape(port_name)}}, {"title": {"$regex": re.escape(port_name)}}, {"raw_data.port_name": port_name}]}]
    async for a in db.alerts.find(q, {"_id": 0, "title": 1, "resolved_at": 1, "resolution_reason": 1, "resolution_note": 1, "resolved_by": 1, "severity": 1}).sort("resolved_at", -1).limit(limit):
        out.append({"kind": "alert_resolved", "when": a.get("resolved_at"), "title": a.get("title"), "outcome": a.get("resolution_reason"),
                    "note": a.get("resolution_note"), "by": a.get("resolved_by")})
    fq: dict = {"client_id": client_id, "device_ip": device_ip}
    if port_name:
        fq["port_name"] = port_name
    async for f in db.ai_feedback.find(fq, {"_id": 0}).sort("created_at", -1).limit(limit):
        out.append({"kind": "ai_feedback", "when": f.get("created_at"), "analysis": f.get("analysis_kind"), "ai_verdict": f.get("ai_verdict"),
                    "correct": f.get("correct"), "note": f.get("note"), "by": f.get("by")})
    out.sort(key=lambda x: x.get("when") or "", reverse=True)
    return out[:limit]


def kb_instructions() -> str:
    return ("\nUsa la BASE DI CONOSCENZA fornita (voci vendor con id) come riferimento tecnico prioritario e cita l'id della voce quando la usi "
            "(campo 'kb_refs'). Usa la MEMORIA CASI (come il NOC ha risolto casi passati sullo stesso device/porta, e i feedback del tecnico sulle "
            "analisi precedenti) per non ripetere errori: se un feedback dice che un verdetto era sbagliato, spiega perché ora è diverso o correggi.")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
