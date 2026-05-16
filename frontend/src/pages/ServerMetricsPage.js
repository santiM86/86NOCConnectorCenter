import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Desktop, ArrowClockwise, HardDrives, Cpu, Memory } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

/**
 * ServerMetricsPage — vista admin con CPU/RAM/Disk LIVE dei server con
 * Agent installato. I dati arrivano dal poller `sysmetrics` del Go agent
 * (gopsutil → WMI su Windows / /proc su Linux) e vengono persistiti in
 * `sys_metrics_latest` / `sys_metrics_history`.
 *
 * Polling: ogni 30s (i sample arrivano ogni 60s lato agent).
 */
export default function ServerMetricsPage() {
  const [data, setData] = useState({ count: 0, agents: [] });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  const fetchData = async () => {
    try {
      const r = await axios.get(`${API}/sys-metrics/overview`);
      setData(r.data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore caricamento metriche");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30000);
    return () => clearInterval(id);
  }, []);

  const filtered = data.agents.filter((a) => {
    if (!filter) return true;
    const f = filter.toLowerCase();
    return (a.hostname || "").toLowerCase().includes(f) ||
           (a.platform || "").toLowerCase().includes(f);
  });

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="server-metrics-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2">
            <Desktop size={22} /> Server con Agent
          </h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">
            Monitoraggio nativo CPU/RAM/Disk dei server Windows e Linux con agent installato (no SNMP)
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData}
          className="rounded-md text-xs h-8" data-testid="server-metrics-refresh">
          <ArrowClockwise size={14} className="mr-1.5" /> Aggiorna
        </Button>
      </div>

      <div className="noc-panel p-3">
        <input
          type="text"
          placeholder="Filtra per hostname o piattaforma..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full bg-[var(--bg-input)] border border-[var(--bg-border)] rounded px-3 py-1.5 text-xs text-[var(--text-primary)]"
          data-testid="server-metrics-filter"
        />
      </div>

      {loading ? (
        <p className="text-[var(--text-muted)] text-xs">Caricamento…</p>
      ) : filtered.length === 0 ? (
        <div className="noc-panel p-8 text-center">
          <Desktop size={32} className="mx-auto text-[var(--text-muted)] mb-2" />
          <p className="text-[var(--text-muted)] text-xs">
            {data.count === 0
              ? "Nessun agent sta ancora inviando metriche. Aspetta il primo sample (60s dopo il primo collegamento)."
              : "Nessun host corrisponde al filtro."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((a) => <ServerCard key={a.agent_id} a={a} />)}
        </div>
      )}
    </div>
  );
}

function pctColor(pct) {
  if (pct >= 90) return "text-red-400";
  if (pct >= 75) return "text-amber-400";
  if (pct >= 50) return "text-yellow-400";
  return "text-[var(--ok)]";
}

function pctBar(pct) {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 75) return "bg-amber-500";
  if (pct >= 50) return "bg-yellow-500";
  return "bg-emerald-500";
}

function fmtUptime(sec) {
  if (!sec) return "—";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}g ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function ServerCard({ a }) {
  const cpu = a.cpu_percent ?? 0;
  const mem = a.mem_used_pct ?? 0;
  const dmax = a.disk_max_pct ?? 0;

  return (
    <div className={`noc-panel p-4 ${a.stale ? "opacity-60" : ""}`}
      data-testid={`server-card-${a.agent_id}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0">
          <p className="font-heading font-bold text-sm text-[var(--text-primary)] truncate">
            {a.hostname || a.agent_id.slice(0, 8)}
          </p>
          <p className="text-[10px] text-[var(--text-muted)] truncate">{a.platform || a.os}</p>
        </div>
        <span className={`text-[9px] px-1.5 py-0.5 rounded ${
          a.live ? "bg-emerald-500/10 text-emerald-400" : "bg-zinc-500/10 text-zinc-400"
        }`}>
          {a.live ? "● LIVE" : a.stale ? "STALE" : "ONLINE"}
        </span>
      </div>

      <div className="space-y-2.5">
        <Metric icon={Cpu} label="CPU" value={cpu} unit="%"
                detail={`${a.cpu_cores || "?"} cores`} />
        <Metric icon={Memory} label="RAM" value={mem} unit="%"
                detail={`${a.mem_used_mb || 0} / ${a.mem_total_mb || 0} MB`} />
        <Metric icon={HardDrives} label="Disco" value={dmax} unit="%"
                detail={`${(a.disks || []).length} volume${(a.disks || []).length === 1 ? "" : "i"}`} />
      </div>

      <div className="mt-3 pt-2 border-t border-[var(--bg-border)] flex justify-between text-[10px] text-[var(--text-muted)]">
        <span>uptime {fmtUptime(a.uptime_sec)}</span>
        <span>{a.proc_count || "—"} proc</span>
        <span title={a.sampled_at}>
          {a.age_seconds < 60 ? "ora" : a.age_seconds < 3600 ? `${Math.floor(a.age_seconds / 60)}m fa` : `${Math.floor(a.age_seconds / 3600)}h fa`}
        </span>
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value, unit, detail }) {
  const v = Number(value || 0);
  return (
    <div>
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1">
          <Icon size={11} /> {label}
        </span>
        <span className={`text-xs font-mono font-bold ${pctColor(v)}`}>
          {v.toFixed(1)}{unit}
        </span>
      </div>
      <div className="h-1 bg-[var(--bg-input)] rounded-full overflow-hidden">
        <div className={`h-full ${pctBar(v)} transition-all`} style={{ width: `${Math.min(v, 100)}%` }} />
      </div>
      <p className="text-[9px] text-[var(--text-muted)] mt-0.5 truncate">{detail}</p>
    </div>
  );
}
