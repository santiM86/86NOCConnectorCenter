import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  ArrowLeft, HardDrives, Globe, Printer, Database, ShieldCheck,
  Lightning, WifiHigh, WifiSlash, PlugsConnected, CaretDown,
  CheckCircle, Warning, ArrowClockwise, Bell, BellSlash, ChartLine, Monitor, Cpu,
  Plus, Trash, Lock, MagnifyingGlass, Info, PencilSimple,
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
import { canOpenWebConsole, defaultWebPort } from "@/components/WebConsole";
import { useWebConsoleTabs } from "@/components/WebConsoleTabs";
import ILoLiveMetrics from "@/components/ILoLiveMetrics";
import HealthBadge from "@/components/HealthBadge";
import { DeviceEditModal } from "@/components/DeviceEditModal";
import DiscoveryPage from "./DiscoveryPage";
import VulnerabilityPage from "./VulnerabilityPage";

const STATUS_COLOR = { online: "#34C759", offline: "#FF3B30", active: "#FFCC00", degraded: "#FF9500", unknown: "#555" };

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
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

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

  if (loading) return <div className="p-6 text-center text-[var(--text-muted)]">Caricamento...</div>;
  if (!client) return <div className="p-6 text-center text-[var(--text-muted)]">Cliente non trovato</div>;

  const onlineDevices = devices.filter(d => d.status === "online" || d.status === "active").length;
  const offlineDevices = devices.length - onlineDevices;
  const criticalAlerts = alerts.filter(a => a.severity === "critical").length;
  const firewalls = devices.filter(d => ["firewall", "zyxel-usg"].includes(d.device_type));
  const switches = devices.filter(d => d.device_type === "switch");
  const servers = devices.filter(d => ["server", "ilo"].includes(d.device_type));
  const upsList = devices.filter(d => d.device_type === "ups");
  const nasList = devices.filter(d => ["nas", "storage"].includes(d.device_type));
  const apList = devices.filter(d => ["ap", "access-point"].includes(d.device_type));
  const tvccList = devices.filter(d => ["tvcc", "camera", "nvr", "dvr"].includes(d.device_type));
  const printersList = devices.filter(d => d.device_type === "printer");
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
  const knownTypes = new Set(["firewall", "zyxel-usg", "switch", "server", "ilo", "ups", "nas", "storage", "ap", "access-point", "tvcc", "camera", "nvr", "dvr", "printer"]);
  const others = devices.filter(d => !knownTypes.has(d.device_type));

  const tabs = [
    { id: "overview", label: "Panoramica", icon: Monitor },
    { id: "devices", label: `Dispositivi (${devices.length})`, icon: HardDrives },
    { id: "wan", label: `WAN (${wanTargets.length})`, icon: Globe },
    { id: "alerts", label: `Alert (${alerts.length})`, icon: Bell },
    { id: "printers", label: `Stampanti (${mergedPrinters.length})`, icon: Printer },
    { id: "backup", label: `Backup (${backups.length})`, icon: Database },
    { id: "discovery", label: "Auto-Discovery", icon: MagnifyingGlass },
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
      <div className="grid grid-cols-2 md:grid-cols-6 gap-2 mb-4">
        <StatBox label="Dispositivi" value={`${onlineDevices}/${devices.length}`} color={offlineDevices > 0 ? "#FF9500" : "#34C759"} sub={offlineDevices > 0 ? `${offlineDevices} offline` : "Tutti online"} />
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
        {activeTab === "overview" && <OverviewTab devices={devices} wanTargets={wanTargets} alerts={alerts} connector={connector} printers={printers} backups={backups} firewalls={firewalls} switches={switches} servers={servers} upsList={upsList} nasList={nasList} apList={apList} tvccList={tvccList} printersList={printersList} others={others} iloHealth={iloHealth} />}
        {activeTab === "devices" && <DevicesTab devices={devices} clientId={clientId} onRefresh={fetchAll} onOptimisticUpdate={optimisticUpdateDevice} />}
        {activeTab === "wan" && <WanTab targets={wanTargets} clientId={clientId} clientName={client.name} onRefresh={fetchAll} />}
        {activeTab === "alerts" && <AlertsTab alerts={alerts} navigate={navigate} />}
        {activeTab === "printers" && <PrintersTab printers={mergedPrinters} />}
        {activeTab === "backup" && <BackupTab backups={backups} clientId={clientId} />}
        {activeTab === "credentials" && <VaultPage scopedClientId={clientId} scopedClientName={client.name} />}
        {activeTab === "discovery" && <DiscoveryPage scopedClientId={clientId} scopedClientName={client.name} />}
        {activeTab === "vulnerability" && <VulnerabilityPage scopedClientId={clientId} scopedClientName={client.name} />}
      </div>
    </div>
  );
}

/* ==================== OVERVIEW TAB ==================== */
function OverviewTab({ devices, wanTargets, alerts, connector, printers, backups, firewalls, switches, servers, upsList, nasList, apList, tvccList, printersList, others, iloHealth }) {
  return (
    <div className="space-y-4">
      {/* iLO Hardware Health Panel (only shown when we have iLO data) */}
      {iloHealth && iloHealth.length > 0 && <IloHealthPanel iloHealth={iloHealth} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
                const sc = STATUS_COLOR[r?.status] || "#555";
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
          {/* Others / Generic */}
          {others.length > 0 && <DeviceGroup label="Altri Dispositivi" icon={HardDrives} devices={others} color="#64748B" />}
        </div>
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
  return (
    <div className="noc-panel p-4" data-testid="ilo-health-panel">
      <div className="flex items-center gap-2 mb-3">
        <Monitor size={14} weight="bold" className="text-cyan-400" />
        <h3 className="text-[10px] font-bold uppercase tracking-[0.15em] text-cyan-400">Hardware iLO (Redfish) — {iloHealth.length} server</h3>
      </div>
      <div className="space-y-3">
        {iloHealth.map((s, idx) => <IloServerCard key={idx} s={s} healthColor={healthColor} />)}
      </div>
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

/* ==================== DEVICE GROUP ==================== */
function DeviceGroup({ label, icon: Icon, devices, color }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1">
        <Icon size={11} weight="bold" style={{ color }} />
        <p className="text-[8px] uppercase tracking-widest" style={{ color }}>{label} ({devices.length})</p>
      </div>
      <div className="space-y-1">
        {devices.map((d, i) => {
          const sc = STATUS_COLOR[d.status] || "#555";
          return (
            <div key={i} className="flex items-center gap-2 px-2.5 py-1.5 rounded-md border text-[10px]" style={{ borderColor: `${sc}20`, background: `${sc}04` }}>
              <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: sc }}></div>
              <span className="font-medium text-[var(--text-primary)] truncate">{d.name}</span>
              <span className="font-mono text-[var(--text-muted)]">{d.ip_address}</span>
              {d.snmp_community && <span className="text-[8px] px-1 rounded bg-[var(--bg-card)] text-[var(--text-muted)]">{d.snmp_version || "snmp"}: {d.snmp_community}</span>}
              <span className="ml-auto font-bold text-[8px] uppercase" style={{ color: sc }}>{d.status}</span>
              {d.source === "connector" && <span className="text-[7px] px-1 rounded bg-indigo-500/10 text-indigo-400">C</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ==================== DEVICES TAB ==================== */
function DevicesTab({ devices, clientId, onRefresh, onOptimisticUpdate }) {
  const [showAdd, setShowAdd] = useState(false);
  const [profileTarget, setProfileTarget] = useState(null);
  const [infoTarget, setInfoTarget] = useState(null);
  const [editTarget, setEditTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  const webConsole = useWebConsoleTabs();

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
      const { total = 0, matched = 0, skipped = 0, details = [] } = data || {};
      if (matched === 0 && total === 0) {
        toast.info("Nessun device da riconoscere");
        return;
      }
      // Build compact summary for toast
      const newMatches = details
        .filter(d => d.matched)
        .map(d => `• ${d.name || d.device_ip} → ${d.vendor || d.profile_key}`)
        .slice(0, 6);
      const extra = details.filter(d => d.matched).length - newMatches.length;
      const body = newMatches.join("\n") + (extra > 0 ? `\n…e altri ${extra}` : "");
      if (matched > 0) {
        toast.success(
          `Profilo agganciato su ${matched}/${total} device`,
          { description: body || `Skipped: ${skipped}`, duration: 7000 },
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

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[10px] text-[var(--text-muted)]">
          {devices.length} dispositivi totali — i dispositivi manuali vengono interrogati dal connector entro pochi cicli di polling
        </p>
        <div className="flex items-center gap-2">
          <Button
            onClick={() => rematchProfiles()}
            className="bg-cyan-600/90 hover:bg-cyan-600 text-white h-8 text-xs gap-1"
            data-testid="rematch-profiles-btn"
            title="Ri-esegue il fingerprint vendor (Synology, Xanto, HPE Comware, ecc.) su tutti i device del cliente. Utile dopo che lo SNMP ha iniziato a funzionare — i profili manuali non vengono sovrascritti."
          >
            <MagnifyingGlass size={13} /> Riconosci profili
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
            onClick={() => { setForm(emptyForm); setShowAdd(true); }}
            className="bg-indigo-600 hover:bg-indigo-700 text-white h-8 text-xs gap-1"
            data-testid="add-client-device-btn"
          >
            <Plus size={14} weight="bold" /> Aggiungi Dispositivo
          </Button>
        </div>
      </div>

      <div className="noc-panel overflow-x-auto">
        <table className="alert-table min-w-[780px]" data-testid="client-devices-table">
          <thead>
            <tr><th>Nome</th><th>Tipo</th><th>IP</th><th>Metodo</th><th>SNMP</th><th>Community</th><th>Stato</th><th>Fonte</th><th>Ultimo Poll</th><th></th></tr>
          </thead>
          <tbody>
            {devices.length === 0 ? (
              <tr><td colSpan={10} className="text-center text-[var(--text-muted)] py-8 text-xs">Nessun dispositivo — clicca "Aggiungi Dispositivo" per iniziare</td></tr>
            ) : devices.map((d, i) => {
              const sc = STATUS_COLOR[d.status] || "#555";
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
                  <td className="text-[var(--text-primary)] text-xs font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      {d.name}
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
                  <td><span className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--bg-border)]">{d.device_type}</span></td>
                  <td className="font-mono text-[var(--text-muted)] text-xs">{d.ip_address}</td>
                  <td>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded border font-bold ${methodBadge.bg} ${methodBadge.color}`}>
                      {methodBadge.label}
                    </span>
                  </td>
                  <td className="text-[10px] text-[var(--text-muted)]">
                    {monitorType === "snmp" ? (d.snmp_version || "v2c") : "—"}
                  </td>
                  <td className="text-[10px] font-mono text-[var(--text-muted)]">
                    {monitorType === "snmp" && d.snmp_version !== "v3" ? (d.snmp_community || "—") : "—"}
                  </td>
                  <td>
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold" style={{ color: sc }}>
                      {d.status === "online" || d.status === "active" ? <WifiHigh size={12} /> : <WifiSlash size={12} />}
                      {d.status?.toUpperCase()}
                    </span>
                    {d.ping_ms && <span className="ml-1 text-[9px] text-[var(--text-muted)]">{d.ping_ms}ms</span>}
                  </td>
                  <td>{d.source === "connector" ? <span className="text-[8px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold">CONNECTOR</span> : <span className="text-[8px] text-[var(--text-muted)]">Manuale</span>}</td>
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
                      <button
                        onClick={() => navigate(`/device-metrics?ip=${d.ip_address}`)}
                        className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
                        title="Trend metriche storiche"
                        data-testid={`device-trend-${d.ip_address}`}
                      >
                        <ChartLine size={13} />
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
        <Dialog open={!!infoTarget} onOpenChange={(o) => !o && setInfoTarget(null)}>
          <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-6xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-[var(--text-primary)]">
                <Info size={18} className="text-cyan-400" />
                Scheda Dispositivo — {infoTarget.name || infoTarget.ip_address}
              </DialogTitle>
            </DialogHeader>
            <DeviceInfoCard deviceIp={infoTarget.ip_address} onClose={() => setInfoTarget(null)} />
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
  const familyOrder = ["switch", "firewall", "nas", "ups", "server_oob", "unifi", "generic"];
  const familyLabels = { switch: "Switch", firewall: "Firewall", nas: "NAS", ups: "UPS", server_oob: "Server OOB (iLO/iDRAC)", unifi: "UniFi", generic: "Generico" };

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

/* ==================== WAN TAB ==================== */
function WanTab({ targets, clientId, clientName, onRefresh }) {
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const emptyForm = {
    label: "", device_type: "firewall", public_ip: "", gateway_ip: "",
    check_ports: "443", check_ping: true,
  };
  const [form, setForm] = useState(emptyForm);

  const testConnection = async () => {
    if (!form.public_ip) { toast.error("Inserisci un IP pubblico"); return; }
    setTesting(true);
    setTestResult(null);
    try {
      const ports = form.check_ports.split(",").map(p => parseInt(p.trim())).filter(p => !isNaN(p) && p > 0);
      const res = await axios.post(`${API}/external-monitor/test-connection`, {
        public_ip: form.public_ip,
        gateway_ip: form.gateway_ip || null,
        check_ports: ports,
        check_ping: form.check_ping,
      });
      setTestResult(res.data);
      if (res.data.reachable) toast.success("Dispositivo raggiungibile");
      else toast.error("Dispositivo NON raggiungibile");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore test");
    } finally { setTesting(false); }
  };

  const handleSave = async () => {
    if (!form.label || !form.public_ip) { toast.error("Label e IP pubblico obbligatori"); return; }
    setSaving(true);
    try {
      const ports = form.check_ports.split(",").map(p => parseInt(p.trim())).filter(p => !isNaN(p) && p > 0);
      await axios.post(`${API}/external-monitor/targets`, {
        client_id: clientId,
        label: form.label,
        device_type: form.device_type,
        public_ip: form.public_ip,
        gateway_ip: form.gateway_ip || null,
        check_ports: ports,
        check_ping: form.check_ping,
      });
      toast.success(`Target WAN "${form.label}" aggiunto`);
      setForm(emptyForm);
      setTestResult(null);
      setShowAdd(false);
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    } finally { setSaving(false); }
  };

  const handleDelete = async (t) => {
    if (!window.confirm(`Eliminare il target "${t.label}" (${t.public_ip})?`)) return;
    try {
      await axios.delete(`${API}/external-monitor/targets/${t.id}`);
      toast.success("Target eliminato");
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] text-[var(--text-muted)]">
          {targets.length === 0
            ? "Nessun target WAN configurato — aggiungi firewall/router pubblici per monitorare la connettività esterna"
            : `${targets.length} target WAN monitorati — Ping ICMP + TCP port check + Gateway ISP diagnostics`}
        </p>
        <Button
          onClick={() => { setForm(emptyForm); setTestResult(null); setShowAdd(true); }}
          className="bg-indigo-600 hover:bg-indigo-700 text-white h-8 text-xs gap-1"
          data-testid="add-wan-target-btn"
        >
          <Plus size={14} weight="bold" /> Aggiungi Target WAN
        </Button>
      </div>

      {targets.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-muted)] text-xs noc-panel">
          <Globe size={28} className="mx-auto mb-2 opacity-30" />
          <p>Nessun target WAN configurato per {clientName}</p>
          <p className="text-[9px] mt-1">Clicca "Aggiungi Target WAN" per iniziare il monitoraggio</p>
        </div>
      ) : targets.map(t => {
        const r = t.result;
        const sc = STATUS_COLOR[r?.status] || "#555";
        return (
          <div key={t.id} className="noc-panel p-4">
            <div className="flex items-center gap-3 mb-3">
              {t.device_type === "firewall" ? <ShieldCheck size={16} weight="bold" style={{ color: sc }} /> : <HardDrives size={16} weight="bold" style={{ color: sc }} />}
              <div className="flex-1">
                <span className="text-sm font-bold text-[var(--text-primary)]">{t.label}</span>
                <span className="ml-2 text-[8px] px-1.5 py-0.5 rounded font-bold uppercase" style={{ color: sc, background: `${sc}15` }}>{r?.status?.toUpperCase() || "PENDING"}</span>
              </div>
              <span className="font-mono text-[var(--text-muted)] text-xs">{t.public_ip}</span>
              <button onClick={() => handleDelete(t)} className="p-1 rounded hover:bg-[var(--critical-bg)] text-[var(--critical)] transition-colors" title="Rimuovi">
                <Trash size={13} />
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricBox label="Ping ICMP" value={r?.ping?.reachable ? "OK" : "FAIL"} sub={r?.ping?.latency_ms != null ? `${r.ping.latency_ms}ms` : null} color={r?.ping?.reachable ? "#34C759" : "#FF3B30"} />
              <MetricBox label="Packet Loss" value={r?.ping?.packet_loss_pct != null ? `${r.ping.packet_loss_pct}%` : "—"} color={r?.ping?.packet_loss_pct > 5 ? "#FF3B30" : "#34C759"} />
              <MetricBox label="Gateway ISP" value={r?.gateway_ping ? (r.gateway_ping.reachable ? "ONLINE" : "DOWN") : "N/C"} sub={t.gateway_ip || ""} color={r?.gateway_ping?.reachable ? "#34C759" : r?.gateway_ping ? "#FF3B30" : "#555"} />
              <MetricBox label="Ultimo Check" value={r?.checked_at ? new Date(r.checked_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }) : "—"} color="#6366F1" />
            </div>
            {r?.ports?.length > 0 && (
              <div className="mt-3 flex gap-2 flex-wrap">
                {r.ports.map((p, j) => (
                  <span key={j} className="text-[10px] font-mono px-2 py-1 rounded border" style={{ color: p.open ? "#34C759" : "#FF3B30", borderColor: p.open ? "#34C75930" : "#FF3B3030", background: p.open ? "#34C75908" : "#FF3B3008" }}>
                    :{p.port} {p.open ? "OPEN" : "CLOSED"} {p.response_ms && `${p.response_ms}ms`}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* Add WAN Target Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <Globe size={18} className="text-indigo-400" /> Aggiungi Target WAN per {clientName}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Label *</Label>
                <Input value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} placeholder="Firewall Sede Principale" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="wan-label-input" />
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Tipo Dispositivo</Label>
                <Select value={form.device_type} onValueChange={v => setForm({ ...form, device_type: v })}>
                  <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="firewall">Firewall</SelectItem>
                    <SelectItem value="router">Router</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">IP Pubblico *</Label>
                <Input value={form.public_ip} onChange={e => setForm({ ...form, public_ip: e.target.value })} placeholder="82.121.33.10" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs font-mono" data-testid="wan-public-ip-input" />
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">IP Gateway ISP (opzionale)</Label>
                <Input value={form.gateway_ip} onChange={e => setForm({ ...form, gateway_ip: e.target.value })} placeholder="82.121.33.1" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs font-mono" />
              </div>
            </div>
            <div>
              <Label className="text-[var(--text-muted)] text-[10px]">Porte TCP da controllare (separate da virgola)</Label>
              <Input value={form.check_ports} onChange={e => setForm({ ...form, check_ports: e.target.value })} placeholder="443, 80, 8443" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs font-mono" />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="check_ping_wan"
                checked={form.check_ping}
                onChange={e => setForm({ ...form, check_ping: e.target.checked })}
                className="rounded accent-indigo-500"
              />
              <Label htmlFor="check_ping_wan" className="text-[var(--text-primary)] text-[10px] cursor-pointer">
                Abilita Ping ICMP (alcuni firewall bloccano ICMP)
              </Label>
            </div>

            {testResult && (
              <div className={`p-2 rounded text-[10px] ${testResult.reachable ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400" : "bg-red-500/10 border border-red-500/20 text-red-400"}`}>
                Test: {testResult.reachable ? "RAGGIUNGIBILE" : "NON RAGGIUNGIBILE"}
                {testResult.ping?.latency_ms != null && ` | Ping: ${testResult.ping.latency_ms}ms`}
                {testResult.ports?.length > 0 && (
                  <div className="mt-1">Porte: {testResult.ports.map(p => `:${p.port}=${p.open ? "OPEN" : "CLOSED"}`).join(", ")}</div>
                )}
              </div>
            )}

            <div className="flex gap-2">
              <Button
                onClick={testConnection}
                disabled={testing || !form.public_ip}
                variant="outline"
                className="flex-1 h-9 text-xs"
                data-testid="wan-test-btn"
              >
                {testing ? <ArrowClockwise size={13} className="animate-spin mr-1" /> : <Lightning size={13} className="mr-1" />}
                {testing ? "Test in corso..." : "Test Connessione"}
              </Button>
              <Button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white h-9 text-xs"
                data-testid="save-wan-target-btn"
              >
                {saving ? <ArrowClockwise size={13} className="animate-spin mr-1" /> : <Plus size={13} className="mr-1" />}
                {saving ? "Salvataggio..." : "Aggiungi Target"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ==================== ALERTS TAB ==================== */
function AlertsTab({ alerts, navigate }) {
  return (
    <div className="noc-panel overflow-x-auto">
      <table className="alert-table min-w-[560px]">
        <thead><tr><th>Sev.</th><th>Titolo</th><th>Dispositivo</th><th>Data</th></tr></thead>
        <tbody>
          {alerts.length === 0 ? (
            <tr><td colSpan={4} className="text-center text-emerald-400 py-8 text-xs">Nessun alert attivo</td></tr>
          ) : alerts.map(a => {
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
      const mapPromise = axios.get(`${API}/clients/${clientId}/backup/vmbackup/mapping`).catch(() => ({ data: { customers: [] } }));
      const stPromise = axios.get(`${API}/clients/${clientId}/backup/vmbackup/status`).catch(() => ({ data: { items: [], totals: {} } }));
      const [cfgR, custsR, mapR, stR] = await Promise.all([cfgPromise, custsPromise, mapPromise, stPromise]);
      setConfig(cfgR.data);
      setAllCustomers(custsR.data?.customers || []);
      setMapping(mapR.data || { customers: [] });
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
  const items = (status.items || []).filter(it => {
    if (view === "problems" && it.alert_reason !== "failed" && it.alert_reason !== "warning") return false;
    if (view === "stale" && it.alert_reason !== "stale") return false;
    return true;
  });

  return (
    <div className="space-y-3">
      <div className="noc-panel p-3 flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-[260px]">
          <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Hornetsecurity VM Backup (Altaro)</p>
          <p className="text-xs font-semibold text-[var(--text-primary)]">
            {mapping.customers?.length > 0
              ? <>{mapping.customers.length} customer: <span className="text-violet-300">{mapping.customers.join(", ")}</span></>
              : <span className="text-amber-300">Nessun customer mappato — clicca "Modifica"</span>}
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

      {(mapping.customers?.length || 0) > 0 && (
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
            <div className="noc-panel overflow-hidden">
              <div className="overflow-x-auto">
                <table className="noc-table w-full text-[11px]" data-testid="vmbackup-table">
                  <thead>
                    <tr>
                      <th>VM</th>
                      <th>Host</th>
                      <th>Hypervisor</th>
                      <th>Customer</th>
                      <th>Onsite</th>
                      <th>Offsite</th>
                      <th>2° Offsite</th>
                      <th>Ultimo backup</th>
                      <th>Dim.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map(vm => (
                      <tr key={`${vm.customer_name}-${vm.vm_id}`} data-testid={`vmbackup-row-${vm.vm_id}`}>
                        <td className="font-semibold">
                          {vm.vm_name}
                          {vm.alert_reason === "failed" && <span className="ml-1 text-[9px] px-1 rounded bg-red-500/20 text-red-300">FAILED</span>}
                          {vm.alert_reason === "warning" && <span className="ml-1 text-[9px] px-1 rounded bg-amber-500/20 text-amber-300">WARN</span>}
                          {vm.alert_reason === "stale" && <span className="ml-1 text-[9px] px-1 rounded bg-orange-500/20 text-orange-300">STALE</span>}
                        </td>
                        <td className="font-mono text-[10px]">{vm.host_name}</td>
                        <td className="text-[10px] text-[var(--text-muted)]">{vm.host_type}</td>
                        <td className="text-[10px] text-[var(--text-muted)]">{vm.customer_name}</td>
                        <td><StatusPill s={vm.onsite_status_raw || vm.onsite_status} /></td>
                        <td><StatusPill s={vm.offsite_status_raw || vm.offsite_status} /></td>
                        <td><StatusPill s={vm.second_offsite_status_raw || vm.second_offsite_status} muted /></td>
                        <td className="text-[10px] text-[var(--text-muted)] font-mono">
                          {vm.onsite_time ? new Date(vm.onsite_time).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
                        </td>
                        <td className="text-[10px] text-[var(--text-muted)] font-mono">{_fmtBytes(vm.onsite_size_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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

  const items = (statusData.items || []).filter(it => {
    if (filterStatus !== "all") {
      if (filterStatus === "protected_only" && it.status !== "success") return false;
      if (filterStatus === "issues_only" && !["failed", "warning", "in_progress"].includes(it.status)) return false;
      if (!["protected_only", "issues_only"].includes(filterStatus) && it.status !== filterStatus) return false;
    }
    if (filterType !== "all" && it.workload_type !== filterType) return false;
    if (filterTenant !== "all" && it.tenant !== filterTenant) return false;
    return true;
  });
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
              <tr><th>Workload</th><th>Utente</th><th>Tenant</th><th>Tipo</th><th>Stato</th><th>Ultimo backup</th><th>Note</th></tr>
            </thead>
            <tbody>
              {items.slice(0, 1000).map((it, i) => {
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
