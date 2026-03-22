# ============================================================
#  NOC Connector - Collector per dispositivi di rete
#  Raccoglie SNMP Traps e Syslog e li inoltra al NOC Center
# ============================================================
#
#  Utilizzo:
#    python noc_connector.py
#
#  Oppure come servizio Windows:
#    python noc_connector.py --install
#    python noc_connector.py --start
#    python noc_connector.py --stop
#    python noc_connector.py --remove
#
# ============================================================

import socket
import struct
import threading
import time
import json
import sys
import os
import signal
import logging
import argparse
from datetime import datetime, timezone
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import requests
except ImportError:
    print("Installazione dipendenze...")
    os.system(f"{sys.executable} -m pip install requests")
    import requests

# ==================== CONFIGURAZIONE ====================

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DEFAULT_CONFIG = {
    "noc_center_url": "",
    "api_key": "",
    "snmp_trap_port": 162,
    "syslog_port": 514,
    "web_port": 9090,
    "heartbeat_interval_seconds": 60,
    "batch_size": 10,
    "batch_interval_seconds": 5,
    "log_level": "INFO",
    "log_file": "noc_connector.log"
}

VERSION = "1.0.0"

# ==================== LOGGING ====================

def setup_logging(config):
    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    log_level = getattr(logging, config.get("log_level", "INFO").upper(), logging.INFO)
    
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = config.get("log_file", "noc_connector.log")
    if log_file:
        log_dir = os.path.dirname(os.path.abspath(log_file))
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    
    logging.basicConfig(level=log_level, format=log_format, handlers=handlers)
    return logging.getLogger("noc-connector")

# ==================== CONFIGURAZIONE LOADER ====================

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        # Merge with defaults
        for key, val in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = val
        return config
    return None

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def setup_wizard():
    print("\n" + "="*60)
    print("  NOC Connector - Configurazione iniziale")
    print("="*60 + "\n")
    
    config = dict(DEFAULT_CONFIG)
    
    config["noc_center_url"] = input("URL del NOC Center (es. https://device-guardian-28.preview.emergentagent.com): ").strip().rstrip("/")
    config["api_key"] = input("API Key del cliente (dalla pagina Clienti del NOC Center): ").strip()
    
    snmp_port = input(f"Porta SNMP Traps [{config['snmp_trap_port']}]: ").strip()
    if snmp_port:
        config["snmp_trap_port"] = int(snmp_port)
    
    syslog_port = input(f"Porta Syslog [{config['syslog_port']}]: ").strip()
    if syslog_port:
        config["syslog_port"] = int(syslog_port)
    
    web_port = input(f"Porta dashboard web locale [{config['web_port']}]: ").strip()
    if web_port:
        config["web_port"] = int(web_port)
    
    # Test connection
    print("\nTest connessione al NOC Center...")
    try:
        r = requests.get(f"{config['noc_center_url']}/api/health", timeout=10)
        if r.status_code == 200:
            print("  Connessione OK!")
        else:
            print(f"  Attenzione: risposta {r.status_code}")
    except Exception as e:
        print(f"  Errore di connessione: {e}")
        print("  Puoi modificare l'URL in config.json dopo")
    
    # Test API key
    print("Test API key...")
    try:
        r = requests.post(
            f"{config['noc_center_url']}/api/connector/heartbeat",
            headers={"X-API-Key": config["api_key"], "Content-Type": "application/json"},
            json={"connector_version": VERSION, "hostname": socket.gethostname(), "uptime_seconds": 0, "traps_received": 0, "syslogs_received": 0},
            timeout=10
        )
        if r.status_code == 200:
            print("  API Key valida!")
        else:
            print(f"  Attenzione: risposta {r.status_code} - {r.text}")
    except Exception as e:
        print(f"  Errore: {e}")
    
    save_config(config)
    print(f"\nConfigurazione salvata in {CONFIG_FILE}")
    print("Avvia il connector con: python noc_connector.py\n")
    return config

# ==================== SNMP TRAP PARSER ====================

class SNMPTrapParser:
    """Parsa trap SNMP v1/v2c ricevuti via UDP."""
    
    # OID noti per HPE / switch comuni
    KNOWN_TRAPS = {
        "1.3.6.1.6.3.1.1.5.1": ("coldStart", "Il dispositivo si e' riavviato", "critical"),
        "1.3.6.1.6.3.1.1.5.2": ("warmStart", "Il dispositivo si e' riavviato a caldo", "high"),
        "1.3.6.1.6.3.1.1.5.3": ("linkDown", "Interfaccia di rete giu'", "critical"),
        "1.3.6.1.6.3.1.1.5.4": ("linkUp", "Interfaccia di rete su", "low"),
        "1.3.6.1.6.3.1.1.5.5": ("authenticationFailure", "Tentativo di accesso non autorizzato", "high"),
        "1.3.6.1.4.1.11.2.14.11.1.7": ("hpSwitchAuth", "HPE Switch: autenticazione fallita", "high"),
        "1.3.6.1.4.1.11.2.14.11.5.1.7": ("hpPortSecurity", "HPE Switch: violazione sicurezza porta", "critical"),
        "1.3.6.1.4.1.25506.2": ("hpeH3C", "HPE/H3C: evento dispositivo", "medium"),
        "1.3.6.1.4.1.232": ("cpqHealth", "HPE iLO: evento salute server", "high"),
        "1.3.6.1.4.1.232.0": ("cpqTrap", "HPE iLO: trap generico", "medium"),
    }
    
    @staticmethod
    def parse_udp_packet(data, addr):
        """Parse raw SNMP trap packet. Returns dict or None."""
        try:
            device_ip = addr[0]
            hex_data = data.hex()
            
            # Try to extract OIDs from raw packet
            oid = ""
            value = ""
            trap_type = "generic"
            
            # Simple BER/ASN.1 OID extraction
            oid_str = SNMPTrapParser._extract_oids_from_raw(data)
            
            # Match known traps
            for known_oid, (name, desc, sev) in SNMPTrapParser.KNOWN_TRAPS.items():
                if known_oid in oid_str:
                    oid = known_oid
                    trap_type = name
                    value = desc
                    break
            
            if not oid:
                oid = oid_str[:80] if oid_str else f"raw_trap_{hex_data[:40]}"
                trap_type = "generic"
                value = f"Raw trap from {device_ip}"
            
            return {
                "device_ip": device_ip,
                "oid": oid,
                "value": value,
                "trap_type": trap_type,
                "raw_hex": hex_data[:200]
            }
        except Exception as e:
            logging.getLogger("noc-connector").warning(f"Errore parsing SNMP: {e}")
            return {
                "device_ip": addr[0],
                "oid": "parse_error",
                "value": str(e),
                "trap_type": "error",
                "raw_hex": data.hex()[:200]
            }
    
    @staticmethod
    def _extract_oids_from_raw(data):
        """Extract OID strings from raw ASN.1/BER encoded data."""
        oids = []
        i = 0
        while i < len(data) - 2:
            # OID tag is 0x06
            if data[i] == 0x06:
                oid_len = data[i+1]
                if oid_len > 0 and i + 2 + oid_len <= len(data):
                    oid_bytes = data[i+2:i+2+oid_len]
                    try:
                        oid = SNMPTrapParser._decode_oid(oid_bytes)
                        if oid:
                            oids.append(oid)
                    except:
                        pass
                    i += 2 + oid_len
                    continue
            i += 1
        return " | ".join(oids)
    
    @staticmethod
    def _decode_oid(oid_bytes):
        """Decode BER-encoded OID bytes to dotted string."""
        if not oid_bytes:
            return ""
        components = [str(oid_bytes[0] // 40), str(oid_bytes[0] % 40)]
        val = 0
        for byte in oid_bytes[1:]:
            if byte & 0x80:
                val = (val << 7) | (byte & 0x7F)
            else:
                val = (val << 7) | byte
                components.append(str(val))
                val = 0
        return ".".join(components)


# ==================== SYSLOG PARSER ====================

class SyslogParser:
    """Parsa messaggi syslog RFC 3164/5424."""
    
    FACILITY_NAMES = {
        0: "kern", 1: "user", 2: "mail", 3: "daemon", 4: "auth", 5: "syslog",
        6: "lpr", 7: "news", 8: "uucp", 9: "cron", 10: "authpriv", 11: "ftp",
        16: "local0", 17: "local1", 18: "local2", 19: "local3",
        20: "local4", 21: "local5", 22: "local6", 23: "local7"
    }
    
    SEVERITY_NAMES = {
        0: "emergency", 1: "alert", 2: "critical", 3: "error",
        4: "warning", 5: "notice", 6: "info", 7: "debug"
    }
    
    @staticmethod
    def parse(data, addr):
        """Parse syslog message. Returns dict."""
        try:
            msg = data.decode("utf-8", errors="replace").strip()
            device_ip = addr[0]
            facility = 1
            severity_level = 5
            message = msg
            
            # Parse PRI field: <N>
            if msg.startswith("<"):
                end = msg.index(">")
                pri = int(msg[1:end])
                facility = pri >> 3
                severity_level = pri & 0x07
                message = msg[end+1:].strip()
            
            return {
                "device_ip": device_ip,
                "facility": facility,
                "severity_level": severity_level,
                "message": message[:1000],
                "facility_name": SyslogParser.FACILITY_NAMES.get(facility, f"facility{facility}"),
                "severity_name": SyslogParser.SEVERITY_NAMES.get(severity_level, f"level{severity_level}"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "device_ip": addr[0],
                "facility": 1,
                "severity_level": 5,
                "message": data.decode("utf-8", errors="replace")[:1000],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }


# ==================== API SENDER ====================

class APISender:
    """Invia dati al NOC Center via HTTPS con retry e batching."""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.base_url = config["noc_center_url"].rstrip("/")
        self.api_key = config["api_key"]
        self.headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        self.snmp_queue = deque(maxlen=10000)
        self.syslog_queue = deque(maxlen=10000)
        self.stats = {"snmp_sent": 0, "syslog_sent": 0, "errors": 0, "last_error": ""}
        self.running = True
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def queue_snmp(self, trap_data):
        self.snmp_queue.append(trap_data)
    
    def queue_syslog(self, syslog_data):
        self.syslog_queue.append(syslog_data)
    
    def sender_loop(self):
        """Background loop that sends queued data to the API."""
        interval = self.config.get("batch_interval_seconds", 5)
        while self.running:
            try:
                # Send SNMP traps
                while self.snmp_queue:
                    trap = self.snmp_queue.popleft()
                    self._send_snmp(trap)
                
                # Send Syslog messages
                while self.syslog_queue:
                    syslog = self.syslog_queue.popleft()
                    self._send_syslog(syslog)
                    
            except Exception as e:
                self.stats["errors"] += 1
                self.stats["last_error"] = str(e)
                self.logger.error(f"Errore invio: {e}")
            
            time.sleep(interval)
    
    def _send_snmp(self, trap):
        try:
            payload = {
                "device_ip": trap["device_ip"],
                "oid": trap["oid"],
                "value": trap["value"],
                "trap_type": trap["trap_type"]
            }
            r = self.session.post(f"{self.base_url}/api/ingest/snmp", json=payload, timeout=15)
            if r.status_code == 200:
                self.stats["snmp_sent"] += 1
                self.logger.info(f"SNMP -> NOC: {trap['trap_type']} da {trap['device_ip']}")
            else:
                self.stats["errors"] += 1
                self.stats["last_error"] = f"HTTP {r.status_code}: {r.text[:100]}"
                self.logger.warning(f"Errore SNMP API: {r.status_code} {r.text[:100]}")
        except Exception as e:
            self.stats["errors"] += 1
            self.stats["last_error"] = str(e)
            self.snmp_queue.appendleft(trap)  # Re-queue
            self.logger.error(f"Errore connessione SNMP: {e}")
    
    def _send_syslog(self, syslog):
        try:
            payload = {
                "device_ip": syslog["device_ip"],
                "facility": syslog["facility"],
                "severity_level": syslog["severity_level"],
                "message": syslog["message"],
                "timestamp": syslog.get("timestamp")
            }
            r = self.session.post(f"{self.base_url}/api/ingest/syslog", json=payload, timeout=15)
            if r.status_code == 200:
                self.stats["syslog_sent"] += 1
                self.logger.info(f"Syslog -> NOC: [{syslog.get('severity_name','?')}] da {syslog['device_ip']}")
            else:
                self.stats["errors"] += 1
                self.stats["last_error"] = f"HTTP {r.status_code}: {r.text[:100]}"
                self.logger.warning(f"Errore Syslog API: {r.status_code} {r.text[:100]}")
        except Exception as e:
            self.stats["errors"] += 1
            self.stats["last_error"] = str(e)
            self.syslog_queue.appendleft(syslog)
            self.logger.error(f"Errore connessione Syslog: {e}")
    
    def send_heartbeat(self, traps_received, syslogs_received, uptime):
        try:
            payload = {
                "connector_version": VERSION,
                "hostname": socket.gethostname(),
                "uptime_seconds": int(uptime),
                "traps_received": traps_received,
                "syslogs_received": syslogs_received
            }
            r = self.session.post(f"{self.base_url}/api/connector/heartbeat", json=payload, timeout=10)
            if r.status_code == 200:
                self.logger.debug("Heartbeat inviato")
            else:
                self.logger.warning(f"Heartbeat errore: {r.status_code}")
        except Exception as e:
            self.logger.warning(f"Heartbeat fallito: {e}")
    
    def stop(self):
        self.running = False


# ==================== SNMP TRAP LISTENER ====================

class SNMPTrapListener:
    def __init__(self, port, api_sender, logger):
        self.port = port
        self.api_sender = api_sender
        self.logger = logger
        self.running = True
        self.traps_received = 0
        self.sock = None
    
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind(("0.0.0.0", self.port))
        except PermissionError:
            self.logger.error(f"Permesso negato per porta {self.port}. Esegui come Administrator/root.")
            self.logger.info(f"Su Windows: esegui il prompt dei comandi come Amministratore")
            return
        except OSError as e:
            self.logger.error(f"Errore binding porta {self.port}: {e}")
            return
        
        self.sock.settimeout(2.0)
        self.logger.info(f"SNMP Trap listener avviato su porta UDP {self.port}")
        
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                self.traps_received += 1
                trap = SNMPTrapParser.parse_udp_packet(data, addr)
                if trap:
                    self.logger.info(f"[SNMP] {trap['trap_type']} da {trap['device_ip']}")
                    self.api_sender.queue_snmp(trap)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"Errore SNMP listener: {e}")
    
    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()


# ==================== SYSLOG LISTENER ====================

class SyslogListener:
    def __init__(self, port, api_sender, logger):
        self.port = port
        self.api_sender = api_sender
        self.logger = logger
        self.running = True
        self.syslogs_received = 0
        self.sock = None
    
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind(("0.0.0.0", self.port))
        except PermissionError:
            self.logger.error(f"Permesso negato per porta {self.port}. Esegui come Administrator/root.")
            return
        except OSError as e:
            self.logger.error(f"Errore binding porta {self.port}: {e}")
            return
        
        self.sock.settimeout(2.0)
        self.logger.info(f"Syslog listener avviato su porta UDP {self.port}")
        
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                self.syslogs_received += 1
                syslog = SyslogParser.parse(data, addr)
                if syslog:
                    self.logger.info(f"[Syslog] [{syslog.get('severity_name','?')}] {syslog['device_ip']}: {syslog['message'][:80]}")
                    self.api_sender.queue_syslog(syslog)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"Errore Syslog listener: {e}")
    
    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()


# ==================== WEB DASHBOARD ====================

class DashboardHandler(BaseHTTPRequestHandler):
    """Mini dashboard web locale per monitorare il connector."""
    
    connector = None  # Set by NOCConnector
    
    def log_message(self, format, *args):
        pass  # Suppress HTTP logs
    
    def do_GET(self):
        if self.path == "/api/status":
            self._json_response(self._get_status())
        elif self.path == "/":
            self._html_response(self._dashboard_html())
        else:
            self.send_error(404)
    
    def _get_status(self):
        c = DashboardHandler.connector
        if not c:
            return {"error": "Connector not ready"}
        uptime = time.time() - c.start_time
        return {
            "version": VERSION,
            "hostname": socket.gethostname(),
            "uptime_seconds": int(uptime),
            "uptime_human": f"{int(uptime//3600)}h {int((uptime%3600)//60)}m",
            "snmp_traps_received": c.snmp_listener.traps_received if c.snmp_listener else 0,
            "syslog_received": c.syslog_listener.syslogs_received if c.syslog_listener else 0,
            "snmp_sent_to_noc": c.api_sender.stats["snmp_sent"],
            "syslog_sent_to_noc": c.api_sender.stats["syslog_sent"],
            "errors": c.api_sender.stats["errors"],
            "last_error": c.api_sender.stats["last_error"],
            "snmp_queue": len(c.api_sender.snmp_queue),
            "syslog_queue": len(c.api_sender.syslog_queue),
            "noc_center_url": c.config["noc_center_url"],
            "snmp_port": c.config["snmp_trap_port"],
            "syslog_port": c.config["syslog_port"]
        }
    
    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def _html_response(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    
    def _dashboard_html(self):
        return """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NOC Connector</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a0f;color:#eef0ff;min-height:100vh;padding:2rem}
.header{display:flex;align-items:center;gap:12px;margin-bottom:2rem}
.header h1{font-size:1.25rem;font-weight:700;letter-spacing:-0.02em}
.badge{background:rgba(34,197,94,0.12);color:#22c55e;border:1px solid rgba(34,197,94,0.25);padding:2px 10px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:1.5rem}
.card{background:#10101a;border:1px solid #1e1e3a;border-radius:8px;padding:16px}
.card .label{font-size:10px;text-transform:uppercase;letter-spacing:0.06em;color:#5b5f78;margin-bottom:4px}
.card .value{font-size:1.5rem;font-weight:700}
.card .sub{font-size:11px;color:#5b5f78;margin-top:2px}
.critical{color:#ef4444} .high{color:#f59e0b} .medium{color:#3b82f6} .ok{color:#22c55e}
.info-panel{background:#10101a;border:1px solid #1e1e3a;border-radius:8px;padding:16px;margin-bottom:1rem}
.info-row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1e1e3a;font-size:13px}
.info-row:last-child{border:0}
.info-row .k{color:#5b5f78} .info-row .v{color:#eef0ff;font-family:'Cascadia Code','Consolas',monospace}
.err{color:#ef4444;font-size:12px;background:rgba(239,68,68,0.08);padding:8px 12px;border-radius:6px;border:1px solid rgba(239,68,68,0.2);margin-top:8px;word-break:break-all}
</style>
</head><body>
<div class="header">
  <h1>NOC Connector</h1>
  <span class="badge" id="status-badge">Avvio...</span>
</div>
<div class="grid" id="stats"></div>
<div class="info-panel" id="info"></div>
<div id="error-box"></div>
<script>
function update(){
  fetch('/api/status').then(r=>r.json()).then(d=>{
    document.getElementById('status-badge').textContent='Attivo - '+d.uptime_human;
    document.getElementById('stats').innerHTML=`
      <div class="card"><div class="label">SNMP Traps Ricevuti</div><div class="value medium">${d.snmp_traps_received}</div></div>
      <div class="card"><div class="label">Syslog Ricevuti</div><div class="value medium">${d.syslog_received}</div></div>
      <div class="card"><div class="label">Inviati al NOC</div><div class="value ok">${d.snmp_sent_to_noc+d.syslog_sent_to_noc}</div><div class="sub">${d.snmp_sent_to_noc} SNMP + ${d.syslog_sent_to_noc} Syslog</div></div>
      <div class="card"><div class="label">Errori</div><div class="value ${d.errors>0?'critical':'ok'}">${d.errors}</div></div>
      <div class="card"><div class="label">In Coda</div><div class="value ${(d.snmp_queue+d.syslog_queue)>50?'high':'ok'}">${d.snmp_queue+d.syslog_queue}</div></div>
    `;
    document.getElementById('info').innerHTML=`
      <div class="info-row"><span class="k">NOC Center</span><span class="v">${d.noc_center_url}</span></div>
      <div class="info-row"><span class="k">Hostname</span><span class="v">${d.hostname}</span></div>
      <div class="info-row"><span class="k">Versione</span><span class="v">${d.version}</span></div>
      <div class="info-row"><span class="k">Porta SNMP</span><span class="v">UDP ${d.snmp_port}</span></div>
      <div class="info-row"><span class="k">Porta Syslog</span><span class="v">UDP ${d.syslog_port}</span></div>
    `;
    document.getElementById('error-box').innerHTML=d.last_error?`<div class="err">Ultimo errore: ${d.last_error}</div>`:'';
  }).catch(e=>{document.getElementById('status-badge').textContent='Errore';});
}
update(); setInterval(update,3000);
</script>
</body></html>"""


# ==================== MAIN CONNECTOR ====================

class NOCConnector:
    def __init__(self, config):
        self.config = config
        self.logger = setup_logging(config)
        self.start_time = time.time()
        self.running = True
        
        self.api_sender = APISender(config, self.logger)
        self.snmp_listener = SNMPTrapListener(config["snmp_trap_port"], self.api_sender, self.logger)
        self.syslog_listener = SyslogListener(config["syslog_port"], self.api_sender, self.logger)
        
        DashboardHandler.connector = self
    
    def start(self):
        self.logger.info("="*50)
        self.logger.info(f"  NOC Connector v{VERSION}")
        self.logger.info(f"  NOC Center: {self.config['noc_center_url']}")
        self.logger.info(f"  SNMP Trap porta: {self.config['snmp_trap_port']}")
        self.logger.info(f"  Syslog porta: {self.config['syslog_port']}")
        self.logger.info(f"  Dashboard: http://localhost:{self.config['web_port']}")
        self.logger.info("="*50)
        
        # Start threads
        threads = []
        
        t1 = threading.Thread(target=self.snmp_listener.start, name="snmp-listener", daemon=True)
        t1.start()
        threads.append(t1)
        
        t2 = threading.Thread(target=self.syslog_listener.start, name="syslog-listener", daemon=True)
        t2.start()
        threads.append(t2)
        
        t3 = threading.Thread(target=self.api_sender.sender_loop, name="api-sender", daemon=True)
        t3.start()
        threads.append(t3)
        
        t4 = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        t4.start()
        threads.append(t4)
        
        # Start web dashboard
        try:
            server = HTTPServer(("0.0.0.0", self.config["web_port"]), DashboardHandler)
            t5 = threading.Thread(target=server.serve_forever, name="web-dashboard", daemon=True)
            t5.start()
            threads.append(t5)
            self.logger.info(f"Dashboard web: http://localhost:{self.config['web_port']}")
        except Exception as e:
            self.logger.warning(f"Dashboard web non avviata: {e}")
        
        # Handle shutdown
        def signal_handler(sig, frame):
            self.logger.info("\nChiusura in corso...")
            self.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.logger.info("NOC Connector avviato. Premi Ctrl+C per fermare.")
        
        # Keep alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def _heartbeat_loop(self):
        interval = self.config.get("heartbeat_interval_seconds", 60)
        while self.running:
            self.api_sender.send_heartbeat(
                self.snmp_listener.traps_received,
                self.syslog_listener.syslogs_received,
                time.time() - self.start_time
            )
            time.sleep(interval)
    
    def stop(self):
        self.running = False
        self.snmp_listener.stop()
        self.syslog_listener.stop()
        self.api_sender.stop()
        self.logger.info("NOC Connector fermato.")


# ==================== WINDOWS SERVICE ====================

def install_windows_service():
    """Installa come servizio Windows usando NSSM o sc.exe."""
    script_path = os.path.abspath(__file__)
    python_path = sys.executable
    
    print(f"\nPer installare come servizio Windows, usa uno di questi metodi:\n")
    print(f"Metodo 1 - NSSM (consigliato, scarica da nssm.cc):")
    print(f'  nssm install NOCConnector "{python_path}" "{script_path}"')
    print(f'  nssm set NOCConnector AppDirectory "{os.path.dirname(script_path)}"')
    print(f'  nssm start NOCConnector')
    print(f"\nMetodo 2 - Task Scheduler:")
    print(f'  schtasks /create /tn "NOCConnector" /tr "{python_path} {script_path}" /sc onstart /ru SYSTEM')
    print(f"\nMetodo 3 - Avvio manuale:")
    print(f'  {python_path} {script_path}')


# ==================== ENTRY POINT ====================

def main():
    parser = argparse.ArgumentParser(description="NOC Connector - Collector per dispositivi di rete")
    parser.add_argument("--setup", action="store_true", help="Avvia configurazione guidata")
    parser.add_argument("--install", action="store_true", help="Mostra istruzioni installazione servizio Windows")
    parser.add_argument("--test", action="store_true", help="Invia un trap di test al NOC Center")
    args = parser.parse_args()
    
    if args.install:
        install_windows_service()
        return
    
    config = load_config()
    
    if args.setup or not config:
        config = setup_wizard()
        if not args.setup:
            # Continue to run after first setup
            pass
        else:
            return
    
    if args.test:
        logger = setup_logging(config)
        sender = APISender(config, logger)
        logger.info("Invio trap di test...")
        sender._send_snmp({
            "device_ip": "192.168.1.254",
            "oid": "1.3.6.1.6.3.1.1.5.3",
            "value": "Test linkDown trap from NOC Connector",
            "trap_type": "linkDown"
        })
        sender._send_syslog({
            "device_ip": "192.168.1.254",
            "facility": 4,
            "severity_level": 3,
            "message": "Test syslog message from NOC Connector",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Test completato. Sent: {sender.stats['snmp_sent']} SNMP, {sender.stats['syslog_sent']} Syslog, Errori: {sender.stats['errors']}")
        return
    
    connector = NOCConnector(config)
    connector.start()


if __name__ == "__main__":
    main()
