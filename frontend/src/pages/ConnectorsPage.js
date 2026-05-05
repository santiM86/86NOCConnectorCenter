import { useState, useEffect, useRef } from "react";
import axios from "axios";
import JSZip from "jszip";
import { API } from "@/App";
import {
  HardDrive, ArrowClockwise, SealCheck, Warning, Clock,
  WifiHigh, WifiSlash, DownloadSimple, Terminal,
  ArrowsClockwise, CloudArrowUp, Trash, CheckCircle, SpinnerGap
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showInstall, setShowInstall] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [newVersion, setNewVersion] = useState("");
  const [changelog, setChangelog] = useState("");
  const intervalRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    fetchAll();
    fetchUpdateInfo();
    intervalRef.current = setInterval(fetchAll, 5000);
    return () => clearInterval(intervalRef.current);
  }, []);

  // Adaptive polling: switch to fast polling (1.5s) when any update is in progress
  useEffect(() => {
    const hasActiveUpdate = connectors.some(
      c => c.update_status && !["completed", "error"].includes(c.update_status)
    );
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = setInterval(fetchAll, hasActiveUpdate ? 1500 : 5000);
    return () => clearInterval(intervalRef.current);
  }, [connectors.map(c => `${c.client_id}:${c.update_status}:${c.update_progress}`).join(",")]);

  const isNewerVersion = (published, current) => {
    const p = (published || "0.0.0").split(".").map(Number);
    const c = (current || "0.0.0").split(".").map(Number);
    for (let i = 0; i < 3; i++) {
      if ((p[i] || 0) > (c[i] || 0)) return true;
      if ((p[i] || 0) < (c[i] || 0)) return false;
    }
    return false;
  };

  const fetchAll = async () => {
    try {
      const [connRes, clientRes] = await Promise.all([
        axios.get(`${API}/connector/status`),
        axios.get(`${API}/clients`)
      ]);
      setConnectors(connRes.data);
      setClients(clientRes.data);
    } catch (error) {
      console.error("Error:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchUpdateInfo = async () => {
    try {
      const res = await axios.get(`${API}/connector/update-info`);
      setUpdateInfo(res.data);
    } catch {}
  };

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const zip = await JSZip.loadAsync(file);
      // Cerca version.json nella root o in qualsiasi sottocartella
      let versionFile = zip.file("version.json");
      if (!versionFile) {
        const allFiles = Object.keys(zip.files);
        const match = allFiles.find(f => f.endsWith("version.json"));
        if (match) versionFile = zip.file(match);
      }
      if (versionFile) {
        const content = await versionFile.async("string");
        const meta = JSON.parse(content.replace(/^\uFEFF/, "")); // Remove BOM if present
        if (meta.version) setNewVersion(meta.version);
        if (meta.changelog) setChangelog(meta.changelog);
        toast.success(`Rilevato: v${meta.version}`);
      } else {
        toast.info("version.json non trovato nello ZIP — inserisci la versione manualmente");
      }
    } catch (err) {
      console.warn("Impossibile leggere version.json:", err);
    }
  };

  const handleUploadUpdate = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file || !newVersion) { toast.error("Seleziona un file ZIP e inserisci la versione"); return; }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("version", newVersion);
      formData.append("changelog", changelog);
      await axios.post(`${API}/connector/upload-update`, formData, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Aggiornamento v${newVersion} pubblicato!`);
      setNewVersion(""); setChangelog("");
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

  const forceUpdate = async (clientId) => {
    try {
      const res = await axios.post(`${API}/connector/${clientId}/force-update`);
      toast.success(res.data.message);
      // Optimistic UI: set immediate progress state while we wait for the connector to start
      setConnectors(prev => prev.map(c =>
        c.client_id === clientId
          ? { ...c, update_status: "queued", update_progress: 1, update_message: "Aggiornamento forzato inviato — in attesa del prossimo heartbeat..." }
          : c
      ));
      // Trigger fast polling immediately
      setTimeout(fetchAll, 1500);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore invio aggiornamento forzato");
    }
  };

  const resetUpdateStatus = async (clientId) => {
    try {
      await axios.post(`${API}/connector/${clientId}/reset-update-status`);
      toast.success("Stato aggiornamento resettato");
      fetchAll();
    } catch { toast.error("Errore nel reset"); }
  };

  const isOnline = (lastSeen) => lastSeen && (Date.now() - new Date(lastSeen).getTime()) < 120000;

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

  // Group connectors by client
  const clientMap = {};
  clients.forEach(c => { clientMap[c.id] = c.name; });

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="connectors-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Connettori</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Gestione agent 86NocConnector installati</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => { fetchAll(); toast.success("Aggiornato"); }}
          className="rounded-md text-xs h-8 border-[var(--bg-border)] text-[var(--text-secondary)]" data-testid="refresh-connectors-btn">
          <ArrowClockwise size={14} className="mr-1.5" /> Aggiorna
        </Button>
      </div>

      {/* Summary */}
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

      {/* Offline Alert */}
      {offlineCount > 0 && (
        <div className="flex items-start gap-3 p-3 rounded-lg border border-[var(--critical-border)] bg-[var(--critical-bg)]" data-testid="offline-alert-banner">
          <Warning size={18} weight="fill" className="text-[var(--critical)] mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm text-[var(--critical)] font-semibold">{offlineCount} connettore{offlineCount > 1 ? "i" : ""} offline</p>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              Scarica l'ultima versione (v{updateInfo?.version || "?"}) e installala sul server.
              Usa <code className="text-indigo-400 bg-indigo-500/10 px-1 rounded text-[10px]">diagnostica.ps1</code> per verificare.
            </p>
          </div>
        </div>
      )}

      {/* Download */}
      <div className="noc-panel overflow-hidden" data-testid="download-connector-section">
        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center flex-shrink-0">
              <HardDrive size={20} weight="bold" className="text-indigo-400" />
            </div>
            <div>
              <p className="font-heading font-bold text-sm text-[var(--text-primary)]">86NocConnector</p>
              <p className="text-[var(--text-muted)] text-xs">
                Pacchetto Windows nativo {updateInfo?.version && <span className="text-indigo-400 font-mono">v{updateInfo.version}</span>}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowInstall(!showInstall)}
              className="rounded-md text-xs h-8 text-[var(--text-secondary)]" data-testid="toggle-install-guide-btn">
              {showInstall ? "Nascondi guida" : "Guida installazione"}
            </Button>
            <a href="/86NocConnector.zip" download>
              <Button size="sm" className="rounded-md text-xs h-8 bg-indigo-600 hover:bg-indigo-700 text-white" data-testid="download-connector-btn">
                <HardDrive size={14} className="mr-1.5" /> Scarica ZIP
              </Button>
            </a>
          </div>
        </div>

        {showInstall && (
          <div className="border-t border-[var(--bg-border)] p-4 space-y-4 bg-[var(--bg-card)]/50 animate-fade-in">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                { n: 1, t: "Scarica e decomprimi", d: "Scarica il file ZIP e decomprimilo su un server Windows del cliente." },
                { n: 2, t: "Esegui l'installer", d: <>Doppio click su <code className="text-indigo-400 bg-indigo-500/10 px-1 rounded text-[11px]">Installa 86NocConnector.vbs</code></> },
                { n: 3, t: "Configura connessione", d: "Inserisci l'URL del NOC Center e la API Key del cliente." },
              ].map(s => (
                <div key={s.n} className="noc-panel p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="w-6 h-6 rounded-full bg-indigo-600/20 flex items-center justify-center text-indigo-400 text-xs font-bold">{s.n}</span>
                    <p className="text-xs font-medium text-[var(--text-primary)]">{s.t}</p>
                  </div>
                  <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{s.d}</p>
                </div>
              ))}
            </div>
            <div className="flex items-start gap-2 p-3 rounded-lg border border-[var(--medium-border)] bg-[var(--medium-bg)]">
              <Terminal size={16} className="text-[var(--medium)] mt-0.5 flex-shrink-0" />
              <p className="text-[11px] text-[var(--text-secondary)]">
                <strong className="text-[var(--medium)]">Requisiti:</strong> Windows Server 2016+ o Windows 10/11 — PowerShell 5.1 — Porte UDP 162 (SNMP) e 514 (Syslog) libere
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Auto-Update */}
      <div className="noc-panel overflow-hidden" data-testid="update-management-section">
        <div className="p-4">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center flex-shrink-0">
              <ArrowsClockwise size={20} weight="bold" className="text-emerald-400" />
            </div>
            <div className="flex-1">
              <p className="font-heading font-bold text-sm text-[var(--text-primary)]">Aggiornamento Automatico</p>
              <p className="text-[var(--text-muted)] text-xs">
                {updateInfo?.version ? `v${updateInfo.version} — ${updateInfo.updated_connectors || 0}/${updateInfo.total_connectors || 0} aggiornati` : "Nessun aggiornamento"}
              </p>
              <p className="text-[9px] text-emerald-400 mt-0.5 flex items-center gap-1">
                <ArrowsClockwise size={9} /> Check automatico ogni 5 minuti · Aggiornamento immediato con pulsante "Aggiorna"
              </p>
            </div>
            {updateInfo?.pending_connectors > 0 && (
              <span className="text-[10px] px-2 py-1 rounded border text-[var(--medium)] bg-[var(--medium-bg)] border-[var(--medium-border)]">
                {updateInfo.pending_connectors} in attesa
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-end">
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">Versione *</label>
              <input type="text" placeholder="es. 2.4.0" value={newVersion} onChange={(e) => setNewVersion(e.target.value)}
                className="w-full h-9 px-3 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-xs font-mono focus:outline-none focus:border-indigo-500" data-testid="update-version-input" />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest block mb-1">File ZIP</label>
              <input ref={fileInputRef} type="file" accept=".zip" onChange={handleFileSelect}
                className="w-full h-9 text-xs text-[var(--text-secondary)] file:mr-2 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-[var(--bg-hover)] file:text-[var(--text-primary)] file:cursor-pointer" data-testid="update-file-input" />
            </div>
            <Button onClick={handleUploadUpdate} disabled={uploading || !newVersion} size="sm"
              className="rounded-md text-xs h-9 bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50" data-testid="publish-update-btn">
              <CloudArrowUp size={14} className="mr-1.5" /> {uploading ? "Caricamento..." : "Pubblica"}
            </Button>
          </div>
          <input type="text" placeholder="Changelog (opzionale)" value={changelog} onChange={(e) => setChangelog(e.target.value)}
            className="w-full h-8 px-3 mt-3 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-secondary)] text-xs focus:outline-none focus:border-indigo-500" data-testid="update-changelog-input" />
          {updateInfo?.published_at && (
            <p className="text-[10px] text-[var(--text-muted)] mt-2">
              Ultimo: v{updateInfo.version} — {new Date(updateInfo.published_at).toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}
              {updateInfo.changelog && ` — ${updateInfo.changelog}`}
            </p>
          )}
        </div>
      </div>

      {/* Connector List */}
      <h2 className="font-heading text-sm font-bold text-[var(--text-primary)]">Connettori Installati</h2>

      {loading ? (
        <div className="noc-panel p-8 text-center text-[var(--text-muted)] text-sm">Caricamento...</div>
      ) : connectors.length === 0 ? (
        <div className="noc-panel p-8 text-center" data-testid="no-connectors">
          <HardDrive size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-[var(--text-secondary)] text-sm mb-1">Nessun connettore installato</p>
          <p className="text-[var(--text-muted)] text-xs">Scarica e installa 86NocConnector su un server</p>
        </div>
      ) : (
        <div className="space-y-2">
          {(() => {
            // Raggruppa per client_id: master in cima, scanner figli indentati sotto.
            // Se un cliente ha solo scanner (senza master), li mostra comunque.
            const byClient = {};
            for (const c of connectors) {
              const cid = c.client_id || "_orphan_";
              if (!byClient[cid]) byClient[cid] = { master: null, scanners: [] };
              if ((c.mode || "master") === "scanner") byClient[cid].scanners.push(c);
              else byClient[cid].master = c;
            }
            const ordered = [];
            for (const [cid, group] of Object.entries(byClient)) {
              if (group.master) ordered.push({ ...group.master, _isChild: false, _clientId: cid });
              for (const s of group.scanners) ordered.push({ ...s, _isChild: !!group.master, _clientId: cid });
            }
            return ordered;
          })().map((c, i) => {
            const online = isOnline(c.last_seen);
            const isChild = c._isChild;
            return (
              <div key={i}
                className={`noc-panel overflow-hidden ${isChild ? "ml-8 border-l-2 border-l-sky-500/40 relative" : ""}`}
                data-testid={`connector-${c.client_id}`}>
                {isChild && (
                  <div className="absolute -left-4 top-1/2 -translate-y-1/2 w-4 h-px bg-sky-500/40" aria-hidden="true" />
                )}
                <div className="p-3 flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 relative group ${online ? "bg-[var(--low-bg)] border border-[var(--low-border)]" : "bg-[var(--critical-bg)] border border-[var(--critical-border)]"}`}>
                    {online ? <SealCheck size={18} weight="fill" className="text-[var(--ok)]" /> : <Warning size={18} weight="fill" className="text-[var(--critical)]" />}
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-50 pointer-events-none">
                      <div className="bg-[#111] border border-[var(--bg-border)] rounded-md px-3 py-2 shadow-xl whitespace-nowrap">
                        <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-1">Connector Info</p>
                        <p className="text-xs text-[var(--text-primary)] font-mono">v{c.connector_version || "?"}</p>
                        <p className="text-xs text-[var(--text-secondary)] font-mono">{c.connector_ip || c.hostname || "N/A"}</p>
                      </div>
                      <div className="w-2 h-2 bg-[#111] border-r border-b border-[var(--bg-border)] rotate-45 absolute left-1/2 -translate-x-1/2 -bottom-1"></div>
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-heading font-bold text-sm text-[var(--text-primary)] truncate">
                        {(c.mode || "master") === "scanner" ? `Connector Scanner — ${c.hostname || "Server"}` : (c.hostname || "Server")}
                      </p>
                      <span className="text-[10px] text-[var(--text-muted)] font-mono">{clientMap[c.client_id] || ""}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${online ? "text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]" : "text-[var(--critical)] bg-[var(--critical-bg)] border-[var(--critical-border)]"}`}>
                        {online ? "ONLINE" : "OFFLINE"}
                      </span>
                      {/* Mode badge: master = full polling (cyan), scanner = LAN discovery (azzurro/sky) */}
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${
                          (c.mode || "master") === "scanner"
                            ? "text-sky-300 bg-sky-500/10 border-sky-500/40"
                            : "text-emerald-300 bg-emerald-500/10 border-emerald-500/30"
                        }`}
                        title={(c.mode || "master") === "scanner"
                          ? "Modalita' SCANNER: solo discovery LAN (ARP/mDNS/SNMP locale). Per VLAN remote dove il master non arriva."
                          : "Modalita' MASTER: polling completo switch/firewall + Syslog/Trap. Uno per sito."}
                        data-testid={`connector-mode-${c.client_id}`}>
                        {(c.mode || "master").toUpperCase()}
                      </span>
                      {c.subnet && (
                        <span className="text-[10px] text-[var(--text-muted)] font-mono" title="Subnet locale">
                          {c.subnet}{c.vlan_id ? ` · VLAN ${c.vlan_id}` : ""}
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-x-4 gap-y-0.5 mt-1">
                      <InfoItem label="Versione" value={`v${c.connector_version || "?"}`} />
                      <InfoItem label="Uptime" value={formatUptime(c.uptime_seconds)} />
                      <InfoItem label={(c.mode || "master") === "scanner" ? "Endpoint scan" : "SNMP"}
                        value={(c.mode || "master") === "scanner" ? (c.last_lan_scan_endpoints ?? 0) : (c.traps_received || 0)} />
                      <InfoItem label={(c.mode || "master") === "scanner" ? "Ultima scan" : "Syslog"}
                        value={(c.mode || "master") === "scanner" ? formatLastSeen(c.last_lan_scan_at) : (c.syslogs_received || 0)} />
                      <InfoItem label="Ultimo" value={formatLastSeen(c.last_seen)} />
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {updateInfo?.version && isNewerVersion(updateInfo.version, c.connector_version) && (
                      <button
                        onClick={() => forceUpdate(c.client_id)}
                        disabled={!online}
                        title={online ? "Forza aggiornamento immediato" : "Connector offline — impossibile aggiornare da remoto"}
                        className={`h-7 px-2 rounded-md flex items-center gap-1 text-[10px] font-medium border transition-colors ${
                          online
                            ? "text-amber-400 bg-amber-500/10 border-amber-500/20 hover:bg-amber-500/20 cursor-pointer"
                            : "text-[var(--text-muted)] bg-[var(--bg-hover)] border-[var(--bg-border)] opacity-50 cursor-not-allowed"
                        }`}
                        data-testid={`force-update-btn-${c.client_id}`}>
                        <ArrowsClockwise size={12} /> Aggiorna
                      </button>
                    )}
                    <button onClick={() => deleteConnector(c.hostname || c.client_name)}
                      className="w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] transition-colors"
                      data-testid={`delete-connector-${c.client_id}`}>
                      <Trash size={14} />
                    </button>
                  </div>
                </div>

                {/* Update progress — sempre visibile durante aggiornamento */}
                {c.update_status && !["completed", "error"].includes(c.update_status) && (
                  <div className="mx-4 mb-3 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20" data-testid={`update-progress-${c.client_id}`}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] text-amber-400 font-semibold flex items-center gap-1.5">
                        <ArrowsClockwise size={12} className="animate-spin" />
                        {c.update_message || "Aggiornamento in corso..."}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-mono font-bold text-amber-400">{c.update_progress || 0}%</span>
                        <button
                          onClick={() => resetUpdateStatus(c.client_id)}
                          className="text-[9px] px-2 py-0.5 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20 transition-colors"
                          title="Annulla aggiornamento">
                          Annulla
                        </button>
                      </div>
                    </div>
                    <div className="w-full h-2.5 rounded-full bg-[var(--bg-panel)] overflow-hidden relative">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-400 transition-all duration-500 relative"
                        style={{ width: `${c.update_progress || 3}%` }}
                      >
                        <div className="absolute inset-0 bg-white/20 animate-pulse" />
                      </div>
                    </div>
                    <p className="text-[9px] text-[var(--text-muted)] mt-1.5 font-mono uppercase tracking-wider">
                      Stato: {c.update_status}
                    </p>
                    {c.update_status === "queued" && !online && (
                      <p className="text-[9px] text-red-400 mt-1 flex items-center gap-1">
                        <Warning size={9} /> Connector OFFLINE — l'ordine verra' ricevuto solo al prossimo ritorno online. Timeout automatico dopo 10 minuti.
                      </p>
                    )}
                  </div>
                )}
                {c.update_status === "completed" && (
                  <div className="mx-4 mb-3 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between">
                    <span className="text-[11px] text-emerald-400 font-semibold flex items-center gap-1.5">
                      <CheckCircle size={12} weight="bold" /> Aggiornamento completato con successo!
                    </span>
                    <button onClick={() => resetUpdateStatus(c.client_id)}
                      className="text-[9px] px-2 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-amber-400 hover:bg-amber-500/10 border border-[var(--bg-border)] transition-colors"
                      data-testid={`reset-update-${c.client_id}`}>Chiudi</button>
                  </div>
                )}
                {c.update_status === "error" && (
                  <div className="mx-4 mb-3 p-2 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-between">
                    <span className="text-[11px] text-red-400 font-semibold flex items-center gap-1.5">
                      <Warning size={12} weight="bold" /> Errore: {c.update_message || "Aggiornamento fallito"}
                    </span>
                    <button onClick={() => resetUpdateStatus(c.client_id)}
                      className="text-[9px] px-2 py-0.5 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20 transition-colors">Chiudi</button>
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
    <div className="flex items-center gap-1">
      <span className="text-[10px] text-[var(--text-muted)]">{label}:</span>
      <span className="text-[11px] font-mono text-[var(--text-secondary)]">{value}</span>
    </div>
  );
}
