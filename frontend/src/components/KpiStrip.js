import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { TrendUp, TrendDown, Minus } from "@phosphor-icons/react";

const TONE = {
  ok: { text: "text-emerald-400", stroke: "#34d399" },
  warn: { text: "text-amber-400", stroke: "#fbbf24" },
  crit: { text: "text-red-400", stroke: "#f87171" },
  info: { text: "text-sky-400", stroke: "#38bdf8" },
};
const PERIODS = [["24h", "24h"], ["7d", "7 gg"], ["30d", "30 gg"]];

function Sparkline({ series, stroke }) {
  if (!series || series.length < 2) return <div className="h-7" />;
  const w = 120, h = 28, pad = 2;
  const max = Math.max(...series), min = Math.min(...series);
  const rng = max - min || 1;
  const pts = series.map((v, i) => `${pad + (i / (series.length - 1)) * (w - pad * 2)},${h - pad - ((v - min) / rng) * (h - pad * 2)}`);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-7" preserveAspectRatio="none" aria-hidden>
      <polyline points={pts.join(" ")} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" opacity="0.9" />
      <polygon points={`${pad},${h} ${pts.join(" ")} ${w - pad},${h}`} fill={stroke} opacity="0.08" />
    </svg>
  );
}

function Trend({ t, unit }) {
  if (!t || t.delta === 0 || t.good === null) return <span className="text-[10px] text-[var(--text-muted)] flex items-center gap-0.5"><Minus size={10} /> stabile</span>;
  const Icon = t.delta > 0 ? TrendUp : TrendDown;
  const cls = t.good ? "text-emerald-400" : "text-red-400";
  const txt = t.pct != null && Math.abs(t.pct) < 1000 ? `${t.delta > 0 ? "+" : ""}${t.pct}%` : `${t.delta > 0 ? "+" : ""}${t.delta}${unit || ""}`;
  return <span className={`text-[10px] font-mono flex items-center gap-0.5 ${cls}`}><Icon size={11} weight="bold" /> {txt}</span>;
}

function KpiTile({ k, onClick }) {
  const tone = TONE[k.tone] || TONE.info;
  const fmt = () => {
    if (k.value == null) return ["—", ""];
    if (k.unit === "%") return [`${k.value}%`, ""];
    if (k.unit === "min" && k.value >= 120) return [(k.value / 60).toFixed(1), "h"];
    return [k.value, k.unit || ""];
  };
  const [val, unit] = fmt();
  return (
    <button onClick={onClick} className="noc-panel p-3 text-left flex flex-col gap-1 hover:border-indigo-500/40 transition-colors group" data-testid={`kpi-tile-${k.key}`}>
      <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] truncate">{k.label}</span>
      <span className={`font-mono text-2xl font-bold leading-none ${tone.text}`} data-testid={`kpi-value-${k.key}`}>
        {val}{unit && <span className="text-xs ml-1 text-[var(--text-muted)]">{unit}</span>}
      </span>
      <Sparkline series={k.series} stroke={tone.stroke} />
      <div className="flex items-center justify-between gap-1">
        <span className="text-[10px] text-[var(--text-secondary)] truncate" title={k.sub}>{k.sub}</span>
        <Trend t={k.trend} unit={k.unit} />
      </div>
    </button>
  );
}

export function KpiStrip() {
  const [period, setPeriod] = useState(() => localStorage.getItem("kpi_period") || "24h");
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    const load = () => axios.get(`${API}/overview/kpi`, { params: { period }, timeout: 60000 })
      .then(r => { if (alive) { setData(r.data); setErr(null); } })
      .catch(e => { if (alive) setErr(e?.response?.data?.detail || "KPI non disponibili"); });
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [period]);

  const pick = (p) => { setPeriod(p); localStorage.setItem("kpi_period", p); };

  return (
    <div className="space-y-2" data-testid="kpi-strip">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">
          KPI {data?.snapshots != null && data.snapshots < 2 && <span className="ml-1 normal-case tracking-normal">· storico in costruzione (trend e sparkline compaiono dopo qualche ora)</span>}
        </span>
        <div className="flex gap-1" data-testid="kpi-period-selector">
          {PERIODS.map(([v, l]) => (
            <button key={v} onClick={() => pick(v)} data-testid={`kpi-period-${v}`}
              className={`text-[10px] px-2 py-0.5 rounded-md font-semibold transition-all ${period === v ? "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}>{l}</button>
          ))}
        </div>
      </div>
      {err && <div className="text-[11px] text-amber-400" data-testid="kpi-error">{err}</div>}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-9 gap-2">
        {(data?.kpis || Array.from({ length: 9 }, (_, i) => ({ key: `sk${i}`, label: "…", sub: "", series: [] }))).map(k => (
          <KpiTile key={k.key} k={k} onClick={() => k.link && navigate(k.link)} />
        ))}
      </div>
    </div>
  );
}
