# Test Credentials — ARGUS Center

## Admin
- Email: `info@86bit.it`
- Password: `Ariel17051986@!@86`
- Role: `admin`

## ⚠️ 2FA OBBLIGATORIO PER ADMIN (dal 2026-08-07)
Gli utenti con ruolo `admin` che NON hanno il 2FA attivo ricevono al login un
token ristretto (`requires_2fa_setup: true`, nessun refresh_token) e DEVONO
configurare il 2FA (TOTP, compatibile Microsoft/Google Authenticator) prima di
accedere. Flusso per testing automatico (l'account admin è in stato "enroll
richiesto"):
1. `POST /api/auth/login` → `{token (enroll), requires_2fa_setup:true}`
2. `POST /api/auth/setup-2fa` con header Bearer enroll token, body `{}` (NIENTE
   password nel flusso enroll) → ritorna `{secret, qr_code, uri}`
3. Calcolare il codice: `pyotp.TOTP(secret).now()`
4. `POST /api/auth/confirm-2fa` `{code}` (Bearer enroll token) → ritorna
   `{token (pieno), refresh_token, user}` → ora si accede a tutto.
5. Login successivi: `requires_2fa:true` (nessun refresh) → `POST
   /api/auth/verify-2fa` `{code}` → ritorna token pieno + refresh_token.
Per riportare l'admin allo stato pulito "enroll richiesto": unset `totp_secret`
+ `two_factor_enabled=false` su `db.users`.

## Backup admin (storico)
- Email: `admin@86bit.it`
- Password: `password`
- Role: `admin`

## Endpoint da testare con questi credenziali
- Login: `POST /api/auth/login`
- Auto-Discovery aggregata: `GET /api/connector/discovery-results/{client_id}` (ritorna `device_count`, `scanner_endpoints_count`, `scanner_last_seen_at`)
- Lista connectors: `GET /api/connector/list`

## URL di riferimento
- Preview env: `https://noc-monitor-4.preview.emergentagent.com`
- Produzione cliente: `https://argus.86bit.it`
