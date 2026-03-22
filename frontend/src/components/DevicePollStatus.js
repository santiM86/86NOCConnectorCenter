import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { 
  HardDrive, 
  ArrowClockwise, 
  WifiHigh, 
  WifiSlash, 
  Clock, 
  Plus, 
  Trash,
  CircleDashed,
  ArrowUp,
  ArrowDown
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function DevicePollStatus() {
  const [devices, setDevices] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newDevice, setNewDevice] = useState({ ip: "", community: "public", name: "" });
  const [selectedClient, setSelectedClient] = useState("");
  const [expandedDevice, setExpandedDevice] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [pollRes, clientsRes] = await Promise.all([
        axios.get(`${API}/connector/device-poll-status`),
        axios.get(`${API}/clients`)
      ]);
      setDevices(pollRes.data);
      setClients(clientsRes.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const addDevice = async () => {
    if (!newDevice.ip || !selectedClient) {
      toast.error("Seleziona un cliente e inserisci l'IP");
      return;
    }
    try {
      await axios.post(`${API}/connector/${selectedClient}/managed-devices`, {
        ip: newDevice.ip,
        community: newDevice.community || "public",
        name: newDevice.name || newDevice.ip
      });
      toast.success(`Dispositivo ${newDevice.name || newDevice.ip} aggiunto. Il connector lo rileverà entro 10 cicli di polling.`);
      setNewDevice({ ip: "", community: "public", name: "" });
      setShowAdd(false);
      fetchData();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const removeDevice = async (clientId, deviceId) => {
    try {
      await axios.delete(`${API}/connector/${clientId}/managed-devices/${deviceId}`);
      toast.success("Dispositivo rimosso");
      fetchData();
    } catch (e) {
      toast.error("Errore rimozione");
    }
  };

  const removePolledDevice = async (deviceIp) => {
    if (!window.confirm(`Eliminare il dispositivo ${deviceIp} dal monitoraggio?`)) return;
    try {
      await axios.delete(`${API}/connector/device-poll-status/${encodeURIComponent(deviceIp)}`);
      toast.success("Dispositivo rimosso");
      fetchData();
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    }
  };

  const formatTime = (ts) => {
    if (!ts) return "Mai";
    const d = new Date(ts);
    const diff = Date.now() - d.getTime();
    if (diff < 60000) return "Adesso";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m fa`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h fa`;
    return d.toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  const isRecent = (ts) => {
    if (!ts) return false;
    return (Date.now() - new Date(ts).getTime()) < 180000; // 3 min
  };

  const portsByStatus = (ports) => {
    const up = ports.filter(p => p.status === "up").length;
    const down = ports.filter(p => p.status === "down").length;
    const other = ports.length - up - down;
    return { up, down, other, total: ports.length };
  };

  return (
    <div className="space-y-3" data-testid="device-poll-status">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center flex-shrink-0">
            <HardDrive size={20} weight="bold" className="text-blue-400" />
          </div>
          <div>
            <p className="font-heading font-bold text-sm text-[var(--text-primary)]">
              Stato Dispositivi Monitorati
            </p>
            <p className="text-[var(--text-muted)] text-xs">
              Stato in tempo reale da polling SNMP — {devices.length} dispositivi
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchData}
            className="rounded-md text-xs h-8 text-[var(--text-secondary)]"
            data-testid="refresh-poll-status-btn"
          >
            <ArrowClockwise size={14} className="mr-1" />
            Aggiorna
          </Button>
          <Button
            size="sm"
            onClick={() => setShowAdd(!showAdd)}
            className="rounded-md text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
            data-testid="add-device-btn"
          >
            <Plus size={14} className="mr-1" />
            Aggiungi
          </Button>
        </div>
      </div>

      {/* Add device form */}
      {showAdd && (
        <div className="noc-panel p-4 space-y-3 animate-fade-in" data-testid="add-device-form">
          <p className="text-xs font-medium text-[var(--text-primary)]">Aggiungi dispositivo da monitorare</p>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end">
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Cliente *</label>
              <select
                value={selectedClient}
                onChange={(e) => setSelectedClient(e.target.value)}
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs"
                data-testid="select-client"
              >
                <option value="">Seleziona...</option>
                {clients.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">IP Address *</label>
              <input
                type="text"
                value={newDevice.ip}
                onChange={(e) => setNewDevice({...newDevice, ip: e.target.value})}
                placeholder="192.168.1.2"
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono"
                data-testid="device-ip-input"
              />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Community</label>
              <input
                type="text"
                value={newDevice.community}
                onChange={(e) => setNewDevice({...newDevice, community: e.target.value})}
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono"
                data-testid="device-community-input"
              />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Nome</label>
              <input
                type="text"
                value={newDevice.name}
                onChange={(e) => setNewDevice({...newDevice, name: e.target.value})}
                placeholder="HPE 1820 48G"
                className="w-full h-8 px-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono"
                data-testid="device-name-input"
              />
            </div>
            <Button
              onClick={addDevice}
              size="sm"
              className="rounded-md text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
              data-testid="confirm-add-device-btn"
            >
              Conferma
            </Button>
          </div>
        </div>
      )}

      {/* Device list */}
      {loading ? (
        <div className="noc-panel p-6 text-center text-[var(--text-muted)] text-sm">Caricamento...</div>
      ) : devices.length === 0 ? (
        <div className="noc-panel p-6 text-center" data-testid="no-polled-devices">
          <CircleDashed size={28} className="mx-auto mb-2 text-[var(--text-muted)]" />
          <p className="text-[var(--text-secondary)] text-sm">Nessun dispositivo monitorato</p>
          <p className="text-[var(--text-muted)] text-xs mt-1">
            Aggiungi un dispositivo dal pulsante qui sopra oppure dall'installer del connector
          </p>
        </div>
      ) : (
        <div className="grid gap-2">
          {devices.map((dev, i) => {
            const recent = isRecent(dev.last_poll);
            const portStats = portsByStatus(dev.ports || []);
            const expanded = expandedDevice === i;

            return (
              <div key={i} className="noc-panel overflow-hidden" data-testid={`polled-device-${i}`}>
                <div 
                  className="p-3 flex items-center gap-3 cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
                  onClick={() => setExpandedDevice(expanded ? null : i)}
                >
                  {/* Status indicator */}
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    dev.reachable && recent
                      ? "bg-[var(--low-bg)] border border-[var(--low-border)]"
                      : "bg-[var(--critical-bg)] border border-[var(--critical-border)]"
                  }`}>
                    {dev.reachable && recent
                      ? <WifiHigh size={18} weight="fill" className="text-[var(--ok)]" />
                      : <WifiSlash size={18} weight="fill" className="text-[var(--critical)]" />
                    }
                  </div>

                  {/* Device info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-heading font-bold text-sm text-[var(--text-primary)] truncate">
                        {dev.device_name}
                      </p>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                        dev.reachable && recent
                          ? "text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]"
                          : "text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]"
                      }`}>
                        {dev.reachable && recent ? "OK" : "NON RAGGIUNGIBILE"}
                      </span>
                    </div>
                    <p className="font-mono text-xs text-[var(--text-muted)]">{dev.device_ip}</p>
                  </div>

                  {/* Port summary */}
                  {portStats.total > 0 && (
                    <div className="hidden md:flex items-center gap-3">
                      <div className="flex items-center gap-1">
                        <ArrowUp size={12} className="text-[var(--ok)]" />
                        <span className="text-xs font-mono text-[var(--ok)]">{portStats.up}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <ArrowDown size={12} className="text-[var(--critical)]" />
                        <span className="text-xs font-mono text-[var(--critical)]">{portStats.down}</span>
                      </div>
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {portStats.total} porte
                      </span>
                    </div>
                  )}

                  {/* Last check */}
                  <div className="text-right flex-shrink-0">
                    <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1 justify-end">
                      <Clock size={10} />
                      Ultimo check
                    </p>
                    <p className={`text-xs font-mono ${recent ? "text-[var(--ok)]" : "text-[var(--critical)]"}`}>
                      {formatTime(dev.last_poll)}
                    </p>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => { e.stopPropagation(); removePolledDevice(dev.device_ip); }}
                    className="flex-shrink-0 w-8 h-8 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] transition-colors"
                    title="Elimina dispositivo"
                    data-testid={`delete-polled-device-${i}`}
                  >
                    <Trash size={15} />
                  </button>
                </div>

                {/* Expanded port details */}
                {expanded && (
                  <div className="border-t border-[var(--bg-border)] p-3 bg-[var(--bg-card)]/50 animate-fade-in">
                    {dev.sys_descr && (
                      <p className="text-[11px] text-[var(--text-muted)] mb-2 truncate" title={dev.sys_descr}>
                        {dev.sys_descr}
                      </p>
                    )}
                    {dev.sys_uptime && (
                      <p className="text-[11px] text-[var(--text-muted)] mb-3">
                        Uptime switch: {dev.sys_uptime}
                      </p>
                    )}
                    {(dev.ports || []).length > 0 ? (
                      <div className="grid grid-cols-6 sm:grid-cols-8 md:grid-cols-12 gap-1.5">
                        {(dev.ports || []).sort((a,b) => parseInt(a.index) - parseInt(b.index)).map((port, pi) => (
                          <div
                            key={pi}
                            title={`Porta ${port.index}: ${port.status}`}
                            className={`h-7 rounded flex items-center justify-center text-[9px] font-mono border ${
                              port.status === "up"
                                ? "bg-[var(--low-bg)] border-[var(--low-border)] text-[var(--ok)]"
                                : port.status === "down"
                                ? "bg-[var(--critical-bg)] border-[var(--critical-border)] text-[var(--critical)]"
                                : "bg-[var(--bg-hover)] border-[var(--bg-border)] text-[var(--text-muted)]"
                            }`}
                          >
                            {port.index}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-[var(--text-muted)]">Nessun dato porte disponibile</p>
                    )}
                    <div className="flex items-center gap-2 mt-3">
                      <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
                        <div className="w-3 h-3 rounded bg-[var(--low-bg)] border border-[var(--low-border)]"></div> UP
                      </span>
                      <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
                        <div className="w-3 h-3 rounded bg-[var(--critical-bg)] border border-[var(--critical-border)]"></div> DOWN
                      </span>
                      <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
                        <div className="w-3 h-3 rounded bg-[var(--bg-hover)] border border-[var(--bg-border)]"></div> Altro
                      </span>
                    </div>
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
