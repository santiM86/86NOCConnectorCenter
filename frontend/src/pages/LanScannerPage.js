import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * Scanner LAN — versione web (NOC Center).
 *
 * Modi:
 *   • globale (sidebar): qualsiasi agent live, dropdown completo.
 *   • per-cliente (tab in ClientOverviewPage): filtra agent del cliente
 *     e abilita "Importa nel cliente" sui device scoperti.
 *
 * Avvia uno scan ICMP+ARP+NBNS sull'agent Connector selezionato e
 * mostra i risultati live (polling 1s). Selezione multipla + bulk-import
 * in `managed_devices` con scelta monitor_type (ping/snmp) + community.
 */
export default function LanScannerPage({ scopedClientId, scopedClientName } = {}) {
  const token = localStorage.getItem("noc_token");
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [cidr, setCidr] = useState("");
  const [filter, setFilter] = useState("");

  const [scanId, setScanId] = useState(null);
  const [run, setRun] = useState(null);
  const [starting, setStarting] = useState(false);

  // Selezione multipla righe (per import)
  const [selectedIps, setSelectedIps] = useState(() => new Set());
  // Modal import
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [defaultMonitorType, setDefaultMonitorType] = useState("ping");
  const [defaultCommunity, setDefaultCommunity] = useState("public");
  const [defaultDeviceType, setDefaultDeviceType] = useState("generic");
  // v4.9.1: auto-classifica device_type da vendor OUI + hostname pattern.
  // ON di default — abbatte il time-to-onboarding sui pattern noti.
  const [autoClassify, setAutoClassify] = useState(true);

  const pollRef = useRef(null);

  // Carica lista agent connessi (filtrata per cliente se scopedClientId).
  const refreshAgents = useCallback(() => {
    const url = scopedClientId
      ? `${API}/api/agents?client_id=${encodeURIComponent(scopedClientId)}`
      : `${API}/api/agents`;
    axios.get(url, { headers })
      .then((r) => {
        const list = Array.isArray(r.data?.agents) ? r.data.agents : [];
        const live = list.filter((a) => a.live);
        setAgents(live);
        if (!selectedAgent && live.length > 0) {
          setSelectedAgent(live[0].agent_id);
        }
      })
      .catch(() => toast.error("Impossibile caricare la lista agent"));
  }, [headers, selectedAgent, scopedClientId]);

  useEffect(() => { refreshAgents(); }, [refreshAgents]);

  // Polling stato scan.
  useEffect(() => {
    if (!scanId) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await axios.get(`${API}/api/lan-scans/${scanId}`, { headers });
        if (cancelled) return;
        setRun(r.data);
        if (r.data?.status && r.data.status !== "running") {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch (_e) { /* ignore */ }
    };
    tick();
    pollRef.current = setInterval(tick, 1000);
    return () => { cancelled = true; if (pollRef.current) clearInterval(pollRef.current); };
  }, [scanId, headers]);

  const startScan = async () => {
    if (!selectedAgent) { toast.error("Seleziona un agent"); return; }
    setStarting(true);
    setRun(null);
    setSelectedIps(new Set());
    try {
      const r = await axios.post(`${API}/api/lan-scans`,
        { agent_id: selectedAgent, cidr: cidr.trim() },
        { headers });
      setScanId(r.data.scan_id);
      setRun(r.data);
      toast.success(`Scan avviato su ${r.data.cidr || "subnet locale"}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore avvio scan");
    } finally {
      setStarting(false);
    }
  };

  const cancelScan = async () => {
    if (!scanId) return;
    try {
      await axios.delete(`${API}/api/lan-scans/${scanId}`, { headers });
      toast.info("Scan cancellato");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore cancellazione");
    }
  };

  const running = run?.status === "running";
  const results = useMemo(() => {
    const arr = Array.isArray(run?.results) ? run.results.slice() : [];
    arr.sort((a, b) => ipNum(a.ip) - ipNum(b.ip));
    if (!filter.trim()) return arr;
    const q = filter.toLowerCase();
    return arr.filter((r) =>
      [r.ip, r.hostname, r.mac, r.vendor]
        .filter(Boolean).some((v) => String(v).toLowerCase().includes(q)));
  }, [run, filter]);

  const aliveCount = results.filter((r) => r.status === "alive").length;
  const arpCount = results.filter((r) => r.status === "arp-only").length;
  const pct = run?.progress?.total
    ? Math.round((run.progress.done / run.progress.total) * 100) : 0;

  // Selezione
  const toggleIp = (ip) => {
    setSelectedIps((s) => {
      const n = new Set(s);
      if (n.has(ip)) n.delete(ip); else n.add(ip);
      return n;
    });
  };
  const selectAllAlive = () => {
    const ips = results.filter((r) => r.status === "alive").map((r) => r.ip);
    setSelectedIps(new Set(ips));
  };
  const clearSelection = () => setSelectedIps(new Set());
  const allAliveSelected = aliveCount > 0 &&
    results.filter((r) => r.status === "alive").every((r) => selectedIps.has(r.ip));

  // Import
  const doImport = async () => {
    if (!scopedClientId) { toast.error("client_id mancante"); return; }
    if (selectedIps.size === 0) return;
    setImporting(true);
    const devices = results.filter((r) => selectedIps.has(r.ip)).map((r) => {
      const suggested = autoClassify ? suggestDeviceType(r.vendor, r.hostname, r.device_name) : null;
      return {
        ip: r.ip,
        name: r.hostname || r.device_name || r.ip,
        hostname: r.hostname,
        monitor_type: defaultMonitorType,
        community: defaultCommunity,
        device_type: suggested || defaultDeviceType,
      };
    });
    try {
      const res = await axios.post(`${API}/api/lan-scans/${scanId}/import`,
        { client_id: scopedClientId, devices }, { headers });
      toast.success(`Importati ${res.data.imported} dispositivi${res.data.skipped?.length ? ` (${res.data.skipped.length} già presenti, saltati)` : ""}`);
      setImportOpen(false);
      setSelectedIps(new Set());
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore import");
    } finally {
      setImporting(false);
    }
  };

  // Stili colorTokens condizionali al tab embedded vs full-page.
  const cardBg = scopedClientId ? "bg-[var(--bg-panel)]" : "bg-white";
  const borderC = scopedClientId ? "border-[var(--bg-border)]" : "border-[var(--border,#e5e7eb)]";
  const txtMuted = scopedClientId ? "text-[var(--text-muted)]" : "text-[var(--text-secondary,#64748b)]";
  const txtPrimary = scopedClientId ? "text-[var(--text-primary)]" : "text-[var(--text-primary,#1a1a2a)]";

  return (
    <div className={`${scopedClientId ? "p-2" : "p-6"} space-y-5 ${txtPrimary}`} data-testid="lan-scanner-page">
      {!scopedClientId && (
        <header>
          <div className={`text-[11px] uppercase tracking-[0.18em] ${txtMuted}`}>
            Network discovery on-demand
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Scanner LAN</h1>
          <p className={`text-sm mt-1 max-w-2xl ${txtMuted}`}>
            Lancia uno scan attivo (ICMP nativo + ARP + NBNS + reverse DNS) tramite un Connector
            Windows. Risultati live, niente UI desktop bloccata.
          </p>
        </header>
      )}

      {/* Controlli */}
      <div className={`rounded-xl border ${borderC} ${cardBg} p-5 shadow-sm space-y-4`}>
        <div className="grid grid-cols-1 md:grid-cols-[2fr_2fr_auto_auto] gap-3 items-end">
          <div>
            <label className={`text-xs ${txtMuted}`}>
              {scopedClientId ? `Connector del cliente${scopedClientName ? ` "${scopedClientName}"` : ""}` : "Agent Connector"} ({agents.length} live)
            </label>
            <select
              data-testid="lan-scan-agent"
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
              disabled={running}
              className={`mt-1 w-full rounded-md border ${borderC} px-3 py-2 text-sm ${cardBg}`}
            >
              {agents.length === 0 && <option value="">(nessun connector live)</option>}
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.hostname || a.agent_id.slice(0, 8)} {!scopedClientId && `· ${a.client_id?.slice(0, 8) || "no-client"}`}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={`text-xs ${txtMuted}`}>CIDR target (vuoto = auto-detect)</label>
            <input
              data-testid="lan-scan-cidr"
              value={cidr}
              onChange={(e) => setCidr(e.target.value)}
              placeholder="es. 192.168.1.0/24"
              disabled={running}
              className={`mt-1 w-full rounded-md border ${borderC} px-3 py-2 text-sm font-mono ${cardBg}`}
            />
          </div>
          {!running ? (
            <button
              data-testid="lan-scan-start"
              onClick={startScan}
              disabled={starting || !selectedAgent}
              className="px-5 py-2 rounded-md bg-[#1040e0] text-white text-sm font-medium hover:bg-[#0d34b8] disabled:opacity-50 transition-colors"
            >
              {starting ? "Avvio…" : "▶ Avvia scan"}
            </button>
          ) : (
            <button
              data-testid="lan-scan-cancel"
              onClick={cancelScan}
              className="px-5 py-2 rounded-md bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors"
            >
              ■ Annulla
            </button>
          )}
          <button
            onClick={refreshAgents} disabled={running} title="Ricarica lista agent"
            className={`px-3 py-2 rounded-md border ${borderC} text-sm hover:bg-slate-50 dark:hover:bg-slate-700`}
          >↻</button>
        </div>

        {/* Progress */}
        {(running || run?.status === "done" || run?.status === "error") && (
          <div className="space-y-2" data-testid="lan-scan-progress">
            <div className="h-2 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
              <div className={`h-full transition-all ${run?.status === "error" ? "bg-red-500" : "bg-emerald-500"}`} style={{ width: `${pct}%` }} />
            </div>
            <div className={`text-xs font-mono flex flex-wrap gap-4 ${txtMuted}`}>
              <span>{running ? "● in corso" : run?.status === "error" ? "✗ errore" : "✓ completato"}</span>
              <span>{run?.progress?.done ?? 0}/{run?.progress?.total ?? 0} probe</span>
              <span className="text-emerald-500">● {aliveCount} alive</span>
              {arpCount > 0 && <span className="text-amber-500">◐ {arpCount} arp-only</span>}
              <span>cidr: {run?.cidr || "—"}</span>
              {run?.error && <span className="text-red-500">errore: {run.error}</span>}
            </div>
          </div>
        )}
      </div>

      {/* Toolbar selezione + tabella */}
      <div className={`rounded-xl border ${borderC} ${cardBg} shadow-sm`}>
        <div className={`flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b ${borderC}`}>
          <div className="flex items-center gap-3">
            <h2 className="font-semibold">Risultati ({results.length})</h2>
            {scopedClientId && results.length > 0 && (
              <>
                <button
                  onClick={selectAllAlive}
                  className="text-xs px-2.5 py-1 rounded border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700"
                  data-testid="lan-scan-select-all"
                >Seleziona tutti alive ({aliveCount})</button>
                {selectedIps.size > 0 && (
                  <>
                    <span className={`text-xs ${txtMuted}`}>{selectedIps.size} selezionati</span>
                    <button onClick={clearSelection} className={`text-xs ${txtMuted} hover:underline`}>cancella</button>
                    <button
                      onClick={() => setImportOpen(true)}
                      className="text-xs px-3 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 font-medium"
                      data-testid="lan-scan-import-btn"
                    >+ Importa {selectedIps.size} nel cliente</button>
                  </>
                )}
              </>
            )}
          </div>
          <input
            data-testid="lan-scan-filter"
            value={filter} onChange={(e) => setFilter(e.target.value)}
            placeholder="filtra: ip, hostname, mac…"
            className={`px-3 py-1.5 rounded-md border ${borderC} text-xs w-64 ${cardBg}`}
          />
        </div>
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full text-sm" data-testid="lan-scan-table">
            <thead className={`sticky top-0 text-xs uppercase tracking-wider ${txtMuted} ${scopedClientId ? "bg-[var(--bg-card)]" : "bg-slate-50"}`}>
              <tr>
                {scopedClientId && (
                  <th className="px-3 py-2 w-10">
                    <input
                      type="checkbox" checked={allAliveSelected}
                      onChange={() => allAliveSelected ? clearSelection() : selectAllAlive()}
                      data-testid="lan-scan-select-all-cb"
                    />
                  </th>
                )}
                <th className="text-left px-4 py-2 w-24">Stato</th>
                <th className="text-left px-4 py-2 font-mono w-36">IP</th>
                <th className="text-left px-4 py-2 w-20">RTT</th>
                <th className="text-left px-4 py-2">Hostname</th>
                <th className="text-left px-4 py-2 font-mono">MAC</th>
                <th className="text-left px-4 py-2">Vendor</th>
                {scopedClientId && <th className="text-left px-4 py-2 w-28">Tipo (auto)</th>}
              </tr>
            </thead>
            <tbody>
              {results.length === 0 ? (
                <tr>
                  <td colSpan={scopedClientId ? 8 : 6} className={`text-center py-12 ${txtMuted}`}>
                    {running ? "Scan in corso, primi risultati in arrivo…" : run ? "Nessun host trovato." : "Avvia uno scan per iniziare."}
                  </td>
                </tr>
              ) : results.map((r) => {
                const sel = selectedIps.has(r.ip);
                return (
                  <tr key={r.ip}
                      className={`border-t ${borderC} cursor-pointer ${sel ? "bg-emerald-50 dark:bg-emerald-900/20" : (scopedClientId ? "hover:bg-slate-700/30" : "hover:bg-slate-50")}`}
                      onClick={() => scopedClientId && r.status === "alive" && toggleIp(r.ip)}
                      data-testid={`lan-scan-row-${r.ip}`}>
                    {scopedClientId && (
                      <td className="px-3 py-1.5">
                        <input type="checkbox" checked={sel}
                          disabled={r.status !== "alive"}
                          onChange={() => toggleIp(r.ip)}
                          onClick={(e) => e.stopPropagation()}
                          data-testid={`lan-scan-cb-${r.ip}`} />
                      </td>
                    )}
                    <td className="px-4 py-1.5">
                      {r.status === "alive" ? <span className="text-emerald-500 font-medium">● alive</span>
                        : r.status === "arp-only" ? <span className="text-amber-500 font-medium">◐ arp</span>
                        : <span className={txtMuted}>○ {r.status}</span>}
                    </td>
                    <td className="px-4 py-1.5 font-mono">{r.ip}</td>
                    <td className={`px-4 py-1.5 font-mono text-xs ${txtMuted}`}>{r.rtt_ms >= 0 ? `${r.rtt_ms} ms` : ""}</td>
                    <td className="px-4 py-1.5">{r.hostname || (r.device_name && <span className={`${txtMuted} italic`} title={`Fingerbank score: ${r.device_score ?? "?"}`}>{r.device_name}</span>) || ""}</td>
                    <td className="px-4 py-1.5 font-mono text-xs">{r.mac || ""}</td>
                    <td className="px-4 py-1.5 text-xs">{r.vendor || ""}</td>
                    {scopedClientId && (() => {
                      const sug = suggestDeviceType(r.vendor, r.hostname, r.device_name);
                      return (
                        <td className="px-4 py-1.5 text-xs">
                          {sug ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-400 font-medium">
                              {sug}
                            </span>
                          ) : (
                            <span className={txtMuted}>—</span>
                          )}
                        </td>
                      );
                    })()}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal Import */}
      {importOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
             onClick={(e) => e.target === e.currentTarget && setImportOpen(false)}
             data-testid="lan-scan-import-modal">
          <div className="bg-[var(--bg-panel,#fff)] rounded-xl border border-[var(--bg-border,#e5e7eb)] w-full max-w-md p-5 shadow-2xl">
            <h3 className="text-lg font-semibold mb-1">Importa {selectedIps.size} dispositivi</h3>
            <p className={`text-xs ${txtMuted} mb-4`}>
              I device verranno aggiunti a "{scopedClientName || scopedClientId}". Quelli già presenti vengono saltati.
            </p>

            {/* Auto-classifica toggle */}
            <label className={`flex items-start gap-2.5 cursor-pointer p-2.5 rounded-md border ${borderC} mb-4 hover:bg-slate-50 dark:hover:bg-slate-700/40`}>
              <input
                type="checkbox"
                checked={autoClassify}
                onChange={(e) => setAutoClassify(e.target.checked)}
                className="mt-0.5"
                data-testid="lan-scan-import-autoclassify"
              />
              <span className="text-xs">
                <span className="font-medium">Auto-classifica tipo</span> da vendor + hostname.<br />
                {(() => {
                  const sel = results.filter((r) => selectedIps.has(r.ip));
                  const classified = sel.filter((r) => suggestDeviceType(r.vendor, r.hostname, r.device_name));
                  return (
                    <span className={txtMuted}>
                      {classified.length}/{sel.length} riconosciuti — gli altri useranno il default sotto.
                    </span>
                  );
                })()}
              </span>
            </label>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium">Tipo monitor (default per tutti)</label>
                <select value={defaultMonitorType} onChange={(e) => setDefaultMonitorType(e.target.value)}
                  className={`mt-1 w-full rounded-md border ${borderC} px-3 py-2 text-sm ${cardBg}`}>
                  <option value="ping">Ping (ICMP base)</option>
                  <option value="snmp">SNMP (richiede community)</option>
                </select>
              </div>
              {defaultMonitorType === "snmp" && (
                <div>
                  <label className="text-xs font-medium">SNMP Community</label>
                  <input value={defaultCommunity} onChange={(e) => setDefaultCommunity(e.target.value)}
                    className={`mt-1 w-full rounded-md border ${borderC} px-3 py-2 text-sm font-mono ${cardBg}`} />
                </div>
              )}
              <div>
                <label className="text-xs font-medium">
                  Device type {autoClassify ? "(default per non riconosciuti)" : "(per tutti)"}
                </label>
                <select value={defaultDeviceType} onChange={(e) => setDefaultDeviceType(e.target.value)}
                  className={`mt-1 w-full rounded-md border ${borderC} px-3 py-2 text-sm ${cardBg}`}>
                  <option value="generic">Generico</option>
                  <option value="server">Server</option>
                  <option value="workstation">Workstation</option>
                  <option value="switch">Switch</option>
                  <option value="firewall">Firewall</option>
                  <option value="ap">Access Point</option>
                  <option value="printer">Stampante</option>
                  <option value="nas">NAS / Storage</option>
                  <option value="ups">UPS</option>
                  <option value="camera">Telecamera</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setImportOpen(false)} disabled={importing}
                className={`px-4 py-2 rounded-md text-sm border ${borderC} hover:bg-slate-50 dark:hover:bg-slate-700`}>
                Annulla
              </button>
              <button onClick={doImport} disabled={importing}
                className="px-4 py-2 rounded-md text-sm bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                data-testid="lan-scan-import-confirm">
                {importing ? "Import…" : `Importa ${selectedIps.size}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ipNum(s) {
  if (!s) return 0;
  const m = String(s).split(".").map(Number);
  if (m.length !== 4 || m.some((n) => Number.isNaN(n))) return 0;
  return ((m[0] << 24) >>> 0) + ((m[1] << 16) >>> 0) + ((m[2] << 8) >>> 0) + m[3];
}

/**
 * suggestDeviceType — inferenza tipo device da vendor OUI + hint hostname.
 *
 * Riduce drasticamente l'attrito di onboarding: l'utente importa decine di
 * device senza dover classificare manualmente ognuno. Quando l'inferenza
 * fallisce (vendor sconosciuto + hostname senza pattern noti), ritorna null
 * e l'UI usa il default scelto nel modal.
 */
function suggestDeviceType(vendor, hostname, deviceName) {
  const v = (vendor || "").toLowerCase();
  const h = (hostname || "").toLowerCase();
  const d = (deviceName || "").toLowerCase();

  // 0. Fingerbank device_name è la fonte più ricca quando presente
  if (d) {
    if (/printer|laserjet|deskjet|officejet|brother|canon|epson|kyocera|lexmark/i.test(d)) return "printer";
    if (/iphone|ipad|android|smartphone|mobile|google pixel|samsung galaxy/i.test(d)) return "workstation";
    if (/server|esxi|vmware|hyper-?v|proxmox|xenserver/i.test(d)) return "server";
    if (/synology|qnap|nas|truenas/i.test(d)) return "nas";
    if (/firewall|fortigate|sonicwall|sophos|palo alto|usg/i.test(d)) return "firewall";
    if (/switch|catalyst|nexus|meraki|aruba/i.test(d)) return "switch";
    if (/access point|unifi|aruba ap|ruckus|wifi/i.test(d)) return "ap";
    if (/camera|ipcam|nvr|dvr|hikvision|dahua/i.test(d)) return "camera";
    if (/macbook|imac|mac mini|mac pro/i.test(d)) return "workstation";
    if (/ups|smart-ups|riello/i.test(d)) return "ups";
  }

  // 1. Hostname pattern check (prevale sul vendor: il nome è scelto dall'IT)
  if (/^(srv|server|dc|ad|adc|backup|vm|hv|host)[\W_-]?/i.test(h)) return "server";
  if (/^(fw|firewall|fortigate|fortinet|usg|sophos)[\W_-]?/i.test(h)) return "firewall";
  if (/^(sw|switch|core|access|cisco)[\W_-]?/i.test(h)) return "switch";
  if (/^(ap|wap|wifi|aplab|airwave|unifi)[\W_-]?/i.test(h)) return "ap";
  if (/^(nas|storage|qnap|synology|ds[0-9])/i.test(h)) return "nas";
  if (/^(stampante|printer|prn|brother|hpprt|epson|canon)/i.test(h)) return "printer";
  if (/^(ups|riello|apc|eaton)/i.test(h)) return "ups";
  if (/^(cam|tvcc|camera|nvr|dvr|hik)/i.test(h)) return "camera";
  if (/^(pc|wks|ws|notebook|laptop|nb|mac|imac)[\W_-]?/i.test(h)) return "workstation";

  // 2. Vendor OUI match
  if (/hyper-v|vmware|virtualbox|qemu/i.test(v)) return "server";
  if (/synology|qnap|netgear readynas/i.test(v)) return "nas";
  if (/hp print|brother|canon|epson|ricoh|konica|kyocera|lexmark/i.test(v)) return "printer";
  if (/cisco meraki|aruba|ruckus|extreme/i.test(v)) return "switch";
  if (/ubiquiti|tp-link|netgear|aruba ap|d-link/i.test(v)) return "ap";
  if (/fritz|zyxel|fortinet|paloalto|sophos|sonicwall/i.test(v)) return "firewall";
  if (/mikrotik|routerboard/i.test(v)) return "switch"; // spesso usati come switch L3 in PMI
  if (/hikvision|dahua|axis|bosch security/i.test(v)) return "camera";
  if (/espressif|raspberry|particle|tuya|shelly/i.test(v)) return "iot";
  if (/apple/i.test(v)) return "workstation";
  if (/dell|lenovo|asus|acer|samsung|gigabyte/i.test(v)) return "workstation";
  if (/hp\b/i.test(v)) return "workstation"; // HP generico (computer), HP Print è già sopra

  return null;
}
