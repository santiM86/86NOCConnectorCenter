# 86NocConnector

Collector per dispositivi di rete. Raccoglie SNMP Traps e Syslog e li inoltra al NOC Center cloud.

```
[Switch/Firewall/ILO] --SNMP/Syslog--> [86NocConnector] --HTTPS--> [NOC Center]
```

## Installazione rapida

1. Copia la cartella `noc-connector` sul server Windows
2. Doppio click su `setup.bat` (scarica Python embedded, una volta sola)
3. Doppio click su `install.bat` (apre il wizard di installazione)
4. Inserisci URL del NOC Center e API Key
5. Fine. L'icona appare nella system tray vicino all'orologio.

## Struttura file

```
noc-connector/
  setup.bat              Prima esecuzione: scarica Python embedded + dipendenze
  install.bat            Avvia wizard installazione
  uninstall.bat          Disinstalla tutto
  86NocConnector.bat     Avvia manualmente l'icona tray
  src/
    connector.py         Motore (SNMP + Syslog collector)
    tray_app.py          Icona system tray
    installer_gui.py     Wizard installazione GUI
  python/                Python embedded (creato da setup.bat)
```

## Dopo l'installazione

- Icona nella system tray (vicino all'orologio)
- Tasto destro sull'icona: Stato, Avvia, Ferma, Riavvia, Log, Configurazione
- Si avvia automaticamente con Windows
- Configurazione: `C:\ProgramData\86NocConnector\config.json`
- Log: `C:\ProgramData\86NocConnector\logs\connector.log`

## Configurazione HPE 5130 JG941A

Accedi allo switch via console/SSH. Sostituisci `IP_SERVER` con l'IP del server dove gira 86NocConnector:

```
system-view

snmp-agent
snmp-agent community read public
snmp-agent community write private
snmp-agent sys-info version v2c
snmp-agent target-host trap address udp-domain IP_SERVER params securityname public v2c
snmp-agent trap enable standard
snmp-agent trap enable interface-mib
snmp-agent trap enable configuration
snmp-agent trap enable system

info-center loghost IP_SERVER facility local7
info-center source default loghost level notification

save force
```

## Configurazione altri dispositivi

### Firewall generico
- SNMP Trap destination: IP_SERVER porta 162
- Syslog server: IP_SERVER porta 514

### HPE iLO
- Administration > Management > SNMP Settings
- Aggiungi Trap Destination: IP_SERVER
- Alert Destinations: seleziona tutti gli alert

### Backup Server (Veeam, etc.)
- Syslog forwarding verso IP_SERVER:514

## Troubleshooting

### Firewall Windows
```cmd
netsh advfirewall firewall add rule name="86NocConnector SNMP" dir=in action=allow protocol=UDP localport=162
netsh advfirewall firewall add rule name="86NocConnector Syslog" dir=in action=allow protocol=UDP localport=514
```

### Verifica porte in ascolto
```cmd
netstat -an | findstr "162 514"
```

### Permesso negato?
Esegui come Amministratore (tasto destro > Esegui come amministratore).

## Disinstallazione
Doppio click su `uninstall.bat` oppure:
```cmd
sc stop 86NocConnector
sc delete 86NocConnector
```
