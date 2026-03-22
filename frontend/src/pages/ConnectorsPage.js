import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { 
  HardDrive, 
  ArrowClockwise,
  SealCheck,
  Warning,
  Clock,
  WifiHigh,
  WifiSlash
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef(null);

  useEffect(() => {
    fetchConnectors();
    intervalRef.current = setInterval(fetchConnectors, 15000);
    return () => clearInterval(intervalRef.current);
  }, []);

  const fetchConnectors = async () => {
    try {
      const res = await axios.get(`${API}/connector/status`);
      setConnectors(res.data);
    } catch (error) {
      console.error("Error fetching connectors:", error);
    } finally {
      setLoading(false);
    }
  };

  const isOnline = (lastSeen) => {
    if (!lastSeen) return false;
    return (Date.now() - new Date(lastSeen).getTime()) < 120000;
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
          onClick={() => { fetchConnectors(); toast.success("Aggiornato"); }}
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

      {/* Connector list */}
      {loading ? (
        <div className="noc-panel p-8 text-center text-[var(--text-muted)] text-sm">
          Caricamento...
        </div>
      ) : connectors.length === 0 ? (
        <div className="noc-panel p-8 text-center" data-testid="no-connectors">
          <HardDrive size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-[var(--text-secondary)] text-sm mb-1">Nessun connettore registrato</p>
          <p className="text-[var(--text-muted)] text-xs">
            Installa 86NocConnector su un server client per vederlo qui
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {connectors.map((c, i) => {
            const online = isOnline(c.last_seen);
            return (
              <div key={i} className="noc-panel p-4" data-testid={`connector-card-${i}`}>
                <div className="flex items-start gap-3">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    online ? "bg-[var(--low-bg)] border border-[var(--low-border)]" : "bg-[var(--critical-bg)] border border-[var(--critical-border)]"
                  }`}>
                    {online 
                      ? <SealCheck size={20} weight="fill" className="text-[var(--ok)]" />
                      : <Warning size={20} weight="fill" className="text-[var(--critical)]" />
                    }
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <p className="font-heading font-bold text-sm text-[var(--text-primary)] truncate">
                        {c.client_name || "Sconosciuto"}
                      </p>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                        online 
                          ? "text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]" 
                          : "text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]"
                      }`}>
                        {online ? "ONLINE" : "OFFLINE"}
                      </span>
                    </div>
                    <p className="font-mono text-xs text-[var(--text-muted)] mb-2">{c.hostname}</p>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1.5">
                      <InfoItem label="Versione" value={`v${c.connector_version || "?"}`} />
                      <InfoItem label="Uptime" value={formatUptime(c.uptime_seconds)} />
                      <InfoItem label="SNMP Traps" value={c.traps_received || 0} />
                      <InfoItem label="Syslog" value={c.syslogs_received || 0} />
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1 justify-end">
                      <Clock size={10} />
                      Visto
                    </p>
                    <p className="text-xs font-mono text-[var(--text-secondary)]">
                      {formatLastSeen(c.last_seen)}
                    </p>
                  </div>
                </div>
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
