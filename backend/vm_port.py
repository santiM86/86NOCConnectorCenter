"""Porte con piu' dispositivi: riconoscimento VM (OUI hypervisor) e host di virtualizzazione."""
from __future__ import annotations

from typing import Optional

VM_OUIS = {
    "00:15:5D": "Hyper-V", "00:50:56": "VMware", "00:0C:29": "VMware", "00:05:69": "VMware", "00:1C:14": "VMware",
    "52:54:00": "KVM/QEMU", "08:00:27": "VirtualBox", "00:16:3E": "Xen", "00:1C:42": "Parallels",
}
_VIRT = ("hyperv", "vmware", "vm_generic")


def vm_kind(mac: str) -> Optional[str]:
    return VM_OUIS.get((mac or "").upper().replace("-", ":")[:8])


def build_vm_host(attached: list[dict], groups: list[dict], md_by_ip: dict) -> Optional[dict]:
    """Se la porta e' di un host di virtualizzazione ritorna {kind, host_name, host_ip, host_mac, vms[]}."""
    if len(attached) < 2:
        return None
    ips = {a.get("ip") for a in attached if a.get("ip")}
    group = next((g for g in groups if ips & {m.get("ip") for m in g.get("members") or []}), None)
    kinds = [vm_kind(a["mac"]) for a in attached if vm_kind(a["mac"])]
    if not kinds and not group:
        return None
    host = None
    if group:
        host = next((a for a in attached if a.get("ip") == group["host_ip"]), None) or \
            {"name": group["host_name"], "ip": group["host_ip"], "mac": group.get("mac", "").upper()}
    if host is None:
        host = next((a for a in attached if a.get("ip") and (md_by_ip.get(a["ip"]) or {}).get("virtualization") == "physical"), None)
    if host is None:
        phys = [a for a in attached if not vm_kind(a["mac"]) and (md_by_ip.get(a.get("ip") or "") or {}).get("virtualization") not in _VIRT]
        host = phys[0] if len(phys) == 1 else None
    vms = [a for a in attached if not host or a["mac"] != host.get("mac")]
    return {
        "kind": max(set(kinds), key=kinds.count) if kinds else "VM",
        "host_name": (host or {}).get("name") or "", "host_ip": (host or {}).get("ip") or "", "host_mac": (host or {}).get("mac") or "",
        "vms": [{"name": v.get("name"), "ip": v.get("ip") or "", "mac": v["mac"]} for v in vms],
    }
