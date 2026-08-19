import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { ListChecks, CircleNotch, ShieldCheck, Clock, GitFork } from "@phosphor-icons/react";

const TIER_STYLE = {
  certo_100: { label: "CERTO 100%", cls: "bg-emerald-500/15 text-emerald-400 border-emerald-500/40" },
  quasi_certo: { label: "QUASI CERTO", cls: "bg-lime-500/15 text-lime-400 border-lime-500/40" },
  alta: { label: "ALTA", cls: "bg-amber-500/15 text-amber-400 border-amber-500/40" },
  incerto: { label: "DA VERIFICARE", cls: "bg-slate-500/15 text-slate-300 border-slate-500/40" },
};

const SEV_STYLE = {
  critical: "text-red-400", high: "text-amber-400", medium: "text-yellow-300",
  low: "text-sky-300", none: "text-emerald-400",
};

function fmtLatency(s) {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `~${Math.round(s / 60)} min`;
  return `${Math.round(s / 3600)} h`;
}

export default function DiagnosisCatalogPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/diagnosis/catalog`)
      .then(res => setData(res.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-[var(--text-muted)]">
        <CircleNotch size={28} className="animate-spin text-indigo-400" />
      </div>
    );
  }
  if (!data) {
    return <p className="text-red-400 p-6" data-testid="catalog-error">Impossibile caricare il catalogo diagnosi.</p>;
  }

  const s = data.summary;

  return (
    <div className="p-4 sm:p-6 space-y-6 max-w-6xl" data-testid="diagnosis-catalog-page">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-xl bg-indigo-500/15 border border-indigo-500/30">
          <ListChecks size={22} className="text-indigo-400" weight="duotone" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Catalogo Diagnosi</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1 max-w-2xl">
            Tutte le situazioni che Argus sa rilevare e dichiarare, con la confidenza reale,
            il segnale che le determina e l'azione consigliata. La fonte di verità del NOC.
          </p>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { k: "situations_total", label: "Situazioni totali", v: s.situations_total },
          { k: "certain_100", label: "Certe al 100%", v: s.certain_100, accent: "text-emerald-400" },
          { k: "domains", label: "Domini", v: s.domains },
          { k: "cross", label: "Combinazioni trasversali", v: s.cross_combinations },
        ].map(c => (
          <div key={c.k} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-deep)] p-3" data-testid={`catalog-stat-${c.k}`}>
            <div className={`text-2xl font-bold ${c.accent || "text-[var(--text-primary)]"}`}>{c.v}</div>
            <div className="text-[11px] text-[var(--text-muted)] mt-0.5">{c.label}</div>
          </div>
        ))}
      </div>

      {/* Detection latency */}
      <section className="rounded-xl border border-[var(--border-subtle)] p-4" data-testid="catalog-latency">
        <div className="flex items-center gap-2 mb-3">
          <Clock size={16} className="text-sky-400" />
          <h2 className="text-base font-semibold text-[var(--text-primary)]">Tempi di rilevamento</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5">
          {data.detection_latency.map((l, i) => (
            <div key={i} className="flex items-center justify-between text-xs border-b border-[var(--border-subtle)]/50 py-1">
              <span className="text-[var(--text-primary)]">{l.signal}</span>
              <span className="font-mono text-sky-300 whitespace-nowrap ml-3">{fmtLatency(l.cadence_s)}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Domains */}
      {data.domains.map(dom => (
        <section key={dom.domain} className="space-y-2" data-testid={`catalog-domain-${dom.domain}`}>
          <h2 className="text-base font-semibold text-[var(--text-primary)] flex items-center gap-2">
            <ShieldCheck size={16} className="text-indigo-400" /> {dom.label}
            <span className="text-[11px] font-normal text-[var(--text-muted)]">({dom.situations.length})</span>
          </h2>
          <div className="rounded-xl border border-[var(--border-subtle)] overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-[var(--bg-deep)] text-[var(--text-muted)]">
                <tr className="text-left">
                  <th className="px-3 py-2 font-medium">Situazione</th>
                  <th className="px-3 py-2 font-medium">Certezza</th>
                  <th className="px-3 py-2 font-medium hidden md:table-cell">Come la rilevo</th>
                  <th className="px-3 py-2 font-medium hidden lg:table-cell">Azione</th>
                </tr>
              </thead>
              <tbody>
                {dom.situations.map(sit => {
                  const tier = TIER_STYLE[sit.tier] || TIER_STYLE.incerto;
                  return (
                    <tr key={sit.code} className="border-t border-[var(--border-subtle)] align-top" data-testid={`catalog-sit-${sit.code}`}>
                      <td className="px-3 py-2">
                        <span className={`font-semibold ${SEV_STYLE[sit.severity] || "text-[var(--text-primary)]"}`}>{sit.label}</span>
                        <div className="text-[10px] text-[var(--text-muted)] font-mono">{sit.code}</div>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className={`inline-block px-1.5 py-0.5 rounded border text-[9px] font-bold ${tier.cls}`}>{tier.label}</span>
                        <span className="ml-1 text-[10px] text-[var(--text-muted)] font-mono">{sit.confidence}%</span>
                      </td>
                      <td className="px-3 py-2 text-[var(--text-muted)] hidden md:table-cell">{sit.trigger}</td>
                      <td className="px-3 py-2 text-[var(--text-muted)] hidden lg:table-cell">{sit.action}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      {/* Cross combinations */}
      <section className="space-y-2" data-testid="catalog-cross">
        <h2 className="text-base font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <GitFork size={16} className="text-fuchsia-400" /> Combinazioni trasversali (verdetto unico)
        </h2>
        <div className="grid md:grid-cols-2 gap-3">
          {data.cross_combinations.map((c, i) => (
            <div key={i} className="rounded-xl border border-fuchsia-500/25 bg-fuchsia-500/5 p-3" data-testid={`catalog-cross-${i}`}>
              <div className="font-semibold text-[var(--text-primary)] text-sm">{c.situation}</div>
              <div className="text-[11px] text-fuchsia-300 mt-1 font-mono">{c.combo}</div>
              <div className="text-xs text-[var(--text-primary)] mt-1.5">{c.verdict}</div>
              <div className="text-[11px] text-[var(--text-muted)] mt-1 italic">{c.why}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
