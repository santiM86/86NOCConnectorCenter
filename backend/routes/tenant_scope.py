"""Helper multi-tenant per endpoint by-IP.

Gli IP privati (10.x / 192.168.x) collidono tra clienti diversi: qualunque
query/azione by-IP DEVE essere scoped al client_id corretto per evitare
data-leak o azioni cross-tenant.
"""
from fastapi import HTTPException
from database import db


async def resolve_device_client_id(device_ip: str, client_id):
    """Ritorna il client_id da usare per lo scope di un endpoint by-IP.

    - client_id fornito → usato as-is.
    - altrimenti dedotto dal proprietario del device in managed_devices.
    - IP presente su >1 cliente → 400 (client_id obbligatorio).
    - IP su 0 clienti → None (il chiamante decide se ritornare vuoto/404).
    """
    if client_id:
        return client_id
    owners = [c for c in await db.managed_devices.distinct("client_id", {"ip": device_ip}) if c]
    if len(owners) == 1:
        return owners[0]
    if len(owners) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"IP {device_ip} presente su {len(owners)} clienti diversi: client_id obbligatorio.",
        )
    return None
