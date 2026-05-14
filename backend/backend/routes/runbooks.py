"""
Runbooks — procedure operative per tecnici NOC.
Ogni runbook ha: titolo, device_type/alert_type (trigger match),
steps (ordinati, con comando/spiegazione), owner, last_updated.
Quando si apre un alert, il frontend cerca runbook matching e mostra "procedura suggerita".
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/runbooks", tags=["runbooks"])


class RunbookStep(BaseModel):
    order: int
    title: str
    description: Optional[str] = None
    command: Optional[str] = None  # Comando shell/CLI opzionale
    expected_result: Optional[str] = None


class Runbook(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    device_types: List[str] = []       # match: switch, router, ilo, firewall, nas, ups
    alert_keywords: List[str] = []     # match titolo/messaggio alert (case-insensitive)
    severity_match: List[str] = []     # ["critical", "warning"] — empty = any
    vendor_match: List[str] = []       # ["HPE", "Cisco", "Synology"] — empty = any
    profile_keys: List[str] = []       # ["synology_dsm", "hp_procurve"] — empty = any
    capability_match: List[str] = []   # ["disk_smart", "vpn_tunnels"] — empty = any
    steps: List[RunbookStep] = []
    tags: List[str] = []


@router.get("")
async def list_runbooks(device_type: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {}
    if device_type:
        q["device_types"] = device_type
    cursor = db.runbooks.find(q, {"_id": 0}).sort("updated_at", -1).limit(200)
    return {"items": [d async for d in cursor]}


@router.get("/{rb_id}")
async def get_runbook(rb_id: str, current_user: dict = Depends(get_current_user)):
    rb = await db.runbooks.find_one({"id": rb_id}, {"_id": 0})
    if not rb:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return rb


@router.post("")
async def create_runbook(rb: Runbook, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    now = datetime.now(timezone.utc)
    data = rb.model_dump()
    data["id"] = data.get("id") or str(uuid.uuid4())
    data["created_at"] = now
    data["updated_at"] = now
    data["created_by"] = current_user.get("email")
    # Normalize keywords to lowercase
    data["alert_keywords"] = [k.lower() for k in (data.get("alert_keywords") or [])]
    data["device_types"] = [k.lower() for k in (data.get("device_types") or [])]
    await db.runbooks.insert_one(data)
    data.pop("_id", None)  # Remove MongoDB ObjectId before returning
    return data


@router.put("/{rb_id}")
async def update_runbook(rb_id: str, rb: Runbook, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    data = rb.model_dump()
    data["updated_at"] = datetime.now(timezone.utc)
    data["updated_by"] = current_user.get("email")
    data["alert_keywords"] = [k.lower() for k in (data.get("alert_keywords") or [])]
    data["device_types"] = [k.lower() for k in (data.get("device_types") or [])]
    data.pop("id", None)
    res = await db.runbooks.update_one({"id": rb_id}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.delete("/{rb_id}")
async def delete_runbook(rb_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    res = await db.runbooks.delete_one({"id": rb_id})
    return {"deleted": res.deleted_count > 0}


@router.get("/match/alert/{alert_id}")
async def match_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    """Trova i runbook rilevanti per un alert specifico.
    Scoring: profile_key (+5) > keyword (+3) > device_type (+2) > vendor (+2) > capability (+2) > severity (+1).
    """
    alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    device_type = (alert.get("device_type") or "").lower()
    severity = (alert.get("severity") or "").lower()
    title = (alert.get("title") or "").lower()
    message = (alert.get("message") or "").lower()
    haystack = f"{title} {message}"

    # Enrich alert context from device_poll_status (profile_key, vendor, capabilities)
    device_ip = alert.get("device_ip") or alert.get("source_ip")
    profile_key = ""
    vendor = ""
    family = ""
    capabilities: list[str] = []
    if device_ip:
        ps = await db.device_poll_status.find_one(
            {"device_ip": device_ip},
            {"_id": 0, "profile_key": 1, "vendor": 1, "family": 1}
        ) or {}
        profile_key = (ps.get("profile_key") or "").lower()
        vendor = (ps.get("vendor") or "").lower()
        family = (ps.get("family") or "").lower()
        # Pull capabilities list from the profile library
        if profile_key:
            try:
                from device_profiles import get_profile
                prof = get_profile(profile_key) or {}
                capabilities = [c.lower() for c in (prof.get("capabilities") or [])]
            except Exception:
                pass
        # Use profile family as device_type fallback
        if not device_type and family:
            device_type = family

    cursor = db.runbooks.find({}, {"_id": 0}).limit(200)
    matches = []
    async for rb in cursor:
        score = 0
        reasons: list[str] = []

        # profile_key match (highest signal — vendor+model specific)
        rb_profiles = [p.lower() for p in (rb.get("profile_keys") or [])]
        if profile_key and rb_profiles and profile_key in rb_profiles:
            score += 5; reasons.append(f"profile:{profile_key}")

        # keyword match (very strong — direct alert wording)
        kw_hits = [kw for kw in (rb.get("alert_keywords") or []) if kw and kw in haystack]
        if kw_hits:
            score += 3 * len(kw_hits)
            reasons.append(f"keywords:{','.join(kw_hits[:3])}")

        # device_type match
        rb_types = [t.lower() for t in (rb.get("device_types") or [])]
        if device_type and rb_types and device_type in rb_types:
            score += 2; reasons.append(f"type:{device_type}")

        # vendor match (case-insensitive contains)
        rb_vendors = [v.lower() for v in (rb.get("vendor_match") or [])]
        if vendor and rb_vendors:
            for rv in rb_vendors:
                if rv in vendor or vendor in rv:
                    score += 2; reasons.append(f"vendor:{rv}"); break

        # capability match (e.g. disk_smart, vpn_tunnels)
        rb_caps = [c.lower() for c in (rb.get("capability_match") or [])]
        cap_hits = [c for c in rb_caps if c in capabilities]
        if cap_hits:
            score += 2 * len(cap_hits)
            reasons.append(f"caps:{','.join(cap_hits[:3])}")

        # severity match
        rb_sev = [s.lower() for s in (rb.get("severity_match") or [])]
        if severity and rb_sev and severity in rb_sev:
            score += 1; reasons.append(f"severity:{severity}")

        if score > 0:
            rb["_match_score"] = score
            rb["_match_reasons"] = reasons
            matches.append(rb)
    matches.sort(key=lambda x: x.get("_match_score", 0), reverse=True)
    return {
        "alert": alert,
        "context": {"profile_key": profile_key, "vendor": vendor, "family": family, "capabilities": capabilities},
        "matches": matches[:5],
    }


@router.post("/seed-defaults")
async def seed_default_runbooks(current_user: dict = Depends(get_current_user)):
    """Seed di runbook starter per i profili vendor principali (idempotente).
    Inserisce solo se non esiste gia' un runbook con lo stesso slug (tag 'seed:<slug>').
    """
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    seeds = _default_seeds()
    now = datetime.now(timezone.utc)
    inserted = 0
    skipped = 0
    for seed in seeds:
        slug = seed.pop("_slug")
        existing = await db.runbooks.find_one({"tags": f"seed:{slug}"})
        if existing:
            skipped += 1
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "created_at": now, "updated_at": now,
            "created_by": current_user.get("email"),
            **seed,
        }
        doc["tags"] = list(set((doc.get("tags") or []) + [f"seed:{slug}"]))
        doc["alert_keywords"] = [k.lower() for k in (doc.get("alert_keywords") or [])]
        doc["device_types"] = [k.lower() for k in (doc.get("device_types") or [])]
        await db.runbooks.insert_one(doc)
        inserted += 1
    return {"ok": True, "inserted": inserted, "skipped": skipped, "total_seeds": len(seeds)}


def _default_seeds() -> list[dict]:
    """Runbook starter templates per i profili vendor. Editabili dall'UI dopo seed."""
    return [
        {
            "_slug": "synology-disk-degraded",
            "title": "Synology — Disco degradato / RAID in Degrade",
            "description": "Procedura di triage per Synology DSM quando un disco è marcato Degrade o Failed.",
            "device_types": ["nas"],
            "vendor_match": ["synology"],
            "profile_keys": ["synology_dsm"],
            "capability_match": ["disk_smart", "raid_status"],
            "severity_match": ["critical", "high", "warning"],
            "alert_keywords": ["disco", "disk", "raid", "smart", "degrade", "failed", "volume"],
            "tags": ["vendor:synology", "hardware:storage"],
            "steps": [
                {"order": 1, "title": "Identifica il disco", "description": "DSM → Storage Manager → HDD/SSD. Nota lo slot del disco con stato rosso."},
                {"order": 2, "title": "Verifica SMART", "description": "Clicca sul disco → Health Info → SMART. Controlla Reallocated Sectors, Pending Sectors, UDMA CRC Errors.", "expected_result": "Se Reallocated>0 o Pending>0 → disco in predictive failure, sostituire."},
                {"order": 3, "title": "Controlla log DSM", "description": "Log Center → filtra per 'storage' e 'disk'. Cerca pattern di errori I/O ricorrenti."},
                {"order": 4, "title": "Hot-swap del disco", "description": "Se il NAS supporta hot-swap (tutti i DiskStation 2-bay+), estrai il disco guasto, inserisci il ricambio stesso tipo/capacità ≥.", "expected_result": "DSM rileva il nuovo disco entro 30s"},
                {"order": 5, "title": "Avvia Repair RAID", "description": "Storage Manager → Volume → Repair. La ricostruzione può durare 6-24h per volumi grandi."},
                {"order": 6, "title": "Post-repair", "description": "Verifica integrità: 'btrfs scrub start -r /volume1' (DSM 7 con Btrfs) oppure Data Scrubbing pianificato."},
            ],
        },
        {
            "_slug": "synology-volume-full",
            "title": "Synology — Volume >90% pieno",
            "description": "Gestione volume DSM quasi pieno.",
            "device_types": ["nas"],
            "vendor_match": ["synology"],
            "profile_keys": ["synology_dsm"],
            "capability_match": ["volume_usage"],
            "alert_keywords": ["volume", "space", "full", "pieno", "storage", "disk"],
            "severity_match": ["critical", "high", "warning"],
            "tags": ["vendor:synology", "capacity"],
            "steps": [
                {"order": 1, "title": "Identifica cartelle 'pesanti'", "description": "File Station → ordina per dimensione. Usa anche Storage Analyzer (pacchetto Synology gratuito)."},
                {"order": 2, "title": "Verifica snapshot", "description": "Snapshot Replication → controlla retention. Snapshot vecchi su iSCSI/BTRFS possono occupare GB."},
                {"order": 3, "title": "Svuota cestino #recycle", "description": "File Station → Controllo → Svuota tutti i cestini condivisi. Libera spesso 5-20% istantaneamente."},
                {"order": 4, "title": "Pianifica espansione", "description": "Se dopo cleanup il volume resta >80% → valuta add shelf o migrare a NAS più capiente."},
            ],
        },
        {
            "_slug": "fortinet-vpn-down",
            "title": "Fortinet — Tunnel VPN IPsec DOWN",
            "description": "Troubleshooting tunnel VPN IPsec fra FortiGate.",
            "device_types": ["firewall"],
            "vendor_match": ["fortinet"],
            "profile_keys": ["fortinet_fortigate"],
            "capability_match": ["vpn_tunnels"],
            "severity_match": ["critical", "high"],
            "alert_keywords": ["vpn", "tunnel", "ipsec", "down", "phase"],
            "tags": ["vendor:fortinet", "vpn"],
            "steps": [
                {"order": 1, "title": "Check Phase-1/Phase-2 status", "command": "diagnose vpn ike gateway list name <gw_name>", "expected_result": "State 'established' su phase1; stats con packets>0"},
                {"order": 2, "title": "Debug negoziazione live", "command": "diagnose debug application ike -1\\ndiagnose debug enable", "description": "Attiva debug + prova a pingare un IP remoto. Poi 'diagnose debug disable' quando finito."},
                {"order": 3, "title": "Verifica PSK / certificato", "description": "VPN → IPsec Tunnels → seleziona il tunnel → verifica PSK. Se mismatched, il log mostra 'preshared key mismatch'."},
                {"order": 4, "title": "Check routing / policy", "description": "Policy & Objects → verifica che ci sia policy IPv4 fra le subnet. Routing: 'get router info routing-table all'."},
                {"order": 5, "title": "Flush e riavvia tunnel", "command": "diagnose vpn tunnel flush\\ndiagnose vpn tunnel up <tunnel>"},
            ],
        },
        {
            "_slug": "apc-ups-on-battery",
            "title": "APC UPS — Passaggio a batteria",
            "description": "Alert UPS on-battery. Verifica runtime residuo, graceful shutdown se prolungato.",
            "device_types": ["ups"],
            "vendor_match": ["apc"],
            "profile_keys": ["apc_ups"],
            "capability_match": ["battery_monitoring", "input_voltage"],
            "severity_match": ["critical", "high", "warning"],
            "alert_keywords": ["ups", "battery", "batteria", "power", "onbattery", "blackout"],
            "tags": ["vendor:apc", "power"],
            "steps": [
                {"order": 1, "title": "Verifica runtime residuo", "description": "Web UI UPS o SNMP: upsAdvBatteryRunTime. Se <10min → shutdown procedure. Se >30min → monitoraggio."},
                {"order": 2, "title": "Check input voltage", "description": "upsAdvInputVoltage. Se 0V = blackout totale. Se <200V = brown-out, UPS protegge ma non shutdown immediato."},
                {"order": 3, "title": "Notifica utenti se prolungato", "description": "Se blackout >5min e runtime <20min → avvisa utenti di salvare + logout su server critici."},
                {"order": 4, "title": "Graceful shutdown", "description": "Se runtime <5min → trigger graceful shutdown server via PowerChute Network Shutdown o script CLI. Priorità: DB → app → infra."},
                {"order": 5, "title": "Post-ripristino", "description": "Ritorno rete elettrica → verifica self-test: upsAdvTestDiagnosticsResults deve essere 'passed'. Se 'failed' → pianifica sostituzione batterie."},
            ],
        },
        {
            "_slug": "hp-switch-port-down",
            "title": "HP / Aruba ProCurve — Porta DOWN o flapping",
            "description": "Troubleshoot porta switch HP in stato down o link flapping.",
            "device_types": ["switch"],
            "vendor_match": ["hp", "aruba"],
            "profile_keys": ["hp_procurve"],
            "alert_keywords": ["port", "porta", "link", "down", "flap", "interface"],
            "severity_match": ["high", "warning"],
            "tags": ["vendor:hp", "networking"],
            "steps": [
                {"order": 1, "title": "Verifica stato porta", "command": "show interface <port>", "expected_result": "Link state = Up/Down; errors counters"},
                {"order": 2, "title": "Check errori L1", "command": "show interface <port> | include error", "description": "CRC errors, late collisions → problema cavo o velocità. Giant frames → jumbo mismatch."},
                {"order": 3, "title": "Ispezione fisica", "description": "Verifica cavo patch + punto da patch panel. Testa cavo con tester RJ45. Prova altra porta come controllo."},
                {"order": 4, "title": "Reset porta", "command": "interface <port>\\n  disable\\n  enable"},
                {"order": 5, "title": "Loop detection", "description": "Se flapping continuo → possibile loop L2. Verifica 'show spanning-tree' e 'show loop-protect'."},
            ],
        },
        {
            "_slug": "unifi-ap-offline",
            "title": "UniFi — Access Point Offline / Isolated",
            "description": "AP UniFi non raggiunge il controller (DISCONNECTED/ISOLATED).",
            "device_types": ["unifi"],
            "vendor_match": ["ubiquiti"],
            "profile_keys": ["unifi"],
            "alert_keywords": ["ap", "unifi", "offline", "disconnected", "isolated", "adopt"],
            "tags": ["vendor:ubiquiti", "wifi"],
            "steps": [
                {"order": 1, "title": "Ping + SSH all'AP", "command": "ping <ap_ip>", "description": "Se ping OK ma controller dice offline → problema inform URL."},
                {"order": 2, "title": "SSH + info", "command": "ssh ubnt@<ap_ip>\\ninfo", "description": "Default user: ubnt/ubnt se non adottato; altrimenti credenziali site."},
                {"order": 3, "title": "Re-inform al controller", "command": "set-inform http://<controller_ip>:8080/inform"},
                {"order": 4, "title": "Adopt in controller", "description": "UniFi Controller → Devices → click AP pending → Adopt."},
                {"order": 5, "title": "Se ancora isolated", "command": "syswrapper.sh restore-default", "description": "Factory reset come ultima risorsa."},
            ],
        },
        {
            "_slug": "ilo-fan-critical",
            "title": "HPE iLO — Ventola in stato critical",
            "description": "Ventola server HPE rilevata come critical/failed via Redfish.",
            "device_types": ["ilo", "server_oob"],
            "vendor_match": ["hpe", "hp"],
            "profile_keys": ["hpe_ilo"],
            "capability_match": ["hardware_oob", "thermal_detail"],
            "severity_match": ["critical", "high"],
            "alert_keywords": ["fan", "ventola", "cooling", "redfish"],
            "tags": ["vendor:hpe", "hardware:cooling"],
            "steps": [
                {"order": 1, "title": "Verifica sensore", "description": "iLO UI → Information → Cooling. Trova ventola (Fan X) con 'Condition: Critical/Failed'."},
                {"order": 2, "title": "Check temperature correlate", "description": "Information → Temperatures. CPU/Inlet in rosso? Se sì → rischio shutdown termico imminente."},
                {"order": 3, "title": "Pianifica sostituzione", "description": "Ventole HPE hot-swappable sui ProLiant (Gen9/10/11). PN ventola = ricava da label interna o iLO → Inventory."},
                {"order": 4, "title": "Controllo filo flusso aria", "description": "Prima di sostituire verifica griglie anteriori pulite. Spesso filtri polvere saturi causano fan runaway."},
            ],
        },
        {
            "_slug": "device-offline-generic",
            "title": "Device offline — Troubleshoot generico",
            "description": "Procedura generica quando un device non risponde a ping/SNMP.",
            "device_types": [],  # match any
            "alert_keywords": ["offline", "unreachable", "not responding", "non raggiungibile", "down"],
            "severity_match": ["critical", "high"],
            "tags": ["general", "connectivity"],
            "steps": [
                {"order": 1, "title": "Ping + traceroute dal connector", "command": "ping -c 4 <device_ip>\\ntraceroute <device_ip>"},
                {"order": 2, "title": "Check SNMP", "command": "snmpwalk -v2c -c public <device_ip> 1.3.6.1.2.1.1", "description": "Timeout → SNMP agent down o community cambiata. Reply → device vivo, alert potrebbe essere falso positivo."},
                {"order": 3, "title": "Verifica porta accesso", "description": "tcping / nc -zv <device_ip> <port> sulla porta di management (443/22/80/8443 a seconda del device_type)."},
                {"order": 4, "title": "Check switch edge", "description": "Identifica switch a monte (LLDP o IP ARP). Porta shut/no-shut se flapping."},
                {"order": 5, "title": "On-site se nulla funziona", "description": "Se device continua offline >30min e critical → dispatch tecnico on-site."},
            ],
        },
    ]
