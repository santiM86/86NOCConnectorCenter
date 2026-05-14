// OUI vendor lookup — porting dalla tabella usata in cmd/nocui.
// Copre >80% dei device LAN incontrati in ambienti SMB/MSP.
//
//go:build windows

package lanscan

import "strings"

var ouiTable = map[string]string{
	// Microsoft (Hyper-V virtual NIC + Surface)
	"00:15:5d": "Microsoft Hyper-V", "00:03:ff": "Microsoft",
	"60:45:bd": "Microsoft", "28:18:78": "Microsoft", "00:50:f2": "Microsoft",
	"00:25:64": "Microsoft", "7c:1e:52": "Microsoft", "98:5f:d3": "Microsoft",
	// Apple
	"84:a9:3e": "Apple", "ac:f4:66": "Apple", "f4:39:09": "Apple", "9c:7b:ef": "Apple",
	"04:0e:3c": "Apple", "44:8a:5b": "Apple", "98:f2:b3": "Apple", "f4:f1:5a": "Apple",
	"b0:0c:d1": "Apple", "a4:5e:60": "Apple", "f0:18:98": "Apple", "f0:c1:f1": "Apple",
	"98:01:a7": "Apple", "5c:f9:38": "Apple", "70:48:0f": "Apple", "ac:bc:32": "Apple",
	"ac:de:48": "Apple",
	// Network / routing / wifi
	"70:49:a2": "AVM FRITZ!Box", "58:38:79": "Cisco Meraki", "40:b0:34": "HP",
	"f0:9f:c2": "Ubiquiti", "24:5a:4c": "Ubiquiti", "78:8a:20": "Ubiquiti", "fc:ec:da": "Ubiquiti",
	"04:18:d6": "Ubiquiti", "00:0d:b9": "Mikrotik", "4c:5e:0c": "Mikrotik", "b8:69:f4": "Mikrotik",
	"ec:1f:72": "Mikrotik", "dc:2c:6e": "Mikrotik", "6c:3b:6b": "Mikrotik", "74:4d:28": "Mikrotik",
	"00:13:49": "Zyxel", "5c:6a:80": "Zyxel", "10:7b:ef": "Zyxel", "bc:99:11": "Zyxel",
	"00:18:f3": "ASUSTek", "08:62:66": "ASUSTek", "20:cf:30": "ASUSTek", "60:45:cb": "ASUSTek",
	"00:14:5e": "IBM", "00:1d:c5": "Cisco", "00:1c:f0": "D-Link", "14:d6:4d": "D-Link",
	"a4:2b:b0": "TP-Link", "98:da:c4": "TP-Link", "60:e3:27": "TP-Link",
	"24:f5:a2": "TP-Link", "1c:bf:ce": "TP-Link", "50:c7:bf": "TP-Link",
	"60:32:b1": "FRITZ!Box", "9c:c7:a6": "FRITZ!Box", "08:96:d7": "FRITZ!Box",
	"4c:60:de": "Netgear", "10:0d:7f": "Netgear", "20:e5:2a": "Netgear",
	"00:0c:42": "Routerboard", "f4:8e:38": "Dahua", "3c:e3:6b": "Dahua",
	// VMware
	"00:50:56": "VMware", "00:0c:29": "VMware", "00:1c:14": "VMware", "00:05:69": "VMware",
	// Server / PC
	"d4:81:d7": "Dell", "f4:8e:b8": "Dell", "00:14:22": "Dell", "00:1d:09": "Dell",
	"94:c6:91": "HP", "9c:8e:99": "HP", "70:5a:0f": "HP", "fc:15:b4": "HP",
	"e4:54:e8": "Lenovo", "08:6d:41": "Lenovo", "60:eb:69": "Lenovo",
	// Printers
	"00:21:5a": "HP Print", "9c:b6:d0": "HP Print", "ec:b1:d7": "HP Print",
	"00:1b:a9": "Brother", "00:80:77": "Brother", "30:05:5c": "Brother",
	"00:1e:8f": "Canon", "84:25:3f": "Canon", "00:00:85": "Canon",
	"00:00:48": "Epson", "08:00:83": "Epson", "44:d2:44": "Epson",
	"00:00:74": "Ricoh", "ac:44:f2": "Ricoh", "00:26:73": "Ricoh",
	"00:90:fb": "Konica Minolta", "00:20:6b": "Konica Minolta",
	// IoT / camera
	"5c:cf:7f": "Espressif", "ec:fa:bc": "Espressif", "8c:aa:b5": "Espressif",
	"24:6f:28": "Espressif", "e8:db:84": "Espressif",
	"00:62:6e": "Hikvision", "44:19:b6": "Hikvision", "bc:ad:28": "Hikvision",
	"ec:c8:9c": "Hikvision",
	// NAS
	"00:11:32": "Synology",
	"00:08:9b": "QNAP", "24:5e:be": "QNAP",
	// Phones
	"40:b4:f0": "Xiaomi", "20:47:da": "Xiaomi", "f4:f5:db": "Xiaomi",
	"58:48:22": "OnePlus", "00:9b:ad": "Sony",
}

// ouiVendor ritorna il vendor associato al prefisso OUI del MAC, o "".
func ouiVendor(mac string) string {
	if len(mac) < 8 {
		return ""
	}
	pfx := strings.ToLower(mac[:8])
	if v, ok := ouiTable[pfx]; ok {
		return v
	}
	return ""
}
