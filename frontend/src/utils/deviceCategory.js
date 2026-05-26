/**
 * Categoria device unificata FE/BE.
 *
 * Backend (`backend/device_type_resolver.py::best_device_type`) emette gia'
 * un device_type canonico (printer/switch/firewall/nas/ups/ilo/server/
 * access-point/tvcc/voip/endpoint/endpoint-private/workstation/mobile/iot/
 * generic).
 *
 * Questa funzione FE ha due responsabilita':
 *   1. Normalizza il device_type (rimuove aliasing legacy: ap → access-point,
 *      zyxel-usg → firewall, storage → nas, ...)
 *   2. Fallback per device "generic" senza device_type chiaro: deduce dalla
 *      coppia vendor + hostname usando le STESSE keyword del backend
 *      _OUI_VENDOR_HINTS, cosi' la macroarea e' coerente anche se il
 *      backend non ha potuto classificare (es. record vecchi pre-upgrade).
 *   3. Multicast/broadcast → "_skip" (esclusi dalla UI)
 *
 * Output canonico (15 valori): vedi MACRO_DEFS sotto.
 */

export const MACRO_DEFS = {
  firewall:    { label: "Firewall",         labelPlural: "Firewall",            order:  1 },
  switch:      { label: "Switch",           labelPlural: "Switch",              order:  2 },
  router:      { label: "Router",           labelPlural: "Router",              order:  3 },
  ap:          { label: "Access Point",     labelPlural: "Access Point",        order:  4 },
  server:      { label: "Server",           labelPlural: "Server / iLO",        order:  5 },
  nas:         { label: "NAS",              labelPlural: "NAS / Storage",       order:  6 },
  ups:         { label: "UPS",              labelPlural: "UPS",                 order:  7 },
  printer:     { label: "Stampante",        labelPlural: "Stampanti",           order:  8 },
  tvcc:        { label: "TVCC",             labelPlural: "TVCC / Camere IP",    order:  9 },
  voip:        { label: "VoIP",             labelPlural: "VoIP",                order: 10 },
  workstation: { label: "Workstation",      labelPlural: "Workstation / PC",    order: 11 },
  mobile:      { label: "Mobile",           labelPlural: "Mobile",              order: 12 },
  iot:         { label: "IoT",              labelPlural: "IoT",                 order: 13 },
  other:       { label: "Altro",            labelPlural: "Altro",               order: 14 },
  _skip:       { label: "(multicast)",      labelPlural: "(multicast)",         order: 99 },
};

function isMulticast(ip) {
  if (!ip) return false;
  // 224.0.0.0/4 (224-239) e 255.255.255.255
  return /^(22[4-9]|23\d|255)\./.test(ip);
}

/**
 * Restituisce la categoria macro di un device.
 * @param {Object} d - device dict come ritornato da /api/devices o /api/overview.
 *                     Campi usati: device_type, ip_address, vendor, hostname,
 *                                 name, mac_is_random
 * @returns {string} chiave di MACRO_DEFS
 */
export function macroOf(d) {
  if (!d) return "other";
  if (isMulticast(d.ip_address)) return "_skip";

  const dt = (d.device_type || "").toLowerCase().trim();

  // 1) Mapping diretto da device_type canonico backend
  if (["firewall", "zyxel-usg"].includes(dt)) return "firewall";
  if (dt === "switch") return "switch";
  if (dt === "router") return "router";
  if (dt === "access-point" || dt === "ap") return "ap";
  if (["server", "ilo"].includes(dt)) return "server";
  if (["nas", "storage"].includes(dt)) return "nas";
  if (dt === "ups") return "ups";
  if (dt === "printer") return "printer";
  if (["tvcc", "camera", "nvr", "dvr"].includes(dt)) return "tvcc";
  if (dt === "voip") return "voip";
  if (dt === "workstation") return "workstation";
  if (dt === "mobile") return "mobile";
  if (dt === "iot") return "iot";

  // 2) Fallback vendor/hostname per device_type generici/legacy
  // (allineato a backend/device_type_resolver._OUI_VENDOR_HINTS)
  const vendor = (d.vendor || "").toLowerCase();
  const hostname = ((d.hostname || "") + " " + (d.name || "")).toLowerCase();

  if (/wildix|yealink|polycom|snom|grandstream|panasonic kx|fanvil|mitel|avaya/.test(vendor)) return "voip";
  if (/phone|telefon|sip-|ipphone|voip/.test(hostname)) return "voip";
  if (/hikvision|dahua|axis communications|reolink|uniview|hanwha|mobotix|vivotek|bosch security/.test(vendor)) return "tvcc";
  if (/canon|brother|epson|kyocera|konica|xerox|ricoh|lexmark|sharp|oki|zebra/.test(vendor)) return "printer";
  if (vendor.startsWith("hp ") && /print|laser|inkjet|officejet|deskjet/.test(hostname)) return "printer";
  if (/synology|qnap|asustor|drobo/.test(vendor)) return "nas";
  if (/ubiquiti|ruckus wireless|mist systems|aerohive/.test(vendor)) return "ap";
  if (/american power conversion|eaton|cyberpower|riello/.test(vendor)) return "ups";
  if (/raspberry|nvidia jetson|orange pi|espressif|sonoff|shelly|tasmota|ring|nest labs|tuya/.test(vendor)) return "iot";

  if (dt === "endpoint-private" || d.mac_is_random) return "mobile";

  // Workstation by vendor (laptop/desktop tipici)
  if (/msi|micro-star|elitegroup|lcfc|asus|dell|lenovo|gigabyte|asrock|acer|samsung electron|intel|tmc|liteon|wistron|compal|quanta|inventec|pegatron/.test(vendor)) return "workstation";
  if (vendor === "hp" || /hewlett.packard|hp inc/.test(vendor)) return "workstation";
  if (/apple/.test(vendor) && !d.mac_is_random) return "workstation";

  return "other";
}

/**
 * Restituisce label IT (es. "Stampante"). Comodo per badge/colonna tabella.
 */
export function macroLabel(d) {
  const m = macroOf(d);
  return MACRO_DEFS[m]?.label || "Altro";
}

/**
 * Ordina device per macro categoria + nome.
 */
export function compareByMacro(a, b) {
  const oa = MACRO_DEFS[macroOf(a)]?.order ?? 99;
  const ob = MACRO_DEFS[macroOf(b)]?.order ?? 99;
  if (oa !== ob) return oa - ob;
  return (a.name || "").localeCompare(b.name || "");
}



/* ============ pickDeviceName ============
   Mirror JS di backend/display_name.py::best_display_name.

   Usato OVUNQUE nel frontend dove serve mostrare il "nome corretto" del
   device (mai IP nudo, mai categoria Fingerbank, mai placeholder generico).

   Priorita' (alto -> basso):
     1. d.name (se non-vuoto, non == ip, non "category-like" con "/")
     2. d.hostname (SNMP sys_name / NBNS)
     3. d.sys_name
     4. d.mdns_name
     5. d.fingerbank_device_name (categoria, last resort prima di ip)
     6. ip address

   Nota: backend gia' applica best_display_name su /api/devices, ma questo
   helper FE serve come defense-in-depth per i posti dove l'API ritorna
   ancora il vecchio "name" (es. prima del deploy in produzione).
*/
function _isCategorical(name) {
  if (!name || typeof name !== "string") return false;
  if (!name.includes("/")) return false;
  // FQDN tipo "switch.local/admin" → no
  if (name.includes(".") && !name.includes(" ")) return false;
  return true;
}

export function pickDeviceName(d, fallback = "") {
  if (!d) return fallback;
  const ip = d.ip_address || d.ip || d.device_ip || "";
  const tryFields = ["name", "hostname", "sys_name", "mdns_name"];
  for (const k of tryFields) {
    const v = (d[k] || "").trim();
    if (v && v !== ip && !_isCategorical(v)) return v;
  }
  const fb = (d.fingerbank_device_name || "").trim();
  if (fb && fb !== ip) return fb;
  // Anche se "name" è category-like, meglio che ip nudo
  const nm = (d.name || "").trim();
  if (nm && nm !== ip) return nm;
  return ip || fallback;
}
