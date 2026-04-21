import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  ArrowLeft, HardDrives, Globe, Printer, Database, ShieldCheck,
  Lightning, WifiHigh, WifiSlash, PlugsConnected, CaretDown,
  CheckCircle, Warning, ArrowClockwise, Bell, ChartLine, Monitor,
  Plus, Trash, Lock, MagnifyingGlass,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import VaultPage from "./VaultPage";
import { canOpenWebConsole, defaultWebPort } from "@/components/WebConsole";
import { useWebConsoleTabs } from "@/components/WebConsoleTabs";
import ILoLiveMetrics from "@/components/ILoLiveMetrics";
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
  const [connector, setConnector] = useState(null);
  const [iloHealth, setIloHealth] = useState([]);
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
    try {
      const iloRes = await axios.get(`${API}/clients/${clientId}/ilo-health`);
      setIloHealth(iloRes.data || []);
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
  const knownTypes = new Set(["firewall", "zyxel-usg", "switch", "server", "ilo", "ups", "nas", "storage", "ap", "access-point", "tvcc", "camera", "nvr", "dvr", "printer"]);
  const others = devices.filter(d => !knownTypes.has(d.device_type));

  const tabs = [
    { id: "overview", label: "Panoramica", icon: Monitor },
    { id: "devices", label: `Dispositivi (${devices.length})`, icon: HardDrives },
    { id: "wan", label: `WAN (${wanTargets.length})`, icon: Globe },
    { id: "alerts", label: `Alert (${alerts.length})`, icon: Bell },
    { id: "printers", label: `Stampanti (${printers.length})`, icon: Printer },
    { id: "backup", label: `Backup (${backups.length})`, icon: Database },
    { id: "discovery", label: "Auto-Discovery", icon: MagnifyingGlass },
    { id: "vulnerability", label: "Vulnerability", icon: ShieldCheck },
    { id: "credentials", label: "Credenziali", icon: Lock },
  ];

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
        <StatBox label="Backup" value={backups.length > 0 ? (backups.some(b => b.status === "error") ? "ERR" : "OK") : "—"} color={backups.some(b => b.status === "error") ? "#FF3B30" : "#34C759"} />
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
        {activeTab === "devices" && <DevicesTab devices={devices} clientId={clientId} onRefresh={fetchAll} />}
        {activeTab === "wan" && <WanTab targets={wanTargets} clientId={clientId} clientName={client.name} onRefresh={fetchAll} />}
        {activeTab === "alerts" && <AlertsTab alerts={alerts} navigate={navigate} />}
        {activeTab === "printers" && <PrintersTab printers={printers} />}
        {activeTab === "backup" && <BackupTab backups={backups} />}
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
  const hc = healthColor(s.health_status);

  // Compute real telemetry (NOT just first sensor!)
  const temps = (s.temperatures || []).filter(t => t.value != null && t.value > 0);
  const maxTemp = temps.length ? temps.reduce((a, b) => a.value > b.value ? a : b) : null;
  const critTemps = temps.filter(t => t.value > 75);
  const warnTemps = temps.filter(t => t.value > 65 && t.value <= 75);
  const tempColor = critTemps.length ? "#FF3B30" : warnTemps.length ? "#FFCC00" : "#34C759";

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

        <div className="grid grid-cols-2 gap-2 text-[9px]">
          <InfoBadge label="BIOS" value={s.bios_version} />
          <InfoBadge label="iLO FW" value={s.ilo_firmware} />
          <InfoBadge label="iLO License" value={s.ilo_license} />
          <InfoBadge label="Storage" value={drives.length ? `${okDrives}/${drives.length} drive OK` : "Nessun controller"} color={drivesColor} />
        </div>

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
    </div>
  );
}

function InfoBadge({ label, value, color }) {
  return (
    <div className="p-1.5 rounded bg-[var(--bg-panel)] border border-[var(--bg-border)]">
      <span className="text-[var(--text-muted)] uppercase text-[8px]">{label}</span>{" "}
      <span className="font-mono" style={{ color: color || "var(--text-primary)" }}>{value || "N/D"}</span>
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
function DevicesTab({ devices, clientId, onRefresh }) {
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const webConsole = useWebConsoleTabs();
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
      const payload = {
        name: form.name,
        ip: form.ip,
        device_type: form.device_type,
        monitor_type: form.monitor_type,
        http_port: form.monitor_type === "http" ? parseInt(form.http_port || 80) : 80,
        community: form.monitor_type === "snmp" && form.snmp_version !== "v3" ? (form.community || "public") : "",
        snmp_version: form.snmp_version,
      };
      if (form.monitor_type === "snmp" && form.snmp_version === "v3") {
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
      <div className="flex items-center justify-between">
        <p className="text-[10px] text-[var(--text-muted)]">
          {devices.length} dispositivi totali — i dispositivi manuali vengono interrogati dal connector entro pochi cicli di polling
        </p>
        <Button
          onClick={() => { setForm(emptyForm); setShowAdd(true); }}
          className="bg-indigo-600 hover:bg-indigo-700 text-white h-8 text-xs gap-1"
          data-testid="add-client-device-btn"
        >
          <Plus size={14} weight="bold" /> Aggiungi Dispositivo
        </Button>
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
              }[monitorType] || { label: monitorType.toUpperCase(), color: "text-[var(--text-muted)]", bg: "bg-[var(--bg-hover)] border-[var(--bg-border)]" };
              return (
                <tr key={i}>
                  <td className="text-[var(--text-primary)] text-xs font-medium">{d.name}</td>
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
                          onClick={() => webConsole.open(clientId, d.ip_address, defaultWebPort(d))}
                          className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors"
                          title={`Apri Web Console (porta ${defaultWebPort(d)})`}
                          data-testid={`web-console-btn-${d.ip_address}`}
                        >
                          <Monitor size={13} />
                        </button>
                      )}
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
                  </SelectContent>
                </Select>
              </div>
            </div>

            {form.monitor_type === "http" && (
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Porta HTTP/HTTPS</Label>
                <Input type="number" value={form.http_port} onChange={e => setForm({ ...form, http_port: e.target.value })} placeholder="80" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
              </div>
            )}

            {form.monitor_type === "snmp" && (
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
    </div>
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
      {printers.map((p, i) => (
        <div key={i} className="noc-panel p-3">
          <div className="flex items-center gap-2 mb-2">
            <Printer size={14} className="text-orange-400" />
            <span className="text-xs font-bold text-[var(--text-primary)]">{p.name || p.ip_address}</span>
          </div>
          {p.toner_levels && typeof p.toner_levels === "object" && Object.entries(p.toner_levels).map(([color, level]) => (
            <div key={color} className="flex items-center gap-2 text-[10px] mt-1">
              <span className="text-[var(--text-muted)] w-12">{color}</span>
              <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-card)]"><div className="h-full rounded-full" style={{ width: `${level}%`, backgroundColor: level < 15 ? "#FF3B30" : level < 30 ? "#FF9500" : "#34C759" }}></div></div>
              <span className="font-mono font-bold w-8 text-right" style={{ color: level < 15 ? "#FF3B30" : "#34C759" }}>{level}%</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ==================== BACKUP TAB ==================== */
function BackupTab({ backups }) {
  if (backups.length === 0) return <div className="text-center py-8 text-[var(--text-muted)] text-xs">Nessun backup monitorato</div>;
  return (
    <div className="space-y-2">
      {backups.map((b, i) => {
        const sc = b.status === "ok" || b.status === "success" ? "#34C759" : b.status === "warning" ? "#FF9500" : "#FF3B30";
        return (
          <div key={i} className="noc-panel p-3 flex items-center gap-3">
            <Database size={14} style={{ color: sc }} />
            <div className="flex-1">
              <span className="text-xs font-bold text-[var(--text-primary)]">{b.name || b.job_name || "Backup"}</span>
              <span className="ml-2 text-[8px] px-1.5 py-0.5 rounded font-bold" style={{ color: sc, background: `${sc}15` }}>{b.status?.toUpperCase()}</span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)]">{b.last_success ? new Date(b.last_success).toLocaleString("it-IT") : "Mai"}</span>
          </div>
        );
      })}
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
