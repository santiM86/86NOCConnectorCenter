import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ShieldCheck, ShieldAlert, FileDown, RefreshCw, UserCog, Search, Lock } from "lucide-react";
import { API } from "@/App";

const CAT = {
  logon_success: ["Accesso", "text-emerald-300"], logon_failed: ["Fallito", "text-red-300"], logoff: ["Logoff", "text-[var(--text-muted)]"],
  privileged_logon: ["Privilegi admin", "text-amber-300"], account_created: ["Account creato", "text-red-300"], account_deleted: ["Account eliminato", "text-red-300"],
  account_enabled: ["Abilitato", "text-amber-300"], account_disabled: ["Disabilitato", "text-amber-300"], password_reset: ["Reset psw", "text-amber-300"],
  group_change: ["Gruppo", "text-red-300"], lockout: ["Lockout", "text-amber-300"], log_cleared: ["LOG CANCELLATO", "text-red-400 font-bold"],
  power_on: ["Avvio", "text-cyan-300"], power_off: ["Arresto", "text-cyan-300"], power_crash: ["Crash", "text-red-300"],
  rdp_connect: ["RDP", "text-violet-300"], rdp_session: ["Sessione RDP", "text-violet-300"],
};
const PERIODS = [["24", "24h"], ["168", "7gg"], ["720", "30gg"], ["2160", "90gg"]];
const inp = "h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]";
const fmt = (ts) => { try { return new Date(ts).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "medium" }); } catch { return ts; } };

function Tile({ label, value, tone = "", testid }) {
  return (
    <div className="noc-panel p-3" data-testid={testid}>
      <div className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">{label}</div>
      <div className={`text-xl font-bold mt-1 ${tone}`}>{value}</div>
    </div>
  );
}

function AdminsEditor({ clientId, admins, onSaved }) {
  const [val, setVal] = useState(admins.join(", "));
  useEffect(() => setVal(admins.join(", ")), [admins]);
  const save = async () => {
    try {
      await axios.put(`${API}/seclog/admins/${clientId}`, { users: val.split(/[,\n;]+/).map(s => s.trim()).filter(Boolean) });
      toast.success("Elenco Amministratori di Sistema salvato"); onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore salvataggio"); }
  };
  return (
    <div className="noc-panel p-3 space-y-2" data-testid="seclog-admins">
      <div className="text-[11px] font-semibold flex items-center gap-1.5"><UserCog size={13} className="text-amber-300" /> Amministratori di Sistema designati (nomina formale)</div>
      <p className="text-[10px] text-[var(--text-muted)]">Nomi utente separati da virgola (es. <code>administrator, m.rossi, it-admin</code>). Gli accessi di questi utenti vengono marcati "AdS" nel registro e nel report; in più sono sempre marcati gli accessi con privilegi speciali (Event 4672).</p>
      <div className="flex gap-2">
        <Input value={val} onChange={e => setVal(e.target.value)} placeholder="administrator, nome.cognome" className={inp} data-testid="seclog-admins-input" />
        <Button size="sm" onClick={save} className="h-8 text-xs bg-amber-600 hover:bg-amber-700 text-white" data-testid="seclog-admins-save">Salva</Button>
      </div>
    </div>
  );
}

export default function SecurityLogPage() {
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState(localStorage.getItem("seclog_client") || "");
  const [hours, setHours] = useState("168");
  const [filters, setFilters] = useState({ category: "", q: "", admin_only: false, host: "" });
  const [stats, setStats] = useState(null);
  const [data, setData] = useState({ total: 0, events: [] });
  const [verify, setVerify] = useState(null);
  const [busy, setBusy] = useState(false);
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));

  useEffect(() => { axios.get(`${API}/clients`).then(r => { const l = r.data?.clients || r.data || []; setClients(l); if (!clientId && l[0]) setClientId(l[0].id); }).catch(() => {}); }, []); // eslint-disable-line

  const load = useCallback(async () => {
    if (!clientId) return;
    localStorage.setItem("seclog_client", clientId);
    setBusy(true);
    try {
      const p = { client_id: clientId, hours, limit: 300 };
      if (filters.category) p.category = filters.category;
      if (filters.q) p.q = filters.q;
      if (filters.host) p.host = filters.host;
      if (filters.admin_only) p.admin_only = true;
      const [s, e] = await Promise.all([axios.get(`${API}/seclog/stats`, { params: { client_id: clientId, hours } }), axios.get(`${API}/seclog/events`, { params: p })]);
      setStats(s.data); setData(e.data);
    } catch (err) { toast.error(err.response?.data?.detail || "Errore caricamento registro"); }
    finally { setBusy(false); }
  }, [clientId, hours, filters]);
  useEffect(() => { load(); }, [load]);

  const doVerify = async () => {
    try { const { data: v } = await axios.get(`${API}/seclog/verify`, { params: { client_id: clientId } }); setVerify(v); v.ok ? toast.success(`Integrità verificata: ${v.checked} eventi`) : toast.error(`Catena COMPROMESSA al seq #${v.broken_at_seq}`); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore verifica"); }
  };
  const downloadPdf = async () => {
    try {
      const r = await axios.get(`${API}/seclog/report.pdf`, { params: { client_id: clientId, month }, responseType: "blob" });
      const url = URL.createObjectURL(r.data); const a = document.createElement("a"); a.href = url; a.download = `registro-ads-${month}.pdf`; a.click(); URL.revokeObjectURL(url);
    } catch (e) { toast.error("Errore generazione PDF"); }
  };

  const bc = stats?.by_category || {};
  const clientName = clients.find(c => c.id === clientId)?.name || "";
  return (
    <div className="space-y-4 p-3 md:p-5" data-testid="seclog-page">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-base md:text-lg font-bold flex items-center gap-2"><Lock size={18} className="text-amber-300" /> Registro accessi Amministratori di Sistema</h1>
        <span className="text-[10px] text-[var(--text-muted)]">Garante 27/11/2008 · GDPR art. 32 · NIS2 · catena hash SHA-256</span>
        <div className="ml-auto flex items-center gap-2 flex-wrap">
          <select value={clientId} onChange={e => setClientId(e.target.value)} className={`${inp} rounded-md px-2`} data-testid="seclog-client-select">
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <div className="flex rounded-md border border-[var(--bg-border)] overflow-hidden">
            {PERIODS.map(([h, l]) => <button key={h} onClick={() => setHours(h)} className={`px-2 h-8 text-[11px] ${hours === h ? "bg-amber-500/20 text-amber-200" : "text-[var(--text-muted)]"}`} data-testid={`seclog-period-${l}`}>{l}</button>)}
          </div>
          <Button size="sm" variant="outline" onClick={load} disabled={busy} className="h-8 text-xs" data-testid="seclog-refresh"><RefreshCw size={12} className={busy ? "animate-spin" : ""} /></Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
        <Tile label="Accessi AdS" value={stats?.admin_events ?? "—"} tone="text-amber-300" testid="seclog-kpi-admin" />
        <Tile label="Accessi riusciti" value={bc.logon_success ?? 0} tone="text-emerald-300" testid="seclog-kpi-ok" />
        <Tile label="Accessi falliti" value={bc.logon_failed ?? 0} tone={bc.logon_failed ? "text-red-300" : ""} testid="seclog-kpi-failed" />
        <Tile label="RDP" value={(bc.rdp_connect || 0) + (bc.rdp_session || 0)} tone="text-violet-300" testid="seclog-kpi-rdp" />
        <Tile label="Account / gruppi" value={(bc.account_created || 0) + (bc.account_deleted || 0) + (bc.group_change || 0)} tone={(bc.account_created || bc.group_change) ? "text-red-300" : ""} testid="seclog-kpi-accounts" />
        <Tile label="Eventi totali (storico)" value={stats?.total_all_time ?? "—"} testid="seclog-kpi-total" />
      </div>

      <div className="grid md:grid-cols-3 gap-3">
        <div className="noc-panel p-3 space-y-2 md:col-span-2" data-testid="seclog-integrity">
          <div className="flex items-center gap-2 flex-wrap">
            {verify ? (verify.ok ? <ShieldCheck size={16} className="text-emerald-400" /> : <ShieldAlert size={16} className="text-red-400" />) : <ShieldCheck size={16} className="text-[var(--text-muted)]" />}
            <span className="text-[11px] font-semibold">Integrità del registro (catena hash)</span>
            <span className="text-[10px] text-[var(--text-muted)]">seq #{stats?.chain?.last_seq ?? 0} · ultimo hash <code>{(stats?.chain?.last_hash || "").slice(0, 16)}…</code> · retention {stats?.retention_months ?? 12} mesi</span>
            <Button size="sm" variant="outline" onClick={doVerify} className="h-7 text-xs ml-auto" data-testid="seclog-verify-btn">Verifica integrità</Button>
          </div>
          {verify && <div className={`text-[11px] ${verify.ok ? "text-emerald-300" : "text-red-300"}`} data-testid="seclog-verify-result">{verify.ok ? `✔ ${verify.checked} eventi verificati, nessuna alterazione.` : `✖ ${verify.reason} (seq #${verify.broken_at_seq})`}</div>}
          <div className="flex items-center gap-2 pt-1 border-t border-[var(--bg-border)]">
            <FileDown size={14} className="text-indigo-300" />
            <span className="text-[11px]">Report mensile PDF (accessi AdS + eventi di sicurezza + attestazione integrità)</span>
            <input type="month" value={month} onChange={e => setMonth(e.target.value)} className={`${inp} rounded-md px-2 ml-auto`} data-testid="seclog-report-month" />
            <Button size="sm" onClick={downloadPdf} className="h-8 text-xs bg-indigo-600 hover:bg-indigo-700 text-white" data-testid="seclog-report-btn">Scarica PDF</Button>
          </div>
          <div className="text-[10px] text-[var(--text-muted)]">Server monitorati: {(stats?.hosts || []).length ? stats.hosts.map(h => `${h.host} (${h.n})`).join(" · ") : "nessun evento ricevuto — serve Agent Go ≥ v4.31 su Windows Server/PC (raccoglie Security/System/RDP)."}</div>
        </div>
        <AdminsEditor clientId={clientId} admins={stats?.admins || []} onSaved={load} />
      </div>

      <div className="noc-panel" data-testid="seclog-table">
        <div className="px-3 py-2 border-b border-[var(--bg-border)] flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-semibold">Eventi ({data.total}) — {clientName}</span>
          <select value={filters.category} onChange={e => setFilters(f => ({ ...f, category: e.target.value }))} className={`${inp} rounded-md px-2 ml-auto`} data-testid="seclog-filter-category">
            <option value="">Tutte le categorie</option>
            {Object.entries(CAT).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <select value={filters.host} onChange={e => setFilters(f => ({ ...f, host: e.target.value }))} className={`${inp} rounded-md px-2`} data-testid="seclog-filter-host">
            <option value="">Tutti i server</option>
            {(stats?.hosts || []).map(h => <option key={h.host} value={h.host}>{h.host}</option>)}
          </select>
          <label className="text-[11px] flex items-center gap-1 cursor-pointer"><input type="checkbox" checked={filters.admin_only} onChange={e => setFilters(f => ({ ...f, admin_only: e.target.checked }))} data-testid="seclog-filter-admin" /> solo AdS</label>
          <div className="relative"><Search size={12} className="absolute left-2 top-2.5 text-[var(--text-muted)]" /><Input value={filters.q} onChange={e => setFilters(f => ({ ...f, q: e.target.value }))} placeholder="utente / IP / host" className={`${inp} pl-6 w-44`} data-testid="seclog-filter-q" /></div>
        </div>
        <div className="overflow-x-auto">
          <table className="noc-table w-full text-[11px]">
            <thead><tr><th>Data/ora</th><th>Server</th><th>Evento</th><th>Utente</th><th>Tipo accesso</th><th>Origine</th><th>AdS</th><th>Seq</th></tr></thead>
            <tbody>
              {data.events.map(e => {
                const [lbl, tone] = CAT[e.category] || [e.category, ""];
                return (
                  <tr key={e.id} data-testid={`seclog-row-${e.seq}`} className={e.severity === "critical" ? "bg-red-500/10" : e.severity === "high" ? "bg-amber-500/5" : ""}>
                    <td className="font-mono whitespace-nowrap">{fmt(e.ts)}</td>
                    <td className="font-mono">{e.host}</td>
                    <td><span className={tone}>{lbl}</span> <span className="text-[var(--text-muted)]">· {e.label} ({e.event_id})</span></td>
                    <td className="font-mono">{e.domain ? `${e.domain}\\` : ""}{e.user}{e.target_user && e.target_user !== e.user ? <span className="text-[var(--text-muted)]"> → {e.target_user}</span> : null}{e.group ? <span className="text-red-300"> [{e.group}]</span> : null}</td>
                    <td>{e.logon_type_label || "—"}</td>
                    <td className="font-mono">{e.src_ip || e.workstation || "—"}</td>
                    <td>{e.is_admin ? <span className="text-[9px] px-1 rounded bg-amber-500/20 text-amber-200 font-bold">AdS</span> : ""}</td>
                    <td className="font-mono text-[var(--text-muted)]" title={`hash ${e.hash}`}>#{e.seq}</td>
                  </tr>
                );
              })}
              {!data.events.length && <tr><td colSpan={8} className="text-center py-8 text-[var(--text-muted)]">Nessun evento nel periodo selezionato.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
