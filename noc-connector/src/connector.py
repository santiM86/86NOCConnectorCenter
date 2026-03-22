# -*- coding: utf-8 -*-
"""
86NocConnector - Motore Collector SNMP Traps + Syslog
Raccoglie dati da dispositivi di rete e li inoltra al NOC Center
"""

import socket
import threading
import time
import json
import sys
import os
import logging
from datetime import datetime, timezone
from collections import deque

import requests

VERSION = "1.0.0"
APP_NAME = "86NocConnector"

# ==================== CONFIGURAZIONE ====================

def get_config_dir():
    appdata = os.environ.get("PROGRAMDATA", os.environ.get("APPDATA", os.path.dirname(os.path.abspath(__file__))))
    config_dir = os.path.join(appdata, APP_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return config_dir

def get_config_path():
    return os.path.join(get_config_dir(), "config.json")

def get_log_path():
    log_dir = os.path.join(get_config_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "connector.log")

DEFAULT_CONFIG = {
    "noc_center_url": "",
    "api_key": "",
    "snmp_trap_port": 162,
    "syslog_port": 514,
    "web_port": 9090,
    "heartbeat_interval_seconds": 60,
    "batch_interval_seconds": 3,
}

def load_config():
    path = get_config_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        for key, val in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = val
        return config
    return None

def save_config(config):
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

# ==================== LOGGING ====================

def setup_logging():
    log_path = get_log_path()
    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8", maxBytes=0)
    ]
    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers)
    return logging.getLogger(APP_NAME)

# ==================== SNMP TRAP PARSER ====================

KNOWN_TRAPS = {
    "1.3.6.1.6.3.1.1.5.1": ("coldStart", "Dispositivo riavviato (cold start)", "critical"),
    "1.3.6.1.6.3.1.1.5.2": ("warmStart", "Dispositivo riavviato (warm start)", "high"),
    "1.3.6.1.6.3.1.1.5.3": ("linkDown", "Interfaccia di rete DOWN", "critical"),
    "1.3.6.1.6.3.1.1.5.4": ("linkUp", "Interfaccia di rete UP", "low"),
    "1.3.6.1.6.3.1.1.5.5": ("authenticationFailure", "Tentativo accesso non autorizzato", "high"),
    "1.3.6.1.4.1.11.2.14.11.1.7": ("hpSwitchAuth", "HPE: autenticazione fallita", "high"),
    "1.3.6.1.4.1.11.2.14.11.5.1.7": ("hpPortSecurity", "HPE: violazione sicurezza porta", "critical"),
    "1.3.6.1.4.1.25506.2": ("hpeH3C", "HPE/H3C: evento dispositivo", "medium"),
    "1.3.6.1.4.1.232": ("cpqHealth", "HPE iLO: evento salute server", "high"),
    "1.3.6.1.4.1.232.0": ("cpqTrap", "HPE iLO: trap generico", "medium"),
}

def decode_oid(oid_bytes):
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

def extract_oids(data):
    oids = []
    i = 0
    while i < len(data) - 2:
        if data[i] == 0x06:
            oid_len = data[i+1]
            if 0 < oid_len and i + 2 + oid_len <= len(data):
                try:
                    oid = decode_oid(data[i+2:i+2+oid_len])
                    if oid:
                        oids.append(oid)
                except:
                    pass
                i += 2 + oid_len
                continue
        i += 1
    return oids

def parse_snmp_trap(data, addr):
    try:
        device_ip = addr[0]
        oids = extract_oids(data)
        oid_str = " | ".join(oids)
        
        for known_oid, (name, desc, sev) in KNOWN_TRAPS.items():
            if any(known_oid in o for o in oids):
                return {
                    "device_ip": device_ip,
                    "oid": known_oid,
                    "value": desc,
                    "trap_type": name,
                }
        
        return {
            "device_ip": device_ip,
            "oid": oids[0] if oids else f"raw_{data.hex()[:40]}",
            "value": f"Trap da {device_ip}: {oid_str[:100]}",
            "trap_type": "generic",
        }
    except Exception as e:
        return {
            "device_ip": addr[0],
            "oid": "parse_error",
            "value": str(e),
            "trap_type": "error",
        }

# ==================== SYSLOG PARSER ====================

SYSLOG_SEVERITY = {
    0: "emergency", 1: "alert", 2: "critical", 3: "error",
    4: "warning", 5: "notice", 6: "info", 7: "debug"
}

def parse_syslog(data, addr):
    try:
        msg = data.decode("utf-8", errors="replace").strip()
        device_ip = addr[0]
        facility = 1
        severity_level = 5
        message = msg
        
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
            "severity_name": SYSLOG_SEVERITY.get(severity_level, f"level{severity_level}"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except:
        return {
            "device_ip": addr[0],
            "facility": 1,
            "severity_level": 5,
            "message": data.decode("utf-8", errors="replace")[:1000],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# ==================== API SENDER ====================

class APISender:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.base_url = config["noc_center_url"].rstrip("/")
        self.headers = {"X-API-Key": config["api_key"], "Content-Type": "application/json"}
        self.snmp_queue = deque(maxlen=10000)
        self.syslog_queue = deque(maxlen=10000)
        self.stats = {"snmp_sent": 0, "syslog_sent": 0, "errors": 0, "last_error": ""}
        self.running = True
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def queue_snmp(self, trap):
        self.snmp_queue.append(trap)
    
    def queue_syslog(self, syslog):
        self.syslog_queue.append(syslog)
    
    def sender_loop(self):
        interval = self.config.get("batch_interval_seconds", 3)
        while self.running:
            try:
                while self.snmp_queue:
                    trap = self.snmp_queue.popleft()
                    self._send_snmp(trap)
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
            r = self.session.post(f"{self.base_url}/api/ingest/snmp", json={
                "device_ip": trap["device_ip"], "oid": trap["oid"],
                "value": trap["value"], "trap_type": trap["trap_type"]
            }, timeout=15)
            if r.status_code == 200:
                self.stats["snmp_sent"] += 1
                self.logger.info(f"SNMP -> NOC: {trap['trap_type']} da {trap['device_ip']}")
            else:
                self.stats["errors"] += 1
                self.stats["last_error"] = f"HTTP {r.status_code}"
        except Exception as e:
            self.stats["errors"] += 1
            self.stats["last_error"] = str(e)
            self.snmp_queue.appendleft(trap)
    
    def _send_syslog(self, syslog):
        try:
            r = self.session.post(f"{self.base_url}/api/ingest/syslog", json={
                "device_ip": syslog["device_ip"], "facility": syslog["facility"],
                "severity_level": syslog["severity_level"], "message": syslog["message"],
                "timestamp": syslog.get("timestamp")
            }, timeout=15)
            if r.status_code == 200:
                self.stats["syslog_sent"] += 1
                self.logger.info(f"Syslog -> NOC: [{syslog.get('severity_name','?')}] {syslog['device_ip']}")
            else:
                self.stats["errors"] += 1
                self.stats["last_error"] = f"HTTP {r.status_code}"
        except Exception as e:
            self.stats["errors"] += 1
            self.stats["last_error"] = str(e)
            self.syslog_queue.appendleft(syslog)
    
    def send_heartbeat(self, traps_received, syslogs_received, uptime):
        try:
            self.session.post(f"{self.base_url}/api/connector/heartbeat", json={
                "connector_version": VERSION, "hostname": socket.gethostname(),
                "uptime_seconds": int(uptime),
                "traps_received": traps_received, "syslogs_received": syslogs_received
            }, timeout=10)
        except:
            pass
    
    def stop(self):
        self.running = False

# ==================== LISTENERS ====================

class SNMPListener:
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
        except (PermissionError, OSError) as e:
            self.logger.error(f"Porta SNMP {self.port}: {e}. Serve Amministratore.")
            return
        self.sock.settimeout(2.0)
        self.logger.info(f"SNMP listener attivo su porta UDP {self.port}")
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                self.traps_received += 1
                trap = parse_snmp_trap(data, addr)
                if trap:
                    self.logger.info(f"[SNMP] {trap['trap_type']} da {trap['device_ip']}")
                    self.api_sender.queue_snmp(trap)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"Errore SNMP: {e}")
    
    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()

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
        except (PermissionError, OSError) as e:
            self.logger.error(f"Porta Syslog {self.port}: {e}. Serve Amministratore.")
            return
        self.sock.settimeout(2.0)
        self.logger.info(f"Syslog listener attivo su porta UDP {self.port}")
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                self.syslogs_received += 1
                syslog = parse_syslog(data, addr)
                if syslog:
                    self.logger.info(f"[Syslog] [{syslog.get('severity_name','?')}] {syslog['device_ip']}: {syslog['message'][:60]}")
                    self.api_sender.queue_syslog(syslog)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"Errore Syslog: {e}")
    
    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()

# ==================== CONNECTOR ENGINE ====================

class ConnectorEngine:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.logger = setup_logging()
        self.start_time = time.time()
        self.running = False
        self.api_sender = None
        self.snmp_listener = None
        self.syslog_listener = None
        self._threads = []
    
    def start(self):
        if not self.config:
            self.logger.error("Nessuna configurazione trovata")
            return False
        
        self.running = True
        self.api_sender = APISender(self.config, self.logger)
        self.snmp_listener = SNMPListener(self.config["snmp_trap_port"], self.api_sender, self.logger)
        self.syslog_listener = SyslogListener(self.config["syslog_port"], self.api_sender, self.logger)
        
        self.logger.info("=" * 50)
        self.logger.info(f"  {APP_NAME} v{VERSION}")
        self.logger.info(f"  NOC: {self.config['noc_center_url']}")
        self.logger.info(f"  SNMP: UDP/{self.config['snmp_trap_port']}  Syslog: UDP/{self.config['syslog_port']}")
        self.logger.info("=" * 50)
        
        for target, name in [
            (self.snmp_listener.start, "snmp"),
            (self.syslog_listener.start, "syslog"),
            (self.api_sender.sender_loop, "sender"),
            (self._heartbeat_loop, "heartbeat"),
        ]:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        
        return True
    
    def _heartbeat_loop(self):
        interval = self.config.get("heartbeat_interval_seconds", 60)
        while self.running:
            if self.api_sender:
                self.api_sender.send_heartbeat(
                    self.snmp_listener.traps_received if self.snmp_listener else 0,
                    self.syslog_listener.syslogs_received if self.syslog_listener else 0,
                    time.time() - self.start_time
                )
            time.sleep(interval)
    
    def stop(self):
        self.running = False
        if self.snmp_listener: self.snmp_listener.stop()
        if self.syslog_listener: self.syslog_listener.stop()
        if self.api_sender: self.api_sender.stop()
        self.logger.info(f"{APP_NAME} fermato.")
    
    def get_status(self):
        uptime = time.time() - self.start_time
        return {
            "running": self.running,
            "version": VERSION,
            "uptime": f"{int(uptime//3600)}h {int((uptime%3600)//60)}m",
            "uptime_seconds": int(uptime),
            "snmp_received": self.snmp_listener.traps_received if self.snmp_listener else 0,
            "syslog_received": self.syslog_listener.syslogs_received if self.syslog_listener else 0,
            "snmp_sent": self.api_sender.stats["snmp_sent"] if self.api_sender else 0,
            "syslog_sent": self.api_sender.stats["syslog_sent"] if self.api_sender else 0,
            "errors": self.api_sender.stats["errors"] if self.api_sender else 0,
            "last_error": self.api_sender.stats["last_error"] if self.api_sender else "",
            "queue": (len(self.api_sender.snmp_queue) + len(self.api_sender.syslog_queue)) if self.api_sender else 0,
            "noc_url": self.config.get("noc_center_url", ""),
        }

if __name__ == "__main__":
    import signal
    engine = ConnectorEngine()
    if engine.start():
        signal.signal(signal.SIGINT, lambda s, f: engine.stop())
        signal.signal(signal.SIGTERM, lambda s, f: engine.stop())
        try:
            while engine.running:
                time.sleep(1)
        except KeyboardInterrupt:
            engine.stop()
