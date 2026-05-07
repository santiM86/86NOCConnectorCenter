# Test Credentials — ARGUS Center

## Admin
- Email: `info@86bit.it`
- Password: `Ariel17051986@!@86`
- Role: `admin`

## Backup admin (storico)
- Email: `admin@86bit.it`
- Password: `password`
- Role: `admin`

## Endpoint da testare con questi credenziali
- Login: `POST /api/auth/login`
- Auto-Discovery aggregata: `GET /api/connector/discovery-results/{client_id}` (ritorna `device_count`, `scanner_endpoints_count`, `scanner_last_seen_at`)
- Lista connectors: `GET /api/connector/list`

## URL di riferimento
- Preview env: `https://snmp-hub-noc.preview.emergentagent.com`
- Produzione cliente: `https://argus.86bit.it`
