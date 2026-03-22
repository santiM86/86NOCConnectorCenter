# 86NocConnector

Collector per dispositivi di rete. Raccoglie SNMP Traps e Syslog e li inoltra al NOC Center.
100% PowerShell nativo - nessuna installazione di software aggiuntivo.

```
[Switch/Firewall/ILO] --SNMP/Syslog--> [86NocConnector] --HTTPS--> [NOC Center]
```

## Requisiti
- Windows 10/11 o Windows Server 2016+ (PowerShell 5.1 gia' incluso)
- Nient'altro. Zero installazioni.

## Installazione

1. Copia la cartella sul server
2. Doppio click su **install.bat** (tasto destro > Esegui come amministratore)
3. Segui il wizard: inserisci URL e API Key
4. L'icona appare nella system tray vicino all'orologio

## File

```
86NocConnector/
  install.bat          Doppio click per installare
  uninstall.bat        Doppio click per disinstallare
  86NocConnector.bat   Avvia manualmente l'icona tray
  src/
    connector.ps1      Motore SNMP + Syslog
    tray_app.ps1       Icona system tray
    installer_gui.ps1  Wizard installazione
```

## Configurazione HPE 5130 JG941A

Sostituisci IP_SERVER con l'IP del server dove gira 86NocConnector:

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

## Disinstallazione
Doppio click su **uninstall.bat** (come amministratore)
