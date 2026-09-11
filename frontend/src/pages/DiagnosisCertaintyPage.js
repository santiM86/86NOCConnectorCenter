import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Target, RefreshCw, ShieldCheck, ShieldAlert, ChevronDown, ChevronUp, GitCompare } from "lucide-react";
import { API } from "@/App";
import FusionEvidence from "@/components/FusionEvidence";

const SRC = { ping: "Ping", l2: "L2", datto: "Datto", hyperv: "Hyper-V", ilo: "iLO", port: "Porta", port_memory: "Memoria", schedule: "Orario", nebula: "Nebula", flap: "Flap", ups: "UPS", snmp: "SNMP" };
const confCls = c => c >= 90 ? "text-emerald-300" : c >= 80 ? "text-amber-300" : "text-red-300";

function Kpi({ label, value, sub, testid, tone = "" }) {
  return (
    <div className="noc-panel p-3" data-testid={testid}>
      <p className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
      <p className={`text-2xl font-bold font-mono ${tone}`}>{value}</p>
      {sub && <p className="text-[10px] text-[var(--text-muted)]">{sub}</p>}
    </div>
  );
}

function DeviceRow({ d, clientId }) {
  const [open, setOpen] = useState(false);
  const down = d.reachable === false;
  return (
    <>
      <tr className={`cursor-pointer ${open ? "bg-cyan-500/5" : ""}`} onClick={() => setOpen(o => !o)} data-testid={`fusion-row-${d.ip}`}>
        <td>
          <span className={`inline-block w-2 h-2 rounded-full mr-2 ${down ? "bg-red-400" : d.reachable ? "bg-emerald-400" : "bg-neutral-500"}`} />
          <b className="text-[var(--text-primary)]">{d.name}</b> <span className="font-mono text-[10px] text-[var(--text-muted)]">{d.ip}</span>
          {d.is_vital && <span className="ml-1 text-[8px] px-1 rounded bg-rose-500/20 text-rose-200">VITALE</span>}
        </td>
        <td className="text-[10px]">{d.device_type || d.family}</td>
        <td><span className={`font-mono font-bold ${confCls(d.max_confidence)}`} data-testid={`fusion-max-${d.ip}`}>{d.max_confidence}%</span></td>
        <td className="text-[10px]">
          <span className="inline-flex flex-wrap gap-1">{(d.sources || []).map(s => <span key={s} className="px-1 rounded bg-emerald-500/15 text-emerald-200 border border-emerald-500/30 text-[9px]">{SRC[s] || s}</span>)}</span>
        </td>
        <td className="text-[10px]">
          {down ? <><span className="text-[var(--text-primary)]">{d.verdict_label}</span> <span className={`font-mono font-bold ${confCls(d.confidence)}`}>{d.confidence}%</span>{d.conflict && <span className="ml-1 text-amber-300">conflitto</span>}</> : <span className="text-[var(--text-muted)]">—</span>}
        </td>
        <td className="text-[10px] text-amber-200">{(d.missing || []).length ? `${d.missing.length} azioni` : <span className="text-emerald-300">completo</span>}</td>
        <td className="text-[var(--text-muted)]">{open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</td>
      </tr>
      {open && (
        <tr data-testid={`fusion-detail-${d.ip}`}>
          <td colSpan={7} className="bg-[var(--bg-card)] p-3">
            {(d.missing || []).length > 0 && (
              <div className="mb-2">
                <p className="text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-1">Per arrivare al 90%</p>
                <ul className="space-y-0.5">{d.missing.map((m, i) => <li key={i} className="text-[11px]"><span className="text-amber-200">→ {m.action}</span> <span className="text-[var(--text-muted)]">· {m.gain}</span></li>)}</ul>
              </div>
            )}
            {down && <FusionEvidence ip={d.ip} clientId={clientId} />}
          </td>
        </tr>
      )}
    </>
  );
}

function ShadowPanel({ clientId }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    axios.get(`${API}/fusion/shadow`, { params: clientId ? { client_id: clientId } : {} }).then(r => setData(r.data)).catch(() => {});
  }, [clientId]);
  if (!data) return null;
  return (
    <div className="noc-panel p-3 space-y-2" data-testid="fusion-shadow">
      <h3 className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-indigo-300"><GitCompare size={13} /> Confronto motori (ultimi verdetti su device giù)</h3>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-[11px]">
        <div><span className="text-[var(--text-muted)]">Valutati</span><br /><b className="font-mono">{data.total}</b></div>
        <div><span className="text-[var(--text-muted)]">Accordo</span><br /><b className="font-mono text-emerald-300">{data.agree}</b> / <span className="font-mono text-amber-300">{data.disagree}</span></div>
        <div><span className="text-[var(--text-muted)]">Conf. media v1 → v2</span><br /><b className="font-mono">{data.avg_conf_v1}% → <span className="text-cyan-300">{data.avg_conf_v2}%</span></b></div>
        <div><span className="text-[var(--text-muted)]">≥90% v1 → v2</span><br /><b className="font-mono">{data.v1_ge_90} → <span className="text-cyan-300">{data.v2_ge_90}</span></b></div>
      </div>
      {data.promotion && (
        <div className={`rounded border p-2 text-[11px] ${data.promotion.enabled ? "border-emerald-500/40 bg-emerald-500/5" : "border-indigo-500/30 bg-indigo-500/5"}`} data-testid="fusion-promotion">
          {data.promotion.enabled ? (
            <span className="text-emerald-300">Motore v2 attivo{data.promotion.promoted_at ? ` dal ${new Date(data.promotion.promoted_at).toLocaleString("it-IT")}` : ""}.</span>
          ) : (
            <>
              <b className="text-indigo-200">Auto-attivazione {data.promotion.auto_promote ? "ON" : "OFF"}</b>
              <span className="text-[var(--text-secondary)]"> — il v2 passa in produzione da solo quando i casi reali in shadow soddisfano i criteri:</span>
              <div className="grid grid-cols-3 gap-2 mt-1 font-mono text-[10px]">
                <span className={data.promotion.cases >= data.promotion.min_cases ? "text-emerald-300" : "text-amber-300"} data-testid="fusion-promo-cases">casi {data.promotion.cases}/{data.promotion.min_cases}</span>
                <span className={data.promotion.agree_pct >= data.promotion.min_agree_pct ? "text-emerald-300" : "text-amber-300"} data-testid="fusion-promo-agree">accordo {data.promotion.agree_pct}% (min {data.promotion.min_agree_pct}%)</span>
                <span className={data.promotion.days >= data.promotion.min_days ? "text-emerald-300" : "text-amber-300"} data-testid="fusion-promo-days">giorni {data.promotion.days}/{data.promotion.min_days}</span>
              </div>
            </>
          )}
        </div>
      )}
      {data.rows.length > 0 && (
        <div className="overflow-x-auto"><table className="noc-table w-full text-[10px]" data-testid="fusion-shadow-table">
          <thead><tr><th>Device</th><th>v1</th><th>v2</th><th>Fonti v2</th><th>Ora</th></tr></thead>
          <tbody>{data.rows.slice(0, 50).map(r => (
            <tr key={r.device_ip} className={r.agree ? "" : "bg-amber-500/5"}>
              <td><b>{r.device_name}</b> <span className="font-mono text-[var(--text-muted)]">{r.device_ip}</span></td>
              <td>{r.v1.root_cause} <span className={`font-mono ${confCls(r.v1.confidence)}`}>{r.v1.confidence}%</span></td>
              <td>{r.v2.label} <span className={`font-mono ${confCls(r.v2.confidence)}`}>{r.v2.confidence}%</span>{r.v2.conflict && <span className="text-amber-300"> ⚠</span>}</td>
              <td>{(r.v2.sources || []).map(s => SRC[s] || s).join(", ")}</td>
              <td className="text-[var(--text-muted)]">{new Date(r.ts).toLocaleTimeString("it-IT")}</td>
            </tr>))}</tbody>
        </table></div>
      )}
      {data.rows.length === 0 && <p className="text-[10px] text-[var(--text-muted)]">Nessun device giù valutato nell'ultimo giorno: il confronto si popola automaticamente al prossimo down.</p>}
    </div>
  );
}

export default function DiagnosisCertaintyPage() {
  const [clients, setClients] = useState([]);
  const [cid, setCid] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [cfg, setCfg] = useState(null);
  const [onlyGaps, setOnlyGaps] = useState(true);

  useEffect(() => {
    axios.get(`${API}/clients`).then(r => { const cs = r.data || []; setClients(cs); if (cs[0] && !cid) setCid(cs[0].id); }).catch(() => {});
    axios.get(`${API}/fusion/config`).then(r => setCfg(r.data)).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(() => {
    if (!cid) return;
    setLoading(true);
    axios.get(`${API}/fusion/certainty/${cid}`, { timeout: 120000 }).then(r => setData(r.data))
      .catch(e => toast.error(e.response?.data?.detail || "Errore caricamento")).finally(() => setLoading(false));
  }, [cid]);
  useEffect(load, [load]);

  const toggle = async () => {
    const next = !cfg?.fusion_v2_enabled;
    if (next && !window.confirm("Attivare il motore v2 per gli ALERT reali? I verdetti sui device giù useranno la fusione delle prove.")) return;
    try {
      const r = await axios.put(`${API}/fusion/config`, { fusion_v2_enabled: next });
      setCfg(r.data); toast.success(next ? "Motore v2 ATTIVO sugli alert" : "Motore v2 in sola modalità shadow");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const rows = (data?.devices || []).filter(d => !onlyGaps || d.max_confidence < 90 || d.reachable === false);

  return (
    <div className="space-y-4 p-3 md:p-5" data-testid="fusion-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-base md:text-lg font-bold flex items-center gap-2"><Target size={18} className="text-cyan-300" /> Certezza diagnosi</h1>
        <select value={cid} onChange={e => setCid(e.target.value)} className="h-8 px-2 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]" data-testid="fusion-client-select">
          {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button onClick={load} className="h-8 px-2 rounded border border-[var(--bg-border)] text-[11px] flex items-center gap-1 hover:bg-[var(--bg-hover)]" data-testid="fusion-refresh"><RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Aggiorna</button>
        <label className="ml-auto flex items-center gap-2 text-[11px] cursor-pointer" data-testid="fusion-v2-toggle-label">
          <input type="checkbox" checked={!!cfg?.fusion_v2_enabled} onChange={toggle} className="accent-cyan-400" data-testid="fusion-v2-toggle" />
          {cfg?.fusion_v2_enabled ? <span className="text-emerald-300 flex items-center gap-1"><ShieldCheck size={13} /> Motore v2 guida gli alert</span> : <span className="text-amber-300 flex items-center gap-1"><ShieldAlert size={13} /> Motore v2 in shadow (alert su v1)</span>}
        </label>
      </div>
      <p className="text-[11px] text-[var(--text-secondary)] max-w-3xl">Ogni fonte (ping, MAC, Datto, iLO, porta switch, memoria porta, orario, UPS, Nebula, Hyper-V) è una prova indipendente. Servono <b>3 fonti concordi</b> per una diagnosi ≥90%. Qui vedi, device per device, quante fonti abbiamo già e cosa manca per arrivarci.</p>

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi label="Device pronti al 90%" value={`${data.ready_90}/${data.total}`} sub={`${data.total ? Math.round(100 * data.ready_90 / data.total) : 0}% del parco`} testid="fusion-kpi-ready" tone={data.ready_90 === data.total ? "text-emerald-300" : "text-amber-300"} />
          <Kpi label="Confidenza massima media" value={`${data.avg_max_confidence}%`} testid="fusion-kpi-avg" tone={confCls(data.avg_max_confidence)} />
          <Kpi label="Device giù ora" value={data.down} sub={`${data.down_ge_90} con diagnosi ≥90%`} testid="fusion-kpi-down" tone={data.down ? "text-red-300" : "text-emerald-300"} />
          <div className="noc-panel p-3" data-testid="fusion-kpi-missing">
            <p className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">Cosa manca di più</p>
            <ul className="mt-1 space-y-0.5">{data.missing_summary.slice(0, 3).map(m => <li key={m.key} className="text-[10px]"><b className="font-mono text-amber-300">{m.count}</b> <span className="text-[var(--text-secondary)]">{m.example}</span></li>)}</ul>
          </div>
        </div>
      )}

      <ShadowPanel clientId={cid} />

      <div className="noc-panel">
        <div className="flex items-center gap-3 px-3 py-2 border-b border-[var(--bg-border)] text-[11px]">
          <b>Dispositivi ({rows.length})</b>
          <label className="ml-auto flex items-center gap-1.5 cursor-pointer"><input type="checkbox" checked={onlyGaps} onChange={e => setOnlyGaps(e.target.checked)} className="accent-cyan-400" data-testid="fusion-only-gaps" /> Solo sotto 90% o giù</label>
        </div>
        <div className="overflow-x-auto">
          <table className="noc-table w-full text-[11px]" data-testid="fusion-table">
            <thead><tr><th>Device</th><th>Tipo</th><th>Max %</th><th>Fonti disponibili</th><th>Verdetto attuale</th><th>Da fare</th><th /></tr></thead>
            <tbody>{rows.map(d => <DeviceRow key={d.ip} d={d} clientId={cid} />)}</tbody>
          </table>
          {loading && <p className="text-center text-[11px] text-[var(--text-muted)] py-4">Calcolo copertura fonti…</p>}
          {!loading && data && rows.length === 0 && <p className="text-center text-[11px] text-emerald-300 py-4">Tutti i device hanno copertura ≥90%.</p>}
        </div>
      </div>
    </div>
  );
}
