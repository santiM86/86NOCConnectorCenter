# -*- coding: utf-8 -*-
"""
86NocConnector - System Tray Application
Icona nella barra delle applicazioni vicino all'orologio
"""

import sys
import os
import time
import threading
import webbrowser
import json

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connector import ConnectorEngine, load_config, get_config_path, get_log_path, APP_NAME, VERSION

# ==================== ICON GENERATION ====================

def create_icon_image(status="running"):
    """Create the tray icon programmatically."""
    from PIL import Image, ImageDraw, ImageFont
    
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Background circle
    if status == "running":
        bg_color = (34, 197, 94)      # Green
        accent = (22, 163, 74)
    elif status == "error":
        bg_color = (239, 68, 68)      # Red
        accent = (185, 28, 28)
    else:
        bg_color = (107, 114, 128)    # Gray
        accent = (75, 85, 99)
    
    # Draw rounded square background
    draw.rounded_rectangle([2, 2, size-2, size-2], radius=12, fill=bg_color)
    
    # Draw "86" text
    try:
        font_large = ImageFont.truetype("arial.ttf", 18)
        font_small = ImageFont.truetype("arial.ttf", 11)
    except:
        try:
            font_large = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 18)
            font_small = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 11)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
    
    # "86" on top
    draw.text((14, 6), "86", fill="white", font=font_large)
    # "NOC" on bottom
    draw.text((14, 32), "NOC", fill=(255, 255, 255, 200), font=font_small)
    
    # Status dot in bottom-right
    dot_color = (255, 255, 255) if status == "running" else (255, 200, 200)
    draw.ellipse([size-16, size-16, size-4, size-4], fill=dot_color)
    
    return img

# ==================== TRAY APPLICATION ====================

def run_tray():
    """Main tray application."""
    import pystray
    from PIL import Image
    
    engine = ConnectorEngine()
    engine_started = False
    icon_ref = [None]
    
    def start_engine():
        nonlocal engine_started
        if not engine_started:
            config = load_config()
            if config:
                engine.config = config
                engine.start()
                engine_started = True
                update_icon("running")
            else:
                update_icon("stopped")
    
    def stop_engine():
        nonlocal engine_started
        if engine_started:
            engine.stop()
            engine_started = False
            update_icon("stopped")
    
    def update_icon(status):
        if icon_ref[0]:
            icon_ref[0].icon = create_icon_image(status)
            icon_ref[0].title = get_tooltip()
    
    def get_tooltip():
        if engine_started:
            s = engine.get_status()
            return (
                f"{APP_NAME} v{VERSION}\n"
                f"Stato: Attivo ({s['uptime']})\n"
                f"SNMP: {s['snmp_received']} ricevuti, {s['snmp_sent']} inviati\n"
                f"Syslog: {s['syslog_received']} ricevuti, {s['syslog_sent']} inviati\n"
                f"Errori: {s['errors']}"
            )
        return f"{APP_NAME} v{VERSION}\nStato: Fermo"
    
    def on_open_dashboard(icon, item):
        config = load_config()
        if config and config.get("noc_center_url"):
            webbrowser.open(config["noc_center_url"])
    
    def on_open_local(icon, item):
        config = load_config()
        port = config.get("web_port", 9090) if config else 9090
        webbrowser.open(f"http://localhost:{port}")
    
    def on_view_logs(icon, item):
        log_path = get_log_path()
        if os.path.exists(log_path):
            os.startfile(log_path)
    
    def on_open_config(icon, item):
        config_path = get_config_path()
        if os.path.exists(config_path):
            os.startfile(config_path)
    
    def on_start(icon, item):
        start_engine()
        icon.notify(f"{APP_NAME} avviato", APP_NAME)
    
    def on_stop(icon, item):
        stop_engine()
        icon.notify(f"{APP_NAME} fermato", APP_NAME)
    
    def on_restart(icon, item):
        stop_engine()
        time.sleep(1)
        start_engine()
        icon.notify(f"{APP_NAME} riavviato", APP_NAME)
    
    def on_status(icon, item):
        if engine_started:
            s = engine.get_status()
            msg = (
                f"Stato: Attivo\n"
                f"Uptime: {s['uptime']}\n"
                f"SNMP ricevuti: {s['snmp_received']}\n"
                f"SNMP inviati: {s['snmp_sent']}\n"
                f"Syslog ricevuti: {s['syslog_received']}\n"
                f"Syslog inviati: {s['syslog_sent']}\n"
                f"Errori: {s['errors']}\n"
                f"In coda: {s['queue']}"
            )
            if s['last_error']:
                msg += f"\nUltimo errore: {s['last_error'][:50]}"
        else:
            msg = "Stato: Fermo\nClicca 'Avvia' per iniziare"
        icon.notify(msg, f"{APP_NAME} - Stato")
    
    def on_exit(icon, item):
        stop_engine()
        icon.stop()
    
    def is_running(item):
        return engine_started
    
    def is_stopped(item):
        return not engine_started
    
    # Auto-refresh tooltip
    def tooltip_updater():
        while True:
            time.sleep(10)
            if icon_ref[0] and engine_started:
                icon_ref[0].title = get_tooltip()
                # Update icon color on errors
                s = engine.get_status()
                if s["errors"] > 0 and s["last_error"]:
                    pass  # Keep green, errors might be transient
    
    tooltip_thread = threading.Thread(target=tooltip_updater, daemon=True)
    tooltip_thread.start()
    
    # Build menu
    menu = pystray.Menu(
        pystray.MenuItem(
            f"{APP_NAME} v{VERSION}",
            None,
            enabled=False
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Stato", on_status),
        pystray.MenuItem("Apri NOC Center", on_open_dashboard),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Avvia", on_start, visible=is_stopped),
        pystray.MenuItem("Ferma", on_stop, visible=is_running),
        pystray.MenuItem("Riavvia", on_restart, visible=is_running),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Visualizza Log", on_view_logs),
        pystray.MenuItem("Modifica Configurazione", on_open_config),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Esci", on_exit),
    )
    
    icon = pystray.Icon(
        APP_NAME,
        create_icon_image("stopped"),
        f"{APP_NAME} - Avvio...",
        menu
    )
    icon_ref[0] = icon
    
    # Auto-start engine
    def auto_start():
        time.sleep(1)
        config = load_config()
        if config and config.get("noc_center_url") and config.get("api_key"):
            start_engine()
            icon.notify(f"{APP_NAME} avviato e in ascolto", APP_NAME)
        else:
            icon.notify("Configurazione mancante. Esegui install.bat", APP_NAME)
    
    start_thread = threading.Thread(target=auto_start, daemon=True)
    start_thread.start()
    
    icon.run()


if __name__ == "__main__":
    run_tray()
