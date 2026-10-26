const VM_OUIS = {
  "00:15:5D": "Hyper-V", "00:50:56": "VMware", "00:0C:29": "VMware", "00:05:69": "VMware", "00:1C:14": "VMware",
  "52:54:00": "KVM", "08:00:27": "VirtualBox", "00:16:3E": "Xen", "00:1C:42": "Parallels",
};

export const vmKindOf = (mac) => VM_OUIS[String(mac || "").toUpperCase().slice(0, 8)] || null;

// Porta "multi-dispositivo": >=2 device visti e il vicino non e' uno switch/AP via LLDP (uplink/trunk)
export const isMultiDevicePort = (p) =>
  (p.attached || []).length >= 2 && !(p.neighbor?.match_source === "lldp" && !p.vm_host) && !p.uplink_to;
