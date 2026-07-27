import { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  Desktop, Cpu, HardDrives, Thermometer, Info, MapPin, Package, Shield, Barcode,
  Calendar, Globe, ArrowsClockwise, Warning, CheckCircle, CircleNotch,
  ChartLineUp, NetworkSlash, PencilSimple, FloppyDisk, X as XIcon, Wrench,
} from "@phosphor-icons/react";
import AllMetricsDialog from "@/components/AllMetricsDialog";
import { VendorDetailsPanel } from "@/components/VendorDetailsPanel";
import ErrorBoundary from "@/components/ErrorBoundary";

const API = process.env.REACT_APP_BACKEND_URL;

function Field({ label, value, mono = false, highlight = false }) {
  if (value === null || value === undefined || value === "") return null;
  // Defensive: never render raw objects/arrays
  let displayValue;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    displayValue = String(value);
  } else if (Array.isArray(value)) {
    if (value.length === 0) return null;
    displayValue = value.map((v) =>
      v === null || v === undefined ? "" :
      (typeof v === "object" ? (v.label || v.name || v.value || JSON.stringify(v)) : String(v))
    ).filter(Boolean).join(", ");
  } else if (typeof value === "object") {
    displayValue = value.label || value.name || (value.value !== undefined ? String(value.value) : null);
    if (!displayValue) {
      try { displayValue = JSON.stringify(value); } catch { displayValue = "[object]"; }
    }
  } else {
    displayValue = String(value);
  }
  return (
    <div className="flex items-start justify-between gap-3 py-1 border-b border-[var(--bg-border)]/50">
      <span className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)] whitespace-nowrap pt-0.5">{label}</span>
      <span className={`text-xs text-right ${mono ? "font-mono" : ""} ${highlight ? "text-cyan-300 font-semibold" : "text-[var(--text-primary)]"}`}>
        {displayValue}
      </span>
    </div>
  );
}

function Section({ title, icon: Icon, children, testid, color = "text-[var(--text-primary)]" }) {
  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3" data-testid={testid}>
      <div className={`flex items-center gap-2 mb-2 ${color}`}>
        {Icon && <Icon size={16} weight="duotone" />}
        <h4 className="text-xs font-bold uppercase tracking-wide">{title}</h4>
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function fmtDate(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" });
  } catch {
    return iso;
  }
}

function fmtDateTime(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

/** Defensive: rende sicuro qualsiasi valore per il render React (mai oggetti raw). */
function safe(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.length === 0 ? fallback : value.map((v) => safe(v, "")).filter(Boolean).join(", ");
  if (typeof value === "object") {
    // Synology spesso ritorna { code: 1, label: "Normal" } o { value: X, unit: "C" }
    if (value.label) return String(value.label);
    if (value.name) return String(value.name);
    if (value.value !== undefined) return String(value.value);
    if (value.status !== undefined) return String(value.status);
    try { return JSON.stringify(value); } catch { return fallback; }
  }
  return String(value);
}

export default function DeviceInfoCard({ deviceIp, onClose = null, compact = false, onCardLoaded = null, hypervState = "", hypervHost = "" }) {
  const navigate = useNavigate();
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAllMetrics, setShowAllMetrics] = useState(false);
  // v2026-02-14: rename inline manuale del device (propaga ovunque)
  const [editingName, setEditingName] = useState(false);
  const [newName, setNewName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [mcaInput, setMcaInput] = useState("");
  const [savingMca, setSavingMca] = useState(false);
  const [parentInput, setParentInput] = useState("");
  const [savingParent, setSavingParent] = useState(false);
  const token = localStorage.getItem("noc_token");

  const saveParent = async () => {
    setSavingParent(true);
    try {
      const cid = card?.identity?.client_id || card?.status?.client_id;
      await axios.post(
        `${API}/api/devices/by-ip/${deviceIp}/parent`,
        { parent_ip: parentInput.trim() || null, client_id: cid },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      setParentInput("");
      fetchCard(true);
    } catch (e) {
      // noop
    } finally {
      setSavingParent(false);
    }
  };

  const saveMaxCheckAttempts = async () => {
    setSavingMca(true);
    try {
      const cid = card?.identity?.client_id || card?.status?.client_id;
      await axios.post(
        `${API}/api/devices/by-ip/${deviceIp}/monitoring-config`,
        { max_check_attempts: mcaInput === "" ? null : parseInt(mcaInput, 10), client_id: cid },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      fetchCard(true);
    } catch (e) {
      // noop: errore mostrato dal refresh
    } finally {
      setSavingMca(false);
    }
  };

  const fetchCard = (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    axios
      .get(`${API}/api/devices/by-ip/${deviceIp}/info-card`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        setCard(r.data);
        setLastUpdated(Date.now());
        // v2026-02-14: notifica al parent il display name corretto per
        // sincronizzare il titolo del Dialog (Scheda Dispositivo) e altri
        // posti che ricevono lo stesso device da liste non aggiornate.
        try { onCardLoaded?.(r.data); } catch {}
      })
      .catch((e) => { if (!silent) setError(e.response?.data?.detail || "Errore caricamento scheda"); })
      .finally(() => { if (!silent) setLoading(false); });
  };

  // v2026-06-02: force re-poll SNMP + diagnosi sul perche' lo SNMP non
  // arriva fresco. Caso d'uso: switch HP 10.10.41.221 (ZITAC) con ultimo
  // poll vecchio di settimane perche' subnet-aware dispatcher non manda
  // i target nell'agent giusto.
  const [snmpPolling, setSnmpPolling] = useState(false);
  const forceSnmpPoll = async () => {
    const clientId = card?.client?.id || card?.client_id || card?.identity?.client_id;
    if (!clientId) {
      toast.error("client_id non disponibile in scheda");
      return;
    }
    setSnmpPolling(true);
    try {
      const r = await axios.post(
        `${API}/api/admin/snmp-poll-now/${clientId}/${deviceIp}`, {},
        { headers: { Authorization: `Bearer ${token}` } },
      );
      const reply = r.data?.reply || {};
      const sysName = reply?.sys_name || reply?.sysName || "—";
      toast.success(`✅ Poll SNMP eseguito da ${r.data.executed_by_agent}. sysName=${sysName}`, { duration: 8000 });
      setTimeout(fetchCard, 1500);
    } catch (e) {
      // Se il poll fallisce, esegui automaticamente la diagnosi
      const reason = e.response?.data?.detail || e.message;
      try {
        const diag = await axios.get(
          `${API}/api/admin/snmp-diagnosis/${clientId}/${deviceIp}`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        const d = diag.data;
        // v2026-06-02: include anche tabella agent del cliente per
        // capire QUALE e' offline e da quanto tempo (caso ZITAC: utente
        // pensa che l'agent sia online ma in realta' e' disconnesso da
        // settimane).
        let agentsBlock = "";
        if (Array.isArray(d.agents) && d.agents.length > 0) {
          const lines = d.agents.map(a => {
            const status = a.online ? "🟢 ONLINE" : "🔴 OFFLINE";
            const hb = a.last_heartbeat_at
              ? new Date(a.last_heartbeat_at).toLocaleString("it-IT")
              : "mai";
            const inSub = a.device_ip_in_subnet ? "✓ in subnet" : "✗ fuori subnet";
            return `   ${status} ${a.hostname || a.agent_id?.slice(0, 8)} (${a.role}) ` +
                   `IP=${a.agent_ip || "?"} subnet=${a.subnet || "?"} ${inSub} ` +
                   `last_hb=${hb}`;
          }).join("\n");
          agentsBlock = `\n\n👥 Agent del cliente (${d.agents.length}):\n${lines}`;
        } else {
          agentsBlock = "\n\n👥 Nessun agent registrato in DB per questo cliente.";
        }
        const msg = `❌ Poll fallito: ${reason}\n\n📋 Diagnosi:\n${d.diagnosis}` +
          agentsBlock +
          "\n\n💡 Suggerimenti:\n" +
          (d.suggestions || []).map(s => `• ${s}`).join("\n");
        window.alert(msg);
      } catch {
        toast.error(`Poll SNMP fallito: ${reason}`);
      }
    } finally {
      setSnmpPolling(false);
    }
  };

  const startEditName = (currentName) => {
    setNewName(currentName || "");
    setEditingName(true);
  };

  const saveName = async () => {
    const trimmed = (newName || "").trim();
    if (!trimmed) {
      toast.error("Il nome non puo' essere vuoto");
      return;
    }
    setSavingName(true);
    try {
      // v2026-02-14: passa client_id per disambiguare in scenari multi-tenant
      // dove piu' clienti hanno lo stesso IP (es. 192.168.x.x).
      const clientId = card?.client?.id || card?.client_id || null;
      const body = { name: trimmed };
      if (clientId) body.client_id = clientId;
      const res = await axios.post(
        `${API}/api/devices/by-ip/${deviceIp}/rename`,
        body,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      toast.success(res.data?.message || `Device rinominato in "${trimmed}"`);
      setEditingName(false);
      // Trigger refresh della card e segnala al parent (se vuole ricaricare)
      fetchCard();
      // Custom event globale: la lista dispositivi/panoramica puo' ascoltarlo
      // per refresh immediato senza dipendenza diretta.
      window.dispatchEvent(new CustomEvent("argus:device-renamed", {
        detail: { device_ip: deviceIp, new_name: trimmed, client_id: clientId }
      }));
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio nome");
    } finally {
      setSavingName(false);
    }
  };

  const cancelEditName = () => {
    setEditingName(false);
    setNewName("");
  };

  useEffect(() => {
    fetchCard();
    // v2026-06-23: auto-refresh LIVE ogni 30s mentre la scheda e' aperta
    // (silent = niente spinner, aggiornamento in background) cosi' lo
    // STATO LIVE resta sempre fresco senza dover cliccare Aggiorna.
    const i = setInterval(() => fetchCard(true), 30000);
    return () => clearInterval(i);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceIp]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 text-[var(--text-secondary)]" data-testid="device-info-card-loading">
        <CircleNotch size={20} className="animate-spin mr-2" />
        Caricamento scheda device...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-300 text-sm" data-testid="device-info-card-error">
        <Warning size={16} className="inline mr-2" />
        {error}
      </div>
    );
  }

  if (!card) return null;

  const id = card.identity || {};
  const fw = card.firmware || {};
  const st = card.status || {};
  const hw = card.hardware || {};
  const net = card.network || {};
  const lc = card.lifecycle;
  const loc = card.location || {};
  const fwComp = fw.compliance;

  // Format open_ports: può contenere oggetti {port, service} o stringhe/numeri
  const formatOpenPorts = (ports) => {
    if (!Array.isArray(ports) || ports.length === 0) return null;
    return ports
      .map((p) => {
        if (typeof p === "string" || typeof p === "number") return String(p);
        if (p && typeof p === "object") {
          const port = p.port || p.p;
          const service = p.service || p.name || p.proto;
          if (port && service) return `${port} (${service})`;
          return port ? String(port) : JSON.stringify(p);
        }
        return String(p);
      })
      .join(", ");
  };

  // Determine if SNMP is effectively working — look at REAL data, not just monitor_type field.
  // SNMP is considered working if ANY of these is true:
  //  - monitor_type contains "snmp"
  //  - ENTITY-MIB data was retrieved (v3.4.6+ connector)
  //  - sys_descr is populated (SNMP sysDescr OID)
  //  - device_class is not generic (i.e. SNMP fingerprint matched a profile)
  //  - vendor_metrics populated (vendor-specific SNMP OIDs read)
  //  - device has SNMP version configured in managed_devices (net.snmp_version)
  //  - profile_key assigned (Phase B profiles)
  const sources = card.data_sources || [];
  const hasEntityMib = sources.includes("entity_mib");
  const hasSysDescr = !!card.sys_descr_raw;
  const hasVendorMetrics = (card.vendor_metrics_summary?.count || 0) > 0;
  const hasProfile = !!id.profile_key && id.profile_key !== "generic";
  const hasSnmpConfig = !!net.snmp_version;
  const monitorHasSnmp = (st.monitor_type || "").toLowerCase().includes("snmp");
  const isSnmpMonitored = monitorHasSnmp || hasEntityMib || hasSysDescr || hasVendorMetrics || hasProfile || hasSnmpConfig;

  const sourcesBadges = {
    connector: { label: "Connector", color: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" },
    managed_devices: { label: "Manuale", color: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40" },
    cmdb: { label: "CMDB", color: "bg-indigo-500/20 text-indigo-300 border-indigo-500/40" },
    lifecycle: { label: "Lifecycle", color: "bg-violet-500/20 text-violet-300 border-violet-500/40" },
    redfish_ilo: { label: "iLO Redfish", color: "bg-orange-500/20 text-orange-300 border-orange-500/40" },
    device_profile: { label: "Profilo", color: "bg-blue-500/20 text-blue-300 border-blue-500/40" },
    entity_mib: { label: "ENTITY-MIB", color: "bg-teal-500/20 text-teal-300 border-teal-500/40" },
    sys_descr_parser: { label: "Parser SNMP", color: "bg-slate-500/20 text-slate-300 border-slate-500/40" },
  };

  return (
    <div className="space-y-3" data-testid="device-info-card">
      {/* Header riepilogo */}
      <div className="rounded-xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/5 to-transparent p-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <div className="flex items-center gap-2 mb-1">
              <Desktop size={18} className="text-cyan-400" weight="duotone" />
              {editingName ? (
                <div className="flex items-center gap-1.5 flex-1 min-w-0" data-testid="device-name-edit-row">
                  <input
                    type="text"
                    value={newName}
                    autoFocus
                    onChange={(e) => setNewName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveName();
                      if (e.key === "Escape") cancelEditName();
                    }}
                    disabled={savingName}
                    placeholder="Nome leggibile (es. USGFlex 100H)"
                    maxLength={200}
                    className="h-7 px-2 text-sm font-bold rounded border border-cyan-500/50 bg-[var(--bg-card)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 min-w-[200px] flex-1"
                    data-testid="device-name-input"
                  />
                  <button
                    onClick={saveName}
                    disabled={savingName || !newName.trim()}
                    className="h-7 px-2 rounded border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50 flex items-center gap-1 text-[11px]"
                    title="Salva (Enter)"
                    data-testid="device-name-save-btn"
                  >
                    {savingName ? <CircleNotch size={12} className="animate-spin" /> : <FloppyDisk size={12} weight="bold" />}
                    Salva
                  </button>
                  <button
                    onClick={cancelEditName}
                    disabled={savingName}
                    className="h-7 px-2 rounded border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-red-300 hover:border-red-500/40 flex items-center gap-1 text-[11px]"
                    title="Annulla (Esc)"
                    data-testid="device-name-cancel-btn"
                  >
                    <XIcon size={12} weight="bold" />
                  </button>
                </div>
              ) : (
                <>
                  <h3 className="text-base font-bold text-[var(--text-primary)]" data-testid="device-name-display">
                    {id.hostname || id.ip}
                  </h3>
                  <button
                    onClick={() => startEditName(id.hostname || "")}
                    title="Rinomina manualmente il dispositivo (il nuovo nome sara' usato ovunque in Argus)"
                    className="p-1 rounded hover:bg-cyan-500/15 text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                    data-testid="device-name-edit-btn"
                  >
                    <PencilSimple size={13} weight="bold" />
                  </button>
                </>
              )}
              {st.in_maintenance && (
                <span
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/40"
                  title={st.maintenance_window ? `Manutenzione: ${st.maintenance_window.title || ""}${st.maintenance_window.end_time ? " · fino a " + st.maintenance_window.end_time : ""}` : "In finestra di manutenzione — alert soppressi"}
                  data-testid="device-maintenance-badge">
                  <Wrench size={10} weight="fill" /> IN MANUTENZIONE
                </span>
              )}
              {(st.state_type === "soft" || st.degraded) && st.effective_status !== "offline" && !st.in_maintenance && (
                <span
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40"
                  title={`Stato SOFT (in verifica): ${st.failed_attempts || 0}/${st.max_check_attempts || 5} ping falliti. Nessun alert finche' non si conferma OFFLINE.`}
                  data-testid="device-soft-state-badge">
                  <Warning size={10} weight="fill" /> IN VERIFICA {st.failed_attempts || 0}/{st.max_check_attempts || 5}
                </span>
              )}
              {(() => {
                const eff = st.effective_status || (st.reachable === true ? "online" : st.reachable === false ? "offline" : null);
                if (st.unreachable_dependency) {
                  return (
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-orange-500/20 text-orange-300 border border-orange-500/40"
                      title={`Irraggiungibile: il padre ${st.parent_name || st.parent_ip || ""} è offline`}
                      data-testid="device-status-badge">
                      <NetworkSlash size={10} weight="fill" /> IRRAGGIUNGIBILE
                    </span>
                  );
                }
                const snmpOnly = eff === "online" && st.icmp_reachable === false && st.snmp_reachable === true;
                if (eff === "online") {
                  return (
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      title={st.live_reason_label || "Online"}
                      data-testid="device-status-badge"
                    >
                      <CheckCircle size={10} weight="fill" /> ONLINE{snmpOnly ? " (SNMP)" : ""}
                    </span>
                  );
                }
                if (eff === "stale") {
                  return (
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40"
                      title={st.live_reason_label || "Connector offline — stato incerto"}
                      data-testid="device-status-badge"
                    >
                      <Warning size={10} weight="fill" /> INCERTO
                    </span>
                  );
                }
                if (eff === "offline") {
                  return (
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-red-500/20 text-red-300 border border-red-500/40"
                      title="Nessuna risposta a ICMP ne' SNMP"
                      data-testid="device-status-badge">
                      <Warning size={10} weight="fill" /> OFFLINE
                    </span>
                  );
                }
                return null;
              })()}
            </div>
            <div className="flex items-center gap-3 text-xs text-[var(--text-secondary)] flex-wrap">
              <span className="font-mono">{id.ip}</span>
              {id.mac_primary && <span className="font-mono">MAC: {id.mac_primary}</span>}
              {id.vendor && <span>· <strong className="text-[var(--text-primary)]">{id.vendor}</strong></span>}
              {id.model && <span>{id.model}</span>}
              {id.serial_number && <span className="font-mono text-violet-300">S/N: {id.serial_number}</span>}
            </div>
            {card.client?.name && (
              <div className="text-xs text-cyan-400 mt-1">Cliente: {card.client.name}</div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* Porte Switch: visibile per qualsiasi device identificato come switch/router/network.
                Detection multi-segnale perche' molti device hanno device_type=null in DB ma
                sono palesemente network devices (es. Cisco Catalyst, HPE 5130, Aruba). */}
            {(() => {
              const dt = (id.device_type || id.class || "").toLowerCase();
              const modelL = (id.model || "").toLowerCase();
              const vendorL = (id.vendor || "").toLowerCase();
              const hostL = (id.hostname || "").toLowerCase();
              // Keyword match su modello / hostname
              // v3.8.34: incluso NAS — i NAS Synology/QNAP rispondono a SNMP ifTable
              // standard (MIB-II) e il connector raccoglie gia' i dati. Estendiamo
              // semplicemente la UI per mostrare il bottone anche per nas/server.
              const networkKeywords = [
                "switch", "router", "firewall", "gateway",
                "catalyst", "nexus", "meraki",                    // Cisco
                "procurve", "aruba", "5130", "5140", "5900",      // HPE/Aruba
                "ex2300", "ex3400", "ex4300", "srx",              // Juniper
                "fortigate", "fortiswitch", "fortiap",            // Fortinet
                "zyxel", "xgs", "gs1900", "gs2200",               // Zyxel
                "mikrotik", "routerboard", "ccr", "crs",          // MikroTik
                "unifi", "edgerouter", "edgeswitch", "usg",       // Ubiquiti
                "dgs-", "dxs-",                                   // D-Link
                "powerconnect", "n1500", "n2000", "n3000",        // Dell
                "huawei", "s5700", "s6700", "ar2200",             // Huawei
                "pfsense", "opnsense",                            // OSS firewall
                "synology", "qnap", "diskstation", "rackstation", "ts-",  // NAS
              ];
              const matchesKeyword = networkKeywords.some((k) => modelL.includes(k) || hostL.includes(k));
              const isSwitchLike =
                dt.includes("switch") || dt.includes("router") || dt.includes("firewall") ||
                dt === "nas" || dt === "network-device" || matchesKeyword;
              if (!isSwitchLike) return null;
              // Etichetta dinamica in base al tipo
              const btnLabel = dt === "firewall" ? "Porte firewall"
                : dt === "nas" ? "Interfacce NAS"
                : dt.includes("router") ? "Porte router"
                : "Porte switch";
              return (
                <button
                  onClick={() => {
                    // Workaround Radix Dialog portal: chiudi PRIMA (animazione close ~150ms),
                    // poi naviga. Se navighi subito, il portal overlay rimane "appiccicato"
                    // sopra la nuova pagina perche' la Dialog non ha tempo di cleanup.
                    const url = `/switch-ports/${encodeURIComponent(id.ip)}`;
                    if (onClose) onClose();
                    setTimeout(() => navigate(url), 80);
                  }}
                  title={`${btnLabel} (interfacce ifTable SNMP, traffico Rx/Tx, neighbor LLDP, flap history)`}
                  className="px-2.5 py-1.5 text-[11px] rounded-md border border-indigo-500/40 bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/20 hover:border-indigo-400 flex items-center gap-1.5 transition-colors"
                  data-testid="device-info-card-switch-ports-btn">
                  <NetworkSlash size={13} weight="duotone" />
                  <span className="hidden sm:inline">{btnLabel}</span>
                </button>
              );
            })()}
            <button
              onClick={() => setShowAllMetrics(true)}
              title="Mostra tutte le metriche raccolte"
              className="px-2.5 py-1.5 text-[11px] rounded-md border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 hover:border-cyan-400 flex items-center gap-1.5 transition-colors"
              data-testid="device-info-card-all-metrics-btn">
              <ChartLineUp size={13} weight="duotone" />
              <span className="hidden sm:inline">Tutte le metriche</span>
              {(card.vendor_metrics_summary?.count || 0) > 0 && (
                <span className="px-1 py-0 text-[9px] rounded bg-cyan-400/20 font-mono">{card.vendor_metrics_summary.count}</span>
              )}
            </button>
            <span
              className="hidden md:inline-flex items-center gap-1 px-2 py-1 text-[10px] rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
              title="La scheda si aggiorna automaticamente ogni 30 secondi"
              data-testid="device-info-card-live-indicator">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              LIVE{lastUpdated ? ` · ${new Date(lastUpdated).toLocaleTimeString("it-IT")}` : ""}
            </span>
            <button onClick={() => fetchCard()} title="Aggiorna ora" className="p-2 rounded-md hover:bg-white/5 text-[var(--text-secondary)]" data-testid="device-info-card-refresh">
              <ArrowsClockwise size={14} />
            </button>
            {/* v2026-06-02: Re-poll SNMP + auto-diagnosi se fallisce */}
            <button
              onClick={forceSnmpPoll}
              disabled={snmpPolling}
              title="Forza re-poll SNMP via agent online (con diagnosi automatica se fallisce)"
              className="px-2.5 py-1.5 text-[11px] rounded-md border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 hover:border-emerald-400 flex items-center gap-1.5 transition-colors disabled:opacity-50"
              data-testid="device-info-card-snmp-repoll">
              <ArrowsClockwise size={13} weight="duotone" className={snmpPolling ? "animate-spin" : ""} />
              <span className="hidden sm:inline">{snmpPolling ? "Polling…" : "Re-poll SNMP"}</span>
            </button>
            {onClose && (
              <button onClick={onClose} className="px-3 py-1 text-xs rounded-md border border-[var(--bg-border)] hover:bg-white/5" data-testid="device-info-card-close">
                Chiudi
              </button>
            )}
          </div>
        </div>
        {/* Data sources badges */}
        <div className="flex items-center gap-1 flex-wrap mt-3">
          <span className="text-[10px] uppercase text-[var(--text-secondary)]">Dati raccolti da:</span>
          {(card.data_sources_status || (card.data_sources || []).map(s => ({ key: s, present: true }))).map((s) => {
            const b = sourcesBadges[s.key] || { label: s.key, color: "bg-slate-500/20 text-slate-300 border-slate-500/40" };
            if (s.present) {
              return (
                <span key={s.key} className={`px-2 py-0.5 text-[10px] rounded border ${b.color}`} data-testid={`source-${s.key}`}>
                  {b.label}
                </span>
              );
            }
            // Fonte MANCANTE: badge grigio "spento" con tooltip diagnostico
            return (
              <span
                key={s.key}
                className="px-2 py-0.5 text-[10px] rounded border border-dashed border-[var(--bg-border)] text-[var(--text-muted)] opacity-50 hover:opacity-100 cursor-help transition-opacity"
                title={s.reason || "Fonte non attiva"}
                data-testid={`source-missing-${s.key}`}
              >
                {b.label} <span className="text-[8px]">⊘</span>
              </span>
            );
          })}
          {hypervState && (
            <span
              className={`px-2 py-0.5 text-[10px] rounded border font-bold ${hypervState === "Running" ? "bg-indigo-500/20 text-indigo-200 border-indigo-500/40" : "bg-slate-500/20 text-slate-300 border-slate-500/40"}`}
              title={`Hyper-V${hypervHost ? ` (host ${hypervHost})` : ""}: la VM risulta ${hypervState} a livello hypervisor`}
              data-testid="source-hyperv"
            >
              🖥️ Hyper-V: {hypervState === "Running" ? "ACCESA" : hypervState === "Off" ? "SPENTA" : hypervState.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {!compact && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {/* Identity */}
          <Section title="Identità" icon={Info} testid="info-section-identity" color="text-cyan-300">
            <Field label="Hostname" value={id.hostname} mono />
            <Field label="IP" value={id.ip} mono highlight />
            <Field label="MAC primario" value={id.mac_primary} mono />
            {!id.mac_primary && (
              <div className="py-1 text-[10px] text-amber-300/80 italic">
                MAC non disponibile — verifica che il connector abbia accesso SNMP/ARP al router/switch del segmento
              </div>
            )}
            {id.mac_primary && id.mac_source === "arp-cache" && (
              <div className="py-1 text-[10px] text-[var(--text-secondary)] italic">
                via ARP cache da {id.mac_arp_source_ip || "vicino"}
              </div>
            )}
            <Field label="MAC totali" value={id.mac_count || null} />
            <Field label="Vendor" value={id.vendor} highlight />
            <Field label="Modello" value={id.model} highlight />
            <Field label="Serial Number" value={id.serial_number} mono />
            <Field label="Asset Tag" value={id.asset_tag} mono />
            <Field label="Tipo device" value={id.device_type} />
            <Field label="Profilo" value={id.profile_key} />
            <Field label="OS Family" value={id.os_family} />
          </Section>

          {/* Firmware & Security */}
          <Section title="Firmware & CVE" icon={Shield} testid="info-section-firmware" color="text-violet-300">
            <Field label="Firmware" value={fw.current} mono highlight />
            <Field label="BIOS" value={fw.bios} mono />
            {fwComp && (
              <>
                <Field label="Compliance" value={fwComp.status?.toUpperCase()} highlight />
                <Field label="CVE aperte" value={fwComp.cve_count} />
                <Field label="Severity" value={fwComp.severity} />
              </>
            )}
            {fwComp?.advisory_url && (
              <div className="pt-2">
                <a href={fwComp.advisory_url} target="_blank" rel="noopener noreferrer"
                   className="text-[11px] text-cyan-400 hover:underline">
                  → Vendor advisory
                </a>
              </div>
            )}
          </Section>

          {/* Status */}
          <Section title="Stato Live" icon={ArrowsClockwise} testid="info-section-status" color="text-emerald-300">
            <Field label="Stato effettivo" value={st.effective_status ? st.effective_status.toUpperCase() : (st.reachable === true ? "ONLINE" : st.reachable === false ? "OFFLINE" : null)} highlight />
            {st.live_reason_label && <Field label="Motivo" value={st.live_reason_label} />}
            <Field label="ICMP (ping)" value={st.icmp_reachable === true ? "Risponde" : st.icmp_reachable === false ? "Nessuna risposta" : "n/d"} />
            <Field label="SNMP" value={st.snmp_reachable === true ? (st.snmp_fresh ? "Risponde (fresco)" : "Risponde (stale)") : st.snmp_reachable === false ? "Nessuna risposta" : "n/d"} />
            {st.snmp_last_check_at && <Field label="Ultimo check SNMP" value={fmtDateTime(st.snmp_last_check_at)} />}
            <Field label="Conferma stato" value={st.state_type === "soft" || st.degraded ? `SOFT — in verifica (${st.failed_attempts || 0}/${st.max_check_attempts || 5})` : "HARD — confermato"} highlight={st.state_type === "soft" || st.degraded} />
            <div className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0" data-testid="device-mca-row">
              <span className="text-xs text-[var(--text-secondary)]">Soglia tentativi (Soft→Hard)</span>
              <span className="inline-flex items-center gap-1">
                <input
                  type="number" min={1} max={20}
                  value={mcaInput !== "" ? mcaInput : (st.max_check_attempts ?? "")}
                  onChange={(e) => setMcaInput(e.target.value)}
                  className="w-14 bg-white/5 border border-white/10 rounded px-1.5 py-0.5 text-xs text-right text-[var(--text-primary)]"
                  data-testid="device-mca-input" />
                <button
                  onClick={saveMaxCheckAttempts} disabled={savingMca}
                  className="px-2 py-0.5 text-[10px] rounded-md bg-blue-500/20 text-blue-300 border border-blue-500/40 hover:bg-blue-500/30 disabled:opacity-50"
                  title="Quanti ping falliti consecutivi prima di confermare OFFLINE. Vuoto = default globale."
                  data-testid="device-mca-save">
                  {savingMca ? "..." : "Salva"}
                </button>
              </span>
            </div>
            <div className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0" data-testid="device-parent-row">
              <span className="text-xs text-[var(--text-secondary)]">
                Padre (dipendenza)
                {st.parent_ip && (
                  <span className={`ml-1 ${st.parent_status === "offline" ? "text-orange-400" : "text-emerald-400"}`}>
                    · {st.parent_name || st.parent_ip} ({st.parent_status === "offline" ? "OFFLINE" : st.parent_status || "?"})
                  </span>
                )}
              </span>
              <span className="inline-flex items-center gap-1">
                <input
                  type="text" placeholder="IP switch/gateway (vuoto = auto)"
                  value={parentInput !== "" ? parentInput : (st.parent_ip ?? "")}
                  onChange={(e) => setParentInput(e.target.value)}
                  className="w-32 bg-white/5 border border-white/10 rounded px-1.5 py-0.5 text-xs text-right text-[var(--text-primary)]"
                  data-testid="device-parent-input" />
                <button
                  onClick={saveParent} disabled={savingParent}
                  className="px-2 py-0.5 text-[10px] rounded-md bg-blue-500/20 text-blue-300 border border-blue-500/40 hover:bg-blue-500/30 disabled:opacity-50"
                  title="IP del device a monte. Se il padre è offline, questo device è 'irraggiungibile' e non genera alert. Vuoto = auto da topologia."
                  data-testid="device-parent-save">
                  {savingParent ? "..." : "Salva"}
                </button>
              </span>
            </div>
            <Field label="Monitor tipo" value={isSnmpMonitored && !monitorHasSnmp ? `${st.monitor_type || "http"} + snmp (attivo)` : st.monitor_type} highlight={isSnmpMonitored} />
            <Field label="Ultimo poll" value={fmtDateTime(st.last_poll)} />
            <Field label="Ultimo update" value={fmtDateTime(st.last_update)} />
            <Field label="Uptime (gg)" value={st.uptime_days} />
            <Field label="Connector" value={st.connector_hostname} mono />
            {st.unreachable_since && st.effective_status === "offline" && <Field label="Offline da" value={fmtDateTime(st.unreachable_since)} />}
          </Section>

          {/* Hardware */}
          <Section title="Hardware" icon={Cpu} testid="info-section-hardware" color="text-orange-300">
            <Field label="CPU %" value={hw.cpu_usage} />
            <Field label="Memoria %" value={hw.memory_usage} />
            <Field label="Temperatura °C" value={hw.temperature} />
            <Field label="Power (W)" value={hw.power_watts} />
            <Field label="Fan count" value={hw.fan_count} />
            <Field label="PSU count" value={hw.psu_count} />
            <Field label="Sensori temp." value={hw.temp_sensor_count} />
            <Field label="Dischi (storage)" value={hw.storage_drive_count} />
            <Field label="DIMM RAM" value={hw.memory_dimm_count} />
            <Field label="NIC count" value={hw.nic_count} />
            {hw.firewall_sessions != null && <Field label="Sessioni FW" value={hw.firewall_sessions.toLocaleString("it-IT")} />}
            <Field label="Flash usage %" value={hw.firewall_flash_usage_pct} />

            {/* PSU/Fan structured states (switch HPE/H3C) */}
            {hw.psu_states && Object.keys(hw.psu_states).length > 0 && (
              <div className="mt-2 pt-2 border-t border-[var(--bg-border)]/50 space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">Power Supplies</span>
                {Object.entries(hw.psu_states).map(([idx, st]) => {
                  const n = Number(st);
                  const isValid = Number.isFinite(n) && n > 0;  // 0/empty/NaN = sensor not reporting
                  return (
                    <div key={`psu${idx}`} className="flex items-center justify-between text-[11px]">
                      <span className="text-[var(--text-secondary)]">PSU {idx}</span>
                      <span className={`font-mono ${!isValid ? "text-neutral-400" : n <= 2 ? "text-emerald-400" : "text-red-400"}`}>
                        {!isValid ? "N/D" : n <= 2 ? "OK" : `FAULT (codice ${n})`}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
            {hw.fan_states && Object.keys(hw.fan_states).length > 0 && (
              <div className="mt-2 pt-2 border-t border-[var(--bg-border)]/50 space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">Fans</span>
                {Object.entries(hw.fan_states).map(([idx, st]) => {
                  const n = Number(st);
                  const isValid = Number.isFinite(n) && n > 0;
                  return (
                    <div key={`fan${idx}`} className="flex items-center justify-between text-[11px]">
                      <span className="text-[var(--text-secondary)]">Fan {idx}</span>
                      <span className={`font-mono ${!isValid ? "text-neutral-400" : n <= 2 ? "text-emerald-400" : "text-red-400"}`}>
                        {!isValid ? "N/D" : n <= 2 ? "OK" : `FAULT (codice ${n})`}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </Section>

          {/* Network */}
          <Section title="Rete" icon={Globe} testid="info-section-network" color="text-sky-300">
            <Field label="Interfacce" value={net.interfaces_count || null} />
            <Field label="Porte aperte" value={formatOpenPorts(net.open_ports)} mono />
            <Field label="Ping (ms)" value={net.ping_ms} />
            {net.ping_stats?.avg != null && <Field label="Ping avg" value={`${net.ping_stats.avg}ms`} />}
            {net.ping_stats?.packet_loss != null && <Field label="Packet loss" value={`${net.ping_stats.packet_loss}%`} />}
            <Field label="Web Console" value={net.web_console_url} mono />
            <Field label="Porta WebUI" value={net.web_console_port} />
            <Field label="Web title" value={net.web_console_title} />
            <Field label="SNMP version" value={net.snmp_version} />
            <Field label="SNMP port" value={net.snmp_port} />
          </Section>

          {/* Lifecycle */}
          {lc && (
            <Section title="Lifecycle & Warranty" icon={Calendar} testid="info-section-lifecycle" color="text-indigo-300">
              <Field label="Acquisto" value={fmtDate(lc.purchase_date)} />
              <Field label="Fine garanzia" value={fmtDate(lc.warranty_end)} highlight={lc.risk_band === "high"} />
              <Field label="Fine manutenzione" value={fmtDate(lc.maintenance_end)} />
              <Field label="EOL" value={fmtDate(lc.eol_date)} />
              <Field label="EOSL" value={fmtDate(lc.eosl_date)} />
              <Field label="Risk score" value={lc.risk_score} highlight={lc.risk_band === "high"} />
              <Field label="Risk band" value={lc.risk_band?.toUpperCase()} highlight={lc.risk_band === "high"} />
              <Field label="Criticità" value={lc.criticality} />
              <Field label="Contratto" value={lc.contract_number} mono />
              <Field label="Supporto tier" value={lc.vendor_support_tier} />
            </Section>
          )}

          {/* Location */}
          {Object.values(loc).some((v) => v != null && v !== "") && (
            <Section title="Ubicazione" icon={MapPin} testid="info-section-location" color="text-rose-300">
              <Field label="Site" value={loc.site} />
              <Field label="Edificio" value={loc.building} />
              <Field label="Piano" value={loc.floor} />
              <Field label="Stanza" value={loc.room} />
              <Field label="Rack" value={loc.rack} />
              <Field label="U" value={loc.rack_unit} />
              <Field label="Responsabile" value={loc.owner} />
              <Field label="Costo mensile €" value={loc.cost_monthly} />
              {loc.notes && <Field label="Note" value={loc.notes} />}
            </Section>
          )}

          {/* Vendor metrics */}
          {card.vendor_metrics_summary?.count > 0 && (
            <Section title="Metriche Vendor" icon={HardDrives} testid="info-section-vendor-metrics" color="text-amber-300">
              <div className="text-xs text-[var(--text-secondary)] mb-1">
                {card.vendor_metrics_summary.count} metriche raccolte
              </div>
              <div className="flex flex-wrap gap-1">
                {card.vendor_metrics_summary.keys.map((k) => (
                  <span key={k} className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-[10px] font-mono text-amber-200">
                    {k}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </div>
      )}

      {/* Warning: device monitored only via HTTP (no SNMP telemetry) */}
      {!isSnmpMonitored && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 flex items-start gap-3" data-testid="warning-no-snmp">
          <Warning size={18} className="text-amber-400 flex-shrink-0 mt-0.5" weight="fill" />
          <div className="flex-1">
            <h4 className="text-sm font-semibold text-amber-200">Monitoraggio limitato</h4>
            <p className="text-xs text-amber-100/80 mt-0.5">
              Questo dispositivo è monitorato solo via <code className="px-1 py-0.5 bg-black/30 rounded font-mono">{st.monitor_type || "ping/http"}</code>.
              Per raccogliere informazioni dettagliate su <strong>firmware, HDD/RAID, CPU, temperatura, dischi SMART, volumi</strong>,
              configura anche l'<strong>accesso SNMP</strong> sul dispositivo e aggiungi la community nel pannello Vault del cliente.
            </p>
            <p className="text-xs text-amber-100/60 mt-1">
              Synology: Pannello di Controllo → Terminal & SNMP → Abilita servizio SNMP (v2c) → community (es: <code className="font-mono bg-black/30 px-1 rounded">public</code> o custom).
            </p>
          </div>
        </div>
      )}

      {/* Warning B: SNMP configurato ma nessun dato dettagliato raccolto.
          v2026-06-23: skip questo banner se il device è dichiarato unreachable
          (`st.reachable === false`). Prima il messaggio "il connector sta
          comunicando via SNMP" era ingannevole su device offline: il connector
          NON sta comunicando, sta solo "tentando". Il banner deve mostrarsi
          solo quando SNMP rispondeva ma le metriche dettagliate mancano (cosa
          tipica di profilo SNMP errato o community con vista ristretta). */}
      {isSnmpMonitored && st.reachable !== false && !hasEntityMib && !hasVendorMetrics && hw.cpu_usage == null && hw.memory_usage == null && hw.temperature == null && !fw.current && (
        <div className="rounded-lg border border-sky-500/40 bg-sky-500/10 p-3 flex items-start gap-3" data-testid="warning-snmp-no-data">
          <Info size={18} className="text-sky-400 flex-shrink-0 mt-0.5" weight="duotone" />
          <div className="flex-1">
            <h4 className="text-sm font-semibold text-sky-200">SNMP configurato ma dati limitati</h4>
            <p className="text-xs text-sky-100/80 mt-0.5">
              Il connector sta comunicando via SNMP con questo dispositivo ({net.snmp_version || "v2c"} su porta {net.snmp_port || 161}),
              ma <strong>non ha ancora raccolto metriche dettagliate</strong> (firmware, HDD, CPU, RAM, temperatura).
            </p>
            <p className="text-xs text-sky-100/70 mt-1">
              Cosa verificare (in ordine):
            </p>
            <ul className="text-xs text-sky-100/70 mt-0.5 ml-4 list-disc space-y-0.5">
              <li>La <strong>community SNMP</strong> del device risponde in read-only con vista completa — prova da un terminale sul connector: <code className="font-mono bg-black/30 px-1 rounded">snmpwalk -v2c -c &lt;community&gt; {net.ip || "IP"} .1.3.6.1.2.1.1</code></li>
              <li>Il <strong>profilo vendor</strong> è associato al dispositivo: clicca <em>Configura profilo</em> nella tabella Dispositivi e scegli il profilo corretto (Synology DSM, HPE Comware, APC UPS, generic UPS, ecc.)</li>
              <li>Sul <strong>device vendor</strong> l'SNMP è abilitato ed espone le MIB avanzate (es. Synology: Pannello di Controllo → Terminal &amp; SNMP → Abilita SNMPv2c)</li>
              <li>Attendi 1-2 cicli di poll (~60-120s) dopo aver associato il profilo — il ciclo vendor-specific parte solo se il profilo matcha.</li>
            </ul>
          </div>
        </div>
      )}

      {/* Vendor-specific detailed panels (UPS battery/power, Synology disks/RAID,
          Fortinet HA/FWsessions, Comware CPU/Temp, APC, MikroTik, Cisco, QNAP, Zyxel).
          Il componente fa self-fetch e si auto-renderizza in base al profilo. */}
      <ErrorBoundary label="pannello vendor (telemetria)">
        <VendorDetailsPanel deviceIp={deviceIp} />
      </ErrorBoundary>

      {/* Synology disks & RAID section (when vendor_metrics has them) */}
      {card.identity?.vendor?.toLowerCase().includes("synology") && card.vendor_metrics_summary?.count > 0 && (
        <ErrorBoundary label="dettaglio Synology DSM">
          <SynologyDetailSection deviceIp={card.device_ip} />
        </ErrorBoundary>
      )}

      {card.sys_descr_raw && (
        <details className="rounded-lg border border-[var(--bg-border)] bg-black/20 p-2">
          <summary className="text-[10px] uppercase text-[var(--text-secondary)] cursor-pointer">
            sys_descr raw (debug SNMP)
          </summary>
          <pre className="text-[10px] font-mono text-slate-300 mt-2 whitespace-pre-wrap break-all">
            {card.sys_descr_raw}
          </pre>
        </details>
      )}

      {/* "Tutte le metriche" sub-dialog */}
      {showAllMetrics && (
        <ErrorBoundary
          label="dialog Tutte le metriche"
          hint="Possibile payload SNMP troppo grande o malformato. Chiudi la modale e riprova, oppure usa la ricerca per filtrare le chiavi."
        >
          <AllMetricsDialog
            deviceIp={deviceIp}
            deviceLabel={card.identity?.hostname || card.device_ip}
            onClose={() => setShowAllMetrics(false)}
          />
        </ErrorBoundary>
      )}
    </div>
  );
}

/** Synology disks + RAID live panel (lazy loaded via vendor-details endpoint) */
function SynologyDetailSection({ deviceIp }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const token = localStorage.getItem("noc_token");

  useEffect(() => {
    setLoading(true);
    axios.get(`${API}/api/devices/by-ip/${deviceIp}/vendor-details`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceIp]);

  if (loading) return null;
  if (!data) return null;

  const syn = data.synology || data.vendor_metrics || {};
  const disks = syn.disks || syn.diskStatus || [];
  const raids = syn.raids || syn.raidStatus || [];
  const volumes = syn.volumes || [];
  const dsmVersion = syn.dsm_version || syn.systemVersion || syn.modelName;
  const systemStatus = syn.system_status || syn.systemStatus;
  const temp = syn.temperature;

  const hasContent = (Array.isArray(disks) && disks.length) ||
                     (Array.isArray(raids) && raids.length) ||
                     (Array.isArray(volumes) && volumes.length) ||
                     dsmVersion || systemStatus;

  if (!hasContent) return null;

  return (
    <div className="rounded-xl border border-teal-500/30 bg-gradient-to-br from-teal-500/5 to-transparent p-4" data-testid="synology-detail">
      <div className="flex items-center gap-2 mb-3">
        <HardDrives size={16} className="text-teal-400" weight="duotone" />
        <h4 className="text-sm font-bold uppercase tracking-wide text-teal-300">Synology DSM — Dischi & RAID</h4>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
        {dsmVersion && (
          <div className="rounded bg-black/20 border border-[var(--bg-border)] p-2">
            <div className="text-[10px] uppercase text-[var(--text-secondary)]">DSM Version</div>
            <div className="text-xs font-mono text-teal-300">{dsmVersion}</div>
          </div>
        )}
        {systemStatus && (
          <div className="rounded bg-black/20 border border-[var(--bg-border)] p-2">
            <div className="text-[10px] uppercase text-[var(--text-secondary)]">System Status</div>
            <div className={`text-xs font-bold ${systemStatus === "Normal" || systemStatus === 1 ? "text-emerald-300" : "text-amber-300"}`}>
              {safe(systemStatus)}
            </div>
          </div>
        )}
        {temp != null && (
          <div className="rounded bg-black/20 border border-[var(--bg-border)] p-2">
            <div className="text-[10px] uppercase text-[var(--text-secondary)]">System Temp</div>
            <div className="text-xs font-bold text-orange-300">{safe(temp)}°C</div>
          </div>
        )}
        <div className="rounded bg-black/20 border border-[var(--bg-border)] p-2">
          <div className="text-[10px] uppercase text-[var(--text-secondary)]">Dischi / RAID / Volumi</div>
          <div className="text-xs font-bold text-cyan-300">{(disks?.length || 0)} / {(raids?.length || 0)} / {(volumes?.length || 0)}</div>
        </div>
      </div>

      {Array.isArray(disks) && disks.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs font-semibold text-[var(--text-primary)] mb-1.5">Dischi</h5>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead className="bg-black/30 border-b border-[var(--bg-border)]">
                <tr className="text-left text-[var(--text-secondary)]">
                  <th className="px-2 py-1">#</th>
                  <th className="px-2 py-1">Modello</th>
                  <th className="px-2 py-1">Status</th>
                  <th className="px-2 py-1">SMART</th>
                  <th className="px-2 py-1">Temp</th>
                  <th className="px-2 py-1">Role</th>
                </tr>
              </thead>
              <tbody>
                {disks.map((d, i) => (
                  <tr key={i} className="border-b border-[var(--bg-border)]/50">
                    <td className="px-2 py-1 text-[var(--text-secondary)] font-mono">{d.index ?? i + 1}</td>
                    <td className="px-2 py-1 text-[var(--text-primary)] font-mono">{safe(d.model || d.diskModel)}</td>
                    <td className="px-2 py-1">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] uppercase ${d.status === "Normal" || d.status === 1 ? "bg-emerald-500/20 text-emerald-300" : "bg-red-500/20 text-red-300"}`}>
                        {safe(d.status)}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-[var(--text-primary)]">{safe(d.smart_status || d.smart)}</td>
                    <td className="px-2 py-1 text-orange-300">{d.temp != null ? `${safe(d.temp)}°C` : "—"}</td>
                    <td className="px-2 py-1 text-[var(--text-secondary)]">{safe(d.role || d.type)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {Array.isArray(raids) && raids.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs font-semibold text-[var(--text-primary)] mb-1.5">RAID</h5>
          <div className="flex flex-wrap gap-1.5">
            {raids.map((r, i) => (
              <div key={i} className="rounded bg-black/30 border border-[var(--bg-border)] p-2 text-[10px]">
                <div className="font-mono text-[var(--text-primary)]">{safe(r.name) !== "—" ? safe(r.name) : `RAID ${i + 1}`}</div>
                <div className={`${r.status === "Normal" || r.status === 1 ? "text-emerald-300" : "text-amber-300"}`}>
                  {safe(r.status || r.state)}
                </div>
                {r.level && <div className="text-[var(--text-secondary)]">Level: {safe(r.level)}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {Array.isArray(volumes) && volumes.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold text-[var(--text-primary)] mb-1.5">Volumi</h5>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {volumes.map((v, i) => {
              const usedPct = v.used_pct ?? (v.total && v.used ? Math.round((v.used / v.total) * 100) : null);
              return (
                <div key={i} className="rounded bg-black/30 border border-[var(--bg-border)] p-2 text-[10px]">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[var(--text-primary)]">{safe(v.name || v.id) !== "—" ? safe(v.name || v.id) : `Volume ${i + 1}`}</span>
                    <span className={`${v.status === "Normal" || v.status === 1 ? "text-emerald-300" : "text-amber-300"}`}>{safe(v.status)}</span>
                  </div>
                  {usedPct != null && (
                    <div className="mt-1">
                      <div className="h-1.5 bg-black/50 rounded overflow-hidden">
                        <div className={`h-full ${usedPct > 90 ? "bg-red-500" : usedPct > 75 ? "bg-amber-500" : "bg-emerald-500"}`}
                          style={{ width: `${usedPct}%` }}></div>
                      </div>
                      <div className="text-[9px] text-[var(--text-secondary)] mt-0.5">{usedPct}% usato</div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function _unused() {
  return null;
}
