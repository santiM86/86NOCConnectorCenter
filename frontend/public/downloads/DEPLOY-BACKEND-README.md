# ARGUS Center — Procedura aggiornamento backend Linux di produzione

Questo documento descrive la procedura completa per aggiornare il backend ARGUS
sul tuo server Linux di produzione, **una sola volta**, con rollback automatico
se qualcosa va storto.

> ⚠️ Lo script preserva il file `.env` (con `MONGO_URL`, secret JWT, ecc.) e
> la cartella `data/` (chiavi WireGuard server, file persistenti). Niente di
> tuo viene perso.

## Step 1 — Connettiti al server di produzione

```bash
ssh root@argus.86bit.it
```

## Step 2 — Scarica lo script di deploy

```bash
cd /tmp
curl -fL https://argus.86bit.it/downloads/deploy-backend-linux.sh -o deploy-backend-linux.sh
chmod +x deploy-backend-linux.sh
```

## Step 3 — Lancialo passandogli l'URL del nuovo backend

```bash
sudo bash deploy-backend-linux.sh https://argus.86bit.it/downloads/argus-backend-latest.tar.gz
```

Lo script:

1. **Auto-rileva** dove si trova il backend (default `/opt/argus/backend`, sovrascrivibile via `ARGUS_BACKEND_DIR=...`)
2. **Auto-rileva** se usi systemd o supervisor (sovrascrivibile via `ARGUS_SERVICE_MANAGER=...`)
3. **Auto-rileva** il virtualenv Python (sovrascrivibile via `ARGUS_VENV_DIR=...`)
4. **Mostra il riepilogo** e ti chiede conferma esplicita prima di procedere
5. Crea un **backup completo** in `/opt/argus/backups/backend-<timestamp>/`
6. Stop backend → sostituzione atomica file → preserva `.env` + `data/` → `pip install` → start backend
7. **Health check** post-deploy con retry 30 secondi
8. **Rollback automatico** se la nuova versione non risponde

## Override dei path di default

Se il tuo backend non è in `/opt/argus/backend`, oppure il service ha nomi diversi:

```bash
sudo \
  ARGUS_BACKEND_DIR=/percorso/al/tuo/backend \
  ARGUS_VENV_DIR=/percorso/al/venv \
  ARGUS_SYSTEMD_UNIT=mio-argus-backend \
  bash deploy-backend-linux.sh https://argus.86bit.it/downloads/argus-backend-latest.tar.gz
```

## Cosa fare DOPO il deploy

### Per attivare il server WireGuard EMBEDDED

1. Apri il file `/opt/argus/backend/.env` (sostituisci con il tuo path reale)
2. Aggiungi in fondo queste righe:
   ```
   WG_EMBEDDED_ENABLED=true
   WG_SERVER_HOST=argus.86bit.it
   ```
3. Apri la porta UDP 51820 sul firewall (`ufw allow 51820/udp` o `firewall-cmd`)
4. Riavvia il backend:
   - systemd:    `sudo systemctl restart argus-backend`
   - supervisor: `sudo supervisorctl restart backend`
5. Apri il Center → Impostazioni → WireGuard
6. Nel banner "Server WireGuard Embedded" dovresti vedere lo stato verde "RUNTIME ATTIVO"

### Verifica

```bash
# Stato del processo wireguard-go embedded:
ps -ef | grep wireguard-go

# Logs runtime:
tail -f /var/log/argus-wireguard.log

# Endpoint diagnostico (richiede admin JWT):
curl https://argus.86bit.it/api/admin/wireguard/embedded/status \
     -H "Authorization: Bearer <TUO_JWT>"
```

## Rollback manuale (se necessario)

Se vuoi tornare alla versione precedente per qualsiasi motivo:

```bash
sudo systemctl stop argus-backend     # o supervisorctl stop backend
sudo rm -rf /opt/argus/backend
sudo mv /opt/argus/backups/backend-<TIMESTAMP> /opt/argus/backend
sudo systemctl start argus-backend    # o supervisorctl start backend
```

## Pulizia backup vecchi

Lo script lascia backup dello vecchio backend per ogni deploy. Per pulire quelli più vecchi di 30 giorni:

```bash
sudo find /opt/argus/backups -maxdepth 1 -name 'backend-*' -mtime +30 -exec rm -rf {} \;
```
