# Setup GitHub Auto-Deploy

Configurazione one-time per attivare l'auto-deploy del Center NOC ad
ogni push su branch `main`. Una volta fatto, non dovrai più collegarti
in SSH alla VM Linux: cliccando "Save to GitHub" da Emergent, la VM
`argus.86bit.it` si aggiorna sola in 30-60 secondi.

## 1) Genera il webhook secret

Su qualsiasi macchina con `openssl`:
```bash
openssl rand -hex 32
```
Esempio output: `b3f1d8e9c2a45f7e8d2b9c1f3e6a7d4c5b8e9f0a1c3d6e7f8a9b0c1d2e3f4a5b`

Conserva questo valore — ti servirà in 2 posti (backend + GitHub).

## 2) Configura il backend produzione

Modifica `/home/arslan/86NOCConnectorCenter/backend/.env`:
```
GITHUB_WEBHOOK_SECRET=<incolla-qui-il-secret-generato>
```

Opzionali (default sensati):
```
NOC_REPO_DIR=/home/arslan/86NOCConnectorCenter
NOC_DEPLOY_SCRIPT=/home/arslan/86NOCConnectorCenter/scripts/auto-deploy.sh
NOC_DEPLOY_BRANCH=main
NOC_DEPLOY_REFS=refs/heads/main
NOC_BACKEND_PIP=/home/arslan/86NOCConnectorCenter/backend/venv/bin/pip
```

## 3) Configura il sudoer (per restart noc-backend senza password)

`/etc/sudoers.d/noc-deploy` (crealo con `sudo visudo -f /etc/sudoers.d/noc-deploy`):
```
arslan ALL=(ALL) NOPASSWD: /bin/systemctl restart noc-backend.service
arslan ALL=(ALL) NOPASSWD: /bin/systemctl restart noc-frontend.service
```
**Sostituisci `arslan` con l'utente Unix sotto cui gira noc-backend.service.**
Verifica con: `systemctl show noc-backend.service -p User --value`.

## 4) Rendi lo script eseguibile

```bash
chmod +x /home/arslan/86NOCConnectorCenter/scripts/auto-deploy.sh
```

## 5) Restart noc-backend (1 sola volta, per caricare GITHUB_WEBHOOK_SECRET)

```bash
sudo systemctl restart noc-backend
```

## 6) Verifica la pre-flight check

```bash
curl https://argus.86bit.it/api/webhooks/github-deploy/health
```

Atteso:
```json
{
  "ok": true,
  "webhook_secret_configured": true,
  "repo_dir_exists": true,
  "deploy_script_exists": true,
  "deploy_script_executable": true,
  "git_available": true
}
```

Se `"ok": false`, leggi i campi: ti dice esattamente cosa manca.

## 7) Configura il webhook su GitHub

1. Vai su https://github.com/santiM86/86NOCConnectorCenter
2. Settings → Webhooks → **Add webhook**
3. Compila:
   - **Payload URL**: `https://argus.86bit.it/api/webhooks/github-deploy`
   - **Content type**: `application/json`
   - **Secret**: incolla il valore generato al punto 1
   - **SSL verification**: Enable SSL verification
   - **Which events**: Just the `push` event
   - ✅ Active
4. **Add webhook**

GitHub manderà subito un evento "ping" → se vedi il pallino verde
accanto al webhook, è tutto OK.

## 8) Test end-to-end

Fai una piccola modifica innocua su `main` (es. una riga di commento in
`README.md`), poi `git push origin main`. Sulla VM:
```bash
sudo journalctl -u noc-backend -f
```
Dovresti vedere:
```
auto-deploy success (exit=0, dur=12.3s)
```

E nel Center: il fix è live entro 30-60s **senza nessun SSH**.

## Trigger manuale (emergency)

Se il webhook fallisce o vuoi forzare un re-deploy senza push:
```bash
curl -X POST https://argus.86bit.it/api/webhooks/github-deploy/trigger \
  -H "Authorization: Bearer <JWT_ADMIN>"
```

## Audit storico

Tutti i deploy (success/skip/fail) vengono salvati in Mongo collection
`github_deploy_audit`. Leggibili via:
```bash
curl https://argus.86bit.it/api/webhooks/github-deploy/audit?limit=10 \
  -H "Authorization: Bearer <JWT_ADMIN>"
```

## Troubleshooting

- **HTTP 503 "GITHUB_WEBHOOK_SECRET non configurato"**: il valore non è
  nel `.env` del backend, oppure non hai fatto restart dopo aggiungerlo.
- **HTTP 401 "invalid HMAC signature"**: secret diverso tra backend e
  GitHub. Rigenera entrambi.
- **deploy `exit_code=4` "restart noc-backend failed"**: sudoer non
  configurato correttamente. Verifica con `sudo -l -U arslan`.
- **deploy `exit_code=1` "git fetch failed"**: la VM non ha access al
  repo. Verifica `git -C /home/arslan/86NOCConnectorCenter pull` manuale.
- **deploy `exit_code=3` "yarn build failed"**: leggi il log via audit
  endpoint per il dettaglio (es. moduli mancanti, eslint errors).
