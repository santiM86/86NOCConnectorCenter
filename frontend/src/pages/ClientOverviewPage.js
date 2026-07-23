import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  ArrowLeft, HardDrives, Globe, Printer, Database, ShieldCheck,
  Lightning, WifiHigh, WifiSlash, PlugsConnected, CaretDown,
  CheckCircle, Warning, ArrowClockwise, Bell, BellSlash, ChartLine, Monitor, Cpu,
  Plus, Trash, Lock, MagnifyingGlass, Info, PencilSimple, NetworkSlash,
  Phone, DeviceMobile, Desktop, Network, Key, Star, Check,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import VaultPage from "./VaultPage";
import DeviceInfoCard from "@/components/DeviceInfoCard";
import ErrorBoundary from "@/components/ErrorBoundary";
import { canOpenWebConsole, defaultWebPort } from "@/components/WebConsole";
import { useWebConsoleTabs } from "@/components/WebConsoleTabs";
import ILoLiveMetrics from "@/components/ILoLiveMetrics";
import HealthBadge from "@/components/HealthBadge";
import { DeviceEditModal } from "@/components/DeviceEditModal";
import DiscoveryPage from "./DiscoveryPage";
import VulnerabilityPage from "./VulnerabilityPage";
import LanScannerPage from "./LanScannerPage";
import WanClientTab from "@/components/WanClientTab";
import {
  ProbeVendorButton, TryDefaultCredsButton, BulkCredentialsDialog,
  HealthScoreWidget, LifecyclePanel, IloEventsButton,
  HyperVPanel, VCenterPanel,
} from "@/components/ServerIntelligenceHub";
import BridgeHealthWidget from "@/components/BridgeHealthWidget";
import SafeBoundary from "@/components/SafeBoundary";
import { useSortableTable, SortableTh } from "@/utils/tableSort";
import { macroOf, macroLabel, MACRO_DEFS, pickDeviceName } from "@/utils/deviceCategory";

const STATUS_COLOR = { online: "#34C759", offline: "#FF3B30", active: "#FFCC00", degraded: "#FF9500", unknown: "#555" };
// v2026-02-28 SAFETY: getter difensivo. Se per qualche motivo STATUS_COLOR
// non e' in scope (commit intermedio rotto / minifier overzelo), getStatusColor
// ritorna comunque un fallback grigio invece di lanciare ReferenceError.
function getStatusColor(status) {
  try {
    return (STATUS_COLOR && STATUS_COLOR[status]) || "#555";
  } catch (e) {
    return "#555";
  }
}

export default function ClientOverviewPage() {
  const { clientId } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);
  const [devices, setDevices] = useState([]);
  const [wanTargets, setWanTargets] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [printers, setPrinters] = useState([]);
  const [backups, setBackups] = useState([]);
  const [backupSummary, setBackupSummary] = useState({ m365: null, vm: null });
  const [connector, setConnector] = useState(null);
  const [iloHealth, setIloHealth] = useState([]);
  const [hwHealth, setHwHealth] = useState(null);
  // v3.8.41 watchdog: stato lan-scan per banner "Scanner inattivo"
  const [scanHealth, setScanHealth] = useState({ connectors: [], any_stale: false });
  // v4.15.x: diagnosi auto delle cause di offline (rileva v3 zombie, master morto, ecc.)
  const [diagnosis, setDiagnosis] = useState(null);
  // v4.17.x: coverage subnet per mini-card header
  const [coverage, setCoverage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  const STATUS_COLOR = { online: "#34C759", offline: "#FF3B30", active: "#FFCC00", degraded: "#FF9500", unknown: "#555" };
  const fetchAll = useCallback(async () => {
    try {
      const [clientRes, devRes, wanRes, alertRes] = await Promise.allSettled([
        axios.get(`${API}/clients/${clientId}`),
        axios.get(`${API}/devices?client_id=${clientId}`),
        axios.get(`${API}/external-monitor/status`),
        axios.get(`${API}/alerts?client_id=${clientId}&status=active&limit=50`),
      ]);
      if (clientRes.status === "fulfilled") setClient(clientRes.value.data);
      if (devRes.status === "fulfilled") setDevices(devRes.value.data || []);
      if (wanRes.status === "fulfilled") {
        const wanData = wanRes.value.data;
        const clientTargets = (wanData.targets || []).filter(t => t.client_id === clientId);
        const results = wanData.results || [];
        setWanTargets(clientTargets.map(t => ({ ...t, result: results.find(r => r.target_id === t.id) })));
      }
      if (alertRes.status === "fulfilled") setAlerts(alertRes.value.data || []);
    } catch (e) { console.error(e); }
    // Fetch printers, backup, connector separately (may not have client_id filter)
    try {
      const connRes = await axios.get(`${API}/connector/status`);
      const connectors = connRes.data?.connectors || connRes.data || [];
      const found = (Array.isArray(connectors) ? connectors : []).find(c => c.client_id === clientId);
      setConnector(found || null);
    } catch {}
    // v3.8.41: scan-health per banner watchdog
    try {
      const shRes = await axios.get(`${API}/connectors/scan-health/${clientId}`);
      setScanHealth(shRes.data || { connectors: [], any_stale: false });
    } catch {}
    // v4.15.x: auto-diagnose offline (rileva zombie v3 / master morto / coverage gap)
    try {
      const diagRes = await axios.get(`${API}/clients/${clientId}/devices/diagnose-offline`);
      setDiagnosis(diagRes.data || null);
    } catch {}
    // v4.17.x: coverage subnet
    try {
      const covRes = await axios.get(`${API}/clients/${clientId}/agents-coverage`);
      setCoverage(covRes.data || null);
    } catch {}
    try {
      const printRes = await axios.get(`${API}/printers/${clientId}`);
      setPrinters(printRes.data || []);
    } catch {}
    try {
      const bkpRes = await axios.get(`${API}/backup/dashboard/${clientId}`);
      const data = bkpRes.data;
      setBackups(Array.isArray(data) ? data : (data?.jobs || data?.backups || []));
    } catch {}
    // Aggregati Hornetsecurity (365 + VM) per la card Quick Stats
    try {
      const [m365Res, vmRes] = await Promise.allSettled([
        axios.get(`${API}/clients/${clientId}/backup/hornetsecurity/status`),
        axios.get(`${API}/clients/${clientId}/backup/vmbackup/status`),
      ]);
      const m365 = m365Res.status === "fulfilled" ? m365Res.value.data : null;
      const vm = vmRes.status === "fulfilled" ? vmRes.value.data : null;
      setBackupSummary({ m365, vm });
    } catch {}
    try {
      const iloRes = await axios.get(`${API}/clients/${clientId}/ilo-health`);
      setIloHealth(iloRes.data || []);
    } catch {}
    try {
      const hwRes = await axios.get(`${API}/tv/clients/${clientId}/hardware-health`);
      setHwHealth(hwRes.data || null);
    } catch {}
    setLoading(false);
  }, [clientId]);

  useEffect(() => { fetchAll(); const i = setInterval(fetchAll, 30000); return () => clearInterval(i); }, [fetchAll]);

  // v2026-02-14: ascolto evento globale "argus:device-renamed" emesso da
  // DeviceInfoCard quando l'admin rinomina manualmente un device.
  // Aggiorna la lista locale + il bersaglio del Dialog senza aspettare
  // il prossimo poll automatico.
  useEffect(() => {
    const handler = (ev) => {
      const { device_ip, new_name } = ev.detail || {};
      if (!device_ip || !new_name) return;
      // Patch optimistico devices array
      setDevices(prev => prev.map(d =>
        d.ip_address === device_ip
          ? { ...d, name: new_name, hostname: new_name, name_locked: true }
          : d
      ));
      // Se il rename riguarda il device aperto nel Dialog, aggiorna anche
      // il titolo immediatamente.
      setInfoCardName(prev => {
        // Solo se stiamo guardando proprio quel device
        return device_ip ? new_name : prev;
      });
      // Forza fetchAll per coerenza con backend (display_name resolver)
      fetchAll();
    };
    window.addEventListener("argus:device-renamed", handler);
    return () => window.removeEventListener("argus:device-renamed", handler);
  }, [fetchAll]);

  if (loading) return <div className="p-6 text-center text-[var(--text-muted)]">Caricamento...</div>;
  if (!client) return <div className="p-6 text-center text-[var(--text-muted)]">Cliente non trovato</div>;

  // v4.17.x: status normalizzato lato backend ("active" → "online").
  // Ora panoramica e tabella usano la STESSA definizione di online.
  const onlineDevices = devices.filter(d => d.status === "online" && !/^(22[4-9]|23\d|255)\./.test(d.ip_address || "")).length;
  // v3.8.40: offlineDevices conta solo "veri" device (esclusi multicast/broadcast)
  const realDevicesCount = devices.filter(d => !/^(22[4-9]|23\d|255)\./.test(d.ip_address || "")).length;
  const offlineDevices = realDevicesCount - onlineDevices;
  const criticalAlerts = alerts.filter(a => a.severity === "critical").length;
  // v3.8.20 + 2026-02-13 UNIFIED: classificazione macroaree (PC, VoIP, Mobile,
  // ecc.) per i device. Estratta in `utils/deviceCategory.js` per essere usata
  // identica anche dalla pagina Dispositivi (allineamento Panoramica/Dispositivi).
  // Mantenuto qui l'alias per minimizzare il diff sui filtri.

  const firewalls = devices.filter(d => macroOf(d) === "firewall");
  const switches = devices.filter(d => macroOf(d) === "switch");
  const servers = devices.filter(d => macroOf(d) === "server");
  const upsList = devices.filter(d => macroOf(d) === "ups");
  const nasList = devices.filter(d => macroOf(d) === "nas");
  const apList = devices.filter(d => macroOf(d) === "ap");
  const tvccList = devices.filter(d => macroOf(d) === "tvcc");
  const printersList = devices.filter(d => macroOf(d) === "printer");
  const voipList = devices.filter(d => macroOf(d) === "voip");
  const workstationList = devices.filter(d => macroOf(d) === "workstation");
  const mobileList = devices.filter(d => macroOf(d) === "mobile");
  const iotList = devices.filter(d => macroOf(d) === "iot");
  const skipList = devices.filter(d => macroOf(d) === "_skip");  // multicast/broadcast esclusi dalla UI
  // v3.8.40: il totale "DISPOSITIVI" e il counter del tab non devono includere
  // i multicast/broadcast (IP 224.x, 239.x, 255.x) che NON sono veri device ma
  // gruppi multicast catturati dallo Scanner via ARP table. Includerli inflava
  // il numero (es. 75 in card vs 67 visibili nel raggruppamento Infrastruttura).
  const realDevices = devices.filter(d => macroOf(d) !== "_skip");
  const vitalDevices = realDevices.filter(d => d.is_vital === true);
  // v2026-06 CATEGORIZZAZIONE: separazione Endpoints (PC consumer/mobile/IoT)
  // dall'Infrastruttura di rete. Un PC/laptop offline NON deve influenzare
  // le statistiche "Dispositivi" (infrastruttura). Sezione dedicata "Endpoints".
  const ENDPOINT_MACROS = ["workstation", "mobile", "iot"];
  const endpointList = realDevices.filter(d => ENDPOINT_MACROS.includes(macroOf(d)));
  const infraDevices = realDevices.filter(d => !ENDPOINT_MACROS.includes(macroOf(d)));
  const infraOnline = infraDevices.filter(d => d.status === "online").length;
  const infraOffline = infraDevices.length - infraOnline;
  const endpointOnline = endpointList.filter(d => d.status === "online").length;
  // Tab "Stampanti" = unione di /api/printers (con telemetria toner) + managed_devices con
  // device_type=printer. Match per IP — se entrambi presenti i toner della /api/printers
  // hanno priorità (più specifici).
  const mergedPrinters = (() => {
    const byIp = new Map();
    printersList.forEach(d => byIp.set(d.ip_address, {
      name: d.name,
      ip_address: d.ip_address,
      status: d.status,
      alerts_silenced: d.alerts_silenced,
      from_managed: true,
    }));
    printers.forEach(p => {
      const ip = p.ip_address || p.ip;
      const prev = byIp.get(ip) || {};
      byIp.set(ip, {
        ...prev,
        name: prev.name || p.name,
        ip_address: ip,
        status: p.status || prev.status,
        toner_levels: p.toner_levels,
        page_count: p.page_count,
        alerts_silenced: prev.alerts_silenced ?? p.alerts_silenced,
        has_telemetry: true,
      });
    });
    return Array.from(byIp.values());
  })();
  const knownTypes = new Set(["firewall", "zyxel-usg", "switch", "server", "ilo", "ups", "nas", "storage", "ap", "access-point", "tvcc", "camera", "nvr", "dvr", "printer", "endpoint-private"]);
  const others = devices.filter(d => macroOf(d) === "other");

  const tabs = [
    { id: "overview", label: "Panoramica", icon: Monitor },
    { id: "devices", label: `Dispositivi Vitali (${vitalDevices.length})`, icon: Star },
    { id: "servers", label: `Server (${iloHealth.length})`, icon: Cpu },
    { id: "wan", label: `WAN (${wanTargets.length})`, icon: Globe },
    { id: "alerts", label: `Alert (${alerts.length})`, icon: Bell },
    { id: "printers", label: `Stampanti (${mergedPrinters.length})`, icon: Printer },
    { id: "backup", label: `Backup (${backups.length})`, icon: Database },
    { id: "discovery", label: "Auto-Discovery", icon: MagnifyingGlass },
    { id: "lan-scan", label: "Scanner LAN", icon: WifiHigh },
    { id: "vulnerability", label: "Vulnerability", icon: ShieldCheck },
    { id: "credentials", label: "Credenziali", icon: Lock },
  ];

  // Optimistic update locale: il modal Edit chiama questa per riflettere subito
  // i cambi (es. silence toggle) senza aspettare il refetch async di /api/devices.
  const optimisticUpdateDevice = (updatedDevice) => {
    if (!updatedDevice || !updatedDevice.id) return;
    setDevices(prev => prev.map(d => d.id === updatedDevice.id ? { ...d, ...updatedDevice } : d));
  };

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="client-overview-page">
      {/* v4.15.x Banner ZOMBIE V3 / coverage issues — mostrato solo se ci sono
          device da monitorare (devices.length>0) e c'e' un problema actionable */}
      {diagnosis && devices.length > 0 && (diagnosis.v3_zombie?.active || (diagnosis.recommendations || []).length > 0) && (
        <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 flex items-start gap-3" data-testid="diagnosis-banner">
          <Warning size={18} weight="bold" className="text-rose-400 mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-[12px] font-bold text-rose-300">
              {diagnosis.v3_zombie?.active ? "Connector v3 obsoleto attivo" : "Problema di polling dispositivi"}
            </p>
            {diagnosis.v3_zombie?.active && (
              <p className="text-[10px] text-rose-300/90 mt-0.5">
                Un vecchio Connector v3 PowerShell sta ancora inviando report ({diagnosis.v3_zombie.records_written_by_v3} record).
                I device risultano OFFLINE per colpa sua. Ultimo write: {diagnosis.v3_zombie.last_v3_write}.
              </p>
            )}
            {(diagnosis.recommendations || []).map((r, i) => (
              <p key={i} className="text-[10px] text-rose-300/80 mt-1">→ {r}</p>
            ))}
            {(diagnosis.live_v4_agents || []).length > 0 && (
              <p className="text-[10px] text-rose-300/60 mt-1">
                Agent v4 LIVE: {diagnosis.live_v4_agents.map(a => `${a.hostname} [${a.role}]`).join(", ")}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <button
              onClick={() => diagnoseOffline()}
              className="text-[10px] px-2 py-1 rounded bg-rose-500/20 border border-rose-500/40 text-rose-300 hover:bg-rose-500/30 whitespace-nowrap"
              data-testid="diagnosis-detail-btn"
            >
              🩺 Dettagli
            </button>
            <button
              onClick={() => fetchAll()}
              className="text-[10px] px-2 py-1 rounded bg-rose-500/20 border border-rose-500/40 text-rose-300 hover:bg-rose-500/30 whitespace-nowrap"
              data-testid="diagnosis-recheck-btn"
            >
              Ricarica
            </button>
          </div>
        </div>
      )}
      {/* v4.17.x Mini-card coverage subnet — mostra distribuzione device per connector */}
      {coverage && coverage.total_devices > 0 && (coverage.agents.length > 0 || coverage.orphan_count > 0) && (
        <div className="mb-3 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2" data-testid="coverage-card">
          <div className="flex items-center gap-2 mb-1.5">
            <Network size={14} className="text-sky-400" />
            <span className="text-[11px] font-bold text-sky-300">Distribuzione polling per subnet</span>
            <span className="text-[9px] text-[var(--text-muted)] ml-auto">{coverage.total_devices} device totali</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {coverage.agents.map((a) => {
              const color = a.role === "master"
                ? "bg-sky-500/10 text-sky-200 border-sky-500/40"
                : "bg-violet-500/10 text-violet-200 border-violet-500/40";
              return (
                <div
                  key={a.agent_id}
                  className={`flex items-center gap-1.5 text-[10px] px-2 py-1 rounded border ${color}`}
                  title={`Agent ${a.hostname} [${a.role}] · IP ${a.last_ip || "?"} · v${a.agent_version || "?"}`}
                >
                  <span className="font-bold">{a.hostname}</span>
                  <span className="text-[9px] opacity-70">[{a.role}]</span>
                  <span className="text-[9px] opacity-90">→ {a.subnet || "no subnet"}</span>
                  <span className="text-[9px] font-bold ml-1">{a.device_count} dev</span>
                </div>
              );
            })}
            {coverage.orphan_count > 0 && (
              <div
                className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded border bg-amber-500/10 text-amber-200 border-amber-500/40"
                title={`Device fuori da qualsiasi subnet coperta: ${coverage.orphan_sample.join(", ")}${coverage.orphan_count > 10 ? "..." : ""}`}
              >
                <Warning size={11} weight="bold" />
                <span className="font-bold">{coverage.orphan_count} orfani</span>
                <span className="text-[9px] opacity-90">→ pollati dal master (fallback)</span>
              </div>
            )}
            {coverage.agents.length === 0 && coverage.orphan_count > 0 && (
              <span className="text-[10px] text-amber-300">⚠️ Nessun agent LIVE — tutti i device sono orfani</span>
            )}
          </div>
        </div>
      )}
      {/* v3.8.41 Banner watchdog: Scanner inattivo da Xh */}
      {scanHealth.any_stale && (
        <div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 flex items-start gap-3" data-testid="scanner-stale-banner">
          <Warning size={18} weight="bold" className="text-amber-400 mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-[12px] font-bold text-amber-300">Scanner inattivo — discovery LAN ferma</p>
            <p className="text-[10px] text-amber-300/80 mt-0.5">
              {scanHealth.connectors.filter(c => c.is_stale).map(c => (
                <span key={c.hostname} className="inline-block mr-3">
                  <span className="font-mono">{c.hostname}</span> ({c.mode}): ultimo scan {c.minutes_since_last_scan >= 60 ? `${Math.floor(c.minutes_since_last_scan / 60)}h ${c.minutes_since_last_scan % 60}m` : `${c.minutes_since_last_scan}m`} fa
                </span>
              ))}
            </p>
            <p className="text-[10px] text-amber-300/70 mt-1">
              Il sub-thread <code className="px-1 py-0.5 rounded bg-amber-500/20">Poll-LanEndpoints</code> del Connector si e' bloccato (UDP socket leak / crash silenzioso). Per ripartire:
              {" "}<code className="px-1 py-0.5 rounded bg-amber-500/20">Restart-Service "86NocConnector"</code>{" "}
              sul server cliente. I device tornano fluidi entro ~5 minuti.
            </p>
          </div>
          <button
            onClick={() => fetchAll()}
            className="text-[10px] px-2 py-1 rounded bg-amber-500/20 border border-amber-500/40 text-amber-300 hover:bg-amber-500/30 whitespace-nowrap self-start"
            data-testid="scanner-stale-recheck-btn"
          >
            Ricarica stato
          </button>
        </div>
      )}
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => navigate("/")} className="p-1.5 rounded-md hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">{client.name}</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Monitoraggio completo rete cliente</p>
        </div>
        {hwHealth?.subsystems && hwHealth.ilo_server_count > 0 && (
          <div
            className="hidden md:flex flex-col items-end gap-1 px-3 py-1.5 rounded-md border border-[var(--bg-border)] bg-[var(--bg-panel)]/40"
            data-testid="client-hw-health-badge"
            title={`Health aggregata di ${hwHealth.ilo_server_count} server iLO`}
          >
            <span className="text-[8px] font-bold uppercase tracking-[0.15em] text-cyan-400/60">
              Hardware iLO · {hwHealth.ilo_server_count}
            </span>
            <HealthBadge subsystems={hwHealth.subsystems} size="sm" testId="client-hw-badge" />
          </div>
        )}
        <button onClick={fetchAll} className="p-1.5 rounded-md hover:bg-[var(--bg-hover)] text-[var(--text-muted)]" title="Aggiorna">
          <ArrowClockwise size={16} />
        </button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-7 gap-2 mb-4">
        <StatBox label="Dispositivi" value={`${infraOnline}/${infraDevices.length}`} color={infraOffline > 0 ? "#FF9500" : "#34C759"} sub={infraOffline > 0 ? `${infraOffline} offline` : "Infrastruttura OK"} />
        <StatBox label="Endpoints" value={endpointList.length > 0 ? `${endpointOnline}/${endpointList.length}` : "—"} color={endpointList.length === 0 ? "#555" : "#3B82F6"} sub={endpointList.length > 0 ? "PC / Mobile / IoT" : "nessuno"} />
        <StatBox label="WAN" value={wanTargets.length > 0 ? (wanTargets.every(t => t.result?.status === "online") ? "OK" : "ALERT") : "N/C"} color={wanTargets.every(t => t.result?.status === "online") ? "#34C759" : wanTargets.length > 0 ? "#FF3B30" : "#555"} sub={wanTargets[0]?.result?.ping?.latency_ms ? `${wanTargets[0].result.ping.latency_ms}ms` : ""} />
        <StatBox label="Alert" value={alerts.length} color={criticalAlerts > 0 ? "#FF3B30" : alerts.length > 0 ? "#FF9500" : "#34C759"} sub={criticalAlerts > 0 ? `${criticalAlerts} critici` : "Nessun critico"} />
        <StatBox label="Connettore" value={connector ? "ONLINE" : "OFFLINE"} color={connector ? "#34C759" : "#FF3B30"} sub={connector?.connector_hostname || ""} />
        <StatBox label="Stampanti" value={printers.length > 0 ? `${printers.length}` : "—"} color={printers.some(p => p.toner_low) ? "#FF9500" : "#34C759"} />
        {(() => {
          const m = backupSummary.m365 || {};
          const v = backupSummary.vm || {};
          const m365Mapped = (m.mapped_filters?.length || m.mapped_tenants?.length || 0) > 0;
          const vmMapped = (v.mapped_customers?.length || 0) > 0;
          const m365Failed = m.totals?.active_alerts || 0;
          const m365Total = m.totals?.total_items || 0;
          const m365Ok = m.totals?.by_status?.success || 0;
          const vmFailed = v.totals?.failed || 0;
          const vmWarn = v.totals?.warning || 0;
          const vmStale = v.totals?.stale || 0;
          const vmTotal = v.totals?.vms_total || 0;
          const vmOk = v.totals?.by_status?.success || 0;
          const legacyErr = backups.some(b => b.status === "error");

          const anyFailed = m365Failed > 0 || vmFailed > 0 || legacyErr;
          const anyWarn = vmWarn > 0;
          const anyStale = vmStale > 0;

          let value, color, sub;
          if (!m365Mapped && !vmMapped && backups.length === 0) {
            value = "—"; color = "#555"; sub = "non configurato";
          } else if (anyFailed) {
            const n = m365Failed + vmFailed;
            value = n > 0 ? `${n} KO` : "ERR"; color = "#FF3B30";
            sub = [
              m365Failed ? `365:${m365Failed}` : null,
              vmFailed ? `VM:${vmFailed}` : null,
            ].filter(Boolean).join(" · ") || "backup falliti";
          } else if (anyWarn || anyStale) {
            value = anyWarn ? "WARN" : "STALE"; color = "#FF9500";
            sub = [
              vmWarn ? `${vmWarn} warn` : null,
              vmStale ? `${vmStale} stale` : null,
            ].filter(Boolean).join(" · ");
          } else {
            value = "OK"; color = "#34C759";
            const okTot = m365Ok + vmOk;
            const tot = m365Total + vmTotal + backups.length;
            sub = tot > 0 ? `${okTot}/${tot} protetti` : "tutto ok";
          }
          return <StatBox label="Backup" value={value} color={color} sub={sub} />;
        })()}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-[var(--bg-border)] pb-px overflow-x-auto">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-[11px] font-semibold rounded-t-md transition-colors whitespace-nowrap ${activeTab === t.id ? "bg-[var(--bg-panel)] text-indigo-400 border border-[var(--bg-border)] border-b-transparent -mb-px" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}
            data-testid={`tab-${t.id}`}>
            <t.icon size={13} weight={activeTab === t.id ? "bold" : "regular"} />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[400px]">
        {activeTab === "overview" && <OverviewTab devices={devices} wanTargets={wanTargets} alerts={alerts} connector={connector} printers={printers} backups={backups} firewalls={firewalls} switches={switches} servers={servers} upsList={upsList} nasList={nasList} apList={apList} tvccList={tvccList} printersList={printersList} voipList={voipList} workstationList={workstationList} mobileList={mobileList} iotList={iotList} skipList={skipList} others={others} iloHealth={iloHealth} clientId={clientId} onRefresh={fetchAll} />}
        {activeTab === "devices" && <DevicesTab devices={devices} clientId={clientId} onRefresh={fetchAll} onOptimisticUpdate={optimisticUpdateDevice} />}
        {activeTab === "servers" && <ServersTab iloHealth={iloHealth} clientId={clientId} clientName={client.name} onRefresh={fetchAll} />}
        {activeTab === "wan" && <WanClientTab targets={wanTargets} clientId={clientId} clientName={client.name} onRefresh={fetchAll} />}
        {activeTab === "alerts" && <AlertsTab alerts={alerts} navigate={navigate} clientId={clientId} clientName={client.name} onRefresh={fetchAll} />}
        {activeTab === "printers" && <PrintersTab printers={mergedPrinters} />}
        {activeTab === "backup" && <BackupTab backups={backups} clientId={clientId} />}
        {activeTab === "credentials" && <VaultPage scopedClientId={clientId} scopedClientName={client.name} />}
        {activeTab === "discovery" && <DiscoveryPage scopedClientId={clientId} scopedClientName={client.name} />}
        {activeTab === "lan-scan" && <LanScannerPage scopedClientId={clientId} scopedClientName={client.name} />}
        {activeTab === "vulnerability" && <VulnerabilityPage scopedClientId={clientId} scopedClientName={client.name} />}
      </div>
    </div>
  );
}

/* ==================== OVERVIEW TAB ==================== */
const TRIAGE_INFRA_MACROS = ["firewall", "switch", "router", "server", "nas", "ups", "ap", "tvcc"];

function TriageWizard({ open, onClose, devices, clientId, onDone }) {
  const undecided = devices.filter(d => macroOf(d) !== "_skip" && d.is_vital !== true && d.is_vital !== false);
  const [selected, setSelected] = useState(() => new Set());
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (open) {
      const sugg = undecided.filter(d => TRIAGE_INFRA_MACROS.includes(macroOf(d))).map(d => d.ip_address).filter(Boolean);
      setSelected(new Set(sugg));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const toggle = (ip) => setSelected(prev => { const n = new Set(prev); n.has(ip) ? n.delete(ip) : n.add(ip); return n; });
  const apply = async (isVital) => {
    const ips = Array.from(selected);
    if (!ips.length) { toast.error("Seleziona almeno un dispositivo"); return; }
    setSaving(true);
    try {
      await axios.post(`${API}/devices/bulk-vital`, { ips, is_vital: isVital, client_id: clientId, reason: "triage" });
      toast.success(`${ips.length} dispositivi ${isVital ? "agganciati come VITALI ⭐" : "segnati come Monitorati"}`);
      onDone && onDone();
      onClose();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore aggiornamento"); }
    finally { setSaving(false); }
  };
  const suggested = undecided.filter(d => TRIAGE_INFRA_MACROS.includes(macroOf(d)));
  const rest = undecided.filter(d => !TRIAGE_INFRA_MACROS.includes(macroOf(d)));
  const Row = ({ d }) => {
    const ip = d.ip_address;
    const on = selected.has(ip);
    return (
      <button onClick={() => toggle(ip)}
        className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md border text-left text-[11px] transition-colors ${on ? "bg-indigo-500/15 border-indigo-500/50" : "border-[var(--bg-border)] hover:border-[var(--text-muted)]"}`}
        data-testid={`triage-row-${ip}`}>
        <span className={`w-3.5 h-3.5 rounded-sm border flex items-center justify-center shrink-0 ${on ? "bg-indigo-500 border-indigo-500" : "border-[var(--text-muted)]"}`}>
          {on && <Check size={10} weight="bold" className="text-white" />}
        </span>
        <span className="font-semibold text-[var(--text-primary)] truncate">{d.name || ip}</span>
        <span className="font-mono text-[9px] text-[var(--text-muted)]">{ip}</span>
        <span className="ml-auto text-[8px] uppercase px-1.5 py-0.5 rounded bg-[var(--bg-panel)] text-[var(--text-muted)] shrink-0">{macroOf(d)}</span>
      </button>
    );
  };
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col" data-testid="triage-wizard">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Star size={18} weight="fill" className="text-yellow-400" /> Classifica dispositivi rilevati</DialogTitle>
          <DialogDescription>
            Aggancia come <b>Vitali</b> i dispositivi essenziali da monitorare sempre. I suggeriti (infrastruttura) sono già selezionati.
          </DialogDescription>
        </DialogHeader>
        <div className="overflow-y-auto flex-1 space-y-3 pr-1">
          {suggested.length > 0 && (
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-yellow-400 mb-1.5">⭐ Suggeriti come Vitali · Infrastruttura ({suggested.length})</p>
              <div className="space-y-1">{suggested.map(d => <Row key={d.ip_address} d={d} />)}</div>
            </div>
          )}
          {rest.length > 0 && (
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Altri rilevati ({rest.length})</p>
              <div className="space-y-1">{rest.map(d => <Row key={d.ip_address} d={d} />)}</div>
            </div>
          )}
          {undecided.length === 0 && <p className="text-center text-xs text-[var(--text-muted)] py-8">Nessun dispositivo da classificare 🎉</p>}
        </div>
        <DialogFooter className="gap-2">
          <span className="text-[10px] text-[var(--text-muted)] mr-auto self-center">{selected.size} selezionati</span>
          <Button variant="outline" size="sm" disabled={saving} onClick={() => apply(false)} data-testid="triage-monitor-btn">Segna come Monitorati</Button>
          <Button size="sm" disabled={saving} onClick={() => apply(true)} className="bg-yellow-500 hover:bg-yellow-600 text-black font-semibold" data-testid="triage-vital-btn">
            <Star size={13} weight="fill" className="mr-1" /> Aggancia come Vitali
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OverviewTab({ devices, wanTargets, alerts, connector, printers, backups, firewalls, switches, servers, upsList, nasList, apList, tvccList, printersList, voipList = [], workstationList = [], mobileList = [], iotList = [], skipList = [], others, iloHealth, clientId: clientIdProp, onRefresh }) {
  // v2026-02-28 SAFETY: fallback su useParams se il prop non viene passato.
  // Evita ReferenceError "clientId is not defined" in caso di build parziali
  // dove un commit pre-fix dimentica di passare il prop ma usa la variabile
  // nei figli (es. <DeviceGroup clientId={clientId} />).
  const { clientId: clientIdParam } = useParams();
  const clientId = clientIdProp || clientIdParam;
  const [triageOpen, setTriageOpen] = useState(false);
  const undecidedDevices = devices.filter(d => macroOf(d) !== "_skip" && d.is_vital !== true && d.is_vital !== false);
  const vitalCountOv = devices.filter(d => d.is_vital === true).length;
  return (
    <div className="space-y-4">
      <TriageWizard open={triageOpen} onClose={() => setTriageOpen(false)} devices={devices} clientId={clientId} onDone={onRefresh} />
      {/* Triage hub: dispositivi rilevati da classificare */}
      {undecidedDevices.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-yellow-500/40 bg-yellow-500/10" data-testid="triage-banner">
          <Star size={18} weight="bold" className="text-yellow-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-[var(--text-primary)]">
              🆕 {undecidedDevices.length} dispositivi rilevati da classificare
            </p>
            <p className="text-[10px] text-[var(--text-muted)]">
              Aggancia i dispositivi essenziali come Vitali per monitorarli attivamente. {vitalCountOv} già vitali.
            </p>
          </div>
          <Button size="sm" onClick={() => setTriageOpen(true)}
            className="h-8 bg-yellow-500 hover:bg-yellow-600 text-black font-semibold shrink-0" data-testid="triage-open-btn">
            Classifica ora
          </Button>
        </div>
      )}
      {/* v2026-02-28: Bridge Health Widget — diagnostica live degli agent SNMP/ping */}
      {clientId && (
        <SafeBoundary label="Bridge Health">
          <BridgeHealthWidget clientId={clientId} />
        </SafeBoundary>
      )}

      {/* iLO Hardware Health Panel (only shown when we have iLO data) */}
      {iloHealth && iloHealth.length > 0 && <IloHealthPanel iloHealth={iloHealth} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Left column: Infrastruttura + Endpoints */}
      <div className="space-y-4">
      {/* Network Map */}
      <div className="noc-panel p-4">
        <h3 className="text-[9px] font-bold uppercase tracking-[0.15em] text-indigo-400 mb-3">Infrastruttura di Rete</h3>
        <div className="space-y-2">
          {/* WAN */}
          {wanTargets.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">Connettivita' WAN</p>
              {wanTargets.map(t => {
                const r = t.result;
                const sc = getStatusColor(r?.status);
                return (
                  <div key={t.id} className="flex items-center gap-2 px-3 py-2 rounded-lg border text-[11px]" style={{ borderColor: `${sc}30`, background: `${sc}06` }}>
                    {t.device_type === "firewall" ? <ShieldCheck size={14} weight="bold" style={{ color: sc }} /> : <HardDrives size={14} weight="bold" style={{ color: sc }} />}
                    <span className="font-bold text-[var(--text-primary)]">{t.label}</span>
                    <span className="font-mono text-[var(--text-muted)] text-[10px]">{t.public_ip}</span>
                    <span className="ml-auto font-mono font-bold" style={{ color: sc }}>{r?.status?.toUpperCase() || "..."}</span>
                    {r?.ping?.latency_ms != null && <span className="font-mono text-[var(--text-muted)] text-[10px]">{r.ping.latency_ms}ms</span>}
                    {r?.gateway_ping && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-bold" style={{ color: r.gateway_ping.reachable ? "#34C759" : "#FF3B30", background: r.gateway_ping.reachable ? "#34C75910" : "#FF3B3010" }}>
                        ISP {r.gateway_ping.reachable ? "OK" : "DOWN"}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          {/* Firewalls */}
          {firewalls.length > 0 && <DeviceGroup label="Firewall" icon={ShieldCheck} devices={firewalls} color="#FF3B30" />}
          {/* Switches */}
          {switches.length > 0 && <DeviceGroup label="Switch" icon={HardDrives} devices={switches} color="#6366F1" />}
          {/* Servers / iLO */}
          {servers.length > 0 && <DeviceGroup label="Server / iLO" icon={Monitor} devices={servers} color="#06B6D4" />}
          {/* NAS / Storage */}
          {nasList.length > 0 && <DeviceGroup label="NAS / Storage" icon={Database} devices={nasList} color="#14B8A6" />}
          {/* UPS */}
          {upsList.length > 0 && <DeviceGroup label="UPS" icon={Lightning} devices={upsList} color="#EAB308" />}
          {/* Access Point */}
          {apList.length > 0 && <DeviceGroup label="Access Point / WiFi" icon={WifiHigh} devices={apList} color="#8B5CF6" />}
          {/* TVCC */}
          {tvccList.length > 0 && <DeviceGroup label="TVCC / Videosorveglianza" icon={Monitor} devices={tvccList} color="#F97316" />}
          {/* Printers */}
          {printersList.length > 0 && <DeviceGroup label="Stampanti" icon={Printer} devices={printersList} color="#EC4899" />}
          {/* v3.8.20: nuove macroaree per i device dello Scanner */}
          {voipList.length > 0 && <DeviceGroup label="Telefoni VoIP" icon={Phone} devices={voipList} color="#22C55E" clientId={clientId} />}
          {/* Others / Generic */}
          {others.length > 0 && <DeviceGroup label="Altri Dispositivi" icon={HardDrives} devices={others} color="#64748B" />}
          {/* Skipped multicast/broadcast (nascosti dalla vista principale) */}
          {skipList.length > 0 && (
            <details className="opacity-60 hover:opacity-100 transition-opacity">
              <summary className="cursor-pointer text-[9px] uppercase tracking-[0.15em] text-[var(--text-muted)] py-2 select-none">
                ▸ Multicast / broadcast nascosti ({skipList.length})
              </summary>
              <DeviceGroup label="Multicast / Broadcast (non gestiti)" icon={NetworkSlash} devices={skipList} color="#6B7280" />
            </details>
          )}
        </div>
      </div>

      {/* Endpoints (PC consumer / Mobile / IoT) — separati dall'infrastruttura */}
      {(workstationList.length > 0 || mobileList.length > 0 || iotList.length > 0) && (
        <div className="noc-panel p-4" data-testid="endpoints-panel">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[9px] font-bold uppercase tracking-[0.15em] text-blue-400">Endpoints — PC / Mobile / IoT</h3>
            <span className="text-[9px] text-[var(--text-muted)]" title="Gli endpoint (PC/laptop/smartphone) non influenzano lo stato di salute dell'infrastruttura.">
              {workstationList.length + mobileList.length + iotList.length} dispositivi · esclusi dalla salute infrastruttura
            </span>
          </div>
          <div className="space-y-2">
            {workstationList.length > 0 && <DeviceGroup label="Workstation / PC" icon={Desktop} devices={workstationList} color="#3B82F6" clientId={clientId} />}
            {mobileList.length > 0 && <DeviceGroup label="Smartphone / Mobile (MAC randomizzato)" icon={DeviceMobile} devices={mobileList} color="#A855F7" clientId={clientId} />}
            {iotList.length > 0 && <DeviceGroup label="IoT / Embedded" icon={Cpu} devices={iotList} color="#F59E0B" clientId={clientId} />}
          </div>
        </div>
      )}
      </div>

      {/* Right column: Alerts + Status */}
      <div className="space-y-4">
        {/* Connector */}
        <div className="noc-panel p-4">
          <h3 className="text-[9px] font-bold uppercase tracking-[0.15em] text-cyan-400 mb-2">Connettore</h3>
          {connector ? (
            <div className="flex items-center gap-3">
              <div className="w-2.5 h-2.5 rounded-full bg-emerald-400" style={{ boxShadow: "0 0 8px #34C75960" }}></div>
              <div>
                <p className="text-xs font-bold text-[var(--text-primary)]">{connector.connector_hostname}</p>
                <p className="text-[10px] text-[var(--text-muted)]">v{connector.connector_version} — Ultimo contatto: {connector.last_seen ? new Date(connector.last_seen).toLocaleString("it-IT") : "?"}</p>
              </div>
            </div>
          ) : (
            <p className="text-xs text-red-400">Connettore non collegato</p>
          )}
        </div>

        {/* Recent Alerts */}
        <div className="noc-panel p-4">
          <h3 className="text-[9px] font-bold uppercase tracking-[0.15em] text-amber-400 mb-2">Alert Attivi ({alerts.length})</h3>
          {alerts.length === 0 ? (
            <p className="text-xs text-emerald-400">Nessun alert attivo</p>
          ) : (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {alerts.slice(0, 8).map(a => {
                const sc = a.severity === "critical" ? "#FF3B30" : a.severity === "high" ? "#FF9500" : a.severity === "medium" ? "#FFCC00" : "#888";
                return (
                  <div key={a.id} className="flex items-center gap-2 px-2 py-1.5 rounded text-[10px]" style={{ background: `${sc}06` }}>
                    <span className="text-[8px] px-1 py-0.5 rounded font-bold uppercase" style={{ color: sc, background: `${sc}15` }}>{a.severity?.substring(0, 4)}</span>
                    <span className="text-[var(--text-primary)] truncate flex-1">{a.title}</span>
                    <span className="text-[var(--text-muted)]">{a.device_name}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Printers quick */}
        {printers.length > 0 && (
          <div className="noc-panel p-4">
            <h3 className="text-[9px] font-bold uppercase tracking-[0.15em] text-orange-400 mb-2">Stampanti ({printers.length})</h3>
            <div className="space-y-1">
              {printers.slice(0, 5).map((p, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px]">
                  <Printer size={12} className="text-[var(--text-muted)]" />
                  <span className="text-[var(--text-primary)]">{p.name || p.ip_address}</span>
                  <span className="ml-auto text-[var(--text-muted)]">{p.status || "?"}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

/* ==================== ILO HEALTH PANEL ==================== */
function IloHealthPanel({ iloHealth }) {
  const healthColor = (h) => ({ ok: "#34C759", warning: "#FFCC00", critical: "#FF3B30" }[(h || "").toLowerCase()] || "#64748B");
  // v2026-02-14: nel pannello Panoramica mostriamo SOLO i server con dati
  // Redfish live (BIOS/iLO/serial popolati). I server senza credenziali
  // sono visibili nella tab dedicata "Server" (sezione gialla "da configurare"),
  // ma qui rovinerebbero la vista mostrando 10 card vuote con "N/D" ovunque.
  const real = (iloHealth || []).filter(s => s.has_redfish_data || s.server_model || s.bios_version);
  if (real.length === 0) return null;
  return (
    <div className="noc-panel p-4" data-testid="ilo-health-panel">
      <div className="flex items-center gap-2 mb-3">
        <Monitor size={14} weight="bold" className="text-cyan-400" />
        <h3 className="text-[10px] font-bold uppercase tracking-[0.15em] text-cyan-400">Hardware iLO (Redfish) — {real.length} server</h3>
      </div>
      <div className="space-y-3">
        {real.map((s, idx) => <IloServerCard key={idx} s={s} healthColor={healthColor} />)}
      </div>
    </div>
  );
}

/* ==================== SERVERS TAB (dedicated full view) ====================
   v2026-02-14: tab dedicata "Server" che mostra TUTTI i dati Redfish/iLO
   per i server del cliente:
     - CPU/RAM totale + DIMM
     - Storage (controller, drive, RAID, predict-fail)
     - PSU, Ventole, Sensori temperature
     - Network adapter con link status
     - BIOS, iLO firmware, license
   Riusa il componente IloServerCard (gia' completo) con filtri di salute
   e azioni rapide (poll-now, espandi tutti).
*/
function ServersTab({ iloHealth, clientId, clientName, onRefresh }) {
  const [filter, setFilter] = useState("all"); // all | issues | ok | needs_setup
  const [polling, setPolling] = useState(false);
  const healthColor = (h) => ({ ok: "#34C759", warning: "#FFCC00", critical: "#FF3B30" }[(h || "").toLowerCase()] || "#64748B");

  // v2026-02-14: separazione tra server con dati Redfish live e server che
  // richiedono ancora la configurazione delle credenziali iLO.
  const configuredServers = (iloHealth || []).filter(s => s.has_redfish_data);
  const pendingServers = (iloHealth || []).filter(s => s.needs_ilo_setup || (!s.has_redfish_data && !s.ilo_configured));

  const filtered = configuredServers.filter((s) => {
    if (filter === "all") return true;
    const h = (s.health_status || "").toLowerCase();
    if (filter === "issues") return h === "warning" || h === "critical";
    if (filter === "ok") return h === "ok";
    return true;
  });

  // KPI aggregati top-bar (solo server configurati)
  const totalRamGb = configuredServers.reduce((sum, s) => sum + (Number(s.total_memory_gb) || 0), 0);
  const totalPowerW = configuredServers.reduce((sum, s) => sum + (Number(s.power_watts) || 0), 0);
  const totalDrives = configuredServers.reduce((sum, s) => sum + (s.storage_controllers || []).reduce((a, c) => a + (c.drives?.length || 0), 0), 0);
  const failingDrives = configuredServers.reduce((sum, s) => sum + (s.storage_controllers || []).reduce((a, c) =>
    a + (c.drives || []).filter(d => (d.health || "").toLowerCase() !== "ok" || d.failure_predicted).length, 0), 0);
  const totalDimms = configuredServers.reduce((sum, s) => sum + ((s.memory_dimms || []).filter(d => (d.size_gb || d.capacity_mb) > 0)).length, 0);
  const okServers = configuredServers.filter(s => (s.health_status || "").toLowerCase() === "ok").length;
  const warnServers = configuredServers.filter(s => (s.health_status || "").toLowerCase() === "warning").length;
  const critServers = configuredServers.filter(s => (s.health_status || "").toLowerCase() === "critical").length;

  const pollAllNow = async () => {
    setPolling(true);
    try {
      const ips = configuredServers.map(s => s.device_ip).filter(Boolean);
      if (ips.length === 0) {
        toast.warning("Nessun server iLO configurato per questo cliente");
        return;
      }
      // Single global poll cycle (covers all iLO devices)
      await axios.post(`${API}/redfish/poll-now`, {});
      toast.success(`Polling iLO avviato su ${ips.length} server — risultati tra 10-30s`);
      setTimeout(() => onRefresh?.(), 10000);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore avvio polling iLO");
    } finally {
      setPolling(false);
    }
  };

  if (!iloHealth || iloHealth.length === 0) {
    return (
      <div className="noc-panel p-8 text-center" data-testid="servers-tab-empty">
        <Cpu size={36} className="mx-auto mb-3 opacity-30 text-[var(--text-muted)]" />
        <p className="text-sm text-[var(--text-primary)] font-semibold mb-1">Nessun server rilevato</p>
        <p className="text-xs text-[var(--text-muted)] mb-4 max-w-md mx-auto">
          Argus non ha ancora trovato server (HP ProLiant, Dell, ecc.) o iLO controller nei dispositivi
          gestiti del cliente <b>{clientName}</b>. Aggiungi i server manualmente dalla tab Dispositivi
          o attendi il prossimo ciclo di Auto-Discovery.
        </p>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1"
          onClick={() => onRefresh?.()}
          data-testid="servers-tab-refresh-empty-btn"
        >
          <ArrowClockwise size={12} weight="bold" /> Aggiorna
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="servers-tab">
      {/* KPI bar */}
      <div className="noc-panel p-3">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <ServerKpi label="Server con iLO" value={configuredServers.length} sub={`${okServers} OK · ${warnServers} warn · ${critServers} crit`} color="#06B6D4" testid="kpi-total-servers" />
          <ServerKpi label="RAM Totale" value={`${totalRamGb} GB`} sub={`${totalDimms} DIMM popolati`} color="#8B5CF6" testid="kpi-total-ram" />
          <ServerKpi label="Dischi" value={totalDrives} sub={failingDrives ? `${failingDrives} in errore` : "Tutti OK"} color={failingDrives ? "#FF3B30" : "#34C759"} testid="kpi-total-drives" />
          <ServerKpi label="Potenza" value={totalPowerW ? `${totalPowerW} W` : "—"} sub="consumo live" color="#F59E0B" testid="kpi-total-power" />
          <ServerKpi label="Da configurare" value={pendingServers.length} sub="credenziali iLO mancanti" color={pendingServers.length ? "#FFCC00" : "#34C759"} testid="kpi-pending-servers" />
          <ServerKpi label="Critical" value={critServers} sub="richiede intervento" color="#FF3B30" testid="kpi-crit-servers" />
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2 px-1">
        <div className="flex items-center gap-1 text-xs flex-wrap">
          <span className="text-[var(--text-muted)] mr-2">Filtra:</span>
          {[
            { id: "all", label: `Tutti (${configuredServers.length})` },
            { id: "issues", label: `Solo problemi (${warnServers + critServers})` },
            { id: "ok", label: `Solo OK (${okServers})` },
          ].map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`h-7 px-2.5 rounded border text-xs transition-colors ${
                filter === f.id
                  ? "bg-cyan-500/15 border-cyan-500/50 text-cyan-300"
                  : "border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              }`}
              data-testid={`servers-filter-${f.id}-btn`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs gap-1 border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/10"
            onClick={pollAllNow}
            disabled={polling || configuredServers.length === 0}
            data-testid="servers-poll-all-btn"
            title="Forza polling iLO immediato su tutti i server"
          >
            {polling ? <ArrowClockwise size={12} className="animate-spin" /> : <Lightning size={12} weight="bold" />}
            {polling ? "Polling..." : "Polla iLO ora"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs gap-1"
            onClick={() => onRefresh?.()}
            data-testid="servers-refresh-btn"
          >
            <ArrowClockwise size={12} weight="bold" /> Aggiorna
          </Button>
        </div>
      </div>

      {/* Server cards (riusa IloServerCard) */}
      {configuredServers.length > 0 && (
        filtered.length === 0 ? (
          <div className="noc-panel p-6 text-center text-xs text-[var(--text-muted)]">
            Nessun server corrisponde al filtro selezionato.
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((s, idx) => (
              <IloServerCard key={s.device_ip || idx} s={s} healthColor={healthColor} />
            ))}
          </div>
        )
      )}

      {/* Pending servers (need iLO setup) */}
      {pendingServers.length > 0 && (
        <div className="noc-panel p-4 border-yellow-500/30" data-testid="pending-ilo-servers">
          <div className="flex items-center gap-2 mb-3">
            <Lock size={14} weight="bold" className="text-yellow-400" />
            <h3 className="text-[10px] font-bold uppercase tracking-[0.15em] text-yellow-400">
              Server senza credenziali iLO ({pendingServers.length})
            </h3>
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mb-3">
            Questi server sono stati rilevati ma non hanno credenziali iLO/Redfish configurate.
            Aggiungile dalla tab <b>Credenziali</b> per vedere CPU, RAM, dischi e sensori hardware.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {pendingServers.map((s) => (
              <div
                key={s.device_ip}
                className="rounded-md border border-yellow-500/20 bg-yellow-500/5 p-2.5 hover:border-yellow-500/40 transition-colors"
                data-testid={`pending-server-${s.device_ip}`}
              >
                <div className="flex items-start justify-between gap-2 mb-1">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-bold text-[var(--text-primary)] truncate">{s.device_name}</p>
                    <p className="text-[10px] text-[var(--text-muted)] font-mono">{s.device_ip}</p>
                  </div>
                  <span className="text-[8px] px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-300 font-bold uppercase whitespace-nowrap">
                    No iLO
                  </span>
                </div>
                {s.server_model && (
                  <p className="text-[10px] text-[var(--text-muted)] mt-1 truncate">{s.server_model}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ServerKpi({ label, value, sub, color, testid }) {
  return (
    <div className="rounded-md px-2.5 py-2 bg-[var(--bg-card)] border border-[var(--bg-border)]" data-testid={testid}>
      <p className="text-[8px] uppercase tracking-[0.15em] text-[var(--text-muted)] mb-0.5">{label}</p>
      <p className="text-lg font-bold font-mono leading-none" style={{ color }}>{value}</p>
      {sub && <p className="text-[9px] text-[var(--text-muted)] mt-0.5 opacity-70 truncate" title={sub}>{sub}</p>}
    </div>
  );
}

function IloServerCard({ s, healthColor }) {
  const [expanded, setExpanded] = useState(false);
  const [firmwareCompliance, setFirmwareCompliance] = useState(s.firmware_compliance || null);
  const [timelineSensor, setTimelineSensor] = useState(null);
  const hc = healthColor(s.health_status);

  // Fetch firmware compliance on mount (piggybacks on telemetry poll)
  useEffect(() => {
    if (!s.device_ip) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await axios.get(`${API}/firmware/check/${s.device_ip}`);
        if (!cancelled && res.data && !res.data.error) setFirmwareCompliance(res.data);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [s.device_ip]);

  // Compute real telemetry (NOT just first sensor!)
  const temps = (s.temperatures || []).filter(t => t.value != null && t.value > 0);
  const maxTemp = temps.length ? temps.reduce((a, b) => a.value > b.value ? a : b) : null;
  const critTemps = temps.filter(t => t.value > 75);
  const warnTemps = temps.filter(t => t.value > 65 && t.value <= 75);
  const tempColor = critTemps.length ? "#FF3B30" : warnTemps.length ? "#FFCC00" : "#34C759";
  // Top N sensori ordinati per temperatura decrescente (per mostrare i piu' caldi)
  const topTemps = [...temps].sort((a, b) => b.value - a.value).slice(0, 3);

  const fans = s.fans || [];
  const okFans = fans.filter(f => (f.condition || "").toLowerCase() === "ok").length;
  const fansColor = okFans === fans.length ? "#34C759" : "#FF3B30";

  const psus = s.power_supplies || [];
  const okPsus = psus.filter(p => ["ok"].includes((p.condition || p.health || "").toLowerCase())).length;
  const psuColor = okPsus === psus.length && psus.length > 0 ? "#34C759" : psus.length === 0 ? "#64748B" : "#FF3B30";

  const dimms = (s.memory_dimms || []).filter(d => (d.size_gb || d.capacity_mb) > 0);
  const okDimms = dimms.filter(d => ["ok", ""].includes((d.health || d.status || "ok").toLowerCase())).length;

  const drives = (s.storage_controllers || []).flatMap(c => c.drives || []);
  const okDrives = drives.filter(d => ["ok"].includes((d.health || "").toLowerCase())).length;
  const drivesColor = drives.length === 0 ? "#64748B" : okDrives === drives.length ? "#34C759" : "#FF3B30";
  const storageStale = (s.storage_controllers || []).some(c => c.stale) || drives.some(d => d.stale);
  const storageLastGoodAt = s.storage_last_good_at;

  const nics = s.network_adapters || [];

  return (
    <div className="rounded-lg border" style={{ borderColor: `${hc}30`, background: `${hc}04` }}>
      <div className="p-3">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-sm font-bold text-[var(--text-primary)]">{s.device_name}</p>
            <p className="text-[10px] text-[var(--text-muted)] font-mono">
              {s.device_ip} — {s.server_model || "?"} {s.serial_number ? `· S/N ${s.serial_number}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] px-2 py-1 rounded font-bold uppercase" style={{ color: hc, background: `${hc}18` }}>
              {s.health_status || "?"}
            </span>
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-[9px] px-2 py-1 rounded border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-cyan-400 hover:border-cyan-500/30 transition-colors"
            >
              {expanded ? "Nascondi dettagli" : "Mostra dettagli"}
            </button>
          </div>
        </div>

        {/* Live metrics sparkline — auto-refresh 15s */}
        <div className="mb-3 px-3 py-2 rounded-md bg-[#0d0d12]/40 border border-[var(--bg-border)]">
          <ILoLiveMetrics deviceIp={s.device_ip} deviceName={s.device_name} />
        </div>

        <div className="grid grid-cols-2 md:grid-cols-6 gap-2 mb-3">
          <MiniMetric
            label="Alimentazione"
            value={s.power_watts ? `${s.power_watts}W` : "N/D"}
            color={s.power_watts ? "#F59E0B" : "#64748B"}
          />
          <MiniMetric
            label={`Temp Max ${critTemps.length ? `(${critTemps.length} crit)` : warnTemps.length ? `(${warnTemps.length} warn)` : ""}`}
            value={maxTemp ? `${maxTemp.value}°C` : "N/D"}
            sub={maxTemp?.locale?.substring(0, 14)}
            color={tempColor}
          />
          <MiniMetric
            label={`Sensori`}
            value={temps.length || "N/D"}
            sub={`${critTemps.length + warnTemps.length} anom.`}
            color={critTemps.length ? "#FF3B30" : warnTemps.length ? "#FFCC00" : "#34C759"}
          />
          <MiniMetric label="RAM" value={s.total_memory_gb ? `${s.total_memory_gb}GB` : "N/D"} sub={dimms.length ? `${okDimms}/${dimms.length} DIMM` : null} color="#8B5CF6" />
          <MiniMetric label="Ventole" value={fans.length ? `${okFans}/${fans.length}` : "N/D"} color={fansColor} />
          <MiniMetric label="PSU" value={psus.length ? `${okPsus}/${psus.length}` : "N/D"} color={psuColor} />
        </div>

        {/* Top 3 hottest sensors breakdown (sempre visibile, sotto la griglia metriche) */}
        {topTemps.length > 0 && (
          <div className="mb-3 px-3 py-2 rounded-md bg-[#0d0d12]/40 border border-[var(--bg-border)]" data-testid={`top-temps-${s.device_ip}`}>
            <div className="text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-2 flex items-center gap-2">
              <span>Sensori più caldi</span>
              <span className="text-[8px] text-[var(--text-muted)]/70">(top 3 di {temps.length})</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {topTemps.map((t, idx) => {
                const sensorColor = t.value > 75 ? "#FF3B30" : t.value > 65 ? "#FFCC00" : "#34C759";
                const cond = (t.condition || "ok").toLowerCase();
                const prettyName = prettifySensorName(t.locale);
                return (
                  <button key={idx}
                    onClick={() => setTimelineSensor({ name: t.locale, pretty: prettyName, type: "temperature", device_ip: s.device_ip, device_name: s.device_name })}
                    className="px-2 py-1.5 rounded border text-left hover:brightness-125 transition"
                    style={{ borderColor: `${sensorColor}30`, background: `${sensorColor}08` }}
                    data-testid={`sensor-card-${s.device_ip}-${idx}`}
                    title="Clicca per grafico 24h">
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">Sensore {idx + 1}</span>
                      <span className="text-[8px] font-bold" style={{ color: sensorColor }}>{cond.toUpperCase()}</span>
                    </div>
                    <div className="text-[15px] font-bold mt-0.5" style={{ color: sensorColor }}>{t.value}°C</div>
                    <div className="text-[10px] text-[var(--text-primary)] truncate" title={t.locale}>{prettyName}</div>
                    <div className="text-[8px] text-[var(--text-muted)]/70 font-mono truncate">{t.locale}</div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-[9px]">
          <InfoBadge label="BIOS" value={s.bios_version} />
          <InfoBadge label="iLO FW" value={s.ilo_firmware} />
          <InfoBadge label="iLO License" value={s.ilo_license} />
          <InfoBadge
            label={storageStale ? "Storage (cache)" : "Storage"}
            value={
              drives.length
                ? `${okDrives}/${drives.length} drive OK${storageStale ? " · stale" : ""}`
                : "Nessun controller"
            }
            color={storageStale ? "#A78BFA" : drivesColor}
            tooltip={
              storageStale && storageLastGoodAt
                ? `Dati storage dal cache: ultimo poll completo ${new Date(storageLastGoodAt).toLocaleString("it-IT")}. Redfish /Storage ha avuto timeout o risposta vuota all'ultimo ciclo.`
                : undefined
            }
          />
        </div>

        {/* Firmware compliance badge (stile ParkPlace) */}
        {firmwareCompliance && (
          <FirmwareComplianceBadge fc={firmwareCompliance} />
        )}

        <div className="mt-2 text-[9px] text-[var(--text-muted)] flex items-center gap-2">
          <span>Modalità: <span className="font-mono uppercase text-[var(--text-primary)]">{s.polling_mode?.replace("_", " ") || "?"}</span></span>
          {s.last_poll && <span>· {new Date(s.last_poll).toLocaleString("it-IT", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" })}</span>}
        </div>
      </div>

      {expanded && (
        <div className="border-t border-[var(--bg-border)] p-3 space-y-3 bg-[var(--bg-panel)]">
          {/* Temperature sensors detail */}
          {temps.length > 0 && (
            <SensorTable
              title={`Temperature — ${temps.length} sensori`}
              headers={["Sensore", "Valore", "Stato"]}
              rows={temps.sort((a, b) => b.value - a.value).map(t => {
                const sev = t.value > 75 ? "critical" : t.value > 65 ? "warning" : "ok";
                const color = sev === "critical" ? "#FF3B30" : sev === "warning" ? "#FFCC00" : "#34C759";
                return [t.locale, `${t.value}°C`, { text: sev.toUpperCase(), color }];
              })}
            />
          )}
          {/* Fans detail */}
          {fans.length > 0 && (
            <SensorTable
              title={`Ventole — ${fans.length}`}
              headers={["Ventola", "RPM/%", "Stato"]}
              rows={fans.map(f => [f.locale, f.speed != null ? String(f.speed) : "—", {
                text: (f.condition || "?").toUpperCase(),
                color: (f.condition || "").toLowerCase() === "ok" ? "#34C759" : "#FF3B30"
              }])}
            />
          )}
          {/* PSUs detail */}
          {psus.length > 0 && (
            <SensorTable
              title={`Alimentatori — ${psus.length}`}
              headers={["Nome", "Capacità", "Stato"]}
              rows={psus.map(p => [p.name || "PSU", p.watts ? `${p.watts}W` : "—", {
                text: ((p.condition || p.health || "?").toUpperCase()),
                color: ["ok"].includes((p.condition || p.health || "").toLowerCase()) ? "#34C759" : "#FF3B30"
              }])}
            />
          )}
          {/* Storage drives */}
          {drives.length > 0 && (
            <SensorTable
              title={`Dischi — ${drives.length}`}
              headers={["Slot", "Modello", "Capacità", "Health", "Stato"]}
              rows={drives.map(d => [
                d.slot != null ? `#${d.slot}` : "—",
                d.model || d.name || "?",
                d.capacity_gb ? `${d.capacity_gb}GB` : "—",
                { text: (d.health || "?").toUpperCase(), color: (d.health || "").toLowerCase() === "ok" ? "#34C759" : "#FF3B30" },
                d.state || "?",
              ])}
            />
          )}
          {/* DIMMs */}
          {dimms.length > 0 && (
            <SensorTable
              title={`Memoria DIMM — ${dimms.length}`}
              headers={["Slot", "Capacità", "Velocità", "Tipo", "Stato"]}
              rows={dimms.map(d => [
                d.name || "?",
                d.size_gb ? `${d.size_gb}GB` : (d.capacity_mb ? `${d.capacity_mb}MB` : "?"),
                d.speed_mhz ? `${d.speed_mhz}MHz` : "—",
                d.type || "—",
                { text: (d.health || d.status || "?").toUpperCase(), color: ["ok"].includes((d.health || d.status || "").toLowerCase()) ? "#34C759" : "#FF3B30" },
              ])}
            />
          )}
          {/* NICs */}
          {nics.length > 0 && (
            <SensorTable
              title={`Interfacce di Rete — ${nics.length}`}
              headers={["Nome", "MAC", "Speed", "Link", "Stato"]}
              rows={nics.map(n => [
                n.name || n.id || "NIC",
                n.mac || "—",
                n.speed_mbps ? `${n.speed_mbps}Mbps` : "—",
                { text: (n.link_status || "?").toUpperCase(), color: (n.link_status || "").toLowerCase() === "linkup" ? "#34C759" : "#FF3B30" },
                (n.health || "?"),
              ])}
            />
          )}
          {temps.length === 0 && fans.length === 0 && psus.length === 0 && drives.length === 0 && (
            <p className="text-[10px] text-amber-400">
              ⚠ Nessun sensore hardware dettagliato disponibile. Verifica che la iLO risponda a /redfish/v1/Chassis/1/Thermal e Power.
            </p>
          )}
        </div>
      )}

      {/* Timeline modal */}
      {timelineSensor && (
        <SensorTimelineModal
          device_ip={timelineSensor.device_ip}
          device_name={timelineSensor.device_name}
          sensor={timelineSensor.name}
          pretty={timelineSensor.pretty}
          onClose={() => setTimelineSensor(null)}
        />
      )}
    </div>
  );
}

function SensorTimelineModal({ device_ip, device_name, sensor, pretty, onClose }) {
  const [hours, setHours] = useState(24);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await axios.get(`${API}/redfish/sensor-timeline/${device_ip}`, {
          params: { sensor, hours }
        });
        if (!cancelled) setData(res.data);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [device_ip, sensor, hours]);

  const points = (data?.points || []).map(p => ({
    ts: new Date(p.ts).getTime(),
    label: new Date(p.ts).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }),
    value: p.value,
    stale: p.stale,
  }));
  const stats = data?.stats || {};
  const isTemp = (stats.sensor_type || "temperature") === "temperature";
  const unit = isTemp ? "°C" : "%";

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#0d1117] border border-white/20 rounded-lg max-w-4xl w-full max-h-[90vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="p-5">
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="text-[11px] uppercase text-[var(--text-muted)] tracking-wider">{device_name} · {device_ip}</div>
              <h2 className="text-lg font-bold text-white mt-1">{pretty}</h2>
              <div className="text-[10px] text-[var(--text-muted)] font-mono">{sensor}</div>
            </div>
            <button onClick={onClose} className="text-white/40 hover:text-white text-xl leading-none px-2" data-testid="close-timeline">×</button>
          </div>

          <div className="flex items-center gap-2 mb-4">
            {[6, 24, 72, 168].map(h => (
              <button key={h} onClick={() => setHours(h)}
                className={`px-3 py-1 rounded text-[11px] font-medium transition ${hours === h ? "bg-violet-500/30 text-violet-200 border border-violet-500/50" : "bg-white/5 text-white/60 border border-white/10 hover:bg-white/10"}`}
                data-testid={`timeline-range-${h}`}>
                {h < 24 ? `${h}h` : h < 168 ? `${h/24}g` : "7g"}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="text-white/40 text-center py-12">Caricamento…</div>
          ) : points.length === 0 ? (
            <div className="text-white/40 text-center py-12">Nessun dato disponibile per questa finestra temporale.</div>
          ) : (
            <>
              <div className="grid grid-cols-4 gap-2 mb-4">
                <StatMini label="MIN" value={`${stats.min}${unit}`} color="#34C759" />
                <StatMini label="AVG" value={`${stats.avg}${unit}`} color="#8B5CF6" />
                <StatMini label="MAX" value={`${stats.max}${unit}`} color={stats.max > 75 && isTemp ? "#FF3B30" : stats.max > 65 && isTemp ? "#FFCC00" : "#34C759"} />
                <StatMini label="SAMPLES" value={stats.samples} color="#00D4FF" />
              </div>

              <div className="bg-[#0a0a0f] rounded border border-white/10 p-3">
                <ResponsiveContainer width="100%" height={320}>
                  <AreaChart data={points}>
                    <defs>
                      <linearGradient id="temp-grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#8B5CF6" stopOpacity={0.6} />
                        <stop offset="100%" stopColor="#8B5CF6" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                    <XAxis dataKey="label" stroke="rgba(255,255,255,0.3)" style={{ fontSize: 10 }} tickLine={false} />
                    <YAxis stroke="rgba(255,255,255,0.3)" style={{ fontSize: 10 }} unit={unit} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "#0d1117", border: "1px solid rgba(139,92,246,0.5)", borderRadius: 6, fontSize: 12 }}
                      labelStyle={{ color: "#fff" }}
                      formatter={(v, name, props) => [`${v}${unit}${props.payload.stale ? " (stale)" : ""}`, pretty]}
                    />
                    {isTemp && (
                      <>
                        <CartesianGrid />
                      </>
                    )}
                    <Area type="monotone" dataKey="value" stroke="#8B5CF6" strokeWidth={2} fill="url(#temp-grad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {isTemp && stats.max > 75 && (
                <div className="mt-3 p-2 rounded border border-rose-500/30 bg-rose-500/5 text-[11px] text-rose-400">
                  ⚠ Picco a {stats.max}°C rilevato nella finestra. Verifica ventilazione e raffreddamento della zona.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatMini({ label, value, color }) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded px-3 py-2">
      <div className="text-[9px] uppercase tracking-wider text-white/40">{label}</div>
      <div className="text-lg font-bold mt-0.5" style={{ color }}>{value}</div>
    </div>
  );
}

function InfoBadge({ label, value, color, tooltip }) {
  return (
    <div className="p-1.5 rounded bg-[var(--bg-panel)] border border-[var(--bg-border)]" title={tooltip}>
      <span className="text-[var(--text-muted)] uppercase text-[8px]">{label}</span>{" "}
      <span className="font-mono" style={{ color: color || "var(--text-primary)" }}>{value || "N/D"}</span>
    </div>
  );
}


// Mappa nomi sensori HPE iLO (ProLiant Gen10/Gen9/Gen11) a etichette leggibili italiane.
// iLO espone sensori come "53-CPU1 DigIO", "02-BMC Zone", "15-PCI 1", "01-Inlet Ambient", ecc.
// Rimuoviamo il prefisso ID + mappiamo le abbreviazioni piu' comuni.
function prettifySensorName(raw) {
  if (!raw) return "—";
  // Rimuove prefisso ID numerico stile "53-" o "02-"
  let n = raw.replace(/^\s*\d{1,3}\s*[-_]\s*/, "").trim();
  const lower = n.toLowerCase();

  // Regole di mapping ordinate per specificità
  const rules = [
    { re: /^cpu\s*(\d+)\s*dig\s*io/i, out: m => `CPU ${m[1]} — Digital I/O` },
    { re: /^cpu\s*(\d+)\s*zone/i, out: m => `CPU ${m[1]} — Zona termica` },
    { re: /^cpu\s*(\d+)\s*mem\s*zone/i, out: m => `CPU ${m[1]} — Memoria (DIMM)` },
    { re: /^cpu\s*(\d+)\s*vr/i, out: m => `CPU ${m[1]} — VRM alimentazione` },
    { re: /^cpu\s*(\d+)/i, out: m => `CPU ${m[1]}` },
    { re: /^p(\d+)\s*dimm\s*(\d+)\s*-\s*(\d+)/i, out: m => `Processore ${m[1]} · DIMM ${m[2]}-${m[3]}` },
    { re: /^p(\d+)\s*dimm/i, out: m => `Processore ${m[1]} · DIMM` },
    { re: /^dimm\s*(\d+)/i, out: m => `DIMM slot ${m[1]}` },
    { re: /^inlet\s*ambient/i, out: () => "Aria in ingresso (Inlet)" },
    { re: /^inlet/i, out: () => "Aria in ingresso" },
    { re: /^outlet/i, out: () => "Aria in uscita (Outlet)" },
    { re: /^ambient/i, out: () => "Ambiente sistema" },
    { re: /^sys\s*(amb|board)/i, out: () => "Scheda madre" },
    { re: /^bmc/i, out: () => "BMC (controller iLO)" },
    { re: /^ilo\s*zone/i, out: () => "Zona chip iLO" },
    { re: /^chipset\s*(\d+)?/i, out: m => m[1] ? `Chipset ${m[1]}` : "Chipset PCH" },
    { re: /^pch/i, out: () => "Chipset PCH" },
    { re: /^pci\s*(\d+)/i, out: m => `Slot PCI-E ${m[1]}` },
    { re: /^pci/i, out: () => "Slot PCI-E" },
    { re: /^vr\s*(\d+)?/i, out: m => m[1] ? `VRM ${m[1]}` : "VRM alimentazione" },
    { re: /^i\/?o\s*zone/i, out: () => "Zona I/O (PCIe/NIC)" },
    { re: /^i\/?o\s*board/i, out: () => "Scheda I/O" },
    { re: /^storage\s*batt/i, out: () => "Batteria cache RAID" },
    { re: /^storage\s*zone/i, out: () => "Zona storage" },
    { re: /^hdd\s*max/i, out: () => "Dischi (HDD/SSD)" },
    { re: /^hd\s*controller/i, out: () => "Controller RAID" },
    { re: /^fan\s*(\d+)/i, out: m => `Zona ventola ${m[1]}` },
    { re: /^nic\s*(\d+)?/i, out: m => m[1] ? `Scheda di rete ${m[1]}` : "Scheda di rete" },
    { re: /^power\s*supply\s*(\d+)?/i, out: m => m[1] ? `Alimentatore PSU ${m[1]}` : "Alimentatore" },
    { re: /^supercap/i, out: () => "SuperCap (Smart Array)" },
    { re: /^expansion\s*bay/i, out: () => "Bay espansione" },
    { re: /^memory/i, out: () => "Memoria RAM" },
  ];
  for (const r of rules) {
    const m = n.match(r.re);
    if (m) return r.out(m);
  }
  // Fallback: capitalizza + sostituisce abbreviazioni note
  n = n.replace(/\bzone\b/gi, "zona")
       .replace(/\btemp\b/gi, "")
       .replace(/\s+/g, " ")
       .trim();
  return n.charAt(0).toUpperCase() + n.slice(1);
}

function FirmwareComplianceBadge({ fc }) {
  const [open, setOpen] = useState(false);
  if (!fc || !fc.components?.length) return null;
  const status = fc.overall_status;
  const sev = fc.severity || "low";
  const colorMap = {
    compliant: { fg: "#34C759", bg: "#34C75918", label: "AGGIORNATO" },
    outdated: { fg: "#FFCC00", bg: "#FFCC0018", label: "FW OUTDATED" },
    critical: { fg: "#FF3B30", bg: "#FF3B3018", label: "CVE CRITICAL" },
  };
  const c = colorMap[status] || colorMap.compliant;
  const totalCves = fc.components.reduce((a, x) => a + (x.cve_list?.length || 0), 0);
  return (
    <div className="mt-2" data-testid={`firmware-compliance-${fc.device_ip || "unknown"}`}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full text-left px-2 py-1.5 rounded border transition-colors hover:brightness-125"
        style={{ borderColor: `${c.fg}40`, background: c.bg }}
      >
        <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: c.fg }}>
          {c.label}
        </span>
        {totalCves > 0 && (
          <span className="text-[10px] font-mono" style={{ color: c.fg }}>
            · {totalCves} CVE
          </span>
        )}
        <span className="text-[10px] text-[var(--text-muted)] ml-auto">
          {fc.components.length} componenti · {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-1 px-2">
          {fc.components.map((comp, i) => {
            const ok = comp.status === "up_to_date";
            const critical = comp.status === "critical_outdated";
            const compColor = ok ? "#34C759" : critical ? "#FF3B30" : "#FFCC00";
            return (
              <div key={i} className="text-[10px] border-l-2 pl-2" style={{ borderColor: compColor }}>
                <div className="flex items-center justify-between">
                  <span className="font-mono uppercase text-[var(--text-muted)]">{comp.component}</span>
                  <span className="font-mono" style={{ color: compColor }}>
                    {comp.current_version} {ok ? "=" : "→"} {comp.latest_version}
                  </span>
                </div>
                {(comp.cve_list || []).length > 0 && (
                  <div className="text-[9px] text-rose-400 mt-0.5">
                    CVE: {comp.cve_list.join(", ")}
                  </div>
                )}
                {comp.advisory_url && (
                  <a href={comp.advisory_url} target="_blank" rel="noopener noreferrer"
                    className="text-[9px] text-cyan-400 hover:underline">
                    Advisory →
                  </a>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


function SensorTable({ title, headers, rows }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1">{title}</p>
      <div className="rounded border border-[var(--bg-border)] overflow-hidden">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="bg-[var(--bg-hover)]">
              {headers.map((h, i) => <th key={i} className="px-2 py-1 text-left text-[9px] font-bold text-[var(--text-muted)] uppercase">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-[var(--bg-border)] hover:bg-[var(--bg-hover)]">
                {r.map((cell, j) => (
                  <td key={j} className="px-2 py-1 font-mono">
                    {typeof cell === "object" && cell !== null && cell.text ? (
                      <span style={{ color: cell.color }} className="font-bold">{cell.text}</span>
                    ) : (
                      <span className="text-[var(--text-primary)]">{cell}</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MiniMetric({ label, value, sub, color }) {
  return (
    <div className="px-2 py-1.5 rounded bg-[var(--bg-panel)] border border-[var(--bg-border)] text-center">
      <p className="text-[7px] uppercase tracking-widest text-[var(--text-muted)] mb-0.5 truncate" title={label}>{label}</p>
      <p className="text-[11px] font-bold" style={{ color: color || "var(--text-primary)" }}>{value}</p>
      {sub && <p className="text-[7px] text-[var(--text-muted)] truncate">{sub}</p>}
    </div>
  );
}

/* ==================== VITAL TOGGLE BUTTON ====================
   v2026-02-28: toggle 3-stati per il criticality tier di un device:
   - vital=true (stella piena gialla)  → alert SEMPRE inviati
   - vital=false (stella vuota grigia) → alert silenziati di default
   - vital=null (stella outline neutra) → backward compat (non scelto)
   Endpoint backend: POST /api/devices/by-ip/{ip}/vital body
   {is_vital: bool, client_id: str, reason?: str}
/* ==================== DEVICE GROUP ==================== */
function DeviceGroup({ label, icon: Icon, devices, color, onInfoClick, renderActions, macroKey, onDeviceDrop, clientId: clientIdProp, selectedIps, onToggleSelect }) {
  // v2026-02-28 SAFETY: fallback su useParams (vedi commento in OverviewTab)
  const { clientId: clientIdParam } = useParams();
  const clientId = clientIdProp || clientIdParam;
  // Use centralized pickDeviceName (mirror di best_display_name backend):
  // priorita' name → hostname → sys_name → mdns → fingerbank → ip.
  // Filtra automaticamente nomi "categoriali" Fingerbank (es. "Foo/Bar").
  const _displayName = (d) => pickDeviceName(d, d.ip_address || "—");
  // v2026-02-13 DRAG & DROP: highlight visivo quando un device viene trascinato sopra
  const [isDragOver, setIsDragOver] = useState(false);
  const dropEnabled = !!(macroKey && onDeviceDrop);
  return (
    <div
      onDragOver={dropEnabled ? (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setIsDragOver(true); } : undefined}
      onDragLeave={dropEnabled ? () => setIsDragOver(false) : undefined}
      onDrop={dropEnabled ? (e) => {
        e.preventDefault();
        setIsDragOver(false);
        try {
          const payload = JSON.parse(e.dataTransfer.getData("application/x-argus-device") || "{}");
          if (payload.ip && payload.fromMacro !== macroKey) {
            onDeviceDrop(payload, macroKey);
          }
        } catch { /* malformed payload */ }
      } : undefined}
      className={dropEnabled && isDragOver ? "rounded-lg ring-2 ring-offset-1 ring-offset-transparent" : ""}
      style={dropEnabled && isDragOver ? { ringColor: color } : undefined}
      data-testid={dropEnabled ? `drop-target-${macroKey}` : undefined}
    >
      <div className="flex items-center gap-1.5 mb-1">
        <Icon size={11} weight="bold" style={{ color }} />
        <p className="text-[8px] uppercase tracking-widest" style={{ color }}>
          {label} ({devices.length}){isDragOver ? " — rilascia qui" : ""}
        </p>
      </div>
      <div className="space-y-1">
        {devices.map((d, i) => {
          const sc = getStatusColor(d.status);
          const name = _displayName(d);
          const nameIsIP = name === (d.ip_address || "");
          const clickable = !!onInfoClick;
          return (
            <div
              key={i}
              draggable={dropEnabled}
              onDragStart={dropEnabled ? (e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("application/x-argus-device", JSON.stringify({
                  ip: d.ip_address, name: d.name, fromMacro: macroKey,
                }));
              } : undefined}
              onClick={clickable ? () => onInfoClick(d) : undefined}
              className={`flex items-center gap-2 px-2.5 py-1.5 rounded-md border text-[10px] ${clickable ? "cursor-pointer hover:brightness-125 transition-all" : ""} ${dropEnabled ? "active:cursor-grabbing" : ""}`}
              style={{ borderColor: `${sc}20`, background: `${sc}04` }}
              data-testid={clickable ? `grouped-device-row-${d.ip_address}` : undefined}
              title={dropEnabled ? "Trascina su un'altra categoria per riclassificare" : (d.notes || "")}
            >
              {onToggleSelect && (
                <div
                  onClick={(e) => { e.stopPropagation(); onToggleSelect(d.ip_address); }}
                  onMouseDown={(e) => e.stopPropagation()}
                  className="flex items-center justify-center -my-1.5 -ml-1 py-1.5 px-1.5 cursor-pointer flex-shrink-0"
                  title="Seleziona per azione multipla (vitali)"
                  data-testid={`select-device-${d.ip_address}`}
                >
                  <input
                    type="checkbox"
                    checked={selectedIps?.has(d.ip_address) || false}
                    readOnly
                    tabIndex={-1}
                    className="w-4 h-4 accent-yellow-500 pointer-events-none"
                  />
                </div>
              )}
              <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: sc }}></div>
              <span className={`font-medium truncate ${nameIsIP ? "text-[var(--text-muted)] italic" : "text-[var(--text-primary)]"}`} title={d.notes || ""}>{name}</span>
              {!nameIsIP && <span className="font-mono text-[var(--text-muted)]">{d.ip_address}</span>}
              {/* v2026-06-23: badge "Visto via" mostra la fonte di liveness
                  quando il device È online grazie a evidence diversa dal
                  ping (es. ARP broadcast scanner, FDB switch, sysName SNMP).
                  Aiuta l'operatore a capire perché il NOC dichiara online
                  un device che potrebbe sembrare "offline" nel poll regolare
                  (Windows Firewall ICMP rate-limit, switch ICMP rate-limit). */}
              {d.status === "online" && d.live_evidence && d.live_evidence !== "ping" && (
                <span
                  className="inline-flex items-center gap-0.5 text-[8px] px-1 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 font-mono"
                  title={`Liveness confermata via: ${d.live_evidence.replace(/_/g, ' ')}. Lo Scanner LAN del Connector ha visto questo device alive recentemente anche se ICMP/SNMP poll regolare potrebbe fallire (es. firewall ICMP rate-limited).`}
                  data-testid={`grouped-live-evidence-${d.ip_address}`}
                >
                  via {d.live_evidence === "agent_v4_arp" ? "ARP" :
                       d.live_evidence === "mac_table_switch" ? "FDB" :
                       d.live_evidence === "scanner_lan" ? "scan" :
                       d.live_evidence === "snmp_sysname" ? "SNMP" :
                       d.live_evidence}
                </span>
              )}
              {d.datto_name && d.datto_name !== name && (
                <span
                  className="inline-flex items-center gap-0.5 text-[8px] px-1 py-0.5 rounded bg-fuchsia-500/20 text-fuchsia-200 border border-fuchsia-500/40 font-bold"
                  title={`Datto RMM: ${d.datto_name}${d.datto_match ? ` (match via ${d.datto_match.toUpperCase()})` : ""}`}
                  data-testid={`datto-badge-${d.ip_address}`}
                >
                  DATTO: {d.datto_name}
                </span>
              )}
              {d.vendor && <span className="text-[8px] px-1 rounded bg-[var(--bg-card)] text-[var(--text-muted)] truncate max-w-[120px]" title={d.vendor}>{d.vendor}</span>}
              {d.snmp_community && <span className="text-[8px] px-1 rounded bg-[var(--bg-card)] text-[var(--text-muted)]">{d.snmp_version || "snmp"}: {d.snmp_community}</span>}
              <span className="ml-auto font-bold text-[8px] uppercase" style={{ color: sc }}>{d.status}</span>
              {d.source === "connector" && <span className="text-[7px] px-1 rounded bg-indigo-500/10 text-indigo-400">M</span>}
              {d.source === "connector-master" && <span className="text-[7px] px-1 rounded bg-indigo-500/10 text-indigo-400">M</span>}
              {d.source === "connector-scanner" && <span className="text-[7px] px-1 rounded bg-sky-500/10 text-sky-400">S</span>}
              {renderActions && (
                <div className="flex items-center gap-0.5 ml-1 pl-1.5 border-l border-[var(--bg-border)]" onClick={(e) => e.stopPropagation()}>
                  {renderActions(d)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ==================== DEVICES GROUPED VIEW (clone Panoramica) ====================
   Stesse macroaree, stessi colori/icone, stesso DeviceGroup component, ma con
   click su riga → apre Scheda Dispositivo (info card completa).
   v2026-02-13: richiesto dall'utente "voglio struttura identica come clone"
*/

/* ============ EMPTY MACRO DROP TARGET ============
   Drop zone "ghost" per una macroarea che attualmente non ha device,
   cosi' l'admin puo' creare il primo device nella categoria via drag.
*/
function EmptyMacroDropTarget({ macroKey, label, color, icon: Icon, onDeviceDrop }) {
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        try {
          const payload = JSON.parse(e.dataTransfer.getData("application/x-argus-device") || "{}");
          if (payload.ip && payload.fromMacro !== macroKey) {
            onDeviceDrop(payload, macroKey);
          }
        } catch { /* ignore */ }
      }}
      className={`flex items-center gap-1.5 px-2 py-1 rounded border border-dashed text-[9px] transition-all ${over ? "border-solid scale-105" : "opacity-50 hover:opacity-100"}`}
      style={{ borderColor: color, color }}
      data-testid={`drop-target-empty-${macroKey}`}
    >
      <Icon size={10} weight="bold" />
      <span className="uppercase tracking-wider">{label}</span>
    </div>
  );
}

function DevicesGroupedView({ devices, skipList, onInfoClick, renderActions, onDeviceMove, clientId, selectedIps, onToggleSelect }) {
  // Partizionamento via macroOf (utils/deviceCategory)
  const buckets = {
    firewall: [], switch: [], router: [], server: [], nas: [], ups: [], ap: [],
    tvcc: [], printer: [], voip: [], workstation: [], mobile: [], iot: [], other: [],
  };
  devices.forEach(d => {
    const m = macroOf(d);
    if (m === "_skip") return;
    if (buckets[m]) buckets[m].push(d);
    else buckets.other.push(d);
  });

  const GROUPS = [
    { key: "firewall",    label: "Firewall",                                   icon: ShieldCheck, color: "#FF3B30" },
    { key: "switch",      label: "Switch",                                     icon: HardDrives,  color: "#6366F1" },
    { key: "router",      label: "Router",                                     icon: Network,     color: "#0EA5E9" },
    { key: "server",      label: "Server / iLO",                               icon: Monitor,     color: "#06B6D4" },
    { key: "nas",         label: "NAS / Storage",                              icon: Database,    color: "#14B8A6" },
    { key: "ups",         label: "UPS",                                        icon: Lightning,   color: "#EAB308" },
    { key: "ap",          label: "Access Point / WiFi",                        icon: WifiHigh,    color: "#8B5CF6" },
    { key: "tvcc",        label: "TVCC / Videosorveglianza",                   icon: Monitor,     color: "#F97316" },
    { key: "printer",     label: "Stampanti",                                  icon: Printer,     color: "#EC4899" },
    { key: "voip",        label: "Telefoni VoIP",                              icon: Phone,       color: "#22C55E" },
    { key: "workstation", label: "Workstation / PC",                           icon: Desktop,     color: "#3B82F6" },
    { key: "mobile",      label: "Smartphone / Mobile (MAC randomizzato)",     icon: DeviceMobile,color: "#A855F7" },
    { key: "iot",         label: "IoT / Embedded",                             icon: Cpu,         color: "#F59E0B" },
    { key: "other",       label: "Altri Dispositivi",                          icon: HardDrives,  color: "#64748B" },
  ];

  const totalShown = devices.length;
  if (totalShown === 0) {
    return (
      <div className="noc-panel p-8 text-center text-[var(--text-muted)] text-xs">
        Nessun dispositivo — clicca "Aggiungi Dispositivo" per iniziare
      </div>
    );
  }

  return (
    <div className="noc-panel p-4" data-testid="devices-grouped-view">
      <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-indigo-400 mb-3 flex items-center justify-between">
        <span>Infrastruttura di rete · {totalShown} dispositivi</span>
        {onDeviceMove && (
          <span className="text-[8px] text-[var(--text-muted)] font-normal tracking-normal normal-case italic">
            💡 Trascina un device per spostarlo in un'altra categoria
          </span>
        )}
      </p>
      <div className="space-y-3">
        {GROUPS.map(g => (
          buckets[g.key].length > 0 ? (
            <DeviceGroup
              key={g.key}
              label={g.label}
              icon={g.icon}
              devices={buckets[g.key]}
              color={g.color}
              onInfoClick={onInfoClick}
              renderActions={renderActions}
              macroKey={g.key}
              onDeviceDrop={onDeviceMove}
              clientId={clientId}
              selectedIps={selectedIps}
              onToggleSelect={onToggleSelect}
            />
          ) : null
        ))}
        {/* Drop targets per macroaree VUOTE: visibili come "ghosts" sottili
            in fondo, cosi' l'admin puo' "popolare" una categoria che oggi
            e' vuota (es. trascinare il primo Server in una rete che fino
            a ieri aveva solo workstation). */}
        {onDeviceMove && GROUPS.filter(g => buckets[g.key].length === 0).length > 0 && (
          <div className="pt-3 mt-3 border-t border-dashed border-[var(--bg-border)]">
            <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
              ↓ Categorie disponibili (trascina qui per spostare)
            </p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-1">
              {GROUPS.filter(g => buckets[g.key].length === 0).map(g => (
                <EmptyMacroDropTarget
                  key={g.key}
                  macroKey={g.key}
                  label={g.label}
                  color={g.color}
                  icon={g.icon}
                  onDeviceDrop={onDeviceMove}
                />
              ))}
            </div>
          </div>
        )}
        {skipList && skipList.length > 0 && (
          <details className="opacity-60 hover:opacity-100 transition-opacity">
            <summary className="cursor-pointer text-[9px] uppercase tracking-[0.15em] text-[var(--text-muted)] py-2 select-none">
              ▸ Multicast / broadcast nascosti ({skipList.length})
            </summary>
            <DeviceGroup
              label="Multicast / Broadcast (non gestiti)"
              icon={NetworkSlash}
              devices={skipList}
              color="#6B7280"
              onInfoClick={onInfoClick}
              renderActions={renderActions}
              clientId={clientId}
              selectedIps={selectedIps}
              onToggleSelect={onToggleSelect}
            />
          </details>
        )}
      </div>
    </div>
  );
}

/* ============ DEVICE ACTIONS BAR (stesso set di icone della tabella) ============
   8 azioni cliccabili: Web Console (se applicabile) · Info card · Switch Ports
   (se device è portable) · Trend · Test SNMP · Edit · Profilo · Delete.
   Stesso identico stile/colori della tabella tradizionale, in modo che chi
   cambia vista non perda nulla.
   v2026-02-13: aggiunto per ripristinare i comandi rimossi nella vista
   raggruppata.
*/
function DeviceActionsBar({ d, testingId, onWebConsole, showWebConsole, webPort, onInfo, onSwitchPorts, onTrend, onTestSnmp, onEdit, onProfile, onDelete }) {
  const dt = (d.device_type || "").toLowerCase();
  const modelL = (d.model || d.sys_descr || "").toLowerCase();
  const nameL = (d.name || "").toLowerCase();
  const portsKw = [
    "switch", "router", "firewall", "gateway",
    "catalyst", "nexus", "meraki",
    "procurve", "aruba", "5130", "5140", "5900",
    "ex2300", "ex3400", "ex4300", "srx",
    "fortigate", "fortiswitch", "fortiap",
    "zyxel", "xgs", "gs1900", "gs2200",
    "mikrotik", "routerboard", "ccr", "crs",
    "unifi", "edgerouter", "edgeswitch", "usg",
    "dgs-", "dxs-",
    "powerconnect", "n1500", "n2000", "n3000",
    "huawei", "s5700", "s6700", "ar2200",
    "pfsense", "opnsense",
    "synology", "qnap", "diskstation", "rackstation", "ts-",
  ];
  const portsMatches = portsKw.some(k => modelL.includes(k) || nameL.includes(k));
  const isPortable =
    dt.includes("switch") || dt.includes("router") || dt.includes("firewall") ||
    dt === "nas" || dt === "network-device" || portsMatches;
  const portsTip = dt === "firewall" ? "Porte firewall (ifTable)"
    : dt === "nas" ? "Interfacce NAS (ifTable)"
    : "Porte switch (UP/DOWN + LLDP + flap)";

  const profileClass = d.profile_key
    ? (d.profile_auto_matched
        ? "hover:bg-emerald-500/10 text-emerald-400"
        : "hover:bg-cyan-500/10 text-cyan-400")
    : "hover:bg-amber-500/10 text-amber-400 animate-pulse";
  const profileTitle = d.profile_key
    ? `Profilo: ${d.profile_key}${d.profile_auto_matched ? " (auto)" : " (manuale)"}`
    : "Nessun profilo — clicca per configurare";

  return (
    <>
      {showWebConsole && (
        <button
          onClick={onWebConsole}
          className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
          title={`Apri Web Console (porta ${webPort})${d.profile_key ? ` · profilo ${d.profile_key}` : ""}`}
          data-testid={`grouped-web-console-${d.ip_address}`}
        >
          <Monitor size={11} />
        </button>
      )}
      <button
        onClick={onInfo}
        className="p-1 rounded hover:bg-cyan-500/10 text-cyan-400 transition-colors"
        title="Scheda dispositivo completa"
        data-testid={`grouped-device-info-${d.ip_address}`}
      >
        <Info size={11} />
      </button>
      {isPortable && (
        <button
          onClick={onSwitchPorts}
          className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
          title={portsTip}
          data-testid={`grouped-switch-ports-${d.ip_address}`}
        >
          <NetworkSlash size={11} />
        </button>
      )}
      <button
        onClick={onTrend}
        className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
        title="Trend metriche storiche"
        data-testid={`grouped-device-trend-${d.ip_address}`}
      >
        <ChartLine size={11} />
      </button>
      <button
        onClick={onTestSnmp}
        disabled={testingId === d.id}
        className="p-1 rounded hover:bg-emerald-500/10 text-emerald-400 transition-colors disabled:opacity-30 disabled:cursor-wait"
        title="Test SNMP live"
        data-testid={`grouped-test-snmp-${d.ip_address}`}
      >
        {testingId === d.id ? <span className="inline-block animate-spin text-[10px]">⟳</span> : <span className="text-[10px]">⚡</span>}
      </button>
      <button
        onClick={onEdit}
        className="p-1 rounded hover:bg-violet-500/10 text-violet-400 transition-colors"
        title="Modifica dispositivo"
        data-testid={`grouped-edit-device-${d.ip_address}`}
      >
        <PencilSimple size={11} />
      </button>
      <button
        onClick={onProfile}
        className={`p-1 rounded transition-colors ${profileClass}`}
        title={profileTitle}
        data-testid={`grouped-configure-profile-${d.ip_address}`}
      >
        <Cpu size={11} />
      </button>
      <button
        onClick={onDelete}
        className="p-1 rounded hover:bg-[var(--critical-bg)] text-[var(--critical)] transition-colors"
        title="Rimuovi"
        data-testid={`grouped-delete-device-${d.ip_address}`}
      >
        <Trash size={10} />
      </button>
    </>
  );
}


/* ==================== DEVICES TAB ==================== */
function DevicesTab({ devices, clientId, onRefresh, onOptimisticUpdate }) {
  const [showAdd, setShowAdd] = useState(false);
  const [profileTarget, setProfileTarget] = useState(null);
  const [infoTarget, setInfoTarget] = useState(null);
  const [infoCardName, setInfoCardName] = useState(null);
  // v2026-06-02 fix ghosting: quando l'utente clicca su un device diverso
  // mentre il dialog Scheda Dispositivo e' gia' aperto, il titolo non deve
  // mostrare il nome del device precedente. Resettiamo subito infoCardName
  // appena cambia infoTarget.ip_address; verra' ripopolato da onCardLoaded
  // del nuovo device (DeviceInfoCard remountato grazie alla key prop).
  useEffect(() => {
    setInfoCardName(null);
  }, [infoTarget?.ip_address]);
  const [editTarget, setEditTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  // v3.8.40: nasconde multicast/broadcast (224.x, 239.x, 255.x) dalla tabella
  // di default per coerenza con card "DISPOSITIVI" e Infrastruttura. L'utente
  // puo' attivare il toggle per mostrarli a fini di debug/visibilita' completa.
  const [showMulticast, setShowMulticast] = useState(false);
  // v2026-07: tab "Dispositivi Vitali" — mostra di default SOLO i device
  // marcati come vitali (impostati dalla Panoramica). L'utente puo' comunque
  // passare a "Tutti" dal toggle. Nuova chiave storage per forzare il default.
  const [vitalFilter, setVitalFilter] = useState(() => {
    try { return localStorage.getItem("client-devices-vital-filter-v2") || "vital"; }
    catch { return "vital"; }
  });
  useEffect(() => {
    try { localStorage.setItem("client-devices-vital-filter-v2", vitalFilter); }
    catch { /* ignore */ }
  }, [vitalFilter]);
  // v2026-02-13: vista raggruppata per categoria (clone struttura Panoramica)
  // default "grouped" come richiesto dall'utente ("voglio struttura identica clone")
  const [viewMode, setViewMode] = useState(() => {
    try {
      return localStorage.getItem("client-devices-view") || "grouped";
    } catch { return "grouped"; }
  });
  useEffect(() => {
    try { localStorage.setItem("client-devices-view", viewMode); } catch { /* ignore */ }
  }, [viewMode]);
  // v2026-06: selezione multipla per marcare/rimuovere VITALI in blocco.
  const [selectedIps, setSelectedIps] = useState(() => new Set());
  const [bulkSaving, setBulkSaving] = useState(false);
  const toggleSelect = (ip) => setSelectedIps(prev => {
    const n = new Set(prev);
    if (n.has(ip)) n.delete(ip); else n.add(ip);
    return n;
  });
  const clearSelection = () => setSelectedIps(new Set());
  const webConsole = useWebConsoleTabs();
  const _isMcast = (d) => /^(22[4-9]|23\d|255)\./.test(d?.ip_address || "");
  const visibleDevices = showMulticast ? devices : devices.filter(d => !_isMcast(d));
  const hiddenCount = devices.length - visibleDevices.length;

  // v2026-06: azione multipla vitali. Le checkbox operano sui device visibili.
  const visibleIps = visibleDevices.map(d => d.ip_address).filter(Boolean);
  const allVisibleSelected = visibleIps.length > 0 && visibleIps.every(ip => selectedIps.has(ip));
  const toggleSelectAllVisible = () => setSelectedIps(prev => {
    if (allVisibleSelected) return new Set();
    return new Set(visibleIps);
  });
  const bulkSetVital = async (isVital) => {
    const ips = Array.from(selectedIps);
    if (!ips.length) return;
    setBulkSaving(true);
    try {
      const { data } = await axios.post(`${API}/devices/bulk-vital`, {
        ips, is_vital: isVital, client_id: clientId,
      });
      toast.success(data.message || `${data.modified} dispositivi aggiornati`);
      clearSelection();
      onRefresh?.();
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Errore sconosciuto";
      toast.error(`Azione multipla fallita: ${detail}`);
    } finally {
      setBulkSaving(false);
    }
  };
  const bulkSetSilence = async (silenced) => {
    const ips = Array.from(selectedIps);
    if (!ips.length) return;
    setBulkSaving(true);
    try {
      const { data } = await axios.post(`${API}/devices/bulk-silence`, {
        ips, silenced, client_id: clientId,
      });
      toast.success(data.message || `${data.modified} dispositivi aggiornati`);
      clearSelection();
      onRefresh?.();
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Errore sconosciuto";
      toast.error(`Azione multipla fallita: ${detail}`);
    } finally {
      setBulkSaving(false);
    }
  };
  // v3.8.40: usa visibleDevices (filtrati) per escludere multicast quando richiesto
  const { sorted: sortedDevices, sortKey, sortDir, requestSort } = useSortableTable(
    visibleDevices, "name", "asc",
    {
      persistKey: "client-devices-tab",
      accessors: {
      ip_address: (d) => {
        // Numeric IPv4 sort: 192.168.1.10 viene dopo 192.168.1.2
        const ip = d?.ip_address || "";
        const parts = ip.split(".").map(p => parseInt(p, 10));
        if (parts.length === 4 && parts.every(n => !isNaN(n))) {
          return parts[0] * 16777216 + parts[1] * 65536 + parts[2] * 256 + parts[3];
        }
        return ip.toLowerCase();
      },
      monitor_type: (d) => (d?.monitor_type || "snmp").toLowerCase(),
      snmp: (d) => (d?.snmp_version || "").toLowerCase(),
      community: (d) => (d?.snmp_community || "").toLowerCase(),
      status: (d) => (d?.status || "").toLowerCase(),
      connection: (d) => (d?.connection_type || "zzz").toLowerCase(),
      source: (d) => (d?.source || "manual").toLowerCase(),
      last_poll: (d) => d?.last_poll ? Date.parse(d.last_poll) : 0,
      }
    }
  );

  // 1 click sul pulsante Monitor:
  //  - Apre la Web Console in UNA NUOVA TAB (V4 popup) tramite proxy HTTP diretto del
  //    Center (backend -> device via tunnel WireGuard quando attivo, altrimenti via
  //    route LAN diretta). L'utente vive l'esperienza di navigazione NATIVA:
  //    indietro/avanti, cookies, Basic/Digest auth dialog, download di file — come
  //    se avesse digitato https://<ip>:<port>/ nella barra indirizzi del browser.
  //  - In parallelo (best-effort, non blocca l'apertura) attiva una sessione VPN
  //    audit-scoped al solo device target (TTL 30 min), cosi' il Center ha rotta
  //    verso l'IP privato via tunnel cifrato. Se il setup VPN non e' completo (es.
  //    connector offline o WG non configurato), la sessione fallisce in silenzio e
  //    la proxy V4 tenta comunque il connect diretto.
  //  - Fallback: se il browser blocca la popup (ad es. pop-up blocker senza user
  //    gesture grace window), ripieghiamo sull'iframe V3 LIVE nel dock in basso.
  const openConsoleWithVpn = async (device) => {
    if (!clientId || !device?.ip_address) return;

    // Fire-and-forget: attivazione VPN audit in background (non blocca la popup,
    // altrimenti il browser perderebbe il "user-gesture trust" e bloccherebbe window.open)
    axios
      .post(`${API}/admin/wireguard/session/start`, {
        client_id: clientId,
        target_device_ip: device.ip_address,
        reason: `Web Console: ${device.name || device.ip_address}`,
        ttl_minutes: 30,
        restrict_to_registered_devices: true,
      })
      .catch((e) => {
        const status = e?.response?.status;
        if (status && status !== 404 && status !== 422) {
          console.warn("VPN audit session failed:", e?.response?.data?.detail || e.message);
        }
      });

    // Apri V4 popup (nuova tab). Il backend firma un JWT, torna l'URL proxied
    // e apriamo window.open subito — esperienza "browser nativo".
    const result = await webConsole.openPopup(device.ip_address);

    if (!result) {
      // Popup bloccato / sessione V4 non creabile -> fallback iframe V3 LIVE nel dock
      webConsole.open(clientId, device.ip_address, defaultWebPort(device));
    }
  };

  const emptyForm = {
    name: "", ip: "", device_type: "generic", monitor_type: "snmp",
    snmp_version: "v2c", community: "public", http_port: "80",
    snmpv3_username: "", snmpv3_auth_protocol: "SHA", snmpv3_auth_password: "",
    snmpv3_priv_protocol: "AES", snmpv3_priv_password: "",
    snmpv3_security_level: "authPriv",
  };
  const [form, setForm] = useState(emptyForm);

  const handleSave = async () => {
    if (!form.ip || !form.name) {
      toast.error("Nome e IP sono obbligatori");
      return;
    }
    setSaving(true);
    try {
      const isSnmp = form.monitor_type === "snmp" || form.monitor_type === "snmp+http";
      const isHttp = form.monitor_type === "http" || form.monitor_type === "snmp+http";
      const payload = {
        name: form.name,
        ip: form.ip,
        device_type: form.device_type,
        monitor_type: form.monitor_type,
        http_port: isHttp ? parseInt(form.http_port || 80) : 80,
        community: isSnmp && form.snmp_version !== "v3" ? (form.community || "public") : "",
        snmp_version: form.snmp_version,
      };
      if (isSnmp && form.snmp_version === "v3") {
        payload.snmpv3_username = form.snmpv3_username;
        payload.snmpv3_auth_protocol = form.snmpv3_auth_protocol;
        payload.snmpv3_auth_password = form.snmpv3_auth_password;
        payload.snmpv3_priv_protocol = form.snmpv3_priv_protocol;
        payload.snmpv3_priv_password = form.snmpv3_priv_password;
        payload.snmpv3_security_level = form.snmpv3_security_level;
      }
      await axios.post(`${API}/connector/${clientId}/managed-devices`, payload);
      toast.success(`Dispositivo ${form.name} aggiunto. Il connector lo rileverà entro pochi cicli.`);
      setForm(emptyForm);
      setShowAdd(false);
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nel salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const cleanupStaleDevices = async () => {
    try {
      // Dry-run cleanup basato su staleness (device con last_seen > 30 min ma connector online)
      const { data: preview } = await axios.post(
        `${API}/connector/${clientId}/cleanup-stale-devices`,
        { dry_run: true, stale_threshold_minutes: 30 }
      );
      if (!preview?.ok) {
        toast.error(preview?.message || "Connector offline o non registrato — cleanup saltato");
        return;
      }
      const count = preview.candidates_count || 0;
      if (count === 0) {
        toast.info("Nessun device scomparso dal connector");
        return;
      }
      const ipList = (preview.candidates || []).map(c => `• ${c.name || "(?)"} (${c.ip}) — stale ${c.stale_minutes}min`).join("\n");
      const confirmed = window.confirm(
        `Sto per rimuovere ${count} device che non sono piu' visti dal connector:\n\n${ipList}\n\nConfermi? (I device manuali e quelli silenziati sono protetti)`
      );
      if (!confirmed) return;
      const { data: result } = await axios.post(
        `${API}/connector/${clientId}/cleanup-stale-devices`,
        { dry_run: false, stale_threshold_minutes: 30 }
      );
      toast.success(`Rimossi ${result.removed_count || 0} device scomparsi dal connector`);
      onRefresh?.();
    } catch (e) {
      const status = e.response?.status;
      const det = e.response?.data?.detail || e.message;
      if (status === 404 && /not found/i.test(det) && !/connector/i.test(det)) {
        toast.error("Backend non aggiornato: endpoint /cleanup-stale-devices non esiste. Aggiorna il backend Center a v3.5.27-fase2+.", { duration: 7000 });
      } else if (status === 404 && /connector/i.test(det || "")) {
        toast.error("Connector non registrato per questo cliente: non posso sincronizzare finche` il connector non fa il primo heartbeat.");
      } else {
        toast.error(`Errore cleanup: ${det}`);
      }
    }
  };

  const rematchProfiles = async () => {
    try {
      const { data } = await axios.post(`${API}/clients/${clientId}/rematch-profiles`);
      const { total = 0, matched = 0, skipped = 0, details = [], community_propagated = 0, community_used = "" } = data || {};
      if (matched === 0 && total === 0 && community_propagated === 0) {
        toast.info("Nessun device da riconoscere");
        return;
      }
      // Build compact summary for toast
      const newMatches = details
        .filter(d => d.matched)
        .map(d => `• ${d.name || d.device_ip} → ${d.vendor || d.profile_key}`)
        .slice(0, 6);
      const extra = details.filter(d => d.matched).length - newMatches.length;
      const lines = [];
      if (community_propagated > 0 && community_used) {
        lines.push(`🔑 Community '${community_used}' propagata su ${community_propagated} device`);
      }
      if (newMatches.length) lines.push(...newMatches);
      if (extra > 0) lines.push(`…e altri ${extra} profili`);
      const body = lines.join("\n");
      if (matched > 0 || community_propagated > 0) {
        toast.success(
          `Profili ${matched}/${total}${community_propagated ? ` · community su ${community_propagated} dev.` : ""}`,
          { description: body || `Skipped: ${skipped}`, duration: 8000 },
        );
        onRefresh?.();
      } else {
        toast.warning(
          `Nessun profilo agganciato (${skipped} skip su ${total})`,
          { description: "Controlla che i device abbiano sysObjectID/sysDescr popolati (polling SNMP ok?)." },
        );
      }
    } catch (e) {
      const status = e.response?.status;
      const det = e.response?.data?.detail || e.message;
      if (status === 404) {
        toast.error(
          "Backend non aggiornato: endpoint /rematch-profiles non esiste. Aggiorna il backend Center a v3.5.29-fase2+.",
          { duration: 7000 },
        );
      } else {
        toast.error(`Errore rematch: ${det}`);
      }
    }
  };

  // v3.8.15: ri-esegue OUI + Fingerbank + reverse-DNS sui device auto-censiti
  // dallo Scanner che hanno ancora vendor o nome generici.
  const recognizeUnknowns = async () => {
    try {
      const { data } = await axios.post(`${API}/clients/${clientId}/devices/recognize-unknowns`);
      const { total_scanned = 0, oui_matched = 0, fingerbank_matched = 0, rdns_matched = 0, private_mac_labeled = 0, no_mac = 0, fingerbank_configured = false } = data || {};
      if (total_scanned === 0) {
        toast.info("Nessun device sconosciuto da rivedere", {
          description: "Tutti i device Scanner hanno gia' vendor e nome valorizzati.",
        });
        return;
      }
      const enriched = oui_matched + fingerbank_matched + rdns_matched + private_mac_labeled;
      const lines = [];
      if (oui_matched) lines.push(`• ${oui_matched} vendor OUI`);
      if (fingerbank_matched) lines.push(`• ${fingerbank_matched} profili Fingerbank`);
      if (rdns_matched) lines.push(`• ${rdns_matched} hostname reverse-DNS`);
      if (private_mac_labeled) lines.push(`• ${private_mac_labeled} dispositivi personali (MAC randomizzato)`);
      if (no_mac) lines.push(`• ${no_mac} senza MAC`);
      if (!fingerbank_configured) lines.push(`• Fingerbank non configurato — chiedi all'admin di settare la API key in Amministrazione → Integrazioni`);
      if (enriched > 0) {
        toast.success(`Riconosciuti ${enriched}/${total_scanned} device`, {
          description: lines.join("\n"),
          duration: 8000,
        });
        onRefresh?.();
      } else {
        toast.warning(`Nessun arricchimento possibile su ${total_scanned} device`, {
          description: lines.join("\n") || "Verifica MAC/Fingerbank.",
          duration: 8000,
        });
      }
    } catch (e) {
      toast.error(`Errore: ${e.response?.data?.detail || e.message}`);
    }
  };

  // v3.8.17: ri-correla LAN/Wi-Fi su tutti i device del cliente leggendo
  // CAM table degli switch + LLDP neighbors raccolti dal Connector Master.
  const correlateConnectivity = async () => {
    try {
      const { data } = await axios.post(`${API}/clients/${clientId}/devices/correlate-connectivity`);
      const { total_devices = 0, lan_count = 0, wifi_count = 0, unknown_count = 0,
              via_lldp_ap = 0, via_cam_lan = 0, via_laa_inference = 0, skipped_no_mac = 0 } = data || {};
      const lines = [];
      if (lan_count) lines.push(`• ${lan_count} LAN (cavo)`);
      if (wifi_count) lines.push(`• ${wifi_count} Wi-Fi`);
      if (unknown_count) lines.push(`• ${unknown_count} sconosciuti`);
      if (via_lldp_ap) lines.push(`◦ ${via_lldp_ap} via LLDP-AP (95%)`);
      if (via_cam_lan) lines.push(`◦ ${via_cam_lan} via CAM table (90%)`);
      if (via_laa_inference) lines.push(`◦ ${via_laa_inference} via MAC LAA (75%)`);
      if (skipped_no_mac) lines.push(`◦ ${skipped_no_mac} senza MAC`);
      toast.success(`Connessione classificata su ${total_devices} device`, {
        description: lines.join("\n"),
        duration: 9000,
      });
      onRefresh?.();
    } catch (e) {
      toast.error(`Errore: ${e.response?.data?.detail || e.message}`);
    }
  };

  const forcePingNow = async () => {
    try {
      toast.info("Avvio test ping su tutti i device... attendi 5-15s");
      const { data } = await axios.post(`${API}/clients/${clientId}/devices/force-ping-now`);
      const s = data.summary || {};
      const methods = Object.entries(s.methods || {}).map(([m, c]) => `${m}: ${c}`).join(", ");
      // Estrai sample dei primi offline per debug
      const offlineSample = (data.results || []).filter(r => !r.reachable).slice(0, 10).map(r =>
        `  • ${r.ip} (${r.name || ""}) → ${r.error || "no reply"}`,
      ).join("\n");
      const onlineSample = (data.results || []).filter(r => r.reachable).slice(0, 5).map(r =>
        `  • ${r.ip} → ${r.latency_ms || "?"}ms (${r.method})`,
      ).join("\n");
      const msg = `🧪 TEST PING LIVE — Agent: ${data.agent?.hostname} v${data.agent?.agent_version}\n\n` +
        `Target totali: ${data.targets}\n` +
        `✅ Reachable: ${s.reachable || 0}\n` +
        `❌ Unreachable: ${s.unreachable || 0}\n` +
        `Metodi usati: ${methods || "?"}\n\n` +
        (onlineSample ? `▼ Sample ONLINE:\n${onlineSample}\n\n` : "") +
        (offlineSample ? `▼ Sample OFFLINE (primi 10):\n${offlineSample}` : "");
      alert(msg);
      // Refresh table dopo il test
      onRefresh?.();
    } catch (e) {
      toast.error(`Errore test ping: ${e.response?.data?.detail || e.message}`);
    }
  };

  const diagnoseOffline = async () => {
    try {
      const { data } = await axios.get(
        `${API}/clients/${clientId}/devices/diagnose-offline`,
      );
      // Costruisci summary leggibile
      const liveCount = (data.live_v4_agents || []).length;
      const live = (data.live_v4_agents || []).map(a =>
        `  • ${a.hostname} [${a.role || "?"}] · v${a.agent_version || "?"} · ip=${a.last_ip || "?"}`
      ).join("\n");
      const breakdown = (data.poll_status_breakdown || []).map(b =>
        `  • ${b.source}/${(b.agent_id || "").slice(0, 12)}: ${b.count} record (${b.reachable_count} OK) · last=${b.latest_poll || "n/a"}`
      ).join("\n");
      const recs = (data.recommendations || []).map(r => `→ ${r}`).join("\n");
      const zombie = data.v3_zombie
        ? `\n\n⚠️ V3 ZOMBIE RILEVATO:\n${data.v3_zombie.message}\nUltima scrittura v3: ${data.v3_zombie.last_v3_write}`
        : "";
      const msg = `🩺 DIAGNOSI OFFLINE — ${data.now}\n\n` +
        `▼ Agent v4 LIVE (${liveCount}):\n${live || "  (nessuno)"}\n\n` +
        `▼ Poll status breakdown:\n${breakdown || "  (nessun record)"}\n` +
        zombie +
        `\n\n▼ Recommendations:\n${recs || "  (nessuna)"}`;
      // Mostra in alert (poi spostiamo in modale piu' bella)
      alert(msg);
    } catch (e) {
      toast.error(`Errore diagnosi: ${e.response?.data?.detail || e.message}`);
    }
  };

  const cleanupStalePollStatus = async () => {
    try {
      // Dry-run prima per mostrare la preview
      const { data: preview } = await axios.post(
        `${API}/clients/${clientId}/devices/cleanup-stale-poll-status`,
        { dry_run: true },
      );
      const dupCount = preview?.ips_with_duplicates || 0;
      if (dupCount === 0) {
        toast.info("Nessun record duplicato da pulire — i poll status sono gia' coerenti");
        return;
      }
      const sample = (preview.candidates || []).slice(0, 5).map(c => {
        const losers = (c.deleted || []).map(d =>
          `${(d.agent_id || "?").slice(0,8)} (${d.reachable ? "ok" : "down"})`,
        ).join(", ");
        return `• ${c.ip}: tieni ${(c.kept_agent_id || "?").slice(0,8)} · rimuovi ${losers}`;
      }).join("\n");
      const extra = dupCount > 5 ? `\n…e altri ${dupCount - 5} IP` : "";
      if (!window.confirm(
        `Rilevati ${dupCount} IP con record device_poll_status duplicati (multi-connector).\n\n${sample}${extra}\n\nProcedo con la pulizia?`,
      )) return;
      const { data } = await axios.post(
        `${API}/clients/${clientId}/devices/cleanup-stale-poll-status`,
        { dry_run: false },
      );
      toast.success(`Rimossi ${data.removed} record stale su ${data.ips_with_duplicates} IP`);
      onRefresh?.();
    } catch (e) {
      toast.error(`Errore cleanup: ${e.response?.data?.detail || e.message}`);
    }
  };

  const handleDelete = async (dev) => {
    if (!window.confirm(`Rimuovere "${dev.name}" (${dev.ip_address}) dal monitoraggio?`)) return;
    try {
      // For manual devices we have an id; for connector-discovered we use the device-poll-status endpoint
      if (dev.source === "connector" && !dev.id) {
        await axios.delete(`${API}/connector/device-poll-status/${encodeURIComponent(dev.ip_address)}`);
      } else if (dev.id) {
        await axios.delete(`${API}/connector/${clientId}/managed-devices/${dev.id}`);
      } else {
        await axios.delete(`${API}/connector/device-poll-status/${encodeURIComponent(dev.ip_address)}`);
      }
      toast.success("Dispositivo rimosso");
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore rimozione");
    }
  };

  // ---- Test SNMP live (WS round-trip al connector) ----
  const [testingId, setTestingId] = useState(null);
  const [testReport, setTestReport] = useState(null);
  const handleTestSNMP = async (dev) => {
    if (!dev.id) {
      toast.error("Device senza ID — modifica prima per assegnare un ID");
      return;
    }
    setTestingId(dev.id);
    setTestReport(null);
    try {
      const r = await axios.post(
        `${API}/connector/${clientId}/managed-devices/${dev.id}/test-snmp`
      );
      setTestReport({ device: dev, ...r.data });
    } catch (e) {
      setTestReport({
        device: dev,
        error: e.response?.data?.detail || e.message || "Errore",
      });
    } finally {
      setTestingId(null);
    }
  };

  // ---- CSV Import / Export ----
  const csvInputRef = useRef(null);
  const handleExportCSV = async () => {
    try {
      const r = await axios.get(
        `${API}/connector/${clientId}/managed-devices/export-csv`,
        { responseType: "blob" }
      );
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url;
      const cd = r.headers["content-disposition"] || "";
      const m = cd.match(/filename="([^"]+)"/);
      a.download = m ? m[1] : `argus_devices_${clientId.slice(0, 8)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("CSV scaricato");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Export fallito");
    }
  };

  const handleImportCSV = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!window.confirm(
      `Importare device da "${file.name}"? Saranno saltati gli IP gia' presenti.`
    )) {
      event.target.value = "";
      return;
    }
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await axios.post(
        `${API}/connector/${clientId}/managed-devices/import-csv`,
        form
      );
      const { inserted, skipped_ips = [], errors = [] } = r.data;
      let msg = `Importati ${inserted} device`;
      if (skipped_ips.length > 0) msg += ` · saltati ${skipped_ips.length} IP duplicati`;
      if (errors.length > 0) msg += ` · ${errors.length} errori`;
      toast.success(msg);
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Import fallito");
    } finally {
      event.target.value = "";
    }
  };

  return (
    <div className="space-y-3">
      {(() => {
        const vit = devices.filter(d => d.is_vital === true && !_isMcast(d));
        if (vit.length === 0) return null;
        const online = vit.filter(d => d.status === "online").length;
        const offline = vit.length - online;
        const withSwitch = vit.filter(d => d.switch_ip).length;
        return (
          <div className="flex items-center gap-4 px-4 py-2.5 rounded-lg border border-[var(--bg-border)] bg-[var(--bg-panel)]" data-testid="vital-health-header">
            <div className="flex items-center gap-1.5">
              <Star size={16} weight="fill" className="text-yellow-400" />
              <span className="text-xs font-bold text-[var(--text-primary)]">Salute Vitali</span>
            </div>
            <div className="flex items-center gap-1.5" title="Vitali online">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span className="text-sm font-bold text-emerald-400">{online}</span>
              <span className="text-[10px] text-[var(--text-muted)]">online</span>
            </div>
            <div className="flex items-center gap-1.5" title="Vitali offline">
              <span className={`w-2 h-2 rounded-full ${offline > 0 ? "bg-red-500 animate-pulse" : "bg-[var(--text-muted)]"}`} />
              <span className={`text-sm font-bold ${offline > 0 ? "text-red-500" : "text-[var(--text-muted)]"}`}>{offline}</span>
              <span className="text-[10px] text-[var(--text-muted)]">offline</span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)] ml-auto">
              {online}/{vit.length} vitali attivi{withSwitch > 0 ? ` · ${withSwitch} con dipendenza switch` : ""}
            </span>
          </div>
        );
      })()}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[10px] text-[var(--text-muted)]">
          {visibleDevices.length} dispositivi {hiddenCount > 0 && (
            <span className="text-amber-400/80">({hiddenCount} multicast/broadcast nascosti)</span>
          )} — i dispositivi manuali vengono interrogati dal connector entro pochi cicli di polling
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          {/* v2026-02-13: toggle vista raggruppata/tabella */}
          <div className="inline-flex rounded-md border border-[var(--bg-border)] overflow-hidden" data-testid="devices-view-toggle">
            <button
              onClick={() => setViewMode("grouped")}
              className={`text-[10px] px-2.5 py-1 transition-colors ${viewMode === "grouped" ? "bg-indigo-600 text-white" : "bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}
              data-testid="devices-view-grouped-btn"
              title="Mostra dispositivi raggruppati per categoria (clone Panoramica)"
            >
              📋 Raggruppata
            </button>
            <button
              onClick={() => setViewMode("table")}
              className={`text-[10px] px-2.5 py-1 transition-colors ${viewMode === "table" ? "bg-indigo-600 text-white" : "bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}
              data-testid="devices-view-table-btn"
              title="Mostra dispositivi in tabella tradizionale (azioni edit/info/web console)"
            >
              📊 Tabella
            </button>
          </div>
          {hiddenCount > 0 && (
            <button
              onClick={() => setShowMulticast(s => !s)}
              className={`text-[9px] px-2 py-1 rounded border transition-colors ${showMulticast ? "bg-amber-500/20 border-amber-500/40 text-amber-300" : "border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}
              data-testid="toggle-multicast-btn"
              title="Mostra/nascondi i multicast/broadcast (gruppi non gestiti, raccolti dallo Scanner via ARP)"
            >
              {showMulticast ? "Nascondi" : "Mostra"} multicast ({hiddenCount})
            </button>
          )}
          <Button
            onClick={() => rematchProfiles()}
            className="bg-cyan-600/90 hover:bg-cyan-600 text-white h-8 text-xs gap-1"
            data-testid="rematch-profiles-btn"
            title="Ri-esegue il fingerprint vendor (Synology, Xanto, HPE Comware, ecc.) su tutti i device del cliente. Utile dopo che lo SNMP ha iniziato a funzionare — i profili manuali non vengono sovrascritti."
          >
            <MagnifyingGlass size={13} /> Riconosci profili
          </Button>
          <Button
            onClick={() => recognizeUnknowns()}
            className="bg-sky-600/90 hover:bg-sky-600 text-white h-8 text-xs gap-1"
            data-testid="recognize-unknowns-btn"
            title="Per i device auto-censiti dallo Scanner che hanno ancora vendor/nome generici: ri-esegue OUI lookup, Fingerbank API e reverse-DNS per scoprire vendor, modello e hostname."
          >
            <MagnifyingGlass size={13} /> Riconosci sconosciuti
          </Button>
          <Button
            onClick={async () => {
              if (!window.confirm("Importare i device Datto come managed_devices del cliente?\n\nCrea SOLO i device Datto non gia' presenti nel Center. Quelli esistenti vengono arricchiti con nome Datto. Operazione idempotente.")) return;
              try {
                const { data } = await axios.post(`${API}/clients/${clientId}/datto/seed-managed`);
                if (data.ok) {
                  toast.success(`Seed Datto: ${data.created_managed_devices} creati, ${data.enriched_existing} arricchiti${data.skipped_no_ip ? `, ${data.skipped_no_ip} senza IP saltati` : ""}`, { duration: 8000 });
                  onRefresh?.();
                }
              } catch (e) {
                toast.error(`Errore seed Datto: ${e.response?.data?.detail || e.message}`, { duration: 7000 });
              }
            }}
            className="bg-fuchsia-500/90 hover:bg-fuchsia-500 text-white h-8 text-xs gap-1"
            data-testid="datto-seed-btn"
            title="Importa i device Datto come managed_devices nel Center. Crea solo quelli non già presenti (idempotente). Utile per popolare l'inventario di un cliente nuovo senza dover aspettare lo Scanner LAN."
          >
            📥 Seed Datto
          </Button>
          <Button
            onClick={async () => {
              try {
                const { data } = await axios.post(`${API}/clients/${clientId}/datto/rematch`);
                if (data.ok) {
                  toast.success(data.message);
                  onRefresh?.();
                } else {
                  toast.warning(data.message, { duration: 8000 });
                }
              } catch (e) {
                toast.error(`Errore re-match Datto: ${e.response?.data?.detail || e.message}`, { duration: 7000 });
              }
            }}
            className="bg-fuchsia-600/90 hover:bg-fuchsia-600 text-white h-8 text-xs gap-1"
            data-testid="datto-rematch-btn"
            title="Ri-esegue il match Datto RMM ↔ Center per questo cliente (incrocio su MAC e IP). Scrive il nome ufficiale Datto sui device matchati, visibile come badge fucsia."
          >
            🔗 Match Datto
          </Button>
          <Button
            onClick={() => correlateConnectivity()}
            className="bg-violet-600/90 hover:bg-violet-600 text-white h-8 text-xs gap-1"
            data-testid="correlate-connectivity-btn"
            title="Classifica ogni device come LAN (cavo) o Wi-Fi incrociando la CAM table degli switch SNMP con i neighbor LLDP. Identifica gli AP via keyword (Aruba AP, Unifi, Meraki, ecc.) e marca tutti i loro client come Wi-Fi. Confidenza: 99% se l'AP stesso e' un LLDP neighbor; 95% via LLDP-AP; 90% via CAM table; 75% via inferenza MAC randomizzato."
          >
            <WifiHigh size={13} /> LAN / Wi-Fi
          </Button>
          <Button
            onClick={() => forcePingNow()}
            className="bg-emerald-600/90 hover:bg-emerald-600 text-white h-8 text-xs gap-1"
            data-testid="force-ping-now-btn"
            title="Esegue un ping REAL TIME su TUTTI i device del cliente tramite l'agent v4 master LIVE. Mostra i risultati raw del poller (no persistenza DB intermedia)."
          >
            🧪 Test ping ora
          </Button>
          <Button
            onClick={() => diagnoseOffline()}
            className="bg-cyan-700/90 hover:bg-cyan-600 text-white h-8 text-xs gap-1"
            data-testid="diagnose-offline-btn"
            title="Diagnostica perche' i device sono OFFLINE: rileva agent v4 LIVE, connector v3 zombie, e mostra recommendation actionable."
          >
            🩺 Diagnosi offline
          </Button>
          <Button
            onClick={() => cleanupStaleDevices()}
            className="bg-amber-600/90 hover:bg-amber-600 text-white h-8 text-xs gap-1"
            data-testid="cleanup-stale-btn"
            title="Rimuove dal Center tutti i device attualmente sconosciuti al connector (sincronizzazione inversa). Chiede conferma prima di cancellare."
          >
            <Trash size={13} /> Rimuovi scomparsi
          </Button>
          <Button
            onClick={() => cleanupStalePollStatus()}
            className="bg-rose-600/90 hover:bg-rose-600 text-white h-8 text-xs gap-1"
            data-testid="cleanup-poll-status-btn"
            title="Multi-VLAN: pulisce i record device_poll_status duplicati lasciati da connector che non pollano piu' un IP (es. scanner cross-VLAN). Risolve i device che restano OFFLINE in UI nonostante il master li raggiunga."
          >
            <ArrowClockwise size={13} /> Sblocca offline
          </Button>
          <Button
            onClick={handleExportCSV}
            variant="outline"
            className="border-emerald-500/30 hover:bg-emerald-500/10 text-emerald-300 h-8 text-xs gap-1"
            data-testid="export-csv-btn"
            title="Scarica la lista dispositivi del cliente in formato CSV"
          >
            ⬇️ Esporta CSV
          </Button>
          <Button
            onClick={() => csvInputRef.current?.click()}
            variant="outline"
            className="border-sky-500/30 hover:bg-sky-500/10 text-sky-300 h-8 text-xs gap-1"
            data-testid="import-csv-btn"
            title="Importa dispositivi da CSV (skip su IP gia' esistenti)"
          >
            ⬆️ Importa CSV
          </Button>
          <input
            ref={csvInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={handleImportCSV}
            data-testid="csv-input"
          />
          <Button
            onClick={() => { setForm(emptyForm); setShowAdd(true); }}
            className="bg-indigo-600 hover:bg-indigo-700 text-white h-8 text-xs gap-1"
            data-testid="add-client-device-btn"
          >
            <Plus size={14} weight="bold" /> Aggiungi Dispositivo
          </Button>
        </div>
      </div>

      {/* v2026-06: toolbar azione multipla VITALI. Compare quando selezioni
          almeno un device (checkbox in vista Tabella e Raggruppata). */}
      {selectedIps.size > 0 && (
        <div className="flex items-center gap-2 flex-wrap mb-2 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/40" data-testid="bulk-vital-toolbar">
          <Star size={14} weight="fill" className="text-yellow-400" />
          <span className="text-xs font-semibold text-yellow-200">{selectedIps.size} selezionati</span>
          <div className="h-4 w-px bg-yellow-500/30 mx-1" />
          <button
            onClick={() => bulkSetVital(true)}
            disabled={bulkSaving}
            className="text-[11px] font-bold px-3 py-1 rounded-md bg-yellow-500 text-black hover:bg-yellow-400 transition-colors disabled:opacity-50 flex items-center gap-1"
            data-testid="bulk-mark-vital-btn"
          >
            <Star size={11} weight="fill" /> Marca come VITALI
          </button>
          <button
            onClick={() => bulkSetVital(false)}
            disabled={bulkSaving}
            className="text-[11px] font-semibold px-3 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-50"
            data-testid="bulk-unmark-vital-btn"
          >
            Rimuovi dai vitali
          </button>
          <div className="h-4 w-px bg-yellow-500/30 mx-1" />
          <button
            onClick={() => bulkSetSilence(true)}
            disabled={bulkSaving}
            className="text-[11px] font-semibold px-3 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-amber-300 hover:border-amber-500/40 transition-colors disabled:opacity-50 flex items-center gap-1"
            data-testid="bulk-silence-btn"
          >
            <BellSlash size={11} weight="bold" /> Silenzia alert
          </button>
          <button
            onClick={() => bulkSetSilence(false)}
            disabled={bulkSaving}
            className="text-[11px] font-semibold px-3 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-50 flex items-center gap-1"
            data-testid="bulk-unsilence-btn"
          >
            <Bell size={11} weight="bold" /> Riattiva alert
          </button>
          <button
            onClick={clearSelection}
            disabled={bulkSaving}
            className="text-[11px] px-2 py-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors ml-auto"
            data-testid="bulk-clear-selection-btn"
          >
            Deseleziona tutto
          </button>
        </div>
      )}

      {viewMode === "grouped" ? (
        <DevicesGroupedView
          devices={visibleDevices}
          skipList={showMulticast ? [] : devices.filter(d => _isMcast(d))}
          onInfoClick={(d) => setInfoTarget(d)}
          clientId={clientId}
          selectedIps={selectedIps}
          onToggleSelect={toggleSelect}
          onDeviceMove={async (payload, newMacro) => {
            // v2026-02-13: drag&drop riclassificazione manuale.
            // POST .../move-category con macro target. Lockerà
            // device_type_user_locked così il classifier rispetta la scelta.
            try {
              const { data } = await axios.post(
                `${API}/clients/${clientId}/devices/${encodeURIComponent(payload.ip)}/move-category`,
                { macro: newMacro }
              );
              if (data.noop) {
                toast.info(data.message);
              } else {
                toast.success(`${pickDeviceName(payload, payload.ip)}: ${data.old_type || "—"} → ${data.new_type}`);
              }
              onRefresh?.();
            } catch (e) {
              const detail = e.response?.data?.detail || e.message;
              toast.error(`Spostamento fallito: ${detail}`, { duration: 7000 });
            }
          }}
          renderActions={(d) => (
            <DeviceActionsBar
              d={d}
              testingId={testingId}
              onWebConsole={() => openConsoleWithVpn(d)}
              showWebConsole={canOpenWebConsole(d)}
              webPort={defaultWebPort(d)}
              onInfo={() => setInfoTarget(d)}
              onSwitchPorts={() => navigate(`/switch-ports/${encodeURIComponent(d.ip_address)}`)}
              onTrend={() => navigate(`/device-metrics?ip=${d.ip_address}`)}
              onTestSnmp={() => handleTestSNMP(d)}
              onEdit={() => setEditTarget(d)}
              onProfile={() => setProfileTarget(d)}
              onDelete={() => handleDelete(d)}
            />
          )}
        />
      ) : (
      <div className="noc-panel overflow-x-auto">
        <table className="alert-table min-w-[780px]" data-testid="client-devices-table">
          <thead>
            <tr>
              <th className="py-2 px-2 w-8">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleSelectAllVisible}
                  className="w-3.5 h-3.5 accent-yellow-500 cursor-pointer"
                  title="Seleziona/deseleziona tutti i visibili"
                  data-testid="select-all-devices"
                />
              </th>
              <SortableTh field="name" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Nome</SortableTh>
              <SortableTh field="device_type" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Tipo</SortableTh>
              <SortableTh field="ip_address" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>IP</SortableTh>
              <SortableTh field="monitor_type" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Metodo</SortableTh>
              <SortableTh field="snmp" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>SNMP</SortableTh>
              <SortableTh field="community" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Community</SortableTh>
              <SortableTh field="status" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Stato</SortableTh>
              <SortableTh field="live_evidence" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Vivo via</SortableTh>
              <th className="text-left text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-semibold py-2 px-2">Visto da</th>
              <SortableTh field="connection" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Conn.</SortableTh>
              <SortableTh field="source" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Fonte</SortableTh>
              <SortableTh field="last_poll" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Ultimo Poll</SortableTh>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sortedDevices.length === 0 ? (
              <tr><td colSpan={14} className="text-center text-[var(--text-muted)] py-8 text-xs">Nessun dispositivo — clicca "Aggiungi Dispositivo" per iniziare</td></tr>
            ) : sortedDevices.map((d, i) => {
              const sc = getStatusColor(d.status);
              const monitorType = (d.monitor_type || "snmp").toLowerCase();
              const methodBadge = {
                snmp: { label: "SNMP", color: "text-purple-400", bg: "bg-purple-500/10 border-purple-500/20" },
                ping: { label: "PING", color: "text-cyan-400", bg: "bg-cyan-500/10 border-cyan-500/20" },
                http: { label: "HTTP", color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
                "snmp+http": { label: "SNMP+HTTP", color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" },
                redfish_direct: { label: "REDFISH", color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20" },
              }[monitorType] || { label: monitorType.toUpperCase(), color: "text-[var(--text-muted)]", bg: "bg-[var(--bg-hover)] border-[var(--bg-border)]" };
              return (
                <tr key={i} className={d.alerts_silenced ? "opacity-70" : ""}>
                  <td className="px-2">
                    <div
                      onClick={(e) => { e.stopPropagation(); toggleSelect(d.ip_address); }}
                      className="inline-flex items-center justify-center p-1 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={selectedIps.has(d.ip_address) || false}
                        readOnly
                        tabIndex={-1}
                        className="w-4 h-4 accent-yellow-500 pointer-events-none"
                        data-testid={`select-device-row-${d.ip_address}`}
                      />
                    </div>
                  </td>
                  <td className="text-[var(--text-primary)] text-xs font-medium">
                    <span className="inline-flex items-center gap-1.5 flex-wrap">
                      {pickDeviceName(d)}
                      {d.datto_name && d.datto_name !== d.name && d.datto_name !== pickDeviceName(d) && (
                        <span
                          className="inline-flex items-center gap-0.5 text-[9px] px-1 py-px rounded bg-fuchsia-500/20 text-fuchsia-200 border border-fuchsia-500/40 font-bold"
                          title={`Datto RMM: ${d.datto_name}${d.datto_match ? ` (match via ${d.datto_match.toUpperCase()})` : ""}`}
                          data-testid={`table-datto-badge-${d.ip_address}`}
                        >
                          DATTO: {d.datto_name}
                        </span>
                      )}
                      {d.alerts_silenced && (
                        <span
                          className="inline-flex items-center gap-0.5 text-[9px] px-1 py-px rounded bg-amber-500/15 text-amber-300 border border-amber-500/40"
                          title={d.alerts_silenced_reason ? `Alert silenziati — ${d.alerts_silenced_reason}` : "Alert silenziati per questo device"}
                          data-testid={`silence-badge-${d.ip_address}`}
                        >
                          <BellSlash size={9} weight="fill" /> ALERT OFF
                        </span>
                      )}
                    </span>
                  </td>
                  <td>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--bg-border)]"
                      title={`Categoria: ${macroLabel(d)} · device_type: ${d.device_type || "—"}`}
                      data-testid={`device-category-${d.ip_address}`}
                    >
                      {macroLabel(d)}
                    </span>
                  </td>
                  <td className="font-mono text-[var(--text-muted)] text-xs">{d.ip_address}</td>
                  <td>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded border font-bold ${methodBadge.bg} ${methodBadge.color}`}>
                      {methodBadge.label}
                    </span>
                  </td>
                  <td className="text-[10px] text-[var(--text-muted)]">
                    {(monitorType === "snmp" || monitorType === "snmp+http") ? (d.snmp_version || "v2c") : "—"}
                  </td>
                  <td className="text-[10px] font-mono text-[var(--text-muted)]">
                    {(monitorType === "snmp" || monitorType === "snmp+http") && d.snmp_version !== "v3" ? (d.snmp_community || "—") : "—"}
                  </td>
                  <td>
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold" style={{ color: sc }}>
                      {d.status === "online" || d.status === "active" ? <WifiHigh size={12} /> : <WifiSlash size={12} />}
                      {d.status?.toUpperCase()}
                    </span>
                    {d.ping_ms && <span className="ml-1 text-[9px] text-[var(--text-muted)]">{d.ping_ms}ms</span>}
                    {/* v3.8.37: badge "down da Xh" per device offline.
                        Priorita': unreachable_since (Master poll) > last_seen_at > last_poll */}
                    {(d.status === "offline") && (() => {
                      const ref = d.unreachable_since || d.last_seen_at || d.last_poll;
                      if (!ref) return null;
                      const t = Date.parse(ref);
                      if (Number.isNaN(t)) return null;
                      const ageS = Math.max(0, Math.floor((Date.now() - t) / 1000));
                      const lbl = ageS < 60 ? `${ageS}s`
                        : ageS < 3600 ? `${Math.floor(ageS / 60)}m`
                        : ageS < 86400 ? `${Math.floor(ageS / 3600)}h`
                        : `${Math.floor(ageS / 86400)}g`;
                      return (
                        <div className="text-[9px] mt-0.5 text-red-400/80" title={`${d.unreachable_since ? "Non raggiungibile da" : "Ultima vista"}: ${new Date(t).toLocaleString("it-IT")}`}>
                          down da {lbl}
                        </div>
                      );
                    })()}
                  </td>
                  <td>{(() => {
                    // v4.16.x: "Vivo via" badge — mostra COME il device e' stato
                    // dichiarato online. Aiuta a capire perche' un device
                    // appare online anche se ICMP fallisce.
                    const ev = d.live_evidence;
                    if (!ev || d.status === "offline" || d.status === "pending") {
                      return <span className="text-[8px] text-[var(--text-muted)]" data-testid={`live-evidence-${d.ip_address}`}>—</span>;
                    }
                    const m = String(ev).toLowerCase();
                    if (m.includes("mac_table") || m.includes("snmp")) {
                      return <span title="Visto nella MAC table dello switch SNMP (L2). Device fisicamente collegato anche se ICMP bloccato." className="inline-flex items-center gap-1 text-[8px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 font-bold" data-testid={`live-evidence-${d.ip_address}`}>🔌 FDB</span>;
                    }
                    if (m.includes("tcp_probe") || m.startsWith("tcp_port_")) {
                      const port = (ev.match(/tcp_port_(\d+)/) || [])[1];
                      return <span title={`TCP probe ha risposto${port ? ` su porta ${port}` : ""}. ICMP probabilmente bloccato (firewall/WF).`} className="inline-flex items-center gap-1 text-[8px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30 font-bold" data-testid={`live-evidence-${d.ip_address}`}>⚡ TCP{port ? `:${port}` : ""}</span>;
                    }
                    if (m.includes("icmp_native") || m === "icmp" || m === "ping") {
                      return <span title="Ping ICMP standard" className="inline-flex items-center gap-1 text-[8px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/30 font-bold" data-testid={`live-evidence-${d.ip_address}`}>📡 PING</span>;
                    }
                    if (m.includes("scanner") || m.includes("arp")) {
                      return <span title="Scoperto dallo scanner LAN (ARP/mDNS)" className="inline-flex items-center gap-1 text-[8px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/30 font-bold" data-testid={`live-evidence-${d.ip_address}`}>🔍 SCAN</span>;
                    }
                    if (m.includes("agent_v4")) {
                      return <span title="Visto dall'agent v4 Go (auto-discovery interno)" className="inline-flex items-center gap-1 text-[8px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 font-bold" data-testid={`live-evidence-${d.ip_address}`}>🤖 v4</span>;
                    }
                    return <span title={`Metodo: ${ev}`} className="text-[8px] text-[var(--text-muted)]" data-testid={`live-evidence-${d.ip_address}`}>{ev}</span>;
                  })()}</td>
                  <td>{(() => {
                    // v4.17.x: "Visto da" — lista agent che hanno effettivamente
                    // pollato questo device negli ultimi 5 min. Aiuta a capire
                    // la distribuzione subnet-aware.
                    const sb = d.seen_by || [];
                    if (sb.length === 0) {
                      return <span className="text-[8px] text-[var(--text-muted)]" data-testid={`seen-by-${d.ip_address}`}>—</span>;
                    }
                    return (
                      <div className="flex flex-wrap gap-0.5" data-testid={`seen-by-${d.ip_address}`}>
                        {sb.map((a, i) => {
                          const color = a.role === "master"
                            ? "bg-sky-500/10 text-sky-300 border-sky-500/30"
                            : "bg-violet-500/10 text-violet-300 border-violet-500/30";
                          const reachIcon = a.reachable ? "✓" : "✗";
                          return (
                            <span
                              key={i}
                              title={`${a.hostname} [${a.role}] · ${a.reachable ? "raggiunge" : "non raggiunge"} (method: ${a.method || "?"})`}
                              className={`inline-flex items-center gap-0.5 text-[8px] px-1 py-0.5 rounded border ${color}`}
                            >
                              {reachIcon} {a.hostname.slice(0, 10)}
                            </span>
                          );
                        })}
                      </div>
                    );
                  })()}</td>
                  <td>{(() => {
                    const ct = d.connection_type;
                    const cs = d.connection_source || "";
                    const conf = d.connection_confidence;
                    const via = (d.connection_via_switch && d.connection_via_port) ? `${d.connection_via_switch} / ${d.connection_via_port}` : "";
                    const tip = `Connessione: ${ct || "?"}\nFonte: ${cs}\nConfidenza: ${conf ?? "—"}%${via ? `\nVia: ${via}` : ""}`;
                    if (ct === "wifi") {
                      return <span title={tip} className="inline-flex items-center gap-1 text-[8px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20 font-bold"><WifiHigh size={10} weight="bold"/>WI-FI</span>;
                    }
                    if (ct === "lan") {
                      return <span title={tip} className="inline-flex items-center gap-1 text-[8px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-bold"><PlugsConnected size={10} weight="bold"/>LAN</span>;
                    }
                    return <span title={tip} className="text-[8px] text-[var(--text-muted)]">—</span>;
                  })()}</td>
                  <td>{(() => {
                    const src = d.source || "manual";
                    if (src === "connector-scanner") {
                      return <span className="text-[8px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 font-bold" title="Scoperto e auto-censito dal Connector Scanner">SCANNER</span>;
                    }
                    if (src === "connector-master" || src === "connector") {
                      return <span className="text-[8px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold" title="Censito dal Connector Master (polling SNMP / discovery)">MASTER</span>;
                    }
                    return <span className="text-[8px] text-[var(--text-muted)]">Manuale</span>;
                  })()}</td>
                  <td className="text-[9px] text-[var(--text-muted)]">{d.last_poll ? new Date(d.last_poll).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                  <td>
                    <div className="flex items-center gap-1">
                      {canOpenWebConsole(d) && (
                        <button
                          onClick={() => openConsoleWithVpn(d)}
                          className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
                          title={`Apri Web Console in nuova tab (proxy diretto via VPN, porta ${defaultWebPort(d)})${d.profile_key ? ` · profilo ${d.profile_key}` : " · nessun profilo"}`}
                          data-testid={`web-console-btn-${d.ip_address}`}
                        >
                          <Monitor size={13} />
                        </button>
                      )}
                      <button
                        onClick={() => setInfoTarget(d)}
                        className="p-1 rounded hover:bg-cyan-500/10 text-cyan-400 transition-colors"
                        title="Scheda dispositivo completa (anagrafica, firmware, lifecycle)"
                        data-testid={`device-info-${d.ip_address}`}
                      >
                        <Info size={13} />
                      </button>
                      {/* v3.8.34: Porte/Interfacce — detection multi-segnale per
                          switch/router/firewall/NAS. Il connector raccoglie ifTable
                          standard MIB-II per ogni device SNMP, quindi il bottone si
                          attiva anche per firewall (Zyxel/Fortinet) e NAS (Synology/QNAP). */}
                      {(() => {
                        const dt = (d.device_type || "").toLowerCase();
                        const modelL = (d.model || d.sys_descr || "").toLowerCase();
                        const nameL = (d.name || "").toLowerCase();
                        const kw = [
                          "switch", "router", "firewall", "gateway",
                          "catalyst", "nexus", "meraki",
                          "procurve", "aruba", "5130", "5140", "5900",
                          "ex2300", "ex3400", "ex4300", "srx",
                          "fortigate", "fortiswitch", "fortiap",
                          "zyxel", "xgs", "gs1900", "gs2200",
                          "mikrotik", "routerboard", "ccr", "crs",
                          "unifi", "edgerouter", "edgeswitch", "usg",
                          "dgs-", "dxs-",
                          "powerconnect", "n1500", "n2000", "n3000",
                          "huawei", "s5700", "s6700", "ar2200",
                          "pfsense", "opnsense",
                          "synology", "qnap", "diskstation", "rackstation", "ts-",
                        ];
                        const matches = kw.some((k) => modelL.includes(k) || nameL.includes(k));
                        const isPortable =
                          dt.includes("switch") || dt.includes("router") || dt.includes("firewall") ||
                          dt === "nas" || dt === "network-device" || matches;
                        if (!isPortable) return null;
                        const tip = dt === "firewall" ? "Porte firewall (ifTable: oper/admin/speed, traffico Rx/Tx)"
                          : dt === "nas" ? "Interfacce NAS (ifTable: speed, traffico Rx/Tx)"
                          : "Porte switch (tiles UP/DOWN + neighbor LLDP + flap history)";
                        return (
                          <button
                            onClick={() => navigate(`/switch-ports/${encodeURIComponent(d.ip_address)}`)}
                            className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
                            title={tip}
                            data-testid={`device-switch-ports-${d.ip_address}`}
                          >
                            <NetworkSlash size={13} />
                          </button>
                        );
                      })()}
                      <button
                        onClick={() => navigate(`/device-metrics?ip=${d.ip_address}`)}
                        className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
                        title="Trend metriche storiche"
                        data-testid={`device-trend-${d.ip_address}`}
                      >
                        <ChartLine size={13} />
                      </button>
                      <button
                        onClick={() => handleTestSNMP(d)}
                        disabled={testingId === d.id}
                        className="p-1 rounded hover:bg-emerald-500/10 text-emerald-400 transition-colors disabled:opacity-30 disabled:cursor-wait"
                        title="Test SNMP live (round-trip al connector)"
                        data-testid={`test-snmp-${d.ip_address}`}
                      >
                        {testingId === d.id ? (
                          <span className="inline-block animate-spin">⟳</span>
                        ) : (
                          <span>⚡</span>
                        )}
                      </button>
                      <button
                        onClick={() => setEditTarget(d)}
                        className="p-1 rounded hover:bg-violet-500/10 text-violet-400 transition-colors"
                        title="Modifica dispositivo (metodo, community SNMP, versione, credenziali v3)"
                        data-testid={`edit-device-${d.ip_address}`}
                      >
                        <PencilSimple size={13} />
                      </button>
                      <button
                        onClick={() => setProfileTarget(d)}
                        className={`p-1 rounded transition-colors ${
                          d.profile_key
                            ? (d.profile_auto_matched
                                ? "hover:bg-emerald-500/10 text-emerald-400"
                                : "hover:bg-cyan-500/10 text-cyan-400")
                            : "hover:bg-amber-500/10 text-amber-400 animate-pulse"
                        }`}
                        title={
                          d.profile_key
                            ? `Profilo: ${d.profile_key}${d.profile_auto_matched ? " (auto-rilevato)" : " (configurato manualmente)"}${d.vendor ? ` · ${d.vendor}` : ""}`
                            : "Nessun profilo — clicca per configurare"
                        }
                        data-testid={`configure-profile-${d.ip_address}`}
                      >
                        <Cpu size={13} />
                      </button>
                      <button
                        onClick={() => handleDelete(d)}
                        className="p-1 rounded hover:bg-[var(--critical-bg)] text-[var(--critical)] transition-colors"
                        title="Rimuovi"
                        data-testid={`delete-device-${d.ip_address}`}
                      >
                        <Trash size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      )}

      {/* Add Device Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <HardDrives size={18} className="text-indigo-400" /> Aggiungi Dispositivo
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Nome Dispositivo *</Label>
                <Input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Switch Core 01" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="device-name-input" />
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">IP Address *</Label>
                <Input value={form.ip} onChange={e => setForm({ ...form, ip: e.target.value })} placeholder="192.168.1.10" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs font-mono" data-testid="device-ip-input" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Tipo Dispositivo</Label>
                <Select value={form.device_type} onValueChange={v => setForm({ ...form, device_type: v })}>
                  <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="device-type-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="generic">Generico</SelectItem>
                    <SelectItem value="switch">Switch</SelectItem>
                    <SelectItem value="firewall">Firewall</SelectItem>
                    <SelectItem value="router">Router</SelectItem>
                    <SelectItem value="server">Server</SelectItem>
                    <SelectItem value="ilo">HPE iLO / BMC</SelectItem>
                    <SelectItem value="printer">Stampante</SelectItem>
                    <SelectItem value="ups">UPS</SelectItem>
                    <SelectItem value="ap">Access Point</SelectItem>
                    <SelectItem value="nas">NAS / Storage</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Metodo Monitoraggio</Label>
                <Select value={form.monitor_type} onValueChange={v => setForm({ ...form, monitor_type: v })}>
                  <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="monitor-type-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="snmp">SNMP</SelectItem>
                    <SelectItem value="ping">Ping (ICMP)</SelectItem>
                    <SelectItem value="http">HTTP/HTTPS</SelectItem>
                    <SelectItem value="snmp+http">SNMP + HTTP (device con web UI e metriche)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {(form.monitor_type === "http" || form.monitor_type === "snmp+http") && (
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Porta HTTP/HTTPS</Label>
                <Input type="number" value={form.http_port} onChange={e => setForm({ ...form, http_port: e.target.value })} placeholder="80" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
              </div>
            )}

            {(form.monitor_type === "snmp" || form.monitor_type === "snmp+http") && (
              <div className="p-2.5 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] space-y-2">
                <div>
                  <Label className="text-[var(--text-muted)] text-[10px]">Versione SNMP</Label>
                  <Select value={form.snmp_version} onValueChange={v => setForm({ ...form, snmp_version: v })}>
                    <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="snmp-version-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="v1">v1</SelectItem>
                      <SelectItem value="v2c">v2c</SelectItem>
                      <SelectItem value="v3">v3 (sicuro)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {form.snmp_version !== "v3" ? (
                  <div>
                    <Label className="text-[var(--text-muted)] text-[10px]">Community String</Label>
                    <Input value={form.community} onChange={e => setForm({ ...form, community: e.target.value })} placeholder="public" className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs font-mono" data-testid="snmp-community-input" />
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <Label className="text-[var(--text-muted)] text-[10px]">Username</Label>
                        <Input value={form.snmpv3_username} onChange={e => setForm({ ...form, snmpv3_username: e.target.value })} className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
                      </div>
                      <div>
                        <Label className="text-[var(--text-muted)] text-[10px]">Security Level</Label>
                        <Select value={form.snmpv3_security_level} onValueChange={v => setForm({ ...form, snmpv3_security_level: v })}>
                          <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="noAuthNoPriv">noAuthNoPriv</SelectItem>
                            <SelectItem value="authNoPriv">authNoPriv</SelectItem>
                            <SelectItem value="authPriv">authPriv</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    {form.snmpv3_security_level !== "noAuthNoPriv" && (
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <Label className="text-[var(--text-muted)] text-[10px]">Auth Protocol</Label>
                          <Select value={form.snmpv3_auth_protocol} onValueChange={v => setForm({ ...form, snmpv3_auth_protocol: v })}>
                            <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="MD5">MD5</SelectItem>
                              <SelectItem value="SHA">SHA</SelectItem>
                              <SelectItem value="SHA256">SHA256</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div>
                          <Label className="text-[var(--text-muted)] text-[10px]">Auth Password</Label>
                          <Input type="password" value={form.snmpv3_auth_password} onChange={e => setForm({ ...form, snmpv3_auth_password: e.target.value })} className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
                        </div>
                      </div>
                    )}
                    {form.snmpv3_security_level === "authPriv" && (
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <Label className="text-[var(--text-muted)] text-[10px]">Priv Protocol</Label>
                          <Select value={form.snmpv3_priv_protocol} onValueChange={v => setForm({ ...form, snmpv3_priv_protocol: v })}>
                            <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="DES">DES</SelectItem>
                              <SelectItem value="AES">AES</SelectItem>
                              <SelectItem value="AES256">AES256</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div>
                          <Label className="text-[var(--text-muted)] text-[10px]">Priv Password</Label>
                          <Input type="password" value={form.snmpv3_priv_password} onChange={e => setForm({ ...form, snmpv3_priv_password: e.target.value })} className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <Button
              onClick={handleSave}
              disabled={saving}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white"
              data-testid="save-device-btn"
            >
              {saving ? <ArrowClockwise size={14} className="animate-spin mr-1" /> : <Plus size={14} className="mr-1" />}
              {saving ? "Salvataggio..." : "Aggiungi al Monitoraggio"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Profile Config Modal */}
      {profileTarget && (
        <DeviceProfileModal
          device={profileTarget}
          onClose={() => setProfileTarget(null)}
          onApplied={() => { setProfileTarget(null); onRefresh(); }}
        />
      )}

      {/* Device Edit Modal (rapid edit: monitor-type + SNMP community/version/v3 creds) */}
      {editTarget && (
        <DeviceEditModal
          clientId={clientId}
          device={editTarget}
          open={!!editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={(updatedDevice) => {
            // Optimistic update sullo state parent — evita 1-4s di ritardo prima
            // che il badge ALERT OFF appaia dopo Save.
            if (updatedDevice && updatedDevice.id && onOptimisticUpdate) {
              onOptimisticUpdate(updatedDevice);
            }
            setEditTarget(null);
            onRefresh();
          }}
        />
      )}

      {/* Device Info Card Modal */}
      {infoTarget && (
        <Dialog open={!!infoTarget} onOpenChange={(o) => { if (!o) { setInfoTarget(null); setInfoCardName(null); } }}>
          <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-6xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-[var(--text-primary)]" data-testid="device-card-dialog-title">
                <Info size={18} className="text-cyan-400" />
                Scheda Dispositivo — {
                  infoCardName
                  || pickDeviceName(devices.find(d => d.ip_address === infoTarget.ip_address) || infoTarget)
                }
              </DialogTitle>
            </DialogHeader>
            <ErrorBoundary fallback={<div className="text-sm text-red-400 p-4">Errore caricamento scheda.</div>}>
              {/* v2026-06-02 fix ghosting: la `key={infoTarget.ip_address}`
                  forza React a smontare+rimontare DeviceInfoCard ogni volta
                  che cambia il device selezionato. Senza key il componente
                  conservava lo state vecchio (metriche/identity del device
                  precedente) finché il nuovo fetch non completava, dando
                  l'effetto "ghosting" tra device A e device B. */}
              <DeviceInfoCard
                key={infoTarget.ip_address}
                deviceIp={infoTarget.ip_address}
                onClose={() => { setInfoTarget(null); setInfoCardName(null); }}
                onCardLoaded={(c) => {
                  // v2026-02-14: titolo Dialog si allinea sempre al nome
                  // canonical lato backend (best_display_name) → no piu'
                  // "HP 10.100.61.221" nel titolo quando in card e' "Switch02 HP 5130 52G".
                  const display = c?.identity?.hostname || c?.identity?.ip;
                  if (display) setInfoCardName(display);
                }}
              />
            </ErrorBoundary>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

/* ==================== DEVICE PROFILE MODAL ==================== */
function DeviceProfileModal({ device, onClose, onApplied }) {
  const [profiles, setProfiles] = useState([]);
  const [selected, setSelected] = useState(device.profile_key || "");
  const [applying, setApplying] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/device-profiles`)
      .then(r => {
        setProfiles(r.data?.profiles || []);
        // Auto-suggest by device_type if not already configured
        if (!device.profile_key) {
          const t = (device.device_type || "").toLowerCase();
          const nm = (device.name || "").toLowerCase();
          const suggest = (r.data?.profiles || []).find(p => {
            if (t === "nas") return p.key === "synology_dsm";
            if (t === "ups") {
              // Heuristic: se il nome contiene "xanto" usa il profilo dedicato
              if (nm.includes("xanto") || nm.includes("netagent") || nm.includes("megatec")) {
                return p.key === "xanto_ups";
              }
              return p.key === "generic_ups";
            }
            if (t === "switch") return p.key === "hpe_comware";
            if (t === "ilo" || t === "server_oob" || t === "server") return p.key === "hpe_ilo";
            if (t === "firewall") return p.key === "fortinet_fortigate";
            return false;
          });
          if (suggest) setSelected(suggest.key);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [device.profile_key, device.device_type]);

  const apply = async () => {
    if (!selected) { toast.error("Seleziona un profilo"); return; }
    setApplying(true);
    try {
      await axios.post(`${API}/device-profiles/apply`, {
        device_ip: device.ip_address,
        profile_key: selected,
      });
      // Fire-and-forget: chiedi al connector di rileggere subito la lista dispositivi
      // con il nuovo profilo applicato (evita attesa fino a 10 min sul ciclo normale).
      if (device.client_id) {
        axios.post(`${API}/connector/${device.client_id}/request-refresh`).catch(() => {});
      }
      toast.success(`Profilo "${selected}" applicato a ${device.name} — il connector userà la nuova config entro 30s`);
      onApplied();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    } finally { setApplying(false); }
  };

  const chosen = profiles.find(p => p.key === selected);

  // Group by family for clean dropdown
  const byFamily = profiles.reduce((acc, p) => {
    const f = p.family || "generic";
    if (!acc[f]) acc[f] = [];
    acc[f].push(p);
    return acc;
  }, {});
  // v2026-06-02: aggiunti "printer" (6 profili HP/Epson/Kyocera/Xerox/
  // Brother/Canon) e "generic" all'elenco visibile — prima erano filtrati
  // perche' non presenti in familyOrder, anche se esistevano nei seed
  // backend. UX bug segnalato via screenshot utente.
  const familyOrder = ["switch", "firewall", "nas", "ups", "server_oob", "printer", "unifi", "generic"];
  const familyLabels = { switch: "Switch", firewall: "Firewall", nas: "NAS", ups: "UPS", server_oob: "Server OOB (iLO/iDRAC)", printer: "Stampante", unifi: "UniFi", generic: "Generico" };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
            <Cpu size={18} className="text-indigo-400" />
            Configura profilo — {device.name}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="text-[11px] text-white/60 leading-relaxed">
            Applica un profilo vendor per auto-configurare <strong>porta web console</strong>, <strong>SNMP</strong>, <strong>OID</strong> e <strong>soglie</strong>. La Web Console userà automaticamente le porte corrette.
          </div>

          <div className="grid grid-cols-3 gap-2 text-[10px] font-mono text-white/50">
            <div><span className="text-white/30">IP:</span> <span className="text-white/80">{device.ip_address}</span></div>
            <div><span className="text-white/30">Tipo:</span> <span className="text-white/80">{device.device_type}</span></div>
            <div><span className="text-white/30">Profilo ora:</span> <span className="text-cyan-300">{device.profile_key || "—"}</span></div>
          </div>

          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-white/50 mb-1 block">Seleziona profilo</label>
            <select
              value={selected}
              onChange={e => setSelected(e.target.value)}
              disabled={loading}
              className="w-full bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-3 py-2 text-[12px] text-white focus:border-indigo-500 outline-none"
              data-testid="profile-select"
            >
              <option value="">— scegli un profilo —</option>
              {familyOrder.filter(f => byFamily[f]).map(f => (
                <optgroup key={f} label={familyLabels[f] || f}>
                  {byFamily[f].map(p => (
                    <option key={p.key} value={p.key}>
                      {p.vendor} — {p.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          {chosen && (
            <div className="bg-indigo-500/5 border border-indigo-500/20 rounded-md p-3 space-y-1.5 text-[11px] font-mono" data-testid="profile-preview">
              <div className="text-[9px] font-bold uppercase tracking-wider text-indigo-300 mb-1">Anteprima configurazione</div>
              <div className="flex justify-between"><span className="text-white/50">Web Console:</span> <span className="text-white">{chosen.web_console?.scheme}://{device.ip_address}:{chosen.web_console?.port}{chosen.web_console?.path}</span></div>
              <div className="flex justify-between"><span className="text-white/50">SNMP:</span> <span className="text-white">{chosen.snmp?.version} porta {chosen.snmp?.port}</span></div>
              <div className="flex justify-between"><span className="text-white/50">Polling:</span> <span className="text-white">{chosen.polling_interval_seconds}s</span></div>
              <div className="flex justify-between"><span className="text-white/50">OID monitorati:</span> <span className="text-white">{Object.keys(chosen.oids || {}).length}</span></div>
              {chosen.web_console?.notes && (
                <div className="text-[10px] text-amber-300/80 mt-2 pt-2 border-t border-white/5">
                  ℹ {chosen.web_console.notes}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={onClose} className="h-8 text-xs">Annulla</Button>
            <Button
              onClick={apply}
              disabled={!selected || applying}
              className="bg-indigo-600 hover:bg-indigo-700 text-white h-8 text-xs"
              data-testid="apply-profile-btn"
            >
              {applying ? <ArrowClockwise size={12} className="animate-spin mr-1" /> : <Cpu size={12} className="mr-1" />}
              {applying ? "Applicazione..." : "Applica profilo"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}


/* ==================== ALERTS TAB ==================== */
function AlertsTab({ alerts, navigate, clientId, clientName, onRefresh }) {
  // v3.8.31: ordinamento alert client-side (default: data desc)
  const SEV_RANK = { critical: 4, high: 3, medium: 2, low: 1 };
  const { sorted, sortKey, sortDir, requestSort } = useSortableTable(
    alerts, "created_at", "desc",
    {
      persistKey: "client-alerts-tab",
      accessors: {
        severity: (a) => SEV_RANK[a?.severity] || 0,
        title: (a) => (a?.title || "").toLowerCase(),
        device_name: (a) => (a?.device_name || "").toLowerCase(),
        created_at: (a) => a?.created_at ? Date.parse(a.created_at) : 0,
      },
    }
  );

  // v2026-02-13: pulsante "Elimina tutti" — admin-only sul backend
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [clearScope, setClearScope] = useState("active");
  const [clearing, setClearing] = useState(false);
  const doClear = async () => {
    setClearing(true);
    try {
      const url = `${API}/alerts/clear-all?scope=${clearScope}` + (clientId ? `&client_id=${clientId}` : "");
      const { data } = await axios.delete(url);
      toast.success(`Eliminati ${data.deleted} alert (${data.scope})`);
      setConfirmOpen(false);
      onRefresh?.();
    } catch (e) {
      const detail = e.response?.data?.detail || e.message;
      toast.error(`Errore eliminazione alert: ${detail}`, { duration: 7000 });
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="noc-panel overflow-x-auto">
      <div className="flex items-center justify-between mb-3 px-1">
        <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
          {alerts.length} alert {clientName ? `· ${clientName}` : ""}
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setConfirmOpen(true)}
          disabled={alerts.length === 0}
          className="text-[10px] h-7 border-red-500/40 text-red-300 hover:bg-red-500/10 hover:border-red-500"
          data-testid="alerts-clear-all-btn"
          title={alerts.length === 0 ? "Nessun alert da eliminare" : "Elimina tutti gli alert (admin only)"}
        >
          <Trash size={12} className="mr-1" /> Elimina tutti
        </Button>
      </div>
      <table className="alert-table min-w-[560px]">
        <thead><tr>
          <SortableTh field="severity" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Sev.</SortableTh>
          <SortableTh field="title" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Titolo</SortableTh>
          <SortableTh field="device_name" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Dispositivo</SortableTh>
          <SortableTh field="created_at" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Data</SortableTh>
        </tr></thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr><td colSpan={4} className="text-center text-emerald-400 py-8 text-xs">Nessun alert attivo</td></tr>
          ) : sorted.map(a => {
            const sc = a.severity === "critical" ? "#FF3B30" : a.severity === "high" ? "#FF9500" : "#FFCC00";
            return (
              <tr key={a.id} className="cursor-pointer hover:bg-[var(--bg-hover)]" onClick={() => navigate(`/alerts/${a.id}`)}>
                <td><span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase" style={{ color: sc, background: `${sc}15` }}>{a.severity?.substring(0, 4)}</span></td>
                <td className="text-[var(--text-primary)] text-xs">{a.title}</td>
                <td className="text-[var(--text-muted)] text-xs">{a.device_name}</td>
                <td className="font-mono text-[var(--text-muted)] text-[10px]">{a.created_at ? new Date(a.created_at).toLocaleString("it-IT") : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)]" data-testid="alerts-clear-confirm-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-300">
              <Trash size={18} /> Elimina alert {clientName ? `— ${clientName}` : ""}
            </DialogTitle>
            <DialogDescription className="text-[var(--text-muted)] text-xs">
              L'eliminazione è <strong className="text-red-400">definitiva</strong> (hard delete su MongoDB).
              Per ripristinare serve un backup. L'operazione viene loggata in audit con
              utente e timestamp.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <Label className="text-xs">Quali alert eliminare?</Label>
            <Select value={clearScope} onValueChange={setClearScope}>
              <SelectTrigger data-testid="alerts-clear-scope-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Solo attivi (raccomandato)</SelectItem>
                <SelectItem value="resolved">Solo risolti/acknowledged (storico)</SelectItem>
                <SelectItem value="all">Tutti (attivi + storico) ⚠️</SelectItem>
              </SelectContent>
            </Select>
            <div className="text-[10px] text-amber-300/80 bg-amber-500/10 border border-amber-500/30 rounded p-2">
              {clientId
                ? `Lo scope è limitato al cliente "${clientName}". Gli alert degli altri clienti NON saranno toccati.`
                : "ATTENZIONE: nessun client_id — gli alert di TUTTI i clienti saranno coinvolti."}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={clearing} data-testid="alerts-clear-cancel-btn">
              Annulla
            </Button>
            <Button
              onClick={doClear}
              disabled={clearing}
              className="bg-red-600 hover:bg-red-700 text-white"
              data-testid="alerts-clear-confirm-btn"
            >
              {clearing ? "Eliminazione..." : `Elimina ${clearScope === "all" ? "tutti" : clearScope === "active" ? "attivi" : "storici"}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ==================== PRINTERS TAB ==================== */
function PrintersTab({ printers }) {
  if (printers.length === 0) return <div className="text-center py-8 text-[var(--text-muted)] text-xs">Nessuna stampante monitorata</div>;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {printers.map((p, i) => {
        const sc = p.status === "online" || p.status === "active" ? "#34C759" : p.status === "warning" ? "#FF9500" : p.status === "offline" || p.status === "down" ? "#FF3B30" : "#9E9E9E";
        return (
          <div key={i} className={`noc-panel p-3 ${p.alerts_silenced ? "opacity-75" : ""}`} data-testid={`printer-card-${p.ip_address}`}>
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <Printer size={14} className="text-orange-400 shrink-0" />
                <span className="text-xs font-bold text-[var(--text-primary)] truncate">{p.name || p.ip_address}</span>
              </div>
              <span className="text-[8px] font-bold px-1.5 py-0.5 rounded shrink-0" style={{ color: sc, background: `${sc}15`, border: `1px solid ${sc}40` }}>
                {p.status?.toUpperCase() || "—"}
              </span>
            </div>
            <div className="text-[9px] text-[var(--text-muted)] font-mono mb-2 flex items-center gap-1.5">
              {p.ip_address}
              {p.alerts_silenced && (
                <span className="inline-flex items-center gap-0.5 text-[8px] px-1 py-px rounded bg-amber-500/15 text-amber-300 border border-amber-500/40 normal-case font-sans font-semibold">
                  ALERT OFF
                </span>
              )}
            </div>
            {p.toner_levels && typeof p.toner_levels === "object" && Object.entries(p.toner_levels).length > 0 ? (
              Object.entries(p.toner_levels).map(([color, level]) => (
                <div key={color} className="flex items-center gap-2 text-[10px] mt-1">
                  <span className="text-[var(--text-muted)] w-12 capitalize">{color}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-card)]"><div className="h-full rounded-full" style={{ width: `${level}%`, backgroundColor: level < 15 ? "#FF3B30" : level < 30 ? "#FF9500" : "#34C759" }}></div></div>
                  <span className="font-mono font-bold w-8 text-right" style={{ color: level < 15 ? "#FF3B30" : "#34C759" }}>{level}%</span>
                </div>
              ))
            ) : (
              <p className="text-[9px] text-[var(--text-muted)] italic mt-1">
                Nessuna telemetria toner — {p.has_telemetry === false || !p.has_telemetry ? "configura SNMP Printer-MIB" : "in attesa..."}
              </p>
            )}
            {p.page_count !== undefined && p.page_count !== null && (
              <p className="text-[9px] text-[var(--text-muted)] mt-1.5 font-mono">Pagine: {p.page_count.toLocaleString()}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ==================== BACKUP TAB ==================== */
function BackupTab({ backups, clientId }) {
  const [subTab, setSubTab] = useState("m365");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
        <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Provider:</span>
        <button
          onClick={() => setSubTab("m365")}
          className={`px-3 py-1 rounded-md border text-[11px] font-semibold transition ${
            subTab === "m365"
              ? "bg-cyan-500/20 border-cyan-400 text-cyan-300"
              : "border-cyan-500/30 text-cyan-300/70 hover:bg-cyan-500/10"
          }`}
          data-testid="backup-subtab-m365"
        >
          365 Total Backup
        </button>
        <button
          onClick={() => setSubTab("vm")}
          className={`px-3 py-1 rounded-md border text-[11px] font-semibold transition ${
            subTab === "vm"
              ? "bg-violet-500/20 border-violet-400 text-violet-300"
              : "border-violet-500/30 text-violet-300/70 hover:bg-violet-500/10"
          }`}
          data-testid="backup-subtab-vm"
        >
          VM Backup (Altaro)
        </button>
      </div>
      {subTab === "m365" ? (
        <HornetsecurityBackupPanel clientId={clientId} legacyBackups={backups} />
      ) : (
        <VMBackupPanel clientId={clientId} />
      )}
    </div>
  );
}

/* ==================== HORNETSECURITY VM BACKUP PANEL ==================== */
function VMBackupPanel({ clientId }) {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState(null);
  const [mapping, setMapping] = useState({ customers: [] });
  const [status, setStatus] = useState({ items: [], totals: {} });
  const [allCustomers, setAllCustomers] = useState([]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState([]);
  const [polling, setPolling] = useState(false);
  const [view, setView] = useState("all"); // all | problems | stale

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const cfgPromise = axios.get(`${API}/admin/hornetsecurity-vm/config`).catch(e => {
        if (e?.response?.status === 403) return { data: { configured: false, _no_admin: true } };
        return { data: null };
      });
      const custsPromise = axios.get(`${API}/admin/hornetsecurity-vm/customers`).catch(() => ({ data: { customers: [] } }));
      const mapPromise = axios.get(`${API}/clients/${clientId}/backup/vmbackup/mapping`).catch(() => ({ data: { customers: [], filters: [] } }));
      const stPromise = axios.get(`${API}/clients/${clientId}/backup/vmbackup/status`).catch(() => ({ data: { items: [], totals: {} } }));
      const [cfgR, custsR, mapR, stR] = await Promise.all([cfgPromise, custsPromise, mapPromise, stPromise]);
      setConfig(cfgR.data);
      setAllCustomers(custsR.data?.customers || []);
      setMapping(mapR.data || { customers: [], filters: [] });
      setDraft(mapR.data?.customers || []);
      setStatus(stR.data || { items: [], totals: {} });
    } catch (e) {
      toast.error("Errore caricamento VM Backup");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { reload(); }, [reload]);

  const saveMapping = async () => {
    try {
      const r = await axios.put(`${API}/clients/${clientId}/backup/vmbackup/mapping`, { customers: draft });
      toast.success(`Mapping salvato (${r.data?.alerts_synced ?? 0} alert sincronizzati)`);
      setEditing(false);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore salvataggio");
    }
  };

  const pollNow = async () => {
    setPolling(true);
    try {
      const r = await axios.post(`${API}/admin/hornetsecurity-vm/poll-now`);
      const s = r.data || {};
      toast.success(`Poll completato: ${s.vms || 0} VM (${s.failed || 0} failed, ${s.stale || 0} stale)`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore polling");
    } finally {
      setPolling(false);
    }
  };

  // v3.8.30: hook ordinamento tabella VM. Va PRIMA di qualsiasi early return
  // per rispettare le regole degli React Hook (chiamate sempre nello stesso ordine).
  const _vmAggStatus = (vm) => {
    const vals = [vm?.onsite_status, vm?.offsite_status, vm?.second_offsite_status, vm?.alert_reason]
      .filter(Boolean).map(s => String(s).toLowerCase());
    if (vals.includes("failed") || vals.includes("failure")) return "failed";
    if (vals.includes("warning")) return "warning";
    if (vals.includes("stale")) return "stale";
    if (vals.includes("success")) return "success";
    return "unknown";
  };
  const _filteredItems = (status.items || []).filter(it => {
    if (view === "problems" && it.alert_reason !== "failed" && it.alert_reason !== "warning") return false;
    if (view === "stale" && it.alert_reason !== "stale") return false;
    return true;
  });
  const { sorted: sortedVms, sortKey, sortDir, requestSort } = useSortableTable(
    _filteredItems, null, "asc",
    {
      persistKey: "hornetsecurity-vm-table",
      accessors: {
        vm: (it) => (it?.vm_name || "").toLowerCase(),
        host: (it) => (it?.host_name || "").toLowerCase(),
        customer: (it) => (it?.customer_name || "").toLowerCase(),
        hypervisor: (it) => (it?.host_type || "").toLowerCase(),
        stato: (it) => _vmAggStatus(it),
        last_backup: (it) => it?.onsite_time ? Date.parse(it.onsite_time) : 0,
        size: (it) => Number(it?.onsite_size_bytes || 0),
      },
    }
  );

  if (loading) return <div className="noc-panel p-5 text-[11px] text-[var(--text-muted)] text-center">Caricamento…</div>;

  // Config non presente (no-admin è separato)
  if (!config || (!config.configured && !config._no_admin)) {
    return (
      <div className="noc-panel p-5 text-center">
        <Database size={24} className="mx-auto text-[var(--text-muted)] mb-2" />
        <p className="text-xs text-[var(--text-primary)] font-semibold">Hornetsecurity VM Backup non configurato</p>
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          Configura l'API globale in <em>Amministrazione → Hornetsecurity VM Backup</em> per abilitare il monitoraggio delle VM (Altaro).
        </p>
      </div>
    );
  }

  const t = status.totals || {};
  const items = _filteredItems;

  return (
    <div className="space-y-3">
      <div className="noc-panel p-3 flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-[260px]">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Hornetsecurity VM Backup (Altaro)</p>
          <p className="text-xs font-semibold text-[var(--text-primary)]">
            {(mapping.filters?.length || 0) > 0 ? (
              <>
                {mapping.filters.length} mapping attivi:{" "}
                {mapping.filters.slice(0, 3).map((f, i) => (
                  <span key={i} className="mr-1">
                    {f.hosts && f.hosts.length > 0
                      ? <span className="inline-flex items-center gap-1"><span className="text-[10px] text-violet-300">{f.customer}</span><span className="text-[9px] text-amber-300">→ {f.hosts.join(", ")}</span></span>
                      : <span className="text-[10px] text-violet-300">{f.customer} <span className="text-[9px] text-[var(--text-muted)]">(intero)</span></span>}
                    {i < Math.min(2, mapping.filters.length - 1) ? "," : ""}
                  </span>
                ))}
                {mapping.filters.length > 3 ? `, +${mapping.filters.length - 3}` : ""}
              </>
            ) : (mapping.customers?.length || 0) > 0 ? (
              <>{mapping.customers.length} customer: <span className="text-violet-300">{mapping.customers.join(", ")}</span></>
            ) : (
              <span className="text-amber-300">Nessun customer mappato — clicca "Modifica"</span>
            )}
          </p>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
            Polling ogni {config.polling_interval_minutes} min
            {config.last_polled_at && ` · Ultimo: ${new Date(config.last_polled_at).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}`}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" onClick={pollNow} disabled={polling} className="bg-violet-600 hover:bg-violet-700 h-7 text-[11px]" data-testid="vmbackup-poll-now">
            {polling ? "Polling…" : "Poll Ora"}
          </Button>
          {!editing ? (
            <Button size="sm" variant="outline" onClick={() => { setDraft(mapping.customers || []); setEditing(true); }} className="h-7 text-[11px]" data-testid="vmbackup-edit-mapping">
              Modifica mapping
            </Button>
          ) : (
            <>
              <Button size="sm" onClick={saveMapping} className="bg-emerald-600 hover:bg-emerald-700 h-7 text-[11px]" data-testid="vmbackup-save-mapping">Salva</Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)} className="h-7 text-[11px]">X</Button>
            </>
          )}
        </div>
      </div>

      {editing && (
        <div className="noc-panel p-3">
          <p className="text-[11px] text-[var(--text-muted)] mb-2">Seleziona i customer Hornetsecurity VM di questo cliente:</p>
          <div className="max-h-[220px] overflow-auto border border-[var(--bg-border)] rounded p-2 space-y-1">
            {allCustomers.map(c => {
              const checked = draft.includes(c.customer_name);
              return (
                <label key={c.customer_name} className="flex items-center gap-2 text-[11px] cursor-pointer hover:bg-[var(--bg-hover)] px-1 py-0.5 rounded">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={e => {
                      setDraft(d => e.target.checked ? [...d, c.customer_name] : d.filter(x => x !== c.customer_name));
                    }}
                    data-testid={`vmbackup-customer-checkbox-${c.customer_name}`}
                  />
                  <span className="font-mono flex-1">{c.customer_name}</span>
                  <span className="text-[9px] text-[var(--text-muted)]">
                    {c.vms_total} VM · {c.hosts_count} host
                    {c.vms_failed > 0 && <span className="text-red-400 ml-1">· {c.vms_failed} failed</span>}
                    {c.vms_warning > 0 && <span className="text-amber-400 ml-1">· {c.vms_warning} warn</span>}
                    {c.vms_stale > 0 && <span className="text-orange-300 ml-1">· {c.vms_stale} stale</span>}
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {((mapping.filters?.length || 0) > 0 || (mapping.customers?.length || 0) > 0) && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <StatBox label="VM totali" value={t.vms_total || 0} color="#06B6D4" />
            <StatBox label="Success" value={t.by_status?.success || 0} color="#34C759" />
            <StatBox label="Failed" value={t.failed || 0} color="#FF3B30" />
            <StatBox label="Warning" value={t.warning || 0} color="#FFB400" />
            <StatBox label="Stale > 48h" value={t.stale || 0} color="#FF9500" />
          </div>

          <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
            <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Vista:</span>
            {[
              { id: "all", label: `Tutte (${t.vms_total || 0})`, color: "cyan" },
              { id: "problems", label: `Solo problemi (${(t.failed || 0) + (t.warning || 0)})`, color: "red" },
              { id: "stale", label: `Solo stale (${t.stale || 0})`, color: "orange" },
            ].map(v => {
              const active = view === v.id;
              const cls = v.color === "red"
                ? (active ? "bg-red-500/20 border-red-400 text-red-300" : "border-red-500/30 text-red-300/70 hover:bg-red-500/10")
                : v.color === "orange"
                ? (active ? "bg-orange-500/20 border-orange-400 text-orange-300" : "border-orange-500/30 text-orange-300/70 hover:bg-orange-500/10")
                : (active ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : "border-cyan-500/30 text-cyan-300/70 hover:bg-cyan-500/10");
              return (
                <button key={v.id} onClick={() => setView(v.id)} className={`px-3 py-1 rounded-md border text-[11px] font-semibold transition ${cls}`} data-testid={`vmbackup-view-${v.id}`}>
                  {v.label}
                </button>
              );
            })}
          </div>

          {items.length === 0 ? (
            <div className="noc-panel p-5 text-center text-[11px] text-[var(--text-muted)]">Nessuna VM da mostrare con il filtro corrente.</div>
          ) : (
            <div className="noc-panel overflow-x-auto">
              {/* v3.8.30: layout compatto stile Total Protection — meno colonne (rimosse Hypervisor*, Onsite/Offsite/2°Offsite separate; status aggregato in una sola colonna Stato; size in monospace come "Note") */}
              <table className="noc-table w-full text-[11px]" data-testid="vmbackup-table">
                <thead>
                  <tr>
                    <SortableTh field="vm" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>VM</SortableTh>
                    <SortableTh field="host" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Host</SortableTh>
                    <SortableTh field="customer" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Customer</SortableTh>
                    <SortableTh field="hypervisor" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Tipo</SortableTh>
                    <SortableTh field="stato" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Stato</SortableTh>
                    <SortableTh field="last_backup" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Ultimo backup</SortableTh>
                    <SortableTh field="size" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Dim.</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedVms.slice(0, 1000).map(vm => {
                    const agg = _vmAggStatus(vm);
                    const sc = agg === "success" ? "#34C759"
                      : agg === "failed" ? "#FF3B30"
                      : agg === "warning" ? "#FFB400"
                      : agg === "stale" ? "#FF9500" : "#8E8E93";
                    // Mostra dettaglio destinazioni nel tooltip dello stato
                    const tip = [
                      vm.onsite_status_raw || vm.onsite_status ? `Onsite: ${vm.onsite_status_raw || vm.onsite_status}` : null,
                      vm.offsite_status_raw || vm.offsite_status ? `Offsite: ${vm.offsite_status_raw || vm.offsite_status}` : null,
                      vm.second_offsite_status_raw || vm.second_offsite_status ? `2° Offsite: ${vm.second_offsite_status_raw || vm.second_offsite_status}` : null,
                    ].filter(Boolean).join("\n");
                    return (
                      <tr key={`${vm.customer_name}-${vm.vm_id}`} data-testid={`vmbackup-row-${vm.vm_id}`}>
                        <td className="font-semibold">{vm.vm_name}</td>
                        <td className="text-[10px] text-[var(--text-muted)] font-mono">{vm.host_name || "—"}</td>
                        <td className="text-[10px]">{vm.customer_name}</td>
                        <td><span className="text-[9px] px-1 py-0.5 rounded border border-[var(--bg-border)]">{vm.host_type || "—"}</span></td>
                        <td title={tip || ""}><span className="text-[10px] font-bold uppercase" style={{ color: sc }}>{agg}</span></td>
                        <td className="text-[10px] text-[var(--text-muted)]">{vm.onsite_time ? new Date(vm.onsite_time).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                        <td className="text-[10px] text-[var(--text-muted)] font-mono">{_fmtBytes(vm.onsite_size_bytes)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {items.length > 1000 && <p className="text-[9px] text-[var(--text-muted)] text-center py-2">…limitato a 1000 record visualizzati</p>}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatusPill({ s, muted }) {
  if (!s || s === "Unknown" || s === "unknown") return <span className="text-[9px] text-[var(--text-muted)]">—</span>;
  const low = String(s).toLowerCase();
  let cls = "bg-[var(--bg-hover)] text-[var(--text-muted)] border-[var(--bg-border)]";
  if (low === "success") cls = "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  else if (low === "failed" || low === "failure") cls = "bg-red-500/20 text-red-300 border-red-500/30";
  else if (low === "warning") cls = "bg-amber-500/15 text-amber-300 border-amber-500/30";
  else if (low.includes("progress")) cls = "bg-cyan-500/15 text-cyan-300 border-cyan-500/30";
  return <span className={`text-[9px] px-1.5 py-0.5 rounded border ${cls} ${muted ? "opacity-60" : ""}`}>{s}</span>;
}

function _fmtBytes(n) {
  if (!n || n <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/* ==================== HORNETSECURITY 365 BACKUP PANEL (per-cliente) ==================== */
function HornetsecurityBackupPanel({ clientId, legacyBackups }) {
  const [globalCfg, setGlobalCfg] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const [statusData, setStatusData] = useState({ items: [], totals: {} });
  const [filterStatus, setFilterStatus] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [filterTenant, setFilterTenant] = useState("all");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      // Leggiamo la config globale via admin (richiede admin) — se 403/non-admin, gestiamo gracefully
      let gcfg = null;
      try {
        const r = await axios.get(`${API}/admin/hornetsecurity/global-config`);
        gcfg = r.data;
      } catch (e) {
        if (e?.response?.status === 403) gcfg = { configured: false, _no_admin: true };
        else if (e?.response?.status === 404) gcfg = null; // backend obsoleto
        else throw e;
      }
      setGlobalCfg(gcfg);

      const mr = await axios.get(`${API}/clients/${clientId}/backup/hornetsecurity/mapping`).catch(() => ({ data: null }));
      setMapping(mr.data);

      const sr = await axios.get(`${API}/clients/${clientId}/backup/hornetsecurity/status`).catch(() => ({ data: { items: [], totals: {} } }));
      setStatusData(sr.data || { items: [], totals: {} });
    } catch (e) {
      toast.error(`Errore caricamento backup: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { reload(); }, [reload]);

  const pollGlobalNow = async () => {
    setPolling(true);
    try {
      const { data } = await axios.post(`${API}/admin/hornetsecurity/poll`);
      toast.success(`Poll globale OK — ${data.workloads_total} workload (${data.workloads_failed} falliti)`);
      await reload();
    } catch (e) {
      const status = e?.response?.status;
      const det = e?.response?.data?.detail || e.message;
      if (status === 429) toast.warning(det); else toast.error(`Errore poll: ${det}`);
    } finally {
      setPolling(false);
    }
  };

  // v3.8.30: hook ordinamento workload table — DEVE essere chiamata prima
  // degli early-return (rules-of-hooks).
  const _filteredItems = (statusData.items || []).filter(it => {
    if (filterStatus !== "all") {
      if (filterStatus === "protected_only" && it.status !== "success") return false;
      if (filterStatus === "issues_only" && !["failed", "warning", "in_progress"].includes(it.status)) return false;
      if (!["protected_only", "issues_only"].includes(filterStatus) && it.status !== filterStatus) return false;
    }
    if (filterType !== "all" && it.workload_type !== filterType) return false;
    if (filterTenant !== "all" && it.tenant !== filterTenant) return false;
    return true;
  });
  const { sorted: sortedItems, sortKey, sortDir, requestSort } = useSortableTable(
    _filteredItems, null, "asc",
    {
      persistKey: "hornetsecurity-365-table",
      accessors: {
        workload: (it) => (it?.workload_name || it?.workload_id || "").toLowerCase(),
        utente: (it) => (it?.workload_user || "").toLowerCase(),
        tenant: (it) => (it?.tenant || "").toLowerCase(),
        tipo: (it) => `${it?.workload_type || ""}-${it?.workload_subcategory || ""}`.toLowerCase(),
        stato: (it) => (it?.status || "").toLowerCase(),
        last_backup: (it) => it?.last_backup_time ? Date.parse(it.last_backup_time) : 0,
        note: (it) => (it?.error || "").toLowerCase(),
      },
    }
  );

  if (loading) return <div className="text-center py-8 text-[var(--text-muted)] text-xs">Caricamento backup…</div>;

  // Backend non aggiornato → mostra fallback legacy
  if (globalCfg === null) {
    return (
      <div className="space-y-3">
        <div className="noc-panel p-3 border-l-2 border-amber-400">
          <p className="text-[11px] text-amber-300 font-semibold mb-1">Backend non aggiornato</p>
          <p className="text-[10px] text-[var(--text-muted)]">L'integrazione Hornetsecurity richiede backend v3.5.30+. Aggiorna il Center.</p>
        </div>
        {legacyBackups?.length > 0 && (
          <div className="space-y-2">
            {legacyBackups.map((b, i) => (
              <div key={i} className="noc-panel p-3 text-xs flex items-center gap-3">
                <Database size={14} className="text-[var(--text-muted)]" />
                <span className="flex-1">{b.name || b.job_name}</span>
                <span className="text-[10px]">{b.status?.toUpperCase()}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Config globale assente → CTA verso settings
  if (!globalCfg.configured) {
    return (
      <div className="noc-panel p-5 text-center">
        <Database size={28} className="text-cyan-400 mx-auto mb-2" />
        <p className="text-sm font-semibold mb-1">Hornetsecurity 365 Total Backup</p>
        <p className="text-[11px] text-[var(--text-muted)] mb-3 max-w-md mx-auto">
          La configurazione globale non e` ancora attiva. Un admin deve configurarla in Settings → Hornetsecurity 365 Backup.
        </p>
        {!globalCfg._no_admin && (
          <Button onClick={() => window.location.href = "/settings/hornetsecurity"} className="bg-cyan-600 hover:bg-cyan-700 h-8 text-xs gap-1" data-testid="goto-hornetsecurity-settings">
            Vai alle impostazioni
          </Button>
        )}
      </div>
    );
  }

  const mappedTenants = mapping?.tenants || [];
  const mappedFilters = mapping?.filters || [];
  // Considera mappato se c'e` ALMENO un filter (whole tenant string OR sub-group dict)
  const hasAnyMapping = mappedFilters.length > 0 || mappedTenants.length > 0;

  // Mapping mancante → invito a configurare
  if (!hasAnyMapping) {
    return (
      <div className="space-y-3">
        <div className="noc-panel p-3 flex items-center justify-between">
          <div>
            <p className="text-[11px] text-cyan-300 font-semibold">Hornetsecurity 365 Backup attivo (livello Center)</p>
            <p className="text-[10px] text-[var(--text-muted)]">
              Ultimo poll: {globalCfg.last_polled_at ? new Date(globalCfg.last_polled_at).toLocaleString("it-IT") : "mai"} ·
              {globalCfg.last_poll_summary?.tenants_seen || 0} tenant rilevati
            </p>
          </div>
        </div>
        <div className="noc-panel p-5 text-center">
          <ShieldCheck size={28} className="text-amber-400 mx-auto mb-2" />
          <p className="text-sm font-semibold mb-1">Mapping tenant non configurato</p>
          <p className="text-[11px] text-[var(--text-muted)] mb-3 max-w-md mx-auto">
            Per visualizzare i backup di questo cliente occorre associarlo ai tenant Hornetsecurity corrispondenti. Vai in Settings → Hornetsecurity 365 Backup → tabella mapping.
          </p>
          <Button onClick={() => window.location.href = "/settings/hornetsecurity"} className="bg-amber-600 hover:bg-amber-700 h-8 text-xs gap-1" data-testid="goto-mapping">
            Configura mapping
          </Button>
        </div>
      </div>
    );
  }

  const items = _filteredItems;
  const byStatus = statusData.totals?.by_status || {};
  const byType = statusData.totals?.by_type || {};
  const byTenant = statusData.totals?.by_tenant || {};
  const activeAlerts = statusData.totals?.active_alerts || 0;

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="noc-panel p-3 flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-[260px]">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Hornetsecurity 365 Backup</p>
          <p className="text-xs font-semibold text-[var(--text-primary)]">
            {mappedFilters.length > 0 ? (
              <>
                {mappedFilters.length} mapping attivi:{" "}
                {mappedFilters.slice(0, 3).map((f, i) => (
                  <span key={i} className="mr-1">
                    {f.sub_groups && f.sub_groups.length > 0
                      ? <span className="inline-flex items-center gap-1"><span className="text-[10px] text-cyan-300">{f.tenant}</span><span className="text-[9px] text-amber-300">→ {f.sub_groups.join(", ")}</span></span>
                      : <span className="text-[10px] text-cyan-300">{f.tenant} <span className="text-[9px] text-[var(--text-muted)]">(intero)</span></span>}
                    {i < Math.min(2, mappedFilters.length - 1) ? "," : ""}
                  </span>
                ))}
                {mappedFilters.length > 3 ? `, +${mappedFilters.length - 3}` : ""}
              </>
            ) : (
              <>{mappedTenants.length} tenant mappati: {mappedTenants.slice(0, 3).join(", ")}{mappedTenants.length > 3 ? `, +${mappedTenants.length - 3}` : ""}</>
            )}
          </p>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
            Polling globale ogni {globalCfg.poll_interval_minutes} min
            {globalCfg.last_polled_at && ` · Ultimo: ${new Date(globalCfg.last_polled_at).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}`}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button onClick={pollGlobalNow} disabled={polling} className="bg-cyan-600 hover:bg-cyan-700 h-7 text-[11px] gap-1" data-testid="hornetsecurity-poll-btn">
            {polling ? "..." : "Poll Ora"}
          </Button>
          <Button onClick={() => window.location.href = "/settings/hornetsecurity"} variant="outline" className="h-7 text-[11px]" data-testid="hornetsecurity-settings-btn">
            Settings
          </Button>
        </div>
      </div>

      {/* Stat boxes */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <StatBox label="Workload OK" value={byStatus.success || 0} color="#34C759" />
        <StatBox label="Failed" value={byStatus.failed || 0} color="#FF3B30" />
        <StatBox label="In progress" value={byStatus.in_progress || 0} color="#FFB400" />
        <StatBox label="Alert attivi" value={activeAlerts} color={activeAlerts > 0 ? "#FF9500" : "#34C759"} />
        <StatBox label="Workload tot" value={statusData.totals?.total_items || 0} color="#06B6D4" />
      </div>

      {/* Quick view toggle (primary) */}
      <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
        <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Vista:</span>
        {[
          { id: "all", label: `Tutti (${statusData.totals?.total_items || 0})`, color: "cyan" },
          { id: "protected_only", label: `Solo protetti (${byStatus.success || 0})`, color: "emerald" },
          { id: "issues_only", label: `Solo problemi (${(byStatus.failed || 0) + (byStatus.warning || 0) + (byStatus.in_progress || 0)})`, color: "red" },
        ].map(v => {
          const active = filterStatus === v.id;
          const cls = v.color === "emerald"
            ? (active ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-emerald-500/30 text-emerald-300/70 hover:bg-emerald-500/10")
            : v.color === "red"
            ? (active ? "bg-red-500/20 border-red-400 text-red-300" : "border-red-500/30 text-red-300/70 hover:bg-red-500/10")
            : (active ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : "border-cyan-500/30 text-cyan-300/70 hover:bg-cyan-500/10");
          return (
            <button key={v.id} onClick={() => setFilterStatus(v.id)}
              className={`px-3 py-1 rounded-md border text-[11px] font-semibold transition ${cls}`}
              data-testid={`hornetsecurity-quickfilter-${v.id}`}>
              {v.label}
            </button>
          );
        })}
      </div>

      {/* Filters (advanced) */}
      <details className="text-[11px]">
        <summary className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] cursor-pointer hover:text-cyan-300 select-none">Filtri avanzati</summary>
        <div className="flex items-center gap-2 flex-wrap mt-2 pl-2 border-l border-[var(--bg-border)]">
          <span className="text-[var(--text-muted)]">Stato dettaglio:</span>
          {["all", "success", "failed", "warning", "in_progress", "not_applicable", "excluded"].map(s => (
            <button key={s} onClick={() => setFilterStatus(s)}
              className={`px-2 py-0.5 rounded border text-[10px] ${filterStatus === s ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
              data-testid={`hornetsecurity-filter-status-${s}`}>{s}</button>
          ))}
          <span className="text-[var(--text-muted)] ml-2">Tipo:</span>
          {["all", "mailbox", "onedrive", "sharepoint", "teams", "entra_id", "planner"].map(t => (
            <button key={t} onClick={() => setFilterType(t)}
              className={`px-2 py-0.5 rounded border text-[10px] ${filterType === t ? "bg-violet-500/20 border-violet-400 text-violet-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
              data-testid={`hornetsecurity-filter-type-${t}`}>{t}</button>
          ))}
          {(mappedTenants.length > 1 || mappedFilters.length > 1) && (
            <>
              <span className="text-[var(--text-muted)] ml-2">Tenant:</span>
              <button onClick={() => setFilterTenant("all")} className={`px-2 py-0.5 rounded border text-[10px] ${filterTenant === "all" ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}>all</button>
              {Array.from(new Set([...(mappedTenants || []), ...(mappedFilters || []).map(f => f.tenant)])).map(t => (
                <button key={t} onClick={() => setFilterTenant(t)}
                  className={`px-2 py-0.5 rounded border text-[10px] ${filterTenant === t ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}>{t} ({byTenant[t] || 0})</button>
              ))}
            </>
          )}
        </div>
      </details>

      {/* Workload table */}
      {items.length === 0 ? (
        <div className="noc-panel p-5 text-center text-[11px] text-[var(--text-muted)]">
          Nessun workload corrispondente ai filtri.
        </div>
      ) : (
        <div className="noc-panel overflow-x-auto">
          <table className="noc-table w-full text-[11px]" data-testid="hornetsecurity-workload-table">
            <thead>
              <tr>
                <SortableTh field="workload" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Workload</SortableTh>
                <SortableTh field="utente" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Utente</SortableTh>
                <SortableTh field="tenant" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Tenant</SortableTh>
                <SortableTh field="tipo" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Tipo</SortableTh>
                <SortableTh field="stato" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Stato</SortableTh>
                <SortableTh field="last_backup" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Ultimo backup</SortableTh>
                <SortableTh field="note" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Note</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedItems.slice(0, 1000).map((it, i) => {
                const sc = it.status === "success" ? "#34C759"
                  : it.status === "failed" ? "#FF3B30"
                  : it.status === "in_progress" ? "#FFB400"
                  : it.status === "not_applicable" ? "#666"
                  : it.status === "excluded" ? "#999" : "#8E8E93";
                return (
                  <tr key={i} data-testid={`hornetsecurity-row-${i}`}>
                    <td className="font-semibold">{it.workload_name || it.workload_id}</td>
                    <td className="text-[10px] text-[var(--text-muted)] font-mono">{it.workload_user || ""}</td>
                    <td className="text-[10px]">{it.tenant}</td>
                    <td><span className="text-[9px] px-1 py-0.5 rounded border border-[var(--bg-border)]">{it.workload_type}{it.workload_subcategory ? ` · ${it.workload_subcategory}` : ""}</span></td>
                    <td><span className="text-[10px] font-bold" style={{ color: sc }}>{it.status_raw || it.status}</span></td>
                    <td className="text-[10px] text-[var(--text-muted)]">{it.last_backup_time ? new Date(it.last_backup_time).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                    <td className="text-[10px] text-red-400 truncate max-w-[260px]" title={it.error || ""}>{it.error || ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {items.length > 1000 && <p className="text-[9px] text-[var(--text-muted)] text-center py-2">…limitato a 1000 record visualizzati</p>}
        </div>
      )}
    </div>
  );
}

/* ==================== STAT BOX ==================== */
function StatBox({ label, value, color, sub }) {
  return (
    <div className="noc-panel p-2.5">
      <p className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
      <p className="text-lg font-bold font-mono leading-none mt-1" style={{ color }}>{value}</p>
      {sub && <p className="text-[9px] text-[var(--text-muted)] mt-0.5">{sub}</p>}
    </div>
  );
}

/* ==================== METRIC BOX ==================== */
function MetricBox({ label, value, sub, color }) {
  return (
    <div className="rounded-md px-2.5 py-2 bg-[var(--bg-card)] border border-[var(--bg-border)]">
      <p className="text-[7px] uppercase tracking-[0.15em] text-[var(--text-muted)] mb-0.5">{label}</p>
      <p className="text-sm font-bold font-mono leading-none" style={{ color }}>{value}</p>
      {sub && <p className="text-[9px] text-[var(--text-muted)] mt-0.5 opacity-60">{sub}</p>}
    </div>
  );
}
