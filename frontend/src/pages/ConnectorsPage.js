import { useState, useEffect, useRef } from "react";
import axios from "axios";
import JSZip from "jszip";
import { API } from "@/App";
import { 
  HardDrive, 
  ArrowClockwise,
  SealCheck,
  Warning,
  Clock,
  WifiHigh,
  WifiSlash,
  DownloadSimple,
  Copy,
  CheckCircle,
  Terminal,
  NumberCircleOne,
  NumberCircleTwo,
  NumberCircleThree,
  UploadSimple,
  ArrowsClockwise,
  CloudArrowUp,
  Trash,
  Buildings,
  CaretDown,
  CaretRight,
  ArrowUp,
  ArrowDown
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState([]);
  const [devices, setDevices] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showInstall, setShowInstall] = useState(false);
  const [copied, setCopied] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [newVersion, setNewVersion] = useState("");
  const [changelog, setChangelog] = useState("");
  const [expandedDevice, setExpandedDevice] = useState(null);
  const [collapsedClients, setCollapsedClients] = useState({});
  const [showAddDevice, setShowAddDevice] = useState(false);
  const [newDevice, setNewDevice] = useState({ ip: "", community: "public", name: "" });
  const [addDeviceClientId, setAddDeviceClientId] = useState("");
  const intervalRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    fetchAll();
    fetchUpdateInfo();
    intervalRef.current = setInterval(fetchAll, 15000);
    return () => clearInterval(intervalRef.current);
  }, []);

  const fetchAll = async () => {
    try {
      const [connRes, devRes, clientRes] = await Promise.all([
        axios.get(`${API}/connector/status`),
        axios.get(`${API}/connector/device-poll-status`),
        axios.get(`${API}/clients`)
      ]);
      setConnectors(connRes.data);
      setDevices(devRes.data);
      setClients(clientRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchUpdateInfo = async () => {
    try {
      const res = await axios.get(`${API}/connector/update-info`);
      setUpdateInfo(res.data);
    } catch (error) {
      console.error("Error fetching update info:", error);
    }
  };

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const zip = await JSZip.loadAsync(file);
      const versionFile = zip.file("version.json");
      if (versionFile) {
        const content = await versionFile.async("string");
        const meta = JSON.parse(content);
        if (meta.version) setNewVersion(meta.version);
        if (meta.changelog) setChangelog(meta.changelog);
        toast.success(`Rilevato version.json: v${meta.version}`);
      }
    } catch (err) {
      console.warn("Impossibile leggere version.json dal zip:", err);
    }
  };

  const handleUploadUpdate = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file || !newVersion) {
      toast.error("Seleziona un file ZIP e inserisci la versione");
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("version", newVersion);
      formData.append("changelog", changelog);
      await axios.post(`${API}/connector/upload-update`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      toast.success(`Aggiornamento v${newVersion} pubblicato! I connector si aggiorneranno entro 6 ore.`);
      setNewVersion("");
      setChangelog("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      fetchUpdateInfo();
    } catch (error) {
      toast.error("Errore upload: " + (error.response?.data?.detail || error.message));
    } finally {
      setUploading(false);
    }
  };

  const deleteConnector = async (hostname) => {
    if (!window.confirm(`Eliminare il connettore "${hostname}"?`)) return;
    try {
      await axios.delete(`${API}/connector/status/${encodeURIComponent(hostname)}`);
      toast.success("Connettore eliminato");
      fetchAll();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const deleteDevice = async (deviceIp) => {
    if (!window.confirm(`Eliminare il dispositivo ${deviceIp} dal monitoraggio?`)) return;
    try {
      await axios.delete(`${API}/connector/device-poll-status/${encodeURIComponent(deviceIp)}`);
      toast.success("Dispositivo rimosso");
      fetchAll();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const addDevice = async () => {
    if (!newDevice.ip || !addDeviceClientId) {
      toast.error("Seleziona un cliente e inserisci l'IP");
      return;
    }
    try {
      await axios.post(`${API}/connector/${addDeviceClientId}/managed-devices`, {
        ip: newDevice.ip,
        community: newDevice.community || "public",
        name: newDevice.name || newDevice.ip
      });
      toast.success(`Dispositivo ${newDevice.name || newDevice.ip} aggiunto`);
      setNewDevice({ ip: "", community: "public", name: "" });
      setShowAddDevice(false);
      fetchAll();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const toggleClient = (id) => setCollapsedClients(prev => ({ ...prev, [id]: !prev[id] }));

  const isOnline = (lastSeen) => {
    if (!lastSeen) return false;
    return (Date.now() - new Date(lastSeen).getTime()) < 120000;
  };

  const isRecentPoll = (ts) => {
    if (!ts) return false;
    return (Date.now() - new Date(ts).getTime()) < 180000;
  };

  const formatUptime = (seconds) => {
    if (!seconds) return "N/A";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}g ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  };

  const formatLastSeen = (ts) => {
    if (!ts) return "Mai";
    const d = new Date(ts);
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 60000) return "Adesso";
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m fa`;
    if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}h fa`;
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  const onlineCount = connectors.filter(c => isOnline(c.last_seen)).length;
  const offlineCount = connectors.length - onlineCount;

  // Build unified client groups
  const clientGroups = (() => {
    const groups = {};
    // Add clients from list
    clients.forEach(c => {
      groups[c.id] = { clientId: c.id, clientName: c.name, connectors: [], devices: [] };
    });
    // Add connectors
    connectors.forEach(c => {
      const cid = c.client_id || "unknown";
      if (!groups[cid]) groups[cid] = { clientId: cid, clientName: c.client_name || "Sconosciuto", connectors: [], devices: [] };
      groups[cid].connectors.push(c);
    });
    // Add devices
    devices.forEach(d => {
      const cid = d.client_id || "unknown";
      if (!groups[cid]) groups[cid] = { clientId: cid, clientName: cid, connectors: [], devices: [] };
      groups[cid].devices.push(d);
    });
    // Only return groups that have connectors or devices
    return Object.values(groups)
      .filter(g => g.connectors.length > 0 || g.devices.length > 0)
      .sort((a, b) => a.clientName.localeCompare(b.clientName));
  })();

  const portsByStatus = (ports) => {
    const up = (ports || []).filter(p => p.status === "up").length;
    const down = (ports || []).filter(p => p.status === "down").length;
    return { up, down, total: (ports || []).length };
  };

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="connectors-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">
            Connettori
          </h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">
            Stato degli agent 86NocConnector installati
          </p>
        </div>
        <Button 
          variant="outline" 
          size="sm" 
          onClick={() => { fetchAll(); toast.success("Aggiornato"); }}
          className="rounded-md text-xs h-8 border-[var(--bg-border)] text-[var(--text-secondary)]"
          data-testid="refresh-connectors-btn"
        >
          <ArrowClockwise size={14} className="mr-1.5" />
          Aggiorna
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className="noc-panel p-3 flex items-center gap-3">
          <HardDrive size={18} className="text-[var(--text-muted)]" />
          <div>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Totale</p>
            <p className="font-heading text-lg font-bold text-[var(--text-primary)]">{connectors.length}</p>
          </div>
        </div>
        <div className="noc-panel p-3 flex items-center gap-3">
          <WifiHigh size={18} className="text-[var(--ok)]" />
          <div>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Online</p>
            <p className="font-heading text-lg font-bold text-[var(--ok)]">{onlineCount}</p>
          </div>
        </div>
        <div className="noc-panel p-3 flex items-center gap-3">
          <WifiSlash size={18} className="text-[var(--critical)]" />
          <div>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Offline</p>
            <p className="font-heading text-lg font-bold text-[var(--critical)]">{offlineCount}</p>
          </div>
        </div>
      </div>

      {/* Download & Install Section */}
      <div className="noc-panel overflow-hidden" data-testid="download-connector-section">
        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center flex-shrink-0">
              <DownloadSimple size={20} weight="bold" className="text-indigo-400" />
            </div>
            <div>
              <p className="font-heading font-bold text-sm text-[var(--text-primary)]">
                86NocConnector
              </p>
              <p className="text-[var(--text-muted)] text-xs">
                Pacchetto Windows nativo — nessuna installazione richiesta
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowInstall(!showInstall)}
              className="rounded-md text-xs h-8 text-[var(--text-secondary)]"
              data-testid="toggle-install-guide-btn"
            >
              {showInstall ? "Nascondi guida" : "Guida installazione"}
            </Button>
            <a href="/86NocConnector.zip" download>
              <Button
                size="sm"
                className="rounded-md text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white"
                data-testid="download-connector-btn"
              >
                <DownloadSimple size={14} className="mr-1.5" />
                Scarica ZIP
              </Button>
            </a>
          </div>
        </div>

        {showInstall && (
          <div className="border-t border-[var(--bg-border)] p-4 space-y-4 bg-[var(--bg-card)]/50 animate-fade-in">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <StepCard
                number={1}
                title="Scarica e decomprimi"
                desc="Scarica il file ZIP e decomprimilo su un server Windows del cliente."
              />
              <StepCard
                number={2}
                title="Esegui l'installer"
                desc={<>Doppio click su <code className="text-indigo-400 bg-indigo-500/10 px-1 rounded text-[11px]">Installa 86NocConnector.vbs</code> e segui il wizard.</>}
              />
              <StepCard
                number={3}
                title="Configura connessione"
                desc="Inserisci l'URL del NOC Center e la API Key del cliente. Testa la connessione."
              />
            </div>

            <div className="noc-panel p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">
                  API Key — Come trovarla
                </p>
              </div>
              <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                Vai nella pagina <strong className="text-[var(--text-primary)]">Clienti</strong>, seleziona il cliente e copia la <strong className="text-[var(--text-primary)]">API Key</strong> generata automaticamente. Questa chiave autentica il connector per inviare alert al NOC Center.
              </p>
            </div>

            <div className="flex items-start gap-2 p-3 rounded-lg border border-[var(--medium-border)] bg-[var(--medium-bg)]">
              <Terminal size={16} className="text-[var(--medium)] mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-xs text-[var(--medium)] font-medium mb-0.5">Requisiti</p>
                <p className="text-[11px] text-[var(--text-secondary)]">
                  Windows Server 2016+ o Windows 10/11 — PowerShell 5.1 (preinstallato) — Porte UDP 162 (SNMP) e 514 (Syslog) libere
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Auto-Update Management */}
      <div className="noc-panel overflow-hidden" data-testid="update-management-section">
        <div className="p-4">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center flex-shrink-0">
              <ArrowsClockwise size={20} weight="bold" className="text-emerald-400" />
            </div>
            <div className="flex-1">
              <p className="font-heading font-bold text-sm text-[var(--text-primary)]">
                Aggiornamento Automatico
              </p>
              <p className="text-[var(--text-muted)] text-xs">
                {updateInfo?.version 
                  ? `Versione attuale: v${updateInfo.version} — ${updateInfo.updated_connectors || 0}/${updateInfo.total_connectors || 0} aggiornati`
                  : "Nessun aggiornamento pubblicato"
                }
              </p>
            </div>
            {updateInfo?.pending_connectors > 0 && (
              <span className="text-[10px] px-2 py-1 rounded border text-[var(--medium)] bg-[var(--medium-bg)] border-[var(--medium-border)]">
                {updateInfo.pending_connectors} in attesa
              </span>
            )}
          </div>

          {/* Upload new version */}
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-end">
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Versione *</label>
              <input
                type="text"
                placeholder="es. 1.1.0"
                value={newVersion}
                onChange={(e) => setNewVersion(e.target.value)}
                className="w-full h-9 px-3 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono focus:outline-none focus:border-indigo-500"
                data-testid="update-version-input"
              />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">File ZIP</label>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                onChange={handleFileSelect}
                className="w-full h-9 text-xs text-[var(--text-secondary)] file:mr-2 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-[var(--bg-hover)] file:text-[var(--text-primary)] file:cursor-pointer"
                data-testid="update-file-input"
              />
            </div>
            <Button
              onClick={handleUploadUpdate}
              disabled={uploading || !newVersion}
              size="sm"
              className="rounded-md text-xs h-9 bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
              data-testid="publish-update-btn"
            >
              <CloudArrowUp size={14} className="mr-1.5" />
              {uploading ? "Caricamento..." : "Pubblica"}
            </Button>
          </div>

          <div className="mt-3">
            <input
              type="text"
              placeholder="Changelog (opzionale) — es. Fix polling HPE 1820, miglioramenti stabilita'"
              value={changelog}
              onChange={(e) => setChangelog(e.target.value)}
              className="w-full h-8 px-3 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-secondary)] text-xs focus:outline-none focus:border-indigo-500"
              data-testid="update-changelog-input"
            />
          </div>

          {updateInfo?.published_at && (
            <p className="text-[10px] text-[var(--text-muted)] mt-2">
              Ultimo aggiornamento: v{updateInfo.version} pubblicato il {new Date(updateInfo.published_at).toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}
              {updateInfo.changelog && ` — ${updateInfo.changelog}`}
            </p>
          )}
        </div>
      </div>

      {/* Add Device Form */}
      {showAddDevice && (
        <div className="noc-panel p-4 space-y-3 animate-fade-in" data-testid="add-device-form">
          <p className="text-xs font-medium text-[var(--text-primary)]">Aggiungi dispositivo da monitorare</p>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end">
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Cliente *</label>
              <select value={addDeviceClientId} onChange={(e) => setAddDeviceClientId(e.target.value)}
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs" data-testid="select-client">
                <option value="">Seleziona...</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">IP Address *</label>
              <input type="text" value={newDevice.ip} onChange={(e) => setNewDevice({...newDevice, ip: e.target.value})}
                placeholder="192.168.1.2" className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="device-ip-input" />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Community</label>
              <input type="text" value={newDevice.community} onChange={(e) => setNewDevice({...newDevice, community: e.target.value})}
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="device-community-input" />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Nome</label>
              <input type="text" value={newDevice.name} onChange={(e) => setNewDevice({...newDevice, name: e.target.value})}
                placeholder="HPE 1820 48G" className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono" data-testid="device-name-input" />
            </div>
            <Button onClick={addDevice} size="sm" className="rounded-md text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white" data-testid="confirm-add-device-btn">
              Conferma
            </Button>
          </div>
        </div>
      )}

      {/* Unified Client Groups: Connectors + Devices together */}
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-sm font-bold text-[var(--text-primary)]">
          Stato per Cliente
        </h2>
        <Button variant="outline" size="sm" onClick={() => setShowAddDevice(!showAddDevice)}
          className="rounded-md text-xs h-8 border-[var(--bg-border)] text-[var(--text-secondary)]" data-testid="add-device-btn">
          <HardDrive size={14} className="mr-1.5" />
          {showAddDevice ? "Chiudi" : "+ Dispositivo"}
        </Button>
      </div>

      {loading ? (
        <div className="noc-panel p-8 text-center text-[var(--text-muted)] text-sm">Caricamento...</div>
      ) : clientGroups.length === 0 ? (
        <div className="noc-panel p-8 text-center" data-testid="no-data">
          <HardDrive size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-[var(--text-secondary)] text-sm mb-1">Nessun connettore o dispositivo</p>
          <p className="text-[var(--text-muted)] text-xs">Installa 86NocConnector o aggiungi dispositivi</p>
        </div>
      ) : (
        <div className="space-y-3">
          {clientGroups.map((group) => {
            const collapsed = collapsedClients[group.clientId];
            const connOnline = group.connectors.filter(c => isOnline(c.last_seen)).length;
            const connOffline = group.connectors.length - connOnline;
            const devOk = group.devices.filter(d => d.reachable && isRecentPoll(d.last_poll)).length;
            const devKo = group.devices.length - devOk;

            return (
              <div key={group.clientId} className="noc-panel overflow-hidden" data-testid={`client-group-${group.clientId}`}>
                {/* Client Header */}
                <div className="p-3 flex items-center gap-3 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors border-b border-[var(--bg-border)]"
                  onClick={() => toggleClient(group.clientId)}>
                  {collapsed ? <CaretRight size={14} className="text-[var(--text-muted)]" /> : <CaretDown size={14} className="text-[var(--text-muted)]" />}
                  <div className="w-8 h-8 rounded-lg bg-indigo-600/10 flex items-center justify-center flex-shrink-0">
                    <Buildings size={16} className="text-indigo-400" />
                  </div>
                  <p className="font-heading font-bold text-sm text-[var(--text-primary)] flex-1">{group.clientName}</p>
                  <div className="flex items-center gap-2 text-[10px]">
                    {group.connectors.length > 0 && (
                      <span className="font-mono text-[var(--text-muted)]">{group.connectors.length} conn</span>
                    )}
                    {group.devices.length > 0 && (
                      <span className="font-mono text-[var(--text-muted)]">{group.devices.length} disp</span>
                    )}
                    {connOnline > 0 && <span className="px-1.5 py-0.5 rounded border text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]">{connOnline} ON</span>}
                    {connOffline > 0 && <span className="px-1.5 py-0.5 rounded border text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]">{connOffline} OFF</span>}
                    {devOk > 0 && <span className="px-1.5 py-0.5 rounded border text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]">{devOk} OK</span>}
                    {devKo > 0 && <span className="px-1.5 py-0.5 rounded border text-[var(--medium)] bg-[var(--medium-bg)] border-[var(--medium-border)]">{devKo} KO</span>}
                  </div>
                </div>

                {!collapsed && (
                  <div className="divide-y divide-[var(--bg-border)]">
                    {/* Connectors */}
                    {group.connectors.length > 0 && (
                      <div className="px-3 pt-2 pb-1">
                        <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-1 pl-3">Connettori</p>
                      </div>
                    )}
                    {group.connectors.map((c, i) => {
                      const online = isOnline(c.last_seen);
                      return (
                        <div key={`conn-${i}`} className="p-3 pl-8 flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${online ? "bg-[var(--low-bg)] border border-[var(--low-border)]" : "bg-[var(--critical-bg)] border border-[var(--critical-border)]"}`}>
                            {online ? <SealCheck size={16} weight="fill" className="text-[var(--ok)]" /> : <Warning size={16} weight="fill" className="text-[var(--critical)]" />}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <p className="font-heading font-bold text-xs text-[var(--text-primary)] truncate">{c.hostname || "Server"}</p>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${online ? "text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]" : "text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]"}`}>
                                {online ? "ONLINE" : "OFFLINE"}
                              </span>
                            </div>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-x-3 gap-y-0.5 mt-1">
                              <InfoItem label="Versione" value={`v${c.connector_version || "?"}`} />
                              <InfoItem label="Uptime" value={formatUptime(c.uptime_seconds)} />
                              <InfoItem label="SNMP" value={c.traps_received || 0} />
                              <InfoItem label="Syslog" value={c.syslogs_received || 0} />
                            </div>
                          </div>
                          <div className="text-right flex-shrink-0">
                            <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1 justify-end"><Clock size={10} /> Visto</p>
                            <p className="text-xs font-mono text-[var(--text-secondary)]">{formatLastSeen(c.last_seen)}</p>
                          </div>
                          <button onClick={() => deleteConnector(c.hostname || c.client_name)}
                            className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] transition-colors" title="Elimina">
                            <Trash size={14} />
                          </button>
                        </div>
                      );
                    })}

                    {/* Devices */}
                    {group.devices.length > 0 && (
                      <div className="px-3 pt-2 pb-1">
                        <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-1 pl-3">Dispositivi Monitorati</p>
                      </div>
                    )}
                    {group.devices.map((dev, i) => {
                      const devKey = `${group.clientId}-${dev.device_ip}`;
                      const recent = isRecentPoll(dev.last_poll);
                      const portStats = portsByStatus(dev.ports);
                      const expanded = expandedDevice === devKey;
                      return (
                        <div key={devKey}>
                          <div className="p-3 pl-8 flex items-center gap-3 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
                            onClick={() => setExpandedDevice(expanded ? null : devKey)}>
                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${dev.reachable && recent ? "bg-[var(--low-bg)] border border-[var(--low-border)]" : "bg-[var(--critical-bg)] border border-[var(--critical-border)]"}`}>
                              {dev.reachable && recent ? <WifiHigh size={16} weight="fill" className="text-[var(--ok)]" /> : <WifiSlash size={16} weight="fill" className="text-[var(--critical)]" />}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="font-heading font-bold text-xs text-[var(--text-primary)] truncate">{dev.device_name}</p>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded border ${dev.reachable && recent ? "text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]" : "text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]"}`}>
                                  {dev.reachable && recent ? "OK" : "NON RAGGIUNGIBILE"}
                                </span>
                              </div>
                              <p className="font-mono text-[11px] text-[var(--text-muted)]">{dev.device_ip}</p>
                            </div>
                            {portStats.total > 0 && (
                              <div className="hidden md:flex items-center gap-2">
                                <span className="text-xs font-mono text-[var(--ok)]">{portStats.up}<ArrowUp size={10} className="inline ml-0.5" /></span>
                                <span className="text-xs font-mono text-[var(--critical)]">{portStats.down}<ArrowDown size={10} className="inline ml-0.5" /></span>
                                <span className="text-[10px] text-[var(--text-muted)]">{portStats.total}p</span>
                              </div>
                            )}
                            <div className="text-right flex-shrink-0">
                              <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1 justify-end"><Clock size={10} /> Check</p>
                              <p className={`text-xs font-mono ${recent ? "text-[var(--ok)]" : "text-[var(--critical)]"}`}>{formatLastSeen(dev.last_poll)}</p>
                            </div>
                            <button onClick={(e) => { e.stopPropagation(); deleteDevice(dev.device_ip); }}
                              className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] transition-colors" title="Elimina">
                              <Trash size={14} />
                            </button>
                          </div>
                          {expanded && (
                            <div className="border-t border-[var(--bg-border)] p-3 pl-8 bg-[var(--bg-card)]/50 animate-fade-in">
                              {dev.sys_descr && <p className="text-[11px] text-[var(--text-muted)] mb-1 truncate">{dev.sys_descr}</p>}
                              {dev.sys_uptime && <p className="text-[11px] text-[var(--text-muted)] mb-2">Uptime: {dev.sys_uptime}</p>}
                              {(dev.ports || []).length > 0 ? (
                                <>
                                  <div className="grid grid-cols-6 sm:grid-cols-8 md:grid-cols-12 gap-1.5">
                                    {(dev.ports || []).sort((a,b) => parseInt(a.index) - parseInt(b.index)).map((port, pi) => (
                                      <div key={pi} title={`Porta ${port.index}: ${port.status}`}
                                        className={`h-6 rounded flex items-center justify-center text-[9px] font-mono border ${
                                          port.status === "up" ? "bg-[var(--low-bg)] border-[var(--low-border)] text-[var(--ok)]"
                                          : port.status === "down" ? "bg-[var(--critical-bg)] border-[var(--critical-border)] text-[var(--critical)]"
                                          : "bg-[var(--bg-hover)] border-[var(--bg-border)] text-[var(--text-muted)]"
                                        }`}>{port.index}</div>
                                    ))}
                                  </div>
                                  <div className="flex items-center gap-2 mt-2">
                                    <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]"><div className="w-3 h-3 rounded bg-[var(--low-bg)] border border-[var(--low-border)]"></div>UP</span>
                                    <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]"><div className="w-3 h-3 rounded bg-[var(--critical-bg)] border border-[var(--critical-border)]"></div>DOWN</span>
                                  </div>
                                </>
                              ) : <p className="text-xs text-[var(--text-muted)]">Nessun dato porte</p>}
                            </div>
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
    </div>
  );
}

function InfoItem({ label, value }) {
  return (
    <div>
      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
      <p className="text-xs font-mono text-[var(--text-secondary)]">{value}</p>
    </div>
  );
}

function StepCard({ number, title, desc }) {
  return (
    <div className="flex gap-3 p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]">
      <div className="w-7 h-7 rounded-full bg-indigo-500/15 border border-indigo-500/25 flex items-center justify-center flex-shrink-0">
        <span className="text-indigo-400 font-heading font-bold text-xs">{number}</span>
      </div>
      <div>
        <p className="text-xs font-medium text-[var(--text-primary)] mb-0.5">{title}</p>
        <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">{desc}</p>
      </div>
    </div>
  );
}
