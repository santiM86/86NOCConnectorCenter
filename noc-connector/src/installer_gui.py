# -*- coding: utf-8 -*-
"""
86NocConnector - Installer GUI Wizard
Wizard di installazione con interfaccia grafica
"""

import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys
import json
import subprocess
import threading
import socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from connector import APP_NAME, VERSION, DEFAULT_CONFIG, save_config, get_config_dir, get_config_path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_EXE = os.path.join(BASE_DIR, "python", "python.exe")
TRAY_SCRIPT = os.path.join(BASE_DIR, "src", "tray_app.py")


class InstallerWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Installazione {APP_NAME}")
        self.root.geometry("640x480")
        self.root.resizable(False, False)
        self.root.configure(bg="#f0f0f0")
        
        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 320
        y = (self.root.winfo_screenheight() // 2) - 240
        self.root.geometry(f"640x480+{x}+{y}")
        
        # Try to set icon
        try:
            self.root.iconbitmap(default="")
        except:
            pass
        
        self.current_page = 0
        self.config = dict(DEFAULT_CONFIG)
        
        # Variables
        self.var_url = tk.StringVar()
        self.var_api_key = tk.StringVar()
        self.var_snmp_port = tk.StringVar(value="162")
        self.var_syslog_port = tk.StringVar(value="514")
        self.var_autostart = tk.BooleanVar(value=True)
        
        # Main container
        self.main_frame = tk.Frame(self.root, bg="#f0f0f0")
        self.main_frame.pack(fill="both", expand=True)
        
        # Left panel (branding)
        self.left_panel = tk.Frame(self.main_frame, bg="#0a0a0f", width=200)
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)
        
        # Logo area
        logo_frame = tk.Frame(self.left_panel, bg="#0a0a0f")
        logo_frame.pack(expand=True)
        
        tk.Label(logo_frame, text="86", font=("Arial", 48, "bold"), fg="white", bg="#0a0a0f").pack()
        tk.Label(logo_frame, text="BIT", font=("Arial", 32, "bold"), fg="white", bg="#0a0a0f").pack()
        
        tk.Label(self.left_panel, text="86NocConnector", font=("Arial", 11, "bold"), 
                fg="#6366f1", bg="#0a0a0f").pack(side="bottom", pady=20)
        
        # Right panel (content)
        self.right_panel = tk.Frame(self.main_frame, bg="#f0f0f0")
        self.right_panel.pack(side="right", fill="both", expand=True)
        
        # Content area
        self.content_frame = tk.Frame(self.right_panel, bg="#f0f0f0")
        self.content_frame.pack(fill="both", expand=True, padx=24, pady=16)
        
        # Button bar
        self.button_bar = tk.Frame(self.right_panel, bg="#e0e0e0", height=50)
        self.button_bar.pack(fill="x", side="bottom")
        self.button_bar.pack_propagate(False)
        
        btn_style = {"font": ("Arial", 9), "padx": 16, "pady": 4, "cursor": "hand2"}
        
        self.btn_cancel = tk.Button(self.button_bar, text="Annulla", command=self.on_cancel, 
                                    bg="#ffffff", fg="#333333", relief="solid", bd=1, **btn_style)
        self.btn_cancel.pack(side="right", padx=8, pady=10)
        
        self.btn_next = tk.Button(self.button_bar, text="Avanti >", command=self.on_next,
                                  bg="#6366f1", fg="white", relief="flat", **btn_style)
        self.btn_next.pack(side="right", padx=4, pady=10)
        
        self.btn_back = tk.Button(self.button_bar, text="< Indietro", command=self.on_back,
                                  bg="#ffffff", fg="#333333", relief="solid", bd=1, state="disabled", **btn_style)
        self.btn_back.pack(side="right", padx=4, pady=10)
        
        self.show_page(0)
    
    def clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def show_page(self, page):
        self.current_page = page
        self.clear_content()
        
        self.btn_back.config(state="normal" if page > 0 else "disabled")
        
        if page == 0:
            self.page_welcome()
        elif page == 1:
            self.page_config()
        elif page == 2:
            self.page_install()
        elif page == 3:
            self.page_complete()
    
    # ==================== PAGE 0: WELCOME ====================
    
    def page_welcome(self):
        self.btn_next.config(text="Avanti >", state="normal")
        
        tk.Label(self.content_frame, text=f"Installazione di {APP_NAME}",
                font=("Arial", 16, "bold"), fg="#111111", bg="#f0f0f0",
                anchor="w").pack(fill="x", pady=(0, 16))
        
        tk.Label(self.content_frame, 
                text="Questa procedura guidata installera' 86NocConnector\nsul tuo computer.",
                font=("Arial", 10), fg="#444444", bg="#f0f0f0",
                anchor="w", justify="left").pack(fill="x", pady=(0, 12))
        
        tk.Label(self.content_frame, 
                text="86NocConnector raccoglie SNMP Traps e messaggi Syslog\n"
                     "dai dispositivi di rete (switch, firewall, server ILO)\n"
                     "e li inoltra al NOC Center cloud in tempo reale.",
                font=("Arial", 10), fg="#444444", bg="#f0f0f0",
                anchor="w", justify="left").pack(fill="x", pady=(0, 16))
        
        info_frame = tk.Frame(self.content_frame, bg="#e8eaf6", relief="solid", bd=1)
        info_frame.pack(fill="x", pady=(0, 12))
        tk.Label(info_frame, text="Cosa verra' installato:", font=("Arial", 9, "bold"),
                fg="#333333", bg="#e8eaf6", anchor="w").pack(fill="x", padx=12, pady=(8, 4))
        for item in ["Servizio SNMP Trap listener (porta UDP 162)",
                      "Servizio Syslog listener (porta UDP 514)", 
                      "Icona nella system tray per monitoraggio",
                      "Regole firewall Windows per le porte",
                      "Avvio automatico con Windows"]:
            tk.Label(info_frame, text=f"  \u2022  {item}", font=("Arial", 9),
                    fg="#555555", bg="#e8eaf6", anchor="w").pack(fill="x", padx=12)
        tk.Label(info_frame, text="", bg="#e8eaf6").pack(pady=2)
        
        tk.Label(self.content_frame, text="Clicca su 'Avanti' per continuare.",
                font=("Arial", 10), fg="#666666", bg="#f0f0f0",
                anchor="w").pack(fill="x", side="bottom")
    
    # ==================== PAGE 1: CONFIGURATION ====================
    
    def page_config(self):
        self.btn_next.config(text="Installa >", state="normal")
        
        tk.Label(self.content_frame, text="Configurazione",
                font=("Arial", 16, "bold"), fg="#111111", bg="#f0f0f0",
                anchor="w").pack(fill="x", pady=(0, 4))
        
        tk.Label(self.content_frame, text="Inserisci i dati di connessione al NOC Center.",
                font=("Arial", 10), fg="#444444", bg="#f0f0f0",
                anchor="w").pack(fill="x", pady=(0, 16))
        
        # URL
        tk.Label(self.content_frame, text="URL NOC Center *", font=("Arial", 9, "bold"),
                fg="#333333", bg="#f0f0f0", anchor="w").pack(fill="x")
        url_entry = tk.Entry(self.content_frame, textvariable=self.var_url, font=("Consolas", 10),
                            relief="solid", bd=1)
        url_entry.pack(fill="x", pady=(2, 8), ipady=4)
        url_entry.insert(0, "" if not self.var_url.get() else "")
        tk.Label(self.content_frame, text="Es: https://noc.azienda.it",
                font=("Arial", 8), fg="#999999", bg="#f0f0f0", anchor="w").pack(fill="x", pady=(0, 8))
        
        # API Key
        tk.Label(self.content_frame, text="API Key del Cliente *", font=("Arial", 9, "bold"),
                fg="#333333", bg="#f0f0f0", anchor="w").pack(fill="x")
        tk.Entry(self.content_frame, textvariable=self.var_api_key, font=("Consolas", 10),
                relief="solid", bd=1).pack(fill="x", pady=(2, 8), ipady=4)
        tk.Label(self.content_frame, text="Copiala dalla pagina Clienti del NOC Center",
                font=("Arial", 8), fg="#999999", bg="#f0f0f0", anchor="w").pack(fill="x", pady=(0, 12))
        
        # Ports
        ports_frame = tk.Frame(self.content_frame, bg="#f0f0f0")
        ports_frame.pack(fill="x", pady=(0, 8))
        
        tk.Label(ports_frame, text="Porta SNMP", font=("Arial", 9), fg="#333333", bg="#f0f0f0").pack(side="left")
        tk.Entry(ports_frame, textvariable=self.var_snmp_port, font=("Consolas", 10), width=6,
                relief="solid", bd=1).pack(side="left", padx=(4, 16), ipady=2)
        tk.Label(ports_frame, text="Porta Syslog", font=("Arial", 9), fg="#333333", bg="#f0f0f0").pack(side="left")
        tk.Entry(ports_frame, textvariable=self.var_syslog_port, font=("Consolas", 10), width=6,
                relief="solid", bd=1).pack(side="left", padx=(4, 0), ipady=2)
        
        # Autostart
        tk.Checkbutton(self.content_frame, text="Avvia automaticamente con Windows",
                       variable=self.var_autostart, font=("Arial", 9), fg="#333333", bg="#f0f0f0",
                       activebackground="#f0f0f0", selectcolor="#e0e0e0").pack(fill="x", pady=(8, 0), anchor="w")
        
        # Test button
        tk.Button(self.content_frame, text="Test Connessione", command=self.test_connection,
                 font=("Arial", 9), bg="#ffffff", fg="#6366f1", relief="solid", bd=1,
                 padx=12, pady=2, cursor="hand2").pack(anchor="w", pady=(12, 0))
    
    def test_connection(self):
        url = self.var_url.get().strip().rstrip("/")
        api_key = self.var_api_key.get().strip()
        
        if not url or not api_key:
            messagebox.showwarning("Attenzione", "Inserisci URL e API Key")
            return
        
        try:
            import requests
            # Test health
            r = requests.get(f"{url}/api/health", timeout=10)
            if r.status_code != 200:
                messagebox.showerror("Errore", f"NOC Center non raggiungibile: HTTP {r.status_code}")
                return
            
            # Test API key
            r = requests.post(f"{url}/api/connector/heartbeat",
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={"connector_version": VERSION, "hostname": socket.gethostname(),
                      "uptime_seconds": 0, "traps_received": 0, "syslogs_received": 0},
                timeout=10)
            if r.status_code == 200:
                messagebox.showinfo("Successo", "Connessione al NOC Center riuscita!\nAPI Key valida.")
            elif r.status_code == 401:
                messagebox.showerror("Errore", "API Key non valida. Controlla la chiave.")
            else:
                messagebox.showwarning("Attenzione", f"Risposta: HTTP {r.status_code}\n{r.text[:100]}")
        except Exception as e:
            messagebox.showerror("Errore", f"Connessione fallita:\n{str(e)[:200]}")
    
    # ==================== PAGE 2: INSTALLING ====================
    
    def page_install(self):
        url = self.var_url.get().strip().rstrip("/")
        api_key = self.var_api_key.get().strip()
        
        if not url or not api_key:
            messagebox.showwarning("Attenzione", "URL e API Key sono obbligatori")
            self.show_page(1)
            return
        
        self.btn_next.config(text="Avanti >", state="disabled")
        self.btn_back.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        
        tk.Label(self.content_frame, text="Installazione in corso...",
                font=("Arial", 16, "bold"), fg="#111111", bg="#f0f0f0",
                anchor="w").pack(fill="x", pady=(0, 16))
        
        self.progress = ttk.Progressbar(self.content_frame, length=380, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 12))
        
        self.status_text = tk.Text(self.content_frame, height=12, font=("Consolas", 9),
                                   bg="#1a1a2e", fg="#22c55e", relief="flat", bd=0,
                                   padx=10, pady=8)
        self.status_text.pack(fill="both", expand=True)
        self.status_text.config(state="disabled")
        
        # Run installation in thread
        threading.Thread(target=self.run_installation, daemon=True).start()
    
    def log_status(self, msg):
        self.status_text.config(state="normal")
        self.status_text.insert("end", f"> {msg}\n")
        self.status_text.see("end")
        self.status_text.config(state="disabled")
        self.root.update()
    
    def run_installation(self):
        try:
            total_steps = 5
            step = 0
            
            # Step 1: Save config
            step += 1
            self.progress["value"] = (step / total_steps) * 100
            self.log_status("Salvataggio configurazione...")
            self.config["noc_center_url"] = self.var_url.get().strip().rstrip("/")
            self.config["api_key"] = self.var_api_key.get().strip()
            self.config["snmp_trap_port"] = int(self.var_snmp_port.get())
            self.config["syslog_port"] = int(self.var_syslog_port.get())
            save_config(self.config)
            config_dir = get_config_dir()
            self.log_status(f"  Configurazione salvata in: {config_dir}")
            time.sleep(0.5)
            
            # Step 2: Firewall rules
            step += 1
            self.progress["value"] = (step / total_steps) * 100
            self.log_status("Configurazione firewall Windows...")
            snmp_port = self.config["snmp_trap_port"]
            syslog_port = self.config["syslog_port"]
            try:
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", 
                              "name=86NocConnector SNMP"], capture_output=True)
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", 
                              "name=86NocConnector Syslog"], capture_output=True)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                              "name=86NocConnector SNMP", "dir=in", "action=allow",
                              "protocol=UDP", f"localport={snmp_port}"], capture_output=True)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                              "name=86NocConnector Syslog", "dir=in", "action=allow",
                              "protocol=UDP", f"localport={syslog_port}"], capture_output=True)
                self.log_status(f"  Regola firewall: UDP {snmp_port} (SNMP) - OK")
                self.log_status(f"  Regola firewall: UDP {syslog_port} (Syslog) - OK")
            except Exception as e:
                self.log_status(f"  Firewall: {e} (potrebbe servire Amministratore)")
            time.sleep(0.5)
            
            # Step 3: Autostart
            step += 1
            self.progress["value"] = (step / total_steps) * 100
            if self.var_autostart.get():
                self.log_status("Configurazione avvio automatico...")
                try:
                    bat_path = os.path.join(BASE_DIR, "86NocConnector.bat")
                    subprocess.run(["reg", "add", 
                                  r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                                  "/v", APP_NAME, "/t", "REG_SZ", "/d", bat_path, "/f"],
                                  capture_output=True)
                    self.log_status(f"  Avvio automatico: Registrato")
                except Exception as e:
                    self.log_status(f"  Avvio automatico: {e}")
            time.sleep(0.5)
            
            # Step 4: Test connection
            step += 1
            self.progress["value"] = (step / total_steps) * 100
            self.log_status("Test connessione al NOC Center...")
            try:
                import requests
                r = requests.get(f"{self.config['noc_center_url']}/api/health", timeout=10)
                if r.status_code == 200:
                    self.log_status("  Connessione: OK")
                else:
                    self.log_status(f"  Connessione: HTTP {r.status_code}")
            except Exception as e:
                self.log_status(f"  Connessione: {e}")
            time.sleep(0.5)
            
            # Step 5: Start tray app
            step += 1
            self.progress["value"] = (step / total_steps) * 100
            self.log_status("Avvio 86NocConnector...")
            try:
                if os.path.exists(PYTHON_EXE):
                    subprocess.Popen([PYTHON_EXE, TRAY_SCRIPT], 
                                   creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0x08000000)
                else:
                    subprocess.Popen([sys.executable, TRAY_SCRIPT],
                                   creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0x08000000)
                self.log_status("  86NocConnector avviato nella system tray!")
            except Exception as e:
                self.log_status(f"  Avvio: {e}")
            
            self.progress["value"] = 100
            self.log_status("")
            self.log_status("Installazione completata con successo!")
            
        except Exception as e:
            self.log_status(f"\nERRORE: {e}")
        
        self.root.after(0, lambda: self.btn_next.config(state="normal"))
        self.root.after(0, lambda: self.btn_cancel.config(state="normal"))
    
    # ==================== PAGE 3: COMPLETE ====================
    
    def page_complete(self):
        self.btn_next.config(text="Fine", state="normal")
        self.btn_back.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        
        tk.Label(self.content_frame, text="Installazione Completata!",
                font=("Arial", 16, "bold"), fg="#16a34a", bg="#f0f0f0",
                anchor="w").pack(fill="x", pady=(0, 16))
        
        tk.Label(self.content_frame, 
                text=f"{APP_NAME} e' stato installato e avviato con successo.",
                font=("Arial", 10), fg="#444444", bg="#f0f0f0",
                anchor="w").pack(fill="x", pady=(0, 12))
        
        # Status info
        info_frame = tk.Frame(self.content_frame, bg="#e8f5e9", relief="solid", bd=1)
        info_frame.pack(fill="x", pady=(0, 16))
        
        config_dir = get_config_dir()
        items = [
            f"Configurazione: {config_dir}",
            f"SNMP Trap porta: UDP {self.var_snmp_port.get()}",
            f"Syslog porta: UDP {self.var_syslog_port.get()}",
            f"NOC Center: {self.var_url.get().strip()[:50]}",
            "Icona nella system tray: Attiva",
        ]
        if self.var_autostart.get():
            items.append("Avvio automatico: Abilitato")
        
        for item in items:
            tk.Label(info_frame, text=f"  \u2713  {item}", font=("Arial", 9),
                    fg="#2e7d32", bg="#e8f5e9", anchor="w").pack(fill="x", padx=12, pady=1)
        tk.Label(info_frame, text="", bg="#e8f5e9").pack(pady=2)
        
        tk.Label(self.content_frame, 
                text="Ora configura i dispositivi di rete per inviare\n"
                     "SNMP Traps e Syslog all'indirizzo IP di questo server.",
                font=("Arial", 10), fg="#444444", bg="#f0f0f0",
                anchor="w", justify="left").pack(fill="x", pady=(0, 8))
        
        tk.Label(self.content_frame,
                text="Trovi l'icona di 86NocConnector vicino all'orologio\n"
                     "nella barra delle applicazioni (system tray).\n"
                     "Cliccaci sopra con il tasto destro per le opzioni.",
                font=("Arial", 10, "bold"), fg="#6366f1", bg="#f0f0f0",
                anchor="w", justify="left").pack(fill="x")
    
    # ==================== NAVIGATION ====================
    
    def on_next(self):
        if self.current_page == 3:
            self.root.destroy()
            return
        self.show_page(self.current_page + 1)
    
    def on_back(self):
        if self.current_page > 0:
            self.show_page(self.current_page - 1)
    
    def on_cancel(self):
        if messagebox.askyesno("Annulla", "Vuoi annullare l'installazione?"):
            self.root.destroy()
    
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    wizard = InstallerWizard()
    wizard.run()
