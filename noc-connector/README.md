# NOC Connector - Guida Installazione

## Cos'e'?
Il NOC Connector e' un agente leggero che si installa su un server nella rete locale dei clienti.
Raccoglie SNMP Traps e messaggi Syslog da tutti i dispositivi di rete e li inoltra al NOC Center cloud.

```
[Switch/Firewall/ILO] --SNMP/Syslog--> [NOC Connector] --HTTPS--> [NOC Center Cloud]
```

## Requisiti
- Windows 10/11 o Windows Server 2016+
- Python 3.8+ (scarica da python.org)
- Accesso come Amministratore (per le porte 162 e 514)

## Installazione

### 1. Copia i file
Copia la cartella `noc-connector` sul server Windows, ad esempio in:
```
C:\NOCConnector\
```

### 2. Installa Python (se non presente)
Scarica da https://www.python.org/downloads/ e installa con "Add to PATH" selezionato.

### 3. Installa dipendenze
```cmd
cd C:\NOCConnector
pip install -r requirements.txt
```

### 4. Configurazione iniziale
```cmd
python noc_connector.py --setup
```
Ti verra' chiesto:
- **URL del NOC Center**: `https://device-guardian-28.preview.emergentagent.com`
- **API Key**: la trovi nella pagina Clienti del NOC Center (copia l'API key del cliente)
- **Porte**: lascia i default (162 per SNMP, 514 per Syslog)

### 5. Test connessione
```cmd
python noc_connector.py --test
```
Inviera' un trap e un syslog di test. Verifica che appaia nel NOC Center.

### 6. Avvio
```cmd
python noc_connector.py
```
Il connector mostra i log a video e una dashboard web su http://localhost:9090

### 7. Installazione come servizio Windows (per avvio automatico)
```cmd
python noc_connector.py --install
```
Segui le istruzioni mostrate (consigliato usare NSSM).

## Configurazione HPE 5130 JG941A

### Accedi allo switch via console/SSH e inserisci questi comandi:

```
system-view

# Abilita SNMP
snmp-agent
snmp-agent community read public
snmp-agent community write private
snmp-agent sys-info version v2c

# Configura destinazione trap (sostituisci IP_SERVER con l'IP del server Windows)
snmp-agent target-host trap address udp-domain IP_SERVER params securityname public v2c

# Abilita trap per eventi importanti
snmp-agent trap enable standard
snmp-agent trap enable interface-mib
snmp-agent trap enable configuration
snmp-agent trap enable system

# Configura Syslog remoto (sostituisci IP_SERVER)
info-center loghost IP_SERVER facility local7

# Imposta livello log (0=emergency, 7=debug, consigliato 5=notification)
info-center source default loghost level notification

# Salva configurazione
save force
```

### Esempio con IP server 192.168.1.100:
```
system-view
snmp-agent
snmp-agent community read public
snmp-agent community write private
snmp-agent sys-info version v2c
snmp-agent target-host trap address udp-domain 192.168.1.100 params securityname public v2c
snmp-agent trap enable standard
snmp-agent trap enable interface-mib
snmp-agent trap enable configuration
snmp-agent trap enable system
info-center loghost 192.168.1.100 facility local7
info-center source default loghost level notification
save force
```

## Aggiungere altri dispositivi

Per collegare altri dispositivi, basta configurarli per inviare SNMP traps e/o Syslog
all'IP del server Windows dove gira il NOC Connector.

### Firewall (generico)
- SNMP Trap destination: IP_SERVER porta 162
- Syslog server: IP_SERVER porta 514

### Server HP iLO
- Accedi all'interfaccia web iLO
- Administration > Management > SNMP Settings
- Aggiungi Trap Destination: IP_SERVER
- Alert Destinations: seleziona tutti gli alert

### Backup Server (Veeam, etc.)
- Configura Syslog forwarding verso IP_SERVER:514

## Dashboard Web
Il connector espone una dashboard locale su http://localhost:9090
Mostra in tempo reale:
- Trap SNMP ricevuti e inviati
- Messaggi Syslog ricevuti e inviati
- Errori di connessione
- Stato della coda

## Troubleshooting

### Le porte 162/514 sono gia' in uso?
Modifica le porte in `config.json` e aggiorna la configurazione sullo switch.

### Il connector non riceve trap?
1. Verifica che il firewall Windows consenta UDP 162 e 514
2. Apri Prompt dei comandi come Amministratore:
   ```cmd
   netsh advfirewall firewall add rule name="NOC SNMP" dir=in action=allow protocol=UDP localport=162
   netsh advfirewall firewall add rule name="NOC Syslog" dir=in action=allow protocol=UDP localport=514
   ```

### Errore "Permesso negato"?
Esegui il prompt dei comandi come Amministratore (tasto destro > Esegui come amministratore).
