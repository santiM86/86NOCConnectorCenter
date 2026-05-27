"""
Helper centralizzato per scegliere il display name "migliore" di un device.

Risolve il problema dell'incoerenza UI: senza questa logica un device
puo' apparire con il proprio hostname SNMP nella Scheda Dispositivo
("Switch02 HP 5130 52G") ma con la categoria Fingerbank
("Switch and Wireless Controller/HP Switches") nella lista Dispositivi
e nei modali Overview.

Priorita' (dal piu' affidabile al fallback):
  1. md.name SE name_locked == True (l'admin l'ha bloccato esplicitamente).
  2. pd.sys_name        - sysName SNMP, source-of-truth per network gear.
  3. md.hostname        - NBNS / reverse DNS.
  4. md.mdns_name       - mDNS bonjour.
  5. pd.device_name     - se non e' "category-like" (contiene "/")
  6. md.name            - se non e' "category-like".
  7. md.fingerbank_device_name (es. "Switch and Wireless Controller/HP Switches").
  8. md.name fallback (anche se category-like).
  9. ip.

Usage:
    from display_name import best_display_name
    name = best_display_name(md, pd)
"""

from typing import Any, Mapping, Optional


def _clean(v: Any, ip: Optional[str] = None) -> str:
    """Restituisce v stripped se valido, altrimenti stringa vuota."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if ip and s == ip:
        return ""
    return s


def _looks_categorical(name: str) -> bool:
    """
    Fingerbank ritorna nomi tassonomici tipo
    "Switch and Wireless Controller/HP Switches" o
    "Operating System/Linux".
    Heuristic: contiene "/" e ha almeno 2 parole con maiuscole tipo titolo
    senza essere un FQDN tipo "switch.local/24".
    """
    if "/" not in name:
        return False
    # FQDN-ish: niente spazi e mostra "."
    if "." in name and " " not in name:
        return False
    # Path Linux/Windows non sono nomi device validi ma rientrano qui
    return True


def best_display_name(
    md: Optional[Mapping[str, Any]] = None,
    pd: Optional[Mapping[str, Any]] = None,
    ip: Optional[str] = None,
) -> str:
    """
    Restituisce il miglior display name per il device.

    Args:
        md: documento managed_devices (puo' essere None / vuoto).
        pd: documento device_poll_status (puo' essere None / vuoto).
        ip: ip address come fallback finale; se non passato lo prende da
            md.ip o pd.device_ip.

    Returns:
        Stringa non vuota. Garantito: minimo l'ip o "?" se manca tutto.
    """
    md = md or {}
    pd = pd or {}
    if not ip:
        ip = _clean(md.get("ip") or md.get("ip_address") or pd.get("device_ip"))

    # 1) Locked dall'admin: rispetta sempre la sua scelta.
    # Supporta entrambe le chiavi: `name_locked` (legacy) e `name_user_locked`
    # (v2026-02-14 endpoint /devices/by-ip/{ip}/rename) per retrocompat.
    if md.get("name_locked") or md.get("name_user_locked"):
        locked = _clean(md.get("name"), ip)
        if locked:
            return locked

    # 2) sys_name SNMP (poll fresco) — il piu' autoritativo per network gear.
    sys_name = _clean(pd.get("sys_name"), ip)
    if sys_name:
        return sys_name

    # 3) hostname (NBNS / reverse DNS) salvato nei managed_devices.
    hostname = _clean(md.get("hostname"), ip)
    if hostname:
        return hostname

    # 4) mDNS bonjour name.
    mdns = _clean(md.get("mdns_name"), ip)
    if mdns:
        return mdns

    # 5) pd.device_name se "buono".
    pd_name = _clean(pd.get("device_name"), ip)
    if pd_name and not _looks_categorical(pd_name):
        return pd_name

    # 6) md.name se "buono" (non e' una categoria Fingerbank).
    md_name = _clean(md.get("name"), ip)
    if md_name and not _looks_categorical(md_name):
        return md_name

    # 7) Fingerbank category come tag di fallback.
    fb_name = _clean(md.get("fingerbank_device_name"), ip)
    if fb_name:
        return fb_name

    # 8) Se md.name esiste ma e' "category-like", meglio averlo che niente.
    if md_name:
        return md_name

    # 9) pd_name anche se category-like.
    if pd_name:
        return pd_name

    # 10) ip address as last resort.
    return ip or "?"
