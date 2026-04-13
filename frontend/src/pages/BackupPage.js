import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from "recharts";

const API = process.env.REACT_APP_BACKEND_URL;

export default function BackupPage() {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [data, setData] = useState(null);
  const [history, setHistory] = useState([]);
  const [selectedVm, setSelectedVm] = useState(null);
  const [vmDetail, setVmDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    axios.get(`${API}/api/clients`, { headers }).then(r => {
      const cl = Array.isArray(r.data) ? r.data : r.data.clients || [];
      setClients(cl);
      if (cl.length > 0) setSelectedClient(cl[0].id);
    }).catch(() => {});
  }, []);

  const fetchData = useCallback(() => {
    if (!selectedClient) return;
    setLoading(true);
    Promise.all([
      axios.get(`${API}/api/backup/dashboard/${selectedClient}`, { headers }),
      axios.get(`${API}/api/backup/history/${selectedClient}?days=7`, { headers }),
    ])
      .then(([dashRes, histRes]) => {
        setData(dashRes.data);
        setHistory(histRes.data.data || []);
      })
      .catch(() => toast.error("Errore caricamento dati backup"))
      .finally(() => setLoading(false));
  }, [selectedClient]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openVmDetail = (vmName) => {
    setSelectedVm(vmName);
    axios.get(`${API}/api/backup/vm/${selectedClient}/${encodeURIComponent(vmName)}`, { headers })
      .then(r => setVmDetail(r.data))
      .catch(() => toast.error("Errore caricamento dettagli VM"));
  };

  const formatBytes = (bytes) => {
    if (!bytes) return "-";
    if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
    return `${(bytes / 1e3).toFixed(0)} KB`;
  };

  const fmtTime = (ts) => {
    if (!ts) return "Mai";
    try { return new Date(ts).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); }
    catch { return ts; }
  };

  const fmtDate = (ts) => {
    if (!ts) return "";
    try { return new Date(ts).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" }); }
    catch { return ts.slice(0, 10); }
  };

  const statusConfig = {
    success: { label: "OK", color: "text-emerald-400", bg: "bg-emerald-500/20", dot: "bg-emerald-500" },
    warning: { label: "Warning", color: "text-amber-400", bg: "bg-amber-500/20", dot: "bg-amber-500" },
    failed: { label: "Fallito", color: "text-red-400", bg: "bg-red-500/20", dot: "bg-red-500" },
    missing: { label: "Mancante", color: "text-orange-400", bg: "bg-orange-500/20", dot: "bg-orange-500" },
    unknown: { label: "N/D", color: "text-gray-400", bg: "bg-gray-500/20", dot: "bg-gray-500" },
  };

  const vmStateConfig = {
    Running: "text-emerald-400",
    Off: "text-red-400",
    Saved: "text-amber-400",
    Paused: "text-amber-400",
  };

  const s = data?.summary || {};

  return (
    <div className="space-y-6" data-testid="backup-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Monitoraggio Backup</h1>
          <p className="text-sm text-[var(--text-secondary)]">Hornetsecurity VM Backup + Hyper-V</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={selectedClient} onChange={e => { setSelectedClient(e.target.value); setSelectedVm(null); }}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="backup-client-select">
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={fetchData}
            className="h-8 px-4 text-xs font-semibold rounded-md bg-blue-600 text-white hover:bg-blue-700"
            data-testid="backup-refresh-btn">
            Aggiorna
          </button>
        </div>
      </div>

      {loading && <div className="text-center py-8 text-[var(--text-secondary)]">Caricamento...</div>}

      {data && !loading && (
        <>
          {/* Connection Status */}
          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-1.5 px-2 py-1 text-xs rounded-md border ${data.altaro_connected ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400" : "border-red-500/30 bg-red-500/5 text-red-400"}`}>
              <div className={`w-1.5 h-1.5 rounded-full ${data.altaro_connected ? "bg-emerald-500" : "bg-red-500"}`} />
              Altaro {data.altaro_connected ? "Connesso" : "Non connesso"}
            </div>
            <div className={`flex items-center gap-1.5 px-2 py-1 text-xs rounded-md border ${data.hyperv_connected ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400" : "border-red-500/30 bg-red-500/5 text-red-400"}`}>
              <div className={`w-1.5 h-1.5 rounded-full ${data.hyperv_connected ? "bg-emerald-500" : "bg-red-500"}`} />
              Hyper-V {data.hyperv_connected ? "Connesso" : "Non connesso"}
            </div>
            {data.updated_at && (
              <span className="text-[10px] text-[var(--text-secondary)]">Ultimo aggiornamento: {fmtTime(data.updated_at)}</span>
            )}
          </div>

          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center" data-testid="backup-total">
              <p className="text-3xl font-bold text-[var(--text-primary)]">{s.total_vms || 0}</p>
              <p className="text-xs text-[var(--text-secondary)]">VM Totali</p>
            </div>
            <div className="rounded-lg border border-emerald-500/20 bg-[var(--bg-card)] p-3 text-center" data-testid="backup-ok">
              <p className="text-3xl font-bold text-emerald-400">{s.backup_ok || 0}</p>
              <p className="text-xs text-[var(--text-secondary)]">Backup OK</p>
            </div>
            <div className="rounded-lg border border-amber-500/20 bg-[var(--bg-card)] p-3 text-center" data-testid="backup-warning">
              <p className="text-3xl font-bold text-amber-400">{s.backup_warning || 0}</p>
              <p className="text-xs text-[var(--text-secondary)]">Warning</p>
            </div>
            <div className="rounded-lg border border-red-500/20 bg-[var(--bg-card)] p-3 text-center" data-testid="backup-failed">
              <p className="text-3xl font-bold text-red-400">{s.backup_failed || 0}</p>
              <p className="text-xs text-[var(--text-secondary)]">Falliti</p>
            </div>
            <div className="rounded-lg border border-orange-500/20 bg-[var(--bg-card)] p-3 text-center" data-testid="backup-missing">
              <p className="text-3xl font-bold text-orange-400">{s.backup_missing || 0}</p>
              <p className="text-xs text-[var(--text-secondary)]">Mancanti</p>
            </div>
          </div>

          {/* VM List */}
          {data.vms?.length > 0 && (
            <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-hidden" data-testid="backup-vm-list">
              <div className="p-3 border-b border-[var(--bg-border)]">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Virtual Machine</h3>
              </div>
              <div className="divide-y divide-[var(--bg-border)]">
                {data.vms.map((vm, i) => {
                  const cfg = statusConfig[vm.backup_status] || statusConfig.unknown;
                  return (
                    <div key={i} className="flex items-center justify-between px-4 py-3 hover:bg-[var(--bg-surface)] transition-colors cursor-pointer"
                      onClick={() => openVmDetail(vm.vm_name)} data-testid={`backup-vm-${i}`}>
                      <div className="flex items-center gap-3">
                        <div className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
                        <div>
                          <p className="text-sm font-semibold text-[var(--text-primary)]">{vm.vm_name}</p>
                          <p className="text-xs text-[var(--text-secondary)]">
                            Stato VM: <span className={vmStateConfig[vm.vm_state] || "text-gray-400"}>{vm.vm_state || "N/D"}</span>
                            {vm.memory_mb ? ` | RAM: ${vm.memory_mb} MB` : ""}
                            {vm.checkpoint_count > 0 && <span className="text-amber-400"> | {vm.checkpoint_count} checkpoint</span>}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-4 text-xs">
                        <div className="text-right">
                          <p className="text-[var(--text-secondary)]">Ultimo backup</p>
                          <p className="font-medium text-[var(--text-primary)]">{fmtTime(vm.last_backup_time)}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-[var(--text-secondary)]">Dimensione</p>
                          <p className="font-medium text-[var(--text-primary)]">{formatBytes(vm.last_backup_size_bytes)}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-[var(--text-secondary)]">Prossimo</p>
                          <p className="font-medium text-[var(--text-primary)]">{fmtTime(vm.next_backup_time)}</p>
                        </div>
                        <span className={`px-2 py-1 rounded-md text-xs font-bold ${cfg.bg} ${cfg.color}`}>
                          {cfg.label}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* History Chart */}
          {history.length > 0 && (
            <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid="backup-history-chart">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Storico Backup (ultimi 7 giorni)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={history}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--bg-border)" />
                  <XAxis dataKey="timestamp" tickFormatter={fmtDate} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                  <Tooltip labelFormatter={fmtTime} contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--bg-border)", borderRadius: 8, fontSize: 11 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="backup_ok" name="OK" fill="#10b981" radius={[2, 2, 0, 0]} stackId="a" />
                  <Bar dataKey="backup_warning" name="Warning" fill="#f59e0b" radius={[0, 0, 0, 0]} stackId="a" />
                  <Bar dataKey="backup_failed" name="Falliti" fill="#ef4444" radius={[0, 0, 0, 0]} stackId="a" />
                  <Bar dataKey="backup_missing" name="Mancanti" fill="#f97316" radius={[2, 2, 0, 0]} stackId="a" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Hyper-V VMs (additional info) */}
          {data.hyperv_vms?.length > 0 && data.vms?.length === 0 && (
            <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] overflow-hidden">
              <div className="p-3 border-b border-[var(--bg-border)]">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">VM Hyper-V (senza dati backup)</h3>
              </div>
              <div className="divide-y divide-[var(--bg-border)]">
                {data.hyperv_vms.map((vm, i) => (
                  <div key={i} className="flex items-center justify-between px-4 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${vm.state === "Running" ? "bg-emerald-500" : "bg-red-500"}`} />
                      <span className="font-medium text-[var(--text-primary)]">{vm.name}</span>
                    </div>
                    <span className={vmStateConfig[vm.state] || "text-gray-400"}>{vm.state}</span>
                    <span className="text-[var(--text-secondary)]">{vm.memory_mb} MB RAM</span>
                    <span className="text-[var(--text-secondary)]">CPU: {vm.cpu_usage}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Empty state */}
          {!data.has_data && (
            <div className="text-center py-16">
              <svg className="w-14 h-14 mx-auto mb-3 text-[var(--text-secondary)] opacity-40" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
              </svg>
              <p className="text-sm text-[var(--text-secondary)]">Nessun dato backup disponibile.</p>
              <p className="text-xs text-[var(--text-secondary)] mt-2">
                Configura le credenziali Altaro nel connettore (altaro_username, altaro_password)<br />
                Il connettore inviera automaticamente lo stato dei backup al prossimo ciclo.
              </p>
            </div>
          )}
        </>
      )}

      {/* VM Detail Modal */}
      {selectedVm && vmDetail && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setSelectedVm(null)}>
          <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--bg-border)] p-5 max-w-lg w-full max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()} data-testid="backup-vm-detail-modal">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-[var(--text-primary)]">{vmDetail.vm_name}</h2>
              <button onClick={() => setSelectedVm(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            {vmDetail.backup && (
              <div className="space-y-2 mb-4">
                <h3 className="text-xs font-semibold text-[var(--text-secondary)] uppercase">Stato Backup</h3>
                {[
                  ["Stato", (statusConfig[vmDetail.backup.backup_status] || statusConfig.unknown).label],
                  ["Ultimo Backup", fmtTime(vmDetail.backup.last_backup_time)],
                  ["Dimensione", formatBytes(vmDetail.backup.last_backup_size_bytes)],
                  ["Prossimo", fmtTime(vmDetail.backup.next_backup_time)],
                  ["Tipo", vmDetail.backup.backup_type || "N/D"],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between text-xs">
                    <span className="text-[var(--text-secondary)]">{k}</span>
                    <span className="font-medium text-[var(--text-primary)]">{v}</span>
                  </div>
                ))}
              </div>
            )}

            {vmDetail.hyperv && (
              <div className="space-y-2 mb-4">
                <h3 className="text-xs font-semibold text-[var(--text-secondary)] uppercase">Hyper-V</h3>
                {[
                  ["Stato VM", vmDetail.hyperv.state],
                  ["CPU", `${vmDetail.hyperv.cpu_usage || 0}%`],
                  ["RAM", `${vmDetail.hyperv.memory_mb || 0} MB`],
                  ["Uptime", vmDetail.hyperv.uptime || "N/D"],
                  ["Generazione", vmDetail.hyperv.generation],
                  ["Checkpoint", vmDetail.hyperv.checkpoint_count || 0],
                  ["Replica", vmDetail.hyperv.replication_state || "None"],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between text-xs">
                    <span className="text-[var(--text-secondary)]">{k}</span>
                    <span className="font-medium text-[var(--text-primary)]">{String(v)}</span>
                  </div>
                ))}
              </div>
            )}

            {vmDetail.alerts?.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-[var(--text-secondary)] uppercase mb-2">Storico Alert Backup</h3>
                {vmDetail.alerts.map((a, i) => (
                  <div key={i} className={`text-xs p-2 rounded-md mb-1 ${a.resolved ? "bg-[var(--bg-surface)]" : "bg-red-500/5 border border-red-500/20"}`}>
                    <div className="flex justify-between">
                      <span className={a.resolved ? "text-[var(--text-secondary)]" : "text-red-400 font-semibold"}>{a.title}</span>
                      <span className="text-[var(--text-secondary)]">{fmtTime(a.created_at)}</span>
                    </div>
                    {a.resolved && <span className="text-emerald-400 text-[10px]">Risolto: {fmtTime(a.resolved_at)}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
