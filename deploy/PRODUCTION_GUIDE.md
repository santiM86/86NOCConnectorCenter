# 86BIT NOC Center - Guida Deploy Produzione
# Configurazione ottimizzata per scalabilita' MSP

## Prerequisiti Server
- Ubuntu 22.04+ o Debian 12+
- Minimo: 2 vCPU, 4GB RAM, 50GB SSD (fino a ~30 clienti)
- Consigliato: 4 vCPU, 8GB RAM, 100GB SSD (fino a ~100 clienti)
- MongoDB 7.x
- Python 3.11+
- Node.js 20+

---

## 1. Configurazione Multi-Worker (Gunicorn + Uvicorn)

### File: /etc/systemd/system/noc-backend.service
```ini
[Unit]
Description=86BIT NOC Backend
After=network.target mongod.service
Requires=mongod.service

[Service]
Type=notify
User=noc
Group=noc
WorkingDirectory=/opt/noc/backend
Environment="PATH=/opt/noc/venv/bin"
EnvironmentFile=/opt/noc/backend/.env
ExecStart=/opt/noc/venv/bin/gunicorn server:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 4 \
    --bind 0.0.0.0:8001 \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --max-requests 5000 \
    --max-requests-jitter 500 \
    --access-logfile /var/log/noc/access.log \
    --error-logfile /var/log/noc/error.log \
    --log-level info
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### Spiegazione parametri:
- `--workers 4`: 4 processi paralleli (regola: 2 x CPU cores)
- `--max-requests 5000`: Riavvia worker dopo 5000 richieste (previene memory leak)
- `--max-requests-jitter 500`: Evita che tutti i worker si riavviino insieme
- `--timeout 120`: Timeout per richieste lunghe (AI, PDF, probe)
- `--keep-alive 5`: Mantiene connessioni HTTP aperte 5 secondi

---

## 2. MongoDB Ottimizzato

### File: /etc/mongod.conf
```yaml
storage:
  dbPath: /var/lib/mongodb
  journal:
    enabled: true
  wiredTiger:
    engineConfig:
      cacheSizeGB: 1.5  # 50% della RAM disponibile per MongoDB
    collectionConfig:
      blockCompressor: snappy  # Compressione veloce

systemLog:
  destination: file
  logAppend: true
  path: /var/log/mongodb/mongod.log

net:
  port: 27017
  bindIp: 127.0.0.1  # Solo locale!

security:
  authorization: enabled  # ABILITARE in produzione!

replication:
  replSetName: "noc-rs"  # Per replica set (Step 3)
```

### Creare utente MongoDB:
```bash
mongosh
> use noc_db
> db.createUser({
    user: "noc_app",
    pwd: "CAMBIA_QUESTA_PASSWORD",
    roles: [{ role: "readWrite", db: "noc_db" }]
  })
```

### Aggiornare .env:
```
MONGO_URL="mongodb://noc_app:PASSWORD@127.0.0.1:27017/noc_db?authSource=noc_db"
DB_NAME=noc_db
```

---

## 3. Backup Automatico MongoDB

### File: /opt/noc/scripts/backup_mongo.sh
```bash
#!/bin/bash
# Backup MongoDB giornaliero con rotazione 14 giorni

BACKUP_DIR="/opt/noc/backups"
DATE=$(date +%Y%m%d_%H%M)
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"

# Dump database
mongodump --db=noc_db --out="$BACKUP_DIR/dump_$DATE" --quiet

# Comprimi
tar -czf "$BACKUP_DIR/noc_backup_$DATE.tar.gz" -C "$BACKUP_DIR" "dump_$DATE"
rm -rf "$BACKUP_DIR/dump_$DATE"

# Ruota vecchi backup
find "$BACKUP_DIR" -name "noc_backup_*.tar.gz" -mtime +$RETENTION_DAYS -delete

echo "$(date): Backup completato -> noc_backup_$DATE.tar.gz" >> /var/log/noc/backup.log
```

### Crontab:
```bash
# Backup ogni giorno alle 3:00
0 3 * * * /opt/noc/scripts/backup_mongo.sh
```

---

## 4. Nginx Reverse Proxy

### File: /etc/nginx/sites-available/noc
```nginx
server {
    listen 443 ssl http2;
    server_name noc.86bit.it;

    ssl_certificate /etc/letsencrypt/live/noc.86bit.it/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/noc.86bit.it/privkey.pem;

    # Security headers (gia' presenti nel backend, ma doppio layer)
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Gzip (gia' nel backend, Nginx e' piu' efficiente)
    gzip on;
    gzip_vary on;
    gzip_min_length 256;
    gzip_types text/plain application/json application/javascript text/css;

    # Frontend (React build statica)
    location / {
        root /opt/noc/frontend/build;
        try_files $uri $uri/ /index.html;

        # Cache assets statici
        location ~* \.(js|css|png|jpg|jpeg|svg|woff2|ico)$ {
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
    }

    # Backend API
    location /api {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }

    # WebSocket
    location /ws {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}

# Redirect HTTP -> HTTPS
server {
    listen 80;
    server_name noc.86bit.it;
    return 301 https://$host$request_uri;
}
```

---

## 5. Frontend Build di Produzione

```bash
cd /opt/noc/frontend
# Impostare URL di produzione
echo "REACT_APP_BACKEND_URL=https://noc.86bit.it" > .env.production
# Build ottimizzata
yarn build
# Il risultato e' in /opt/noc/frontend/build (servito da Nginx)
```

---

## 6. Monitoraggio del Server NOC

### Crontab per health check:
```bash
# Check ogni 5 minuti che il NOC sia up
*/5 * * * * curl -sf http://localhost:8001/api/health > /dev/null || systemctl restart noc-backend
```

### Logrotate: /etc/logrotate.d/noc
```
/var/log/noc/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 noc noc
    sharedscripts
    postrotate
        systemctl reload noc-backend > /dev/null 2>&1 || true
    endscript
}
```

---

## 7. Checklist Go-Live

- [ ] Cambiare password admin (admin@86bit.it)
- [ ] Configurare GEMINI_API_KEY in .env
- [ ] Configurare JWT_SECRET (minimo 64 caratteri random)
- [ ] Configurare ENCRYPTION_KEY
- [ ] Abilitare auth MongoDB
- [ ] Configurare SSL con Let's Encrypt
- [ ] Testare backup MongoDB manuale
- [ ] Configurare firewall (solo 443 e 80 aperti)
- [ ] Installare 86NocConnector sul primo cliente
- [ ] Configurare WAN targets (IP pubblici firewall/router)
- [ ] Testare da telefono (PWA)
- [ ] Configurare TV Dashboard su monitor

---

## Sizing Guide

| Clienti | Dispositivi | Server Consigliato | Workers | MongoDB RAM |
|---------|------------|-------------------|---------|-------------|
| 1-10 | 1-200 | 2 vCPU, 4GB RAM | 2 | 1 GB |
| 10-30 | 200-1000 | 4 vCPU, 8GB RAM | 4 | 2 GB |
| 30-100 | 1000-5000 | 8 vCPU, 16GB RAM | 8 | 4 GB |
| 100+ | 5000+ | 16 vCPU, 32GB RAM + Redis | 16 | 8 GB |
