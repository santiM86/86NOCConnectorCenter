"""
Catalogo Diagnosi — fonte di verità delle situazioni che Argus sa dichiarare.
Espone la matrice completa (per la pagina "Catalogo Diagnosi" del frontend):
situazioni per dominio con confidenza reale, trigger, severità e azione, i tempi
di rilevamento (cadenze di polling reali) e le combinazioni trasversali.
"""
from fastapi import APIRouter, Depends
from deps import get_current_user

router = APIRouter(prefix="/api/diagnosis", tags=["diagnosis-catalog"])

# Cadenze REALI di rilevamento (dagli scheduler in server.py / alert_engine.py).
DETECTION_LATENCY = [
    {"signal": "Liveness / correlazione (up/down, ISP, sito isolato)", "cadence_s": 60, "note": "Alert Engine ogni 60s"},
    {"signal": "Connettore/Agent offline (watchdog)", "cadence_s": 60, "note": "connector_watchdog 60s"},
    {"signal": "Stato alimentazione iLO/Redfish (server spento)", "cadence_s": 60, "note": "poll 1 min"},
    {"signal": "Hardware SNMP + Predittiva (RAID/temp/UPS)", "cadence_s": 60, "note": "ad ogni poll SNMP dell'agent (~60s)"},
    {"signal": "Comunicazione C2 (OSINT)", "cadence_s": 120, "note": "osint_c2_tick 2 min"},
    {"signal": "Dispositivi rogue (NAC-lite)", "cadence_s": 180, "note": "rogue_scan 3 min"},
    {"signal": "Anomalie traffico porte", "cadence_s": 300, "note": "traffic_anomaly 5 min"},
    {"signal": "Feed CVE/reputazione (OSINT)", "cadence_s": 300, "note": "feeds 5 min; exposure scan 30 min"},
    {"signal": "Stato host Hyper-V (VM spenta)", "cadence_s": 300, "note": "5 min"},
    {"signal": "Zyxel Nebula Cloud", "cadence_s": 300, "note": "5 min"},
    {"signal": "Backup (Hornetsecurity / VM)", "cadence_s": 60, "note": "1 min"},
    {"signal": "Sync Datto RMM", "cadence_s": 21600, "note": "6 ore"},
]

# Livelli di certezza (mapping % -> etichetta)
def _tier(conf):
    if conf >= 100:
        return "certo_100"
    if conf >= 90:
        return "quasi_certo"
    if conf >= 55:
        return "alta"
    return "incerto"


def _s(code, label, conf, trigger, severity, action):
    return {"code": code, "label": label, "confidence": conf, "tier": _tier(conf),
            "trigger": trigger, "severity": severity, "action": action}


DOMAINS = [
    {
        "domain": "reachability", "label": "Raggiungibilità (up/down)",
        "situations": [
            _s("server_powered_off", "Server SPENTO", 100,
               "Ping FAIL + Datto OFFLINE + iLO/Redfish PowerState=Off", "critical",
               "Riaccendi da iLO/fisicamente, verifica l'alimentazione."),
            _s("healthy", "Dispositivo OPERATIVO", 100,
               "Ping OK (o MAC vivo a L2)", "none", "Nessuna azione."),
            _s("vm_powered_off", "VM spenta di proposito", 100,
               "Host Hyper-V riporta la VM Off/Saved/Paused", "none", "Nessun down: spegnimento intenzionale."),
            _s("site_power_confirmed", "SITO GIÙ — MANCANZA CORRENTE CONFERMATA", 99,
               "Agent on-site giù + WAN esterna giù + UPS rilevato 'su batteria' poco prima", "critical",
               "Blackout elettrico confermato: contatta il cliente/fornitore energia; niente da fare sui device."),
            _s("site_power_down", "SITO GIÙ (corrente o WAN a monte)", 96,
               "Agent on-site giù + sonda WAN esterna vede Internet giù (nessun UPS a conferma)", "critical",
               "Sito totalmente offline: verifica corrente e linea ISP a monte."),
            _s("site_isolated", "SITO ISOLATO", 97,
               "Firewall/gateway DOWN + maggioranza device del sito irraggiungibili", "critical",
               "Verifica uplink/collegamento a monte; non toccare i singoli device."),
            _s("switch_down", "SWITCH DOWN (segmento isolato)", 95,
               "Switch non raggiungibile + tutti i device a valle down", "critical",
               "Verifica alimentazione/uplink dello switch."),
            _s("server_down", "SERVER DOWN", 95,
               "Ping FAIL + Datto OFFLINE + nessuna evidenza L2", "critical",
               "Verifica alimentazione, rete e stato fisico."),
            _s("isp_down", "LINEA ISP GIÙ", 95,
               "Firewall raggiungibile ma Internet (probe WAN) DOWN", "critical",
               "Apri ticket con l'ISP."),
            _s("os_hung", "SO bloccato / crash", 92,
               "Ping FAIL + Datto OFFLINE + iLO acceso (hardware ON)", "critical",
               "Reset via iLO; se non risponde, riavvio fisico e analisi log."),
            _s("datto_agent_issue", "Agent Datto KO (server OK)", 85,
               "Ping OK ma Datto OFFLINE", "low", "Riavvia/reinstalla l'agent Datto RMM."),
            _s("unreachable", "Dispositivo irraggiungibile", 80,
               "Ping FAIL, nessun altro segnale positivo", "high",
               "Verifica alimentazione, cavo/porta di rete."),
            _s("switch_unreachable", "Switch irraggiungibile", 75,
               "Ping FAIL, connettore attivo", "high", "Verifica switch e mgmt-plane."),
            _s("unresponsive_l2_present", "Presente in rete ma non risponde", 70,
               "Ping FAIL + Datto OFFLINE ma MAC vivo su switch", "high",
               "SO/stack di rete KO o riavvio in corso: verifica."),
            _s("firewall_mgmt_down", "Gestione firewall down", 60,
               "IP mgmt firewall irraggiungibile (resto sito ok)", "high", "Verifica il mgmt-plane."),
            _s("connector_blind", "Connettore cieco (incerto)", 30,
               "Ping FAIL ma connettore non disponibile", "none", "Da verificare: nessun alert emesso."),
            _s("no_data", "Nessun dato (non giudicabile)", 0,
               "Device mai pollato", "none", "Attendi il primo ciclo di polling."),
        ],
    },
    {
        "domain": "predictive", "label": "Guasto imminente (predittiva)",
        "situations": [
            _s("predictive_raid", "RAID degradato / in crash", 100,
               "vendor_metrics raidStatus=11/12 o systemStatus=Failed", "critical",
               "Sostituisci il disco guasto e avvia la ricostruzione PRIMA di perdere ridondanza."),
            _s("predictive_temp", "Surriscaldamento imminente", 90,
               "Trend temperatura in salita → ETA proiettata alla soglia critica (≤1h critico, ≤6h alto)", "critical",
               "Verifica ventole/condizionamento e filtri prima del blocco termico."),
            _s("predictive_ups", "UPS in esaurimento", 95,
               "Autonomia ≤5 min o carica ≤20% (critico); carica in calo/su batteria (alto)", "critical",
               "Verifica alimentazione di rete e batteria; pianifica spegnimento controllato."),
        ],
    },
    {
        "domain": "hardware", "label": "Hardware (soglie SNMP)",
        "situations": [
            _s("hardware_fan", "Guasto ventola", 100,
               "Stato enum ventola fuori dai valori sani del profilo", "critical", "Verifica/sostituisci la ventola."),
            _s("hardware_psu", "Guasto alimentatore (PSU)", 100,
               "Stato enum PSU fuori dai valori sani del profilo", "critical", "Verifica/sostituisci l'alimentatore."),
            _s("hardware_temp", "Temperatura oltre soglia", 90,
               "Temperatura ≥ soglia WARN/CRIT del profilo", "high", "Verifica raffreddamento."),
            _s("hardware_cpu", "CPU critica/elevata", 85,
               "CPU ≥ soglia per N cicli consecutivi (anti-picco)", "high", "Verifica carico/processi."),
            _s("hardware_mem", "Memoria satura", 85,
               "Memoria ≥ soglia del profilo", "high", "Verifica consumo memoria."),
        ],
    },
    {
        "domain": "security", "label": "Sicurezza / OSINT / NAC",
        "situations": [
            _s("osint_c2", "Comunicazione con C2 (compromissione)", 95,
               "IP destinazione = IOC noto (match diretto sul feed)", "critical",
               "Isola il device e avvia incident response."),
            _s("osint_exposure", "CVE sfruttata esposta (KEV)", 95,
               "IP pubblico con servizio che matcha una CISA KEV", "critical",
               "Applica patch/mitigazioni con priorità."),
            _s("rogue_device", "Dispositivo rogue / non autorizzato", 85,
               "Nuovo MAC non in allowlist rilevato in rete", "high", "Identifica e autorizza o blocca sulla porta."),
            _s("security_identity_change", "Cambio identità dispositivo", 80,
               "Cambio MAC↔IP / hostname sospetto", "high", "Verifica spoofing/sostituzione."),
            _s("security_mac_ip_roam", "Roaming anomalo MAC", 70,
               "Stesso MAC su porte/segmenti diversi in breve tempo", "medium", "Verifica movimento fisico o spoofing."),
        ],
    },
    {
        "domain": "backup", "label": "Backup",
        "situations": [
            _s("backup", "Backup fallito / non aggiornato", 90,
               "Report Datto / Hornetsecurity / VM backup con job KO o stale", "medium",
               "Verifica job di backup, spazio e destinazione."),
        ],
    },
    {
        "domain": "performance", "label": "Performance / Rete",
        "situations": [
            _s("external_monitor_line", "Linea/servizio esterno degradato", 90,
               "Monitor esterno (probe WAN/servizio pubblico) in errore", "critical", "Verifica linea ISP/servizio."),
            _s("traffic_anomaly", "Anomalia traffico porta", 75,
               "Deviazione significativa dal baseline della porta", "medium", "Verifica saturazione/eventi anomali."),
            _s("port_flap", "Port flapping", 80,
               "Porta switch up/down ripetuti in breve tempo", "high", "Verifica cavo/SFP/negoziazione."),
            _s("wan_public_ip_change", "Cambio IP pubblico WAN", 90,
               "IP pubblico del sito cambiato", "medium", "Verifica se pianificato (DHCP ISP) o anomalo."),
            _s("switch_cascade", "Cascata switch (uplink)", 85,
               "Variazione topologia/uplink a monte", "high", "Verifica l'uplink dello switch a monte."),
        ],
    },
    {
        "domain": "discovery", "label": "Discovery / Nuovi device",
        "situations": [
            _s("new_devices_detected", "Nuovi dispositivi rilevati", 100,
               "Nuovo host individuato dall'auto-discovery (ARP/mDNS/SNMP/LLDP)", "low",
               "Triage: assegna, marca vitale o ignora."),
        ],
    },
]

# Combinazioni TRASVERSALI (il valore del Situation Engine: un verdetto unico).
CROSS_COMBINATIONS = [
    {"situation": "Compromissione su hardware a rischio",
     "combo": "Device UP + comunicazione C2 (sicurezza) + RAID degradato (predittiva)",
     "verdict": "CRITICO — primaria: Sicurezza (C2). Il device funziona ma è compromesso E il suo storage è a rischio.",
     "why": "Sicurezza pesa più della predittiva: prima isolo, poi salvo i dati."},
    {"situation": "Server operativo ma non protetto",
     "combo": "Ping OK (operativo) + backup fallito da giorni",
     "verdict": "WARNING/CRITICO — il server gira ma un guasto oggi = perdita dati non recuperabile.",
     "why": "La raggiungibilità sana non basta: il rischio business viene dal backup."},
    {"situation": "Blackout vs guasto singolo",
     "combo": "Firewall DOWN + maggioranza device down (site_isolated) → tutti i figli soppressi",
     "verdict": "CRITICO — UN solo alert 'SITO ISOLATO' invece di 40 alert separati.",
     "why": "Dedup della causa radice: elimina l'alert-fatigue."},
    {"situation": "Falso down evitato",
     "combo": "Ping FAIL ma VM Running su Hyper-V + MAC vivo",
     "verdict": "OPERATIVO — ICMP filtrato, nessun alert.",
     "why": "L'evidenza multi-fonte evita il falso positivo classico."},
    {"situation": "Guasto termico prima del down",
     "combo": "Device UP + trend temperatura → soglia critica tra ~25 min",
     "verdict": "CRITICO (predittiva) — intervieni ORA, il down non è ancora avvenuto.",
     "why": "Predittiva: dichiaro il problema prima che il device cada."},
]


@router.get("/catalog")
async def get_catalog(current_user: dict = Depends(get_current_user)):
    total = sum(len(d["situations"]) for d in DOMAINS)
    certain = sum(1 for d in DOMAINS for s in d["situations"] if s["confidence"] >= 100)
    return {
        "summary": {"domains": len(DOMAINS), "situations_total": total, "certain_100": certain,
                    "cross_combinations": len(CROSS_COMBINATIONS)},
        "detection_latency": DETECTION_LATENCY,
        "domains": DOMAINS,
        "cross_combinations": CROSS_COMBINATIONS,
    }
