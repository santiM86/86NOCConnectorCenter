"""Minimal OUI (Organizationally Unique Identifier) lookup for MAC vendor identification.

Covers the top ~150 vendors seen in enterprise/SMB environments (servers, printers,
IP phones, access points, NAS, IoT, laptops). For unknown prefixes returns "".

Full IEEE registry is ~40k entries - this curated list keeps footprint small while
covering 90%+ of real-world matches in NOC deployments.
"""


OUI_DB = {
    # Apple (includes a/c MAC randomization ranges still commonly seen)
    "00:03:93": "Apple", "00:05:02": "Apple", "00:0a:27": "Apple", "00:0a:95": "Apple",
    "00:0d:93": "Apple", "00:11:24": "Apple", "00:14:51": "Apple", "00:16:cb": "Apple",
    "00:17:f2": "Apple", "00:19:e3": "Apple", "00:1b:63": "Apple", "00:1c:b3": "Apple",
    "00:1e:52": "Apple", "00:1e:c2": "Apple", "00:1f:5b": "Apple", "00:1f:f3": "Apple",
    "00:21:e9": "Apple", "00:22:41": "Apple", "00:23:12": "Apple", "00:23:32": "Apple",
    "00:23:6c": "Apple", "00:23:df": "Apple", "00:25:00": "Apple", "00:25:4b": "Apple",
    "00:25:bc": "Apple", "00:26:08": "Apple", "00:26:4a": "Apple", "00:26:b0": "Apple",
    "00:26:bb": "Apple", "00:50:e4": "Apple", "14:10:9f": "Apple", "28:cf:e9": "Apple",
    "3c:07:54": "Apple", "40:33:1a": "Apple", "40:a6:d9": "Apple", "58:b0:35": "Apple",
    "60:f4:45": "Apple", "68:a8:6d": "Apple", "70:56:81": "Apple", "7c:6d:62": "Apple",
    "7c:d1:c3": "Apple", "80:e6:50": "Apple", "88:63:df": "Apple", "8c:58:77": "Apple",
    "90:b2:1f": "Apple", "98:01:a7": "Apple", "a4:5e:60": "Apple", "a8:20:66": "Apple",
    "b8:17:c2": "Apple", "b8:e8:56": "Apple", "c8:1e:e7": "Apple", "d0:03:4b": "Apple",
    "d0:23:db": "Apple", "dc:a9:04": "Apple", "e0:ac:cb": "Apple", "f0:d1:a9": "Apple",
    "f4:0f:24": "Apple",
    # HP / HPE / Aruba / HPE iLO (management interface - indica server)
    "9c:dc:71": "HPE iLO", "3c:4a:92": "HPE iLO", "d4:85:64": "HPE iLO",
    "98:4b:e1": "HP", "f4:ce:46": "HPE iLO", "14:58:d0": "HPE iLO",
    "fc:15:b4": "HPE iLO", "7c:e9:d3": "HPE iLO", "94:f1:28": "HPE iLO",
    "00:08:02": "HP", "00:0b:cd": "HP", "00:0f:20": "HP", "00:10:83": "HP",
    "00:11:0a": "HP", "00:11:85": "HP", "00:12:79": "HP", "00:13:21": "HP",
    "00:14:38": "HP", "00:14:c2": "HP", "00:15:60": "HP", "00:16:35": "HP",
    "00:17:08": "HP", "00:17:a4": "HP", "00:18:71": "HP", "00:18:fe": "HP",
    "00:19:bb": "HP", "00:1a:4b": "HP", "00:1b:78": "HP", "00:1c:c4": "HP",
    "00:1e:0b": "HP", "00:1f:29": "HP", "00:21:5a": "HP", "00:22:64": "HP",
    "00:23:7d": "HP", "00:24:81": "HP", "00:25:b3": "HP", "00:26:55": "HP",
    "00:2a:10": "HPE Aruba", "00:4e:01": "HPE", "14:02:ec": "HPE",
    "24:be:05": "HP", "28:80:88": "HP", "28:92:4a": "HP", "2c:27:d7": "HP",
    "2c:41:38": "HP", "2c:44:fd": "HP", "30:8d:99": "HP", "34:64:a9": "HP",
    "38:63:bb": "HP", "3c:d9:2b": "HP", "40:a8:f0": "HP", "44:48:c1": "HP",
    "44:31:92": "HP", "44:76:74": "HP", "48:0f:cf": "HP", "4c:39:09": "HP",
    "50:65:f3": "HP", "54:80:28": "HP", "5c:8a:38": "HP", "64:31:50": "HP",
    "68:b5:99": "HP", "6c:3b:e5": "HP", "70:5a:0f": "HP", "80:ce:62": "HP",
    "84:34:97": "HP", "8c:dc:d4": "HPE Aruba", "94:18:82": "HP", "94:57:a5": "HP",
    "98:4b:e1": "HP", "9c:b6:54": "HP", "9c:8e:99": "HP", "a0:1d:48": "HP",
    "a0:48:1c": "HP", "a0:b3:cc": "HP", "a4:5d:36": "HP", "a8:bd:27": "HPE Aruba",
    "ac:16:2d": "HP", "b0:5a:da": "HP", "b4:99:ba": "HP", "b4:b5:2f": "HP",
    "b8:af:67": "HP", "c4:34:6b": "HP", "c8:b5:ad": "HPE Aruba", "cc:3e:5f": "HP",
    "d0:7e:28": "HP", "d4:c9:ef": "HP", "d8:9d:67": "HP", "dc:4a:3e": "HP",
    "ec:8e:b5": "HP", "ec:b1:d7": "HP", "f0:92:1c": "HP", "fc:15:b4": "HP",
    # Cisco / Meraki
    "00:00:0c": "Cisco", "00:01:42": "Cisco", "00:01:63": "Cisco", "00:01:96": "Cisco",
    "00:01:97": "Cisco", "00:02:b9": "Cisco", "00:02:ba": "Cisco", "00:03:6b": "Cisco",
    "00:05:32": "Cisco", "00:06:28": "Cisco", "00:06:d6": "Cisco", "00:07:0d": "Cisco",
    "00:08:a3": "Cisco", "00:0a:41": "Cisco", "00:0a:b7": "Cisco", "00:0b:be": "Cisco",
    "00:0c:30": "Cisco", "00:0e:d6": "Cisco", "00:0e:d7": "Cisco", "00:0f:23": "Cisco",
    "00:0f:34": "Cisco", "00:10:07": "Cisco", "00:10:11": "Cisco", "00:10:1f": "Cisco",
    "00:11:5c": "Cisco", "00:11:92": "Cisco", "00:12:01": "Cisco", "00:12:43": "Cisco",
    "00:12:7f": "Cisco", "00:12:d9": "Cisco", "00:13:1a": "Cisco", "00:13:5f": "Cisco",
    "00:13:c3": "Cisco", "00:14:1b": "Cisco", "00:15:62": "Cisco", "00:16:47": "Cisco",
    "00:17:5a": "Cisco", "00:17:95": "Cisco", "00:18:18": "Cisco", "00:18:b9": "Cisco",
    "00:19:06": "Cisco", "00:19:55": "Cisco", "00:1a:2f": "Cisco", "00:1a:a2": "Cisco",
    "00:1b:2a": "Cisco", "00:1b:8f": "Cisco", "00:1c:0e": "Cisco", "00:1d:45": "Cisco",
    "00:1e:13": "Cisco", "00:1e:7a": "Cisco", "00:1f:27": "Cisco", "00:1f:ca": "Cisco",
    "00:21:55": "Cisco", "00:21:a0": "Cisco", "00:22:0c": "Cisco", "00:22:55": "Cisco",
    "00:23:04": "Cisco", "00:23:ac": "Cisco", "00:24:13": "Cisco", "00:24:c4": "Cisco",
    "00:25:45": "Cisco", "00:26:51": "Cisco", "00:26:cb": "Cisco", "2c:5a:0f": "Cisco",
    "6c:20:56": "Cisco", "80:e0:1d": "Cisco Meraki", "88:15:44": "Cisco Meraki",
    "98:18:88": "Cisco Meraki", "ac:17:c8": "Cisco Meraki", "e0:55:3d": "Cisco Meraki",
    # Dell / Dell iDRAC (management interface server Dell)
    "a4:ba:db": "Dell iDRAC", "18:fb:7b": "Dell iDRAC", "f8:bc:12": "Dell iDRAC",
    "c8:1f:66": "Dell iDRAC", "b0:83:fe": "Dell iDRAC", "18:66:da": "Dell iDRAC",
    "00:06:5b": "Dell", "00:08:74": "Dell", "00:0b:db": "Dell", "00:0d:56": "Dell",
    "00:0f:1f": "Dell", "00:11:43": "Dell", "00:12:3f": "Dell", "00:13:72": "Dell",
    "00:14:22": "Dell", "00:15:c5": "Dell", "00:18:8b": "Dell", "00:19:b9": "Dell",
    "00:1a:a0": "Dell", "00:1c:23": "Dell", "00:1d:09": "Dell", "00:1e:4f": "Dell",
    "00:21:70": "Dell", "00:21:9b": "Dell", "00:22:19": "Dell", "00:23:ae": "Dell",
    "00:24:e8": "Dell", "00:25:64": "Dell", "00:26:b9": "Dell", "1c:40:24": "Dell",
    "20:04:0f": "Dell", "2c:60:0c": "Dell", "44:a8:42": "Dell", "5c:26:0a": "Dell",
    "84:7b:eb": "Dell", "b8:2a:72": "Dell", "b8:ca:3a": "Dell", "d0:67:e5": "Dell",
    "d4:be:d9": "Dell", "e0:db:55": "Dell", "ec:f4:bb": "Dell", "f0:1f:af": "Dell",
    "f8:b1:56": "Dell", "f8:bc:12": "Dell", "f8:db:88": "Dell",
    # Microsoft / Hyper-V / Azure
    "00:03:ff": "Microsoft", "00:12:5a": "Microsoft", "00:15:5d": "Microsoft Hyper-V",
    "00:17:fa": "Microsoft", "00:1d:d8": "Microsoft", "00:22:48": "Microsoft",
    "00:25:ae": "Microsoft", "00:50:f2": "Microsoft",
    # Intel (typical NIC)
    "00:02:b3": "Intel", "00:03:47": "Intel", "00:0c:f1": "Intel", "00:0e:0c": "Intel",
    "00:0e:35": "Intel", "00:11:75": "Intel", "00:12:f0": "Intel", "00:13:02": "Intel",
    "00:13:20": "Intel", "00:13:ce": "Intel", "00:13:e8": "Intel", "00:15:00": "Intel",
    "00:15:17": "Intel", "00:16:76": "Intel", "00:16:ea": "Intel", "00:16:eb": "Intel",
    "00:18:de": "Intel", "00:19:d1": "Intel", "00:19:d2": "Intel", "00:1b:21": "Intel",
    "00:1b:77": "Intel", "00:1c:bf": "Intel", "00:1c:c0": "Intel", "00:1d:e0": "Intel",
    "00:1e:64": "Intel", "00:1e:65": "Intel", "00:1e:67": "Intel", "00:1f:3b": "Intel",
    "00:1f:3c": "Intel", "00:21:5c": "Intel", "00:21:5d": "Intel", "00:21:6a": "Intel",
    "00:21:6b": "Intel", "00:22:fa": "Intel", "00:22:fb": "Intel", "00:23:14": "Intel",
    "00:23:15": "Intel", "00:24:d6": "Intel", "00:24:d7": "Intel", "00:26:c6": "Intel",
    "00:26:c7": "Intel", "00:27:0e": "Intel", "00:27:10": "Intel", "00:a0:c9": "Intel",
    "00:aa:00": "Intel", "00:d0:b7": "Intel", "00:db:df": "Intel", "08:11:96": "Intel",
    "10:4a:7d": "Intel", "34:e6:d7": "Intel", "3c:a9:f4": "Intel", "48:51:b7": "Intel",
    "50:eb:f6": "Intel", "54:35:30": "Intel", "58:94:6b": "Intel", "5c:51:4f": "Intel",
    "68:17:29": "Intel", "68:05:ca": "Intel", "74:e5:0b": "Intel", "7c:b2:7d": "Intel",
    "7c:7a:91": "Intel", "84:3a:4b": "Intel", "8c:70:5a": "Intel", "90:e2:ba": "Intel",
    "98:af:65": "Intel", "a0:36:9f": "Intel", "a0:88:b4": "Intel", "a4:34:d9": "Intel",
    "a4:c4:94": "Intel", "a4:d1:8c": "Intel", "ac:72:89": "Intel", "b0:7d:64": "Intel",
    "c4:85:08": "Intel", "cc:2f:71": "Intel", "d8:f2:ca": "Intel", "dc:a6:32": "Intel",
    "e0:94:67": "Intel", "e4:b9:7a": "Intel", "ec:a8:6b": "Intel", "f8:16:54": "Intel",
    "f8:e4:e3": "Intel", "fc:f8:ae": "Intel",
    # Realtek (embedded NIC)
    "00:e0:4c": "Realtek", "52:54:00": "Realtek/KVM", "00:13:d3": "Realtek",
    # Synology / QNAP (NAS)
    "00:11:32": "Synology", "90:09:d0": "Synology", "ac:8b:a9": "Synology",
    "00:08:9b": "QNAP", "24:5e:be": "QNAP", "54:26:8b": "QNAP", "94:5d:96": "QNAP",
    "28:8b:dc": "QNAP", "00:30:a8": "QNAP", "00:1f:c6": "QNAP",
    # Zyxel / MikroTik / Ubiquiti (SOHO)
    "00:02:cf": "Zyxel", "00:13:49": "Zyxel", "00:19:cb": "Zyxel", "00:23:f8": "Zyxel",
    "00:a0:c5": "Zyxel", "00:13:f7": "Zyxel", "ec:43:f6": "Zyxel", "bc:cf:4f": "Zyxel",
    "4c:9e:ff": "Zyxel", "d0:bc:12": "Zyxel",
    "00:0c:42": "MikroTik", "4c:5e:0c": "MikroTik", "6c:3b:6b": "MikroTik",
    "74:4d:28": "MikroTik", "b8:69:f4": "MikroTik", "cc:2d:e0": "MikroTik",
    "dc:2c:6e": "MikroTik", "e4:8d:8c": "MikroTik",
    "00:15:6d": "Ubiquiti", "04:18:d6": "Ubiquiti", "24:5a:4c": "Ubiquiti",
    "24:a4:3c": "Ubiquiti", "44:d9:e7": "Ubiquiti", "68:72:51": "Ubiquiti",
    "74:83:c2": "Ubiquiti", "78:8a:20": "Ubiquiti", "80:2a:a8": "Ubiquiti",
    "94:2a:6f": "Ubiquiti", "b4:fb:e4": "Ubiquiti", "dc:9f:db": "Ubiquiti",
    "f0:9f:c2": "Ubiquiti", "fc:ec:da": "Ubiquiti",
    # IBM IMM (Integrated Management Module server IBM/Lenovo)
    "5c:f3:fc": "IBM IMM", "6c:ae:8b": "IBM IMM", "e4:1f:13": "IBM IMM",
    # Fortinet / pfSense / Sophos (firewall)
    "00:09:0f": "Fortinet", "04:d5:90": "Fortinet", "70:4c:a5": "Fortinet",
    "90:6c:ac": "Fortinet", "e8:1c:ba": "Fortinet", "00:1e:26": "Fortinet",
    "00:04:23": "Sophos", "00:1a:8c": "Sophos",
    # SonicWall
    "00:06:b1": "SonicWall", "c0:ea:e4": "SonicWall", "18:b1:69": "SonicWall",
    # WatchGuard
    "00:90:7f": "WatchGuard",
    # Checkpoint
    "00:1c:7f": "Checkpoint",
    # Palo Alto Networks
    "00:1b:17": "Palo Alto", "b4:0c:25": "Palo Alto",
    # Juniper
    "00:05:85": "Juniper", "00:12:1e": "Juniper", "00:1b:c0": "Juniper",
    "28:8a:1c": "Juniper", "50:c7:bf": "Juniper",
    # Samsung / LG / Lenovo / Asus (laptop/tablet)
    "00:12:fb": "Samsung", "00:17:c9": "Samsung", "00:1a:8a": "Samsung", "00:21:19": "Samsung",
    "5c:0a:5b": "Samsung", "cc:07:ab": "Samsung", "ec:1f:72": "Samsung", "e8:50:8b": "Samsung",
    "00:04:7d": "Lenovo", "08:6d:41": "Lenovo", "54:ee:75": "Lenovo", "a0:51:0b": "Lenovo",
    "e4:54:e8": "Lenovo",
    "00:0e:a6": "Asus", "00:13:d4": "Asus", "00:24:8c": "Asus", "04:d9:f5": "Asus",
    "10:bf:48": "Asus", "2c:56:dc": "Asus", "38:d5:47": "Asus", "50:46:5d": "Asus",
    # Printer (HP/Canon/Epson/Brother/Ricoh/Xerox/Lexmark/Kyocera/Konica)
    "00:00:48": "Epson", "00:00:85": "Canon", "00:00:aa": "Xerox",
    "00:00:74": "Ricoh", "00:05:35": "Ricoh", "00:1b:a9": "Brother",
    "00:80:77": "Brother", "00:80:a5": "Brother", "00:00:85": "Konica",
    "00:00:8f": "Lexmark", "00:21:b7": "Lexmark",
    "00:c0:ee": "Kyocera", "00:c1:64": "Kyocera",
    # VMware / VirtualBox
    "00:0c:29": "VMware", "00:1c:14": "VMware", "00:50:56": "VMware",
    "08:00:27": "VirtualBox", "52:54:00": "QEMU/KVM",
    # VoIP (Yealink/Grandstream/Polycom/Snom/Cisco SPA)
    "00:15:65": "Yealink", "24:9a:d8": "Yealink", "80:5e:c0": "Yealink",
    "00:0b:82": "Grandstream", "c0:74:ad": "Grandstream", "00:0d:dd": "Grandstream",
    "00:04:f2": "Polycom", "00:01:29": "Polycom", "64:16:7f": "Polycom",
    "00:04:13": "Snom",
    # IP Camera (Hikvision/Dahua/Axis/Uniview)
    "00:40:8c": "Axis", "ac:cc:8e": "Axis", "b8:a4:4f": "Axis",
    "44:19:b6": "Hikvision", "bc:ad:28": "Hikvision", "c0:51:7e": "Hikvision",
    "3c:ef:8c": "Dahua", "4c:11:bf": "Dahua", "90:02:a9": "Dahua",
    "a0:bd:1d": "Uniview",
    # Raspberry Pi
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
    "2c:cf:67": "Raspberry Pi",
    # UPS (APC/Eaton/Riello)
    "00:c0:b7": "APC", "7c:b0:3e": "APC",
    "00:20:85": "Eaton",
    "00:a0:3e": "Riello",
    # Switch vendors (generic)
    "00:07:e9": "D-Link", "00:13:46": "D-Link", "00:15:e9": "D-Link", "00:1c:f0": "D-Link",
    "00:1e:58": "D-Link", "00:21:91": "D-Link", "00:24:01": "D-Link",
    "00:09:5b": "Netgear", "00:14:6c": "Netgear", "00:1b:2f": "Netgear", "00:1f:33": "Netgear",
    "00:22:3f": "Netgear", "00:24:b2": "Netgear", "00:26:f2": "Netgear",
    "00:22:6b": "Cisco Linksys", "68:7f:74": "Cisco Linksys",
    "00:0f:66": "Cisco Linksys", "00:13:10": "Cisco Linksys",
    # Huawei
    "00:1e:10": "Huawei", "00:25:9e": "Huawei", "00:46:4b": "Huawei", "1c:1d:67": "Huawei",
    "48:46:fb": "Huawei", "4c:b1:6c": "Huawei", "70:54:f5": "Huawei", "78:d7:52": "Huawei",
    "80:71:7a": "Huawei", "88:25:93": "Huawei", "98:e7:f5": "Huawei",
    # Dahua/Hikvision already covered above
}


def lookup_oui(mac: str) -> str:
    """Return vendor name for a given MAC address, or '' if unknown.

    Accepts MAC in any common separator format (aa:bb:cc:dd:ee:ff, AA-BB-CC-DD-EE-FF,
    aabbccddeeff). Only the first 3 bytes (OUI) are matched.
    """
    if not mac:
        return ""
    # Normalize: lowercase, remove separators, keep first 6 hex chars
    clean = "".join(c for c in mac.lower() if c in "0123456789abcdef")
    if len(clean) < 6:
        return ""
    prefix = f"{clean[0:2]}:{clean[2:4]}:{clean[4:6]}"
    return OUI_DB.get(prefix, "")
