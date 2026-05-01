import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { API } from "@/App";
import {
  WifiHigh, WifiSlash, ArrowClockwise, Clock, Buildings,
  CaretDown, CaretRight, ArrowUp, ArrowDown, Export,
  FileArrowUp, MagnifyingGlass, Globe, Desktop, Plus,
  Monitor, X, Trash, CheckCircle, HardDrive, SpinnerGap,
  WifiHigh as WifiIcon, Pulse, ListBullets, Graph,
  CircleNotch, ShieldCheck, Warning,
  Stack as StackIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { DeviceDetailPanel } from "@/components/DeviceDetailPanel";
import NetworkMap from "@/components/NetworkMap";

export default function ClientStatusPage() {
  const [devices, setDevices] = useState([]);
  const [clients, setClients] = useState([]);
  const [connectors, setConnectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedDevice, setExpandedDevice] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [collapsedClients, setCollapsedClients] = useState({});
  const [showAddDevice, setShowAddDevice] = useState(false);
  const [newDevice, setNewDevice] = useState({ ip: "", community: "public", name: "", monitor_type: "snmp", device_type: "network", http_port: 80 });
  const [addDeviceClientId, setAddDeviceClientId] = useState("");
  const intervalRef = useRef(null);
  const importFileRef = useRef(null);
  const [importClientId, setImportClientId] = useState(null);
  const [showDiscovery, setShowDiscovery] = useState(false);
  const [discoveryClientId, setDiscoveryClientId] = useState("");
  const [discoverySubnet, setDiscoverySubnet] = useState("");
  const [discoveryStatus, setDiscoveryStatus] = useState("none");
  const [discoveryResults, setDiscoveryResults] = useState(null);
  const [scanning, setScanning] = useState(false);
  const discoveryPollRef = useRef(null);
  const [webConsole, setWebConsole] = useState(null);
  const webConsolePollRef = useRef(null);
  const [viewMode, setViewMode] = useState("list");

  useEffect(() => {
    fetchAll();
    intervalRef.current = setInterval(fetchAll, 15000);
    return () => clearInterval(intervalRef.current);
  }, []);

  const fetchAll = async () => {
    try {
      const [devRes, clientRes, connRes] = await Promise.all([
        axios.get(`${API}/connector/device-poll-status`),
        axios.get(`${API}/clients`),
        axios.get(`${API}/connector/status`)
      ]);
      setDevices(devRes.data);
      setClients(clientRes.data);
      setConnectors(connRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  const isOnline = (lastSeen) => lastSeen && (Date.now() - new Date(lastSeen).getTime()) < 120000;
  const isRecentPoll = (ts) => ts && (Date.now() - new Date(ts).getTime()) < 600000;

  const formatLastSeen = (ts) => {
    if (!ts) return "Mai";
    const d = new Date(ts);
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 60000) return "Adesso";
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m fa`;
    if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}h fa`;
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  const deleteDevice = async (deviceIp) => {
    try {
      await axios.delete(`${API}/connector/device-poll-status/${encodeURIComponent(deviceIp)}`);
      toast.success(`Dispositivo ${deviceIp} rimosso`);
      setDeleteTarget(null);
      fetchAll();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const exportDevices = (clientName, clientDevices) => {
    const csvHeader = "IP,Community,Nome";
    const csvRows = clientDevices.map(d => `${d.device_ip},${d.community || "public"},${d.device_name || d.device_ip}`);
    const csvContent = [csvHeader, ...csvRows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `dispositivi_${clientName.replace(/\s+/g, "_")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`${clientDevices.length} dispositivi esportati`);
  };

  const handleImportDevices = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !importClientId) return;
    try {
      const text = await file.text();
      const lines = text.split("\n").map(l => l.trim()).filter(l => l && !l.toLowerCase().startsWith("ip"));
      let imported = 0;
      for (const line of lines) {
        const [ip, community, ...nameParts] = line.split(",");
        if (!ip?.trim()) continue;
        try {
          await axios.post(`${API}/connector/${importClientId}/managed-devices`, {
            ip: ip.trim(), community: (community || "public").trim(), name: (nameParts.join(",") || ip).trim()
          });
          imported++;
        } catch {}
      }
      toast.success(`${imported} dispositivi importati`);
      fetchAll();
    } catch (err) {
      toast.error("Errore importazione: " + err.message);
    }
    e.target.value = "";
    setImportClientId(null);
  };

  const addDevice = async () => {
    if (!newDevice.ip || !addDeviceClientId) { toast.error("Seleziona un cliente e inserisci l'IP"); return; }
    try {
      await axios.post(`${API}/connector/${addDeviceClientId}/managed-devices`, {
        ip: newDevice.ip, community: newDevice.community || "public",
        name: newDevice.name || newDevice.ip, monitor_type: newDevice.monitor_type || "snmp",
        device_type: newDevice.device_type || "network", http_port: newDevice.http_port || 80
      });
      toast.success(`Dispositivo ${newDevice.name || newDevice.ip} aggiunto`);
      setNewDevice({ ip: "", community: "public", name: "", monitor_type: "snmp", device_type: "network", http_port: 80 });
      setShowAddDevice(false);
      fetchAll();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const switchMonitorType = async (deviceIp, currentType) => {
    const newType = currentType === "snmp" ? "ping" : "snmp";
    try {
      await axios.put(`${API}/connector/device-poll-status/${encodeURIComponent(deviceIp)}/monitor-type`, { monitor_type: newType, http_port: 80 });
      toast.success(`${deviceIp} cambiato a ${newType === "snmp" ? "SNMP" : "Ping+HTTP"}`);
      fetchAll();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const toggleClient = (id) => setCollapsedClients(prev => ({ ...prev, [id]: !prev[id] }));

  // Discovery
  const startDiscovery = async () => {
    if (!discoveryClientId) { toast.error("Seleziona un cliente"); return; }
    setScanning(true); setDiscoveryStatus("pending");
    try {
      await axios.post(`${API}/connector/start-discovery`, { client_id: discoveryClientId, subnet: discoverySubnet || "" });
      toast.success("Scansione rete avviata!");
      if (discoveryPollRef.current) clearInterval(discoveryPollRef.current);
      discoveryPollRef.current = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API}/connector/discovery-status/${discoveryClientId}`);
          setDiscoveryStatus(statusRes.data.status);
          if (statusRes.data.status === "completed") {
            const res = await axios.get(`${API}/connector/discovery-results/${discoveryClientId}`);
            setDiscoveryResults(res.data); setScanning(false);
            clearInterval(discoveryPollRef.current);
            toast.success(`Scansione completata: ${res.data.device_count || 0} dispositivi trovati`);
          }
        } catch {}
      }, 5000);
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message)); setScanning(false);
    }
  };

  const onDiscoveryClientChange = async (clientId) => {
    setDiscoveryClientId(clientId);
    if (!clientId) { setDiscoveryResults(null); return; }
    try {
      const res = await axios.get(`${API}/connector/discovery-results/${clientId}`);
      if (res.data?.devices?.length > 0) setDiscoveryResults(res.data);
    } catch {}
  };

  const addDiscoveredDevice = async (dev) => {
    if (!discoveryClientId) return;
    try {
      await axios.post(`${API}/connector/${discoveryClientId}/managed-devices`, {
        ip: dev.ip, name: dev.hostname || dev.ip,
        community: dev.suggested_type === "snmp" ? "public" : "", monitor_type: dev.suggested_type || "ping", http_port: dev.http_port || 80
      });
      toast.success(`${dev.hostname || dev.ip} aggiunto`);
      const res = await axios.get(`${API}/connector/discovery-results/${discoveryClientId}`);
      setDiscoveryResults(res.data);
      fetchAll();
    } catch (e) { toast.error("Errore: " + (e.response?.data?.detail || e.message)); }
  };

  useEffect(() => {
    return () => { if (discoveryPollRef.current) clearInterval(discoveryPollRef.current); };
  }, []);

  // Web Console
  const openWebConsole = async (clientId, deviceIp, port, path = "/") => {
    setWebConsole({ clientId, deviceIp, port, path, loading: true, html: null, title: `${deviceIp}:${port}`, progress: 0, startTime: Date.now() });
    try {
      const res = await axios.post(`${API}/connector/web-proxy/request`, {
        client_id: clientId, device_ip: deviceIp, port: port || 80, path, method: "GET"
      });
      const requestId = res.data.request_id;
      if (webConsolePollRef.current) clearInterval(webConsolePollRef.current);
      let attempts = 0;
      const pollFn = async () => {
        attempts++;
        const elapsed = Math.min((attempts / 20) * 100, 95);
        setWebConsole(prev => prev ? { ...prev, progress: elapsed } : null);
        if (attempts > 40) {
          clearInterval(webConsolePollRef.current);
          setWebConsole(prev => prev ? { ...prev, loading: false, progress: 100, html: '<div style="padding:40px;text-align:center;font-family:system-ui"><h2 style="color:#FF3B30;margin-bottom:12px">Timeout</h2><p style="color:#888">Il connettore non ha risposto entro 30 secondi.<br>Verifica che il connettore sia attivo e il dispositivo raggiungibile.</p></div>' } : null);
          return;
        }
        try {
          const resp = await axios.get(`${API}/connector/web-proxy/response/${requestId}`);
          if (resp.data.status === "completed" && resp.data.response) {
            clearInterval(webConsolePollRef.current);
            const loadTime = Date.now() - (webConsolePollRef._startTime || Date.now());
            setWebConsole(prev => prev ? { ...prev, loading: false, progress: 100, html: resp.data.response.body, title: resp.data.response.title || `${deviceIp}:${port}${path}`, error: resp.data.response.error, loadTime } : null);
          }
        } catch {}
      };
      webConsolePollRef._startTime = Date.now();
      // Aggressive polling: 500ms for first 5s, then 1.5s
      let fastPoll = setInterval(pollFn, 500);
      setTimeout(() => {
        clearInterval(fastPoll);
        webConsolePollRef.current = setInterval(pollFn, 1500);
      }, 5000);
      webConsolePollRef.current = fastPoll;
    } catch (e) {
      setWebConsole(prev => prev ? { ...prev, loading: false, progress: 100, html: `<div style="padding:40px;text-align:center;font-family:system-ui"><h2 style="color:#FF3B30;margin-bottom:12px">Errore</h2><p style="color:#888">${e.response?.data?.detail || e.message}</p></div>` } : null);
    }
  };

  const closeWebConsole = () => { if (webConsolePollRef.current) clearInterval(webConsolePollRef.current); setWebConsole(null); };

  useEffect(() => {
    const handleMessage = (event) => {
      if (event.data?.type === 'proxy-navigate' && webConsole) {
        let path = event.data.path;
        if (event.data.baseUrl && path.startsWith(event.data.baseUrl)) path = path.replace(event.data.baseUrl, '');
        if (!path.startsWith('/')) path = '/' + path;
        openWebConsole(webConsole.clientId, webConsole.deviceIp, webConsole.port, path);
      }
    };
    window.addEventListener('message', handleMessage);
    return () => { window.removeEventListener('message', handleMessage); if (webConsolePollRef.current) clearInterval(webConsolePollRef.current); };
  }, [webConsole]);

  const portsByStatus = (ports) => {
    const up = (ports || []).filter(p => p.status === "up").length;
    const down = (ports || []).filter(p => p.status === "down").length;
    return { up, down, total: (ports || []).length };
  };

  // Build client groups (devices only, connectors just for online indicator)
  const clientGroups = (() => {
    const groups = {};
    clients.forEach(c => { groups[c.id] = { clientId: c.id, clientName: c.name, devices: [], connectorOnline: false }; });
    connectors.forEach(c => {
      const cid = c.client_id || "unknown";
      if (groups[cid]) groups[cid].connectorOnline = isOnline(c.last_seen);
    });
    devices.forEach(d => {
      const cid = d.client_id || "unknown";
      if (!groups[cid]) groups[cid] = { clientId: cid, clientName: cid, devices: [], connectorOnline: false };
      groups[cid].devices.push(d);
    });
    return Object.values(groups).filter(g => g.devices.length > 0).sort((a, b) => a.clientName.localeCompare(b.clientName));
  })();

  const totalDevices = devices.length;
  const reachable = devices.filter(d => d.reachable).length;
  const unreachable = totalDevices - reachable;

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="client-status-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Stato Rete</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Monitoraggio dispositivi per cliente</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => { fetchAll(); toast.success("Aggiornato"); }}
          className="rounded-md text-xs h-8 border-[var(--bg-border)] text-[var(--text-secondary)]" data-testid="refresh-status-btn">
          <ArrowClockwise size={14} className="mr-1.5" /> Aggiorna
        </Button>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-3">
        <div className="noc-panel p-3 flex items-center gap-3">
          <Pulse size={18} className="text-[var(--text-muted)]" />
          <div>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Dispositivi</p>
            <p className="font-heading text-lg font-bold text-[var(--text-primary)]">{totalDevices}</p>
          </div>
        </div>
        <div className="noc-panel p-3 flex items-center gap-3">
          <WifiHigh size={18} className="text-[var(--ok)]" />
          <div>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Raggiungibili</p>
            <p className="font-heading text-lg font-bold text-[var(--ok)]">{reachable}</p>
          </div>
        </div>
        <div className="noc-panel p-3 flex items-center gap-3">
          <WifiSlash size={18} className="text-[var(--critical)]" />
          <div>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Non raggiung.</p>
            <p className="font-heading text-lg font-bold text-[var(--critical)]">{unreachable}</p>
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="font-heading text-sm font-bold text-[var(--text-primary)]">Dispositivi per Cliente</h2>
          <div className="flex items-center rounded-md border border-[var(--bg-border)] overflow-hidden" data-testid="view-mode-toggle">
            <button
              onClick={() => setViewMode("list")}
              className={`h-7 px-2.5 flex items-center gap-1 text-[10px] font-medium transition-colors ${viewMode === "list" ? "bg-indigo-600/20 text-indigo-400" : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"}`}
              data-testid="view-mode-list"
            >
              <ListBullets size={13} /> Lista
            </button>
            <button
              onClick={() => setViewMode("map")}
              className={`h-7 px-2.5 flex items-center gap-1 text-[10px] font-medium transition-colors ${viewMode === "map" ? "bg-indigo-600/20 text-indigo-400" : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)]"}`}
              data-testid="view-mode-map"
            >
              <Graph size={13} /> Mappa
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowDiscovery(!showDiscovery)}
            className="rounded-md text-xs h-8 border-[var(--bg-border)] text-[var(--text-secondary)]" data-testid="discovery-toggle-btn">
            <MagnifyingGlass size={14} className="mr-1.5" /> {showDiscovery ? "Chiudi Scansione" : "Scansione Rete"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setShowAddDevice(!showAddDevice)}
            className="rounded-md text-xs h-8 border-[var(--bg-border)] text-[var(--text-secondary)]" data-testid="add-device-btn">
            <HardDrive size={14} className="mr-1.5" /> {showAddDevice ? "Chiudi" : "+ Dispositivo"}
          </Button>
        </div>
      </div>

      {/* Add Device Form */}
      {showAddDevice && (
        <div className="noc-panel p-4 space-y-3 animate-fade-in" data-testid="add-device-form">
          <p className="text-xs font-medium text-[var(--text-primary)]">Aggiungi dispositivo da monitorare</p>
          <div className="grid grid-cols-1 md:grid-cols-6 gap-2 items-end">
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Cliente *</label>
              <select value={addDeviceClientId} onChange={(e) => setAddDeviceClientId(e.target.value)}
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs" data-testid="select-client">
                <option value="">Seleziona...</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">IP *</label>
              <input type="text" value={newDevice.ip} onChange={(e) => setNewDevice({ ...newDevice, ip: e.target.value })}
                placeholder="192.168.1.3" className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="device-ip-input" />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Tipo</label>
              <select value={newDevice.monitor_type} onChange={(e) => {
                  const mt = e.target.value;
                  const isPrinter = mt === "printer";
                  setNewDevice({ ...newDevice, monitor_type: isPrinter ? "snmp" : mt, device_type: isPrinter ? "printer" : "network", community: (mt === "snmp" || isPrinter) ? "public" : "" });
                }}
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs" data-testid="device-type-select">
                <option value="snmp">SNMP</option>
                <option value="ping">Ping + HTTP</option>
                <option value="printer">Stampante SNMP</option>
              </select>
            </div>
            {(newDevice.monitor_type === "snmp" || newDevice.device_type === "printer") ? (
              <div>
                <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Community</label>
                <input type="text" value={newDevice.community} onChange={(e) => setNewDevice({ ...newDevice, community: e.target.value })}
                  className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="device-community-input" />
              </div>
            ) : (
              <div>
                <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Porta HTTP</label>
                <input type="number" value={newDevice.http_port} onChange={(e) => setNewDevice({ ...newDevice, http_port: parseInt(e.target.value) || 80 })}
                  className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="device-http-port-input" />
              </div>
            )}
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Nome</label>
              <input type="text" value={newDevice.name} onChange={(e) => setNewDevice({ ...newDevice, name: e.target.value })}
                placeholder="Switch Reception" className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="device-name-input" />
            </div>
            <Button onClick={addDevice} size="sm" className="rounded-md text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white" data-testid="confirm-add-device-btn">Conferma</Button>
          </div>
        </div>
      )}

      {/* Network Discovery */}
      {showDiscovery && (
        <div className="noc-panel p-4 space-y-3 animate-fade-in" data-testid="discovery-panel">
          <p className="text-xs font-medium text-[var(--text-primary)]">Auto-Discovery Rete</p>
          <p className="text-[11px] text-[var(--text-muted)]">Scansiona la rete del cliente per trovare dispositivi attivi.</p>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Cliente *</label>
              <select value={discoveryClientId} onChange={(e) => onDiscoveryClientChange(e.target.value)}
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs" data-testid="discovery-client-select">
                <option value="">Seleziona...</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Subnet</label>
              <input type="text" value={discoverySubnet} onChange={(e) => setDiscoverySubnet(e.target.value)}
                placeholder="auto-detect" className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="discovery-subnet-input" />
            </div>
            <Button onClick={startDiscovery} disabled={scanning || !discoveryClientId} size="sm"
              className="rounded-md text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50" data-testid="start-discovery-btn">
              <MagnifyingGlass size={14} className="mr-1.5" /> {scanning ? "In corso..." : "Avvia Scansione"}
            </Button>
            {scanning && (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
                <span className="text-[11px] text-indigo-400">In attesa...</span>
              </div>
            )}
          </div>
          {discoveryResults?.devices?.length > 0 && (
            <div className="mt-3 space-y-1" data-testid="discovery-results">
              <p className="text-xs font-medium text-[var(--text-primary)] mb-2">
                {discoveryResults.devices.length} dispositivi trovati
                {discoveryResults.scanned_at && <span className="text-[var(--text-muted)] font-normal ml-2">({formatLastSeen(discoveryResults.scanned_at)})</span>}
              </p>
              <div className="max-h-64 overflow-y-auto space-y-1 pr-1">
                {discoveryResults.devices.map((dev, i) => {
                  const isManaged = discoveryResults.managed_ips?.includes(dev.ip);
                  return (
                    <div key={i} className={`flex items-center gap-3 p-2 rounded-lg border ${isManaged ? "border-[var(--low-border)] bg-[var(--low-bg)]" : "border-[var(--bg-border)] bg-[var(--bg-panel)] hover:bg-[var(--bg-hover)]"} transition-colors`}>
                      <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${isManaged ? "text-[var(--ok)]" : "text-[var(--text-muted)]"}`}>
                        {dev.device_type === "switch/router" || dev.device_type === "network-device" ? <WifiIcon size={14} /> : dev.device_type?.includes("server") ? <Desktop size={14} /> : <Globe size={14} />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-mono text-xs font-bold text-[var(--text-primary)]">{dev.ip}</p>
                          {dev.hostname && <p className="text-[11px] text-[var(--text-secondary)] truncate">{dev.hostname}</p>}
                          <span className="text-[10px] px-1.5 py-0.5 rounded border text-[var(--text-muted)] border-[var(--bg-border)]">{dev.ping_ms}ms</span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          {(dev.open_ports || []).map((p, pi) => (
                            <span key={pi} className="text-[9px] px-1 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)] font-mono">{p.service || p.port}</span>
                          ))}
                          <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${dev.suggested_type === "snmp" ? "text-blue-400 bg-blue-500/10" : "text-indigo-400 bg-indigo-500/10"}`}>
                            {dev.suggested_type === "snmp" ? "SNMP" : "PING"}
                          </span>
                        </div>
                      </div>
                      {isManaged ? (
                        <span className="text-[10px] text-[var(--ok)] flex items-center gap-1 flex-shrink-0"><CheckCircle size={12} weight="fill" /> Monitorato</span>
                      ) : (
                        <Button onClick={() => addDiscoveredDevice(dev)} size="sm" variant="outline"
                          className="rounded-md text-[10px] h-7 px-2 border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10 flex-shrink-0">
                          <Plus size={12} className="mr-1" /> Aggiungi
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Client Device Groups */}
      {loading ? (
        <div className="noc-panel p-8 text-center text-[var(--text-muted)] text-sm">Caricamento...</div>
      ) : clientGroups.length === 0 ? (
        <div className="noc-panel p-8 text-center" data-testid="no-data">
          <HardDrive size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-[var(--text-secondary)] text-sm mb-1">Nessun dispositivo monitorato</p>
          <p className="text-[var(--text-muted)] text-xs">Aggiungi dispositivi o installa un connettore</p>
        </div>
      ) : viewMode === "map" ? (
        <NetworkMap
          clientGroups={clientGroups}
          onDeviceSelect={(dev) => setExpandedDevice(expandedDevice === `map-${dev.device_ip}` ? null : `map-${dev.device_ip}`)}
        />
      ) : (
        <div className="space-y-3">
          {clientGroups.map((group) => {
            const collapsed = collapsedClients[group.clientId];
            const devOk = group.devices.filter(d => d.reachable).length;
            const devKo = group.devices.length - devOk;

            return (
              <div key={group.clientId} className="noc-panel overflow-hidden" data-testid={`client-group-${group.clientId}`}>
                <div className="p-3 flex items-center gap-3 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors border-b border-[var(--bg-border)]"
                  onClick={() => toggleClient(group.clientId)}>
                  {collapsed ? <CaretRight size={14} className="text-[var(--text-muted)]" /> : <CaretDown size={14} className="text-[var(--text-muted)]" />}
                  <div className="w-8 h-8 rounded-lg bg-indigo-600/10 flex items-center justify-center flex-shrink-0">
                    <Buildings size={16} className="text-indigo-400" />
                  </div>
                  <p className="font-heading font-bold text-sm text-[var(--text-primary)] flex-1">{group.clientName}</p>
                  <div className="flex items-center gap-2 text-[10px]">
                    <span className="font-mono text-[var(--text-muted)]">{group.devices.length} disp</span>
                    {group.connectorOnline && <span className="px-1.5 py-0.5 rounded border text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]">Conn ON</span>}
                    {!group.connectorOnline && <span className="px-1.5 py-0.5 rounded border text-[var(--text-muted)] bg-[var(--bg-hover)] border-[var(--bg-border)]">Conn OFF</span>}
                    {devOk > 0 && <span className="px-1.5 py-0.5 rounded border text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]">{devOk} OK</span>}
                    {devKo > 0 && <span className="px-1.5 py-0.5 rounded border text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]">{devKo} KO</span>}
                  </div>
                </div>

                {!collapsed && (
                  <div className="divide-y divide-[var(--bg-border)]">
                    <div className="px-3 pt-2 pb-1 flex items-center justify-between">
                      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest pl-3">Dispositivi Monitorati</p>
                      <div className="flex items-center gap-1">
                        <button onClick={() => exportDevices(group.clientName, group.devices)}
                          className="h-6 px-2 rounded flex items-center gap-1 text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
                          data-testid={`export-devices-${group.clientId}`}>
                          <Export size={11} /> Esporta
                        </button>
                        <button onClick={() => { setImportClientId(group.clientId); importFileRef.current?.click(); }}
                          className="h-6 px-2 rounded flex items-center gap-1 text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
                          data-testid={`import-devices-${group.clientId}`}>
                          <FileArrowUp size={11} /> Importa
                        </button>
                      </div>
                    </div>
                    {group.devices.map((dev, i) => {
                      const devKey = `${group.clientId}-${dev.device_ip}`;
                      const portStats = portsByStatus(dev.ports);
                      const expanded = expandedDevice === devKey;
                      const isPing = dev.monitor_type === "ping" || dev.monitor_type === "http";
                      return (
                        <div key={devKey}>
                          <div className="p-3 pl-8 flex items-center gap-3 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
                            onClick={() => setExpandedDevice(expanded ? null : devKey)}>
                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${dev.reachable ? "bg-[var(--low-bg)] border border-[var(--low-border)]" : "bg-[var(--critical-bg)] border border-[var(--critical-border)]"}`}>
                              {dev.reachable ? <WifiHigh size={16} weight="fill" className="text-[var(--ok)]" /> : <WifiSlash size={16} weight="fill" className="text-[var(--critical)]" />}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="font-heading font-bold text-xs text-[var(--text-primary)] truncate">{dev.device_name}</p>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded border cursor-pointer transition-colors ${isPing ? "text-indigo-400 bg-indigo-500/10 border-indigo-500/20 hover:bg-indigo-500/20" : "text-blue-400 bg-blue-500/10 border-blue-500/20 hover:bg-blue-500/20"}`}
                                  onClick={(e) => { e.stopPropagation(); switchMonitorType(dev.device_ip, isPing ? "ping" : "snmp"); }}
                                  title={`Clicca per cambiare a ${isPing ? "SNMP" : "Ping+HTTP"}`}
                                  data-testid={`switch-type-${dev.device_ip}`}>
                                  {isPing ? "PING" : "SNMP"}
                                </span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded border ${dev.reachable ? "text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]" : "text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]"}`}>
                                  {dev.reachable ? "OK" : "NON RAGGIUNGIBILE"}
                                </span>
                              </div>
                              <p className="font-mono text-[11px] text-[var(--text-muted)]">{dev.device_ip}</p>
                            </div>
                            {!isPing && portStats.total > 0 && (
                              <div className="hidden md:flex items-center gap-2">
                                <span className="text-xs font-mono text-[var(--ok)]">{portStats.up}<ArrowUp size={10} className="inline ml-0.5" /></span>
                                <span className="text-xs font-mono text-[var(--critical)]">{portStats.down}<ArrowDown size={10} className="inline ml-0.5" /></span>
                              </div>
                            )}
                            {isPing && dev.ping_ms != null && (
                              <div className="hidden md:flex items-center gap-2">
                                <span className="text-xs font-mono text-[var(--ok)]">{dev.ping_ms}ms</span>
                                {dev.http_status > 0 && <span className="text-xs font-mono text-indigo-400">HTTP {dev.http_status}</span>}
                              </div>
                            )}
                            <div className="text-right flex-shrink-0">
                              <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1 justify-end"><Clock size={10} /> Check</p>
                              <p className={`text-xs font-mono ${dev.reachable ? "text-[var(--ok)]" : "text-[var(--critical)]"}`}>{formatLastSeen(dev.last_poll)}</p>
                            </div>
                            <button onClick={(e) => { e.stopPropagation(); openWebConsole(group.clientId, dev.device_ip, dev.http_port || 80); }}
                              className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-indigo-400 hover:bg-indigo-500/10 transition-colors" title="Web Console"
                              data-testid={`web-console-${dev.device_ip}`}>
                              <Monitor size={14} />
                            </button>
                            {!isPing && portStats.total > 0 && (
                              <Link to={`/switch-ports/${encodeURIComponent(dev.device_ip)}`}
                                onClick={(e) => e.stopPropagation()}
                                className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-cyan-400 hover:bg-cyan-500/10 transition-colors"
                                title="Vedi porte switch (Up/Down/PoE/Uplink/LLDP)"
                                data-testid={`view-ports-${dev.device_ip}`}>
                                <StackIcon size={14} weight="bold" />
                              </Link>
                            )}
                            <button onClick={(e) => { e.stopPropagation(); setDeleteTarget(dev.device_ip); }}
                              className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] transition-colors" title="Elimina"
                              data-testid={`delete-device-${dev.device_ip}`}>
                              <Trash size={14} />
                            </button>
                          </div>
                          {/* Conferma eliminazione */}
                          {deleteTarget === dev.device_ip && (
                            <div className="flex items-center gap-2 px-8 py-2 bg-red-500/10 border-t border-red-500/20 animate-fade-in" onClick={e => e.stopPropagation()}>
                              <span className="text-xs text-red-400">Eliminare {dev.device_name || dev.device_ip}?</span>
                              <button onClick={() => deleteDevice(dev.device_ip)}
                                className="px-3 py-1 rounded text-[10px] font-bold bg-red-600 text-white hover:bg-red-700 transition-colors"
                                data-testid={`confirm-delete-${dev.device_ip}`}>
                                Elimina
                              </button>
                              <button onClick={() => setDeleteTarget(null)}
                                className="px-3 py-1 rounded text-[10px] font-medium bg-zinc-700 text-zinc-300 hover:bg-zinc-600 transition-colors"
                                data-testid={`cancel-delete-${dev.device_ip}`}>
                                Annulla
                              </button>
                            </div>
                          )}
                          {expanded && (
                            <InlineDeviceDetail
                              clientId={group.clientId}
                              deviceIp={dev.device_ip}
                              deviceName={dev.device_name}
                              isPing={isPing}
                              onClose={() => setExpandedDevice(null)}
                              openWebConsole={openWebConsole}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <input ref={importFileRef} type="file" accept=".csv,.txt" onChange={handleImportDevices} className="hidden" data-testid="import-devices-file-input" />

      {/* Web Console Modal — Enterprise */}
      {webConsole && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3" data-testid="web-console-modal">
          <div className="absolute inset-0 bg-black/80 backdrop-blur-md" onClick={closeWebConsole}></div>
          <div className="relative w-full max-w-7xl h-[90vh] bg-[#0d0d12] rounded-xl border border-[#1e1e2e] shadow-2xl shadow-black/50 flex flex-col overflow-hidden">

            {/* Title Bar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#1e1e2e] bg-[#12121a] flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-red-500/80 cursor-pointer hover:bg-red-500" onClick={closeWebConsole}></div>
                  <div className="w-3 h-3 rounded-full bg-yellow-500/80"></div>
                  <div className="w-3 h-3 rounded-full bg-green-500/80"></div>
                </div>
                <Monitor size={15} className="text-indigo-400 ml-2" />
                <span className="text-[11px] font-bold text-white/90">Web Console</span>
              </div>
              <div className="flex items-center gap-2">
                {!webConsole.loading && webConsole.loadTime && (
                  <span className="text-[9px] text-white/30 font-mono">{(webConsole.loadTime / 1000).toFixed(1)}s</span>
                )}
                <button onClick={closeWebConsole} className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors">
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* URL Bar */}
            <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
              <button onClick={() => openWebConsole(webConsole.clientId, webConsole.deviceIp, webConsole.port, webConsole.path)}
                className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors" title="Ricarica">
                <ArrowClockwise size={13} />
              </button>
              <div className="flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#1a1a26] border border-[#2a2a3e]">
                <Globe size={12} className="text-white/30 flex-shrink-0" />
                <span className="text-[11px] text-white/60 font-mono truncate">
                  http://{webConsole.deviceIp}:{webConsole.port}{webConsole.path}
                </span>
                {webConsole.loading && <CircleNotch size={12} className="text-indigo-400 animate-spin ml-auto flex-shrink-0" />}
                {!webConsole.loading && !webConsole.error && <ShieldCheck size={12} className="text-emerald-400 ml-auto flex-shrink-0" />}
              </div>
              <span className="text-[9px] px-2 py-1 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold whitespace-nowrap">
                via Connector
              </span>
            </div>

            {/* Progress Bar */}
            {webConsole.loading && (
              <div className="h-0.5 bg-[#1e1e2e] flex-shrink-0">
                <div className="h-full bg-indigo-500 transition-all duration-500 ease-out" style={{ width: `${webConsole.progress || 0}%` }}></div>
              </div>
            )}

            {/* Content Area */}
            <div className="flex-1 bg-white overflow-auto">
              {webConsole.loading ? (
                <div className="flex flex-col items-center justify-center h-full gap-4 bg-[#0d0d12]">
                  <div className="relative">
                    <div className="w-12 h-12 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin"></div>
                    <Monitor size={20} className="text-indigo-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
                  </div>
                  <div className="text-center">
                    <p className="text-white/70 text-sm font-medium">Connessione in corso...</p>
                    <p className="text-white/30 text-xs mt-1">{webConsole.deviceIp}:{webConsole.port}{webConsole.path}</p>
                    <p className="text-white/20 text-[10px] mt-2 font-mono">Proxy tramite 86NocConnector</p>
                  </div>
                </div>
              ) : webConsole.error ? (
                <div className="flex items-center justify-center h-full bg-[#0d0d12] p-8">
                  <div className="text-center max-w-md">
                    <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                      <Warning size={28} className="text-red-400" />
                    </div>
                    <p className="text-red-400 font-bold text-lg mb-2">Connessione Fallita</p>
                    <p className="text-white/40 text-sm">{webConsole.error}</p>
                    <button onClick={() => openWebConsole(webConsole.clientId, webConsole.deviceIp, webConsole.port, webConsole.path)}
                      className="mt-4 px-4 py-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-xs font-bold hover:bg-indigo-500/20 transition-colors">
                      Riprova
                    </button>
                  </div>
                </div>
              ) : (
                <iframe srcDoc={webConsole.html} className="w-full h-full border-0" title="Web Console" sandbox="allow-same-origin" />
              )}
            </div>

            {/* Status Bar */}
            <div className="flex items-center justify-between px-3 py-1 border-t border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
              <div className="flex items-center gap-3">
                <span className="text-[9px] text-white/30 font-mono">{webConsole.deviceIp}</span>
                {webConsole.title && webConsole.title !== `${webConsole.deviceIp}:${webConsole.port}` && (
                  <span className="text-[9px] text-white/20">{webConsole.title}</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full ${webConsole.loading ? "bg-amber-400 animate-pulse" : webConsole.error ? "bg-red-400" : "bg-emerald-400"}`}></span>
                <span className="text-[9px] text-white/30">{webConsole.loading ? "Caricamento..." : webConsole.error ? "Errore" : "Connesso"}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function InlineDeviceDetail({ clientId, deviceIp, deviceName, isPing, onClose, openWebConsole }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!clientId || !deviceIp) return;
    setLoading(true);
    axios.get(`${API}/network/device-detail/${clientId}/${deviceIp}`)
      .then(res => setDetail(res.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [clientId, deviceIp]);

  if (loading) {
    return (
      <div className="bg-[var(--bg-card)] border-t border-[var(--bg-border)] px-8 py-4 animate-pulse">
        <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
          <SpinnerGap size={14} className="animate-spin" /> Caricamento dettagli...
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="bg-[var(--bg-card)] border-t border-[var(--bg-border)] px-8 py-4">
        <p className="text-xs text-[var(--text-muted)]">Nessun dato disponibile</p>
      </div>
    );
  }

  const dev = detail.device || {};
  const alerts = detail.alerts || [];
  const portSpeeds = detail.port_speeds || [];
  const endpoints = detail.connected_endpoints || [];
  const lldp = detail.lldp_neighbors || [];
  const macs = detail.mac_connections || [];
  const highSpeedPorts = portSpeeds.filter(p => p.speed_mbps >= 10000);

  return (
    <div className="bg-[var(--bg-deep)] border-t border-[var(--bg-border)] px-8 py-4 animate-fade-in" data-testid={`inline-detail-${deviceIp}`}>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Info */}
        <div className="space-y-2">
          <h4 className="text-[10px] text-indigo-400 uppercase tracking-widest font-semibold">Informazioni</h4>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Stato</span>
              <span className={dev.reachable ? "text-emerald-400" : "text-red-400"}>{dev.reachable ? "Online" : "Offline"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Monitor</span>
              <span className="text-[var(--text-primary)] font-mono">{dev.monitor_type?.toUpperCase() || (isPing ? "PING" : "SNMP")}</span>
            </div>
            {dev.ping_ms != null && (
              <div className="flex justify-between">
                <span className="text-[var(--text-muted)]">Latenza</span>
                <span className={`font-mono ${dev.ping_ms < 10 ? "text-emerald-400" : dev.ping_ms < 50 ? "text-amber-400" : "text-red-400"}`}>{dev.ping_ms} ms</span>
              </div>
            )}
            {dev.sys_descr && (
              <div>
                <span className="text-[var(--text-muted)] text-[10px]">System</span>
                <p className="text-[var(--text-secondary)] text-[10px] mt-0.5 break-all">{dev.sys_descr}</p>
              </div>
            )}
          </div>
          <button onClick={() => openWebConsole ? openWebConsole(clientId, deviceIp, 80) : window.open(`http://${deviceIp}`, "_blank")}
            className="mt-2 w-full h-7 rounded-md text-[10px] font-medium bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-600/30 transition-colors flex items-center justify-center gap-1"
            data-testid={`open-web-${deviceIp}`}>
            <Globe size={12} /> Apri Pagina Web (via Connettore)
          </button>
        </div>

        {/* Alert + Porte */}
        <div className="space-y-2">
          <h4 className="text-[10px] text-indigo-400 uppercase tracking-widest font-semibold">
            Alert <span className="ml-1 text-[var(--text-muted)]">({alerts.length})</span>
          </h4>
          {alerts.length === 0 ? (
            <p className="text-[10px] text-[var(--text-muted)]">Nessun alert</p>
          ) : (
            <div className="space-y-1 max-h-[120px] overflow-y-auto">
              {alerts.slice(0, 5).map((a, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[10px]">
                  <span className={`w-1.5 h-1.5 rounded-full ${a.severity === "critical" ? "bg-red-400" : a.severity === "high" ? "bg-orange-400" : "bg-amber-400"}`} />
                  <span className="text-[var(--text-secondary)] truncate">{a.title}</span>
                </div>
              ))}
            </div>
          )}
          {highSpeedPorts.length > 0 && (
            <div className="mt-2">
              <h4 className="text-[10px] text-indigo-400 uppercase tracking-widest font-semibold">
                Porte High-Speed <span className="ml-1 text-[var(--text-muted)]">({highSpeedPorts.length})</span>
              </h4>
              <div className="flex flex-wrap gap-1 mt-1">
                {highSpeedPorts.map((p, i) => (
                  <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400 border border-orange-500/20 font-mono">
                    Port {p.port || p.port_name || p.port_id || i+1} {Math.round(p.speed_mbps / 1000)}G
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Endpoint Connessi */}
        <div className="space-y-2">
          <h4 className="text-[10px] text-indigo-400 uppercase tracking-widest font-semibold">
            Endpoint Connessi <span className="ml-1 text-[var(--text-muted)]">({endpoints.length})</span>
          </h4>
          {endpoints.length === 0 ? (
            <p className="text-[10px] text-[var(--text-muted)]">Nessun endpoint</p>
          ) : (
            <div className="space-y-1 max-h-[150px] overflow-y-auto">
              {endpoints.map((ep, i) => (
                <div key={i} className="flex items-center justify-between text-[10px] py-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${ep.reachable !== false ? "bg-emerald-400" : "bg-zinc-500"}`} />
                    <span className="text-[var(--text-primary)]">{ep.hostname || ep.name || "?"}</span>
                  </div>
                  <span className="text-[var(--text-muted)] font-mono">{ep.ip || ""}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* LLDP + MAC */}
        <div className="space-y-2">
          {lldp.length > 0 && (
            <div>
              <h4 className="text-[10px] text-indigo-400 uppercase tracking-widest font-semibold">
                LLDP Neighbors <span className="ml-1 text-[var(--text-muted)]">({lldp.length})</span>
              </h4>
              <div className="space-y-1 mt-1">
                {lldp.map((l, i) => (
                  <div key={i} className="text-[10px] text-[var(--text-secondary)]">
                    {l.remote_sys_name || l.remote_port_desc || l.remote_mgmt_ip || "N/A"}
                    {l.local_port && <span className="text-[var(--text-muted)] ml-1">via {l.local_port}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {macs.length > 0 && (
            <div>
              <h4 className="text-[10px] text-indigo-400 uppercase tracking-widest font-semibold">
                Connessioni MAC <span className="ml-1 text-[var(--text-muted)]">({macs.length})</span>
              </h4>
              <div className="space-y-1 mt-1 max-h-[120px] overflow-y-auto">
                {macs.map((m, i) => (
                  <div key={i} className="flex items-center justify-between text-[10px]">
                    <span className="font-mono text-[var(--text-muted)]">{m.mac}</span>
                    <span className="text-[var(--text-secondary)]">{m.port || ""}</span>
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
