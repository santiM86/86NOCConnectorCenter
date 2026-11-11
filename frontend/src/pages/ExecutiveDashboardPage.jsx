import { useEffect, useState } from "react";
import axios from "axios";
import { Gauge, ShieldCheck, Warning, XCircle, CheckCircle, UserCircle, Timer, Siren } from "@phosphor-icons/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const LEVEL = { alto: "#F87171", medio: "#FBBF24", basso: "#34D399" };
const ST = { ok: [CheckCircle, "text-emerald-400"], warn: [Warning, "text-amber-400"], ko: [XCircle, "text-red-400"] };
const UEBA_LABEL = { ueba_impossible: "accesso impossibile", ueba_bruteforce_ok: "brute force riuscito", ueba_new_host: "nuovo host",
  ueba_unusual_hour: "orario insolito", seclog_new_origin: "origine nuova", seclog_after_hours: "fuori orario", seclog_usb_insert: "USB" };
const fmtMin = (m) => (m == null ? "—" : m < 60 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} h`);

const Kpi = ({ icon: Icon, label, value, sub, tid, color = "text-white" }) => (
  <div className="noc-panel p-4" data-testid={tid}>
    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--text-muted)]"><Icon size={12} /> {label}</div>
    <div className={`text-2xl font-bold mt-1 ${color}`}>{value}</div>
    {sub && <div className="text-[10px] text-[var(--text-muted)] mt-0.5">{sub}</div>}
  </div>
);

const RiskGauge = ({ score, level }) => {
  const c = LEVEL[level] || "#94A3B8";
  const deg = Math.round((score / 100) * 270);
  return (
    <div className="noc-panel p-5 flex items-center gap-5" data-testid="exec-risk">
      <div className="relative w-28 h-28 rounded-full" style={{ background: `conic-gradient(from 225deg, ${c} ${deg}deg, rgba(255,255,255,0.06) ${deg}deg 270deg, transparent 270deg)` }}>
        <div className="absolute inset-2 rounded-full bg-[var(--bg-app)] flex flex-col items-center justify-center">
          <span className="text-3xl font-bold" style={{ color: c }} data-testid="exec-risk-score">{score}</span>
          <span className="text-[9px] uppercase text-[var(--text-muted)]">/100</span>
        </div>
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Rischio complessivo</div>
        <div className="text-xl font-bold capitalize" style={{ color: c }} data-testid="exec-risk-level">{level}</div>
        <p className="text-[10px] text-[var(--text-muted)] max-w-[220px] mt-1">Calcolato da alert attivi, utenti a rischio (UEBA) e conformità.</p>
      </div>
    </div>
  );
};

export default function ExecutiveDashboardPage() {
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState("");
  const [days, setDays] = useState(30);
  const [d, setD] = useState(null);
  useEffect(() => { axios.get(`${API}/clients`).then(({ data }) => setClients(data || [])).catch(() => {}); }, []);
  useEffect(() => {
    let alive = true;
    setD(null);
    axios.get(`${API}/executive/summary`, { params: { client_id: clientId || undefined, days } })
      .then(({ data }) => alive && setD(data)).catch(() => alive && setD({ error: true }));
    return () => { alive = false; };
  }, [clientId, days]);

  return (
    <div className="p-4 md:p-8 space-y-5" data-testid="executive-dashboard">
      <div className="flex items-end gap-3 flex-wrap">
        <div className="mr-auto">
          <h1 className="text-2xl md:text-3xl font-bold text-white">Dashboard Direzione</h1>
          <p className="text-[12px] text-[var(--text-muted)]">Rischio, incidenti, tempi di risposta e conformità NIS2/GDPR.</p>
        </div>
        <select value={clientId} onChange={(e) => setClientId(e.target.value)} className="bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2 py-1.5 text-[12px] text-white" data-testid="exec-client-select">
          <option value="">Tutti i clienti</option>
          {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2 py-1.5 text-[12px] text-white" data-testid="exec-days-select">
          <option value={7}>7 giorni</option><option value={30}>30 giorni</option><option value={90}>90 giorni</option>
        </select>
      </div>
      {!d ? <p className="text-[12px] text-[var(--text-muted)]">Caricamento…</p> : d.error ? <p className="text-red-300 text-[12px]">Errore caricamento</p> : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <RiskGauge score={d.risk_score} level={d.risk_level} />
            <div className="lg:col-span-2 grid grid-cols-2 md:grid-cols-4 gap-3">
              <Kpi icon={Siren} label="Alert attivi" value={d.active_alerts} sub={`${d.alerts_by_severity.critical} critici · ${d.alerts_by_severity.high} alti nel periodo`} tid="exec-kpi-alerts" />
              <Kpi icon={ShieldCheck} label="Incidenti" value={d.incidents_period} sub={`${d.incidents_open} aperti · ${d.incidents_auto} correlati in automatico`} tid="exec-kpi-incidents" />
              <Kpi icon={Timer} label="Presa in carico" value={fmtMin(d.mtta_min)} sub="tempo medio (MTTA)" tid="exec-kpi-mtta" />
              <Kpi icon={Gauge} label="Risoluzione" value={fmtMin(d.mttr_min)} sub="tempo medio (MTTR)" tid="exec-kpi-mttr" />
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="noc-panel p-4" data-testid="exec-compliance">
              <div className="flex items-center gap-2 mb-3">
                <h2 className="text-sm font-bold text-white">Conformità NIS2 / GDPR</h2>
                <span className="ml-auto text-lg font-bold text-cyan-300" data-testid="exec-compliance-score">{d.compliance_score}%</span>
              </div>
              <ul className="space-y-2">
                {d.compliance.map((c) => {
                  const [Icon, cls] = ST[c.status];
                  return (
                    <li key={c.key} className="flex items-start gap-2" data-testid={`exec-comp-${c.key}`}>
                      <Icon size={15} weight="fill" className={`${cls} mt-0.5 shrink-0`} />
                      <div className="min-w-0">
                        <div className="text-[12px] text-white">{c.label} <span className="text-[9px] text-[var(--text-muted)] font-mono">{c.norm}</span></div>
                        <div className="text-[10px] text-[var(--text-muted)]">{c.detail}</div>
                      </div>
                    </li>
                  );
                })}
              </ul>
              <p className="text-[9px] text-[var(--text-muted)] mt-3">Indicatori tecnici di supporto: non sostituiscono la valutazione formale di conformità.</p>
            </div>
            <div className="noc-panel p-4" data-testid="exec-risky-users">
              <h2 className="text-sm font-bold text-white mb-3">Utenti a rischio (UEBA)</h2>
              {d.top_risky_users.length === 0 ? (
                <p className="text-[11px] text-[var(--text-muted)]" data-testid="exec-risky-empty">Nessun comportamento anomalo nel periodo. I profili si costruiscono dal Registro Accessi AdS (servono almeno 7 giorni e 40 accessi per utente).</p>
              ) : (
                <ul className="space-y-2">
                  {d.top_risky_users.map((u, i) => (
                    <li key={`${u.client_id}-${u.user}`} className="flex items-center gap-2" data-testid={`exec-risky-user-${i}`}>
                      <UserCircle size={18} className="text-sky-300" />
                      <div className="min-w-0 flex-1">
                        <div className="text-[12px] font-mono text-white truncate">{u.user}</div>
                        <div className="text-[10px] text-[var(--text-muted)] truncate">{Object.entries(u.types).map(([k, v]) => `${UEBA_LABEL[k] || k} ×${v}`).join(" · ")}</div>
                      </div>
                      <div className="w-24 h-1.5 rounded bg-white/5 overflow-hidden"><div className="h-full" style={{ width: `${u.score}%`, background: u.score >= 60 ? "#F87171" : u.score >= 30 ? "#FBBF24" : "#34D399" }} /></div>
                      <span className="text-[11px] font-bold w-8 text-right text-white">{u.score}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
