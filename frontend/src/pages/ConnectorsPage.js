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
  CloudArrowUp
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showInstall, setShowInstall] = useState(false);
  const [copied, setCopied] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [newVersion, setNewVersion] = useState("");
  const [changelog, setChangelog] = useState("");
  const intervalRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    fetchConnectors();
    fetchUpdateInfo();
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

  const fetchUpdateInfo = async () => {
    try {
      const res = await axios.get(`${API}/connector/update-info`);
      setUpdateInfo(res.data);
    } catch (error) {
      console.error("Error fetching update info:", error);
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
