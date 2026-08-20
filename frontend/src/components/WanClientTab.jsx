import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import {
  Globe, ShieldCheck, HardDrives, WifiHigh, Lightning, Plus, Trash,
  ArrowClockwise, CheckCircle, Warning, MapPin, Pulse, Gauge,
  ArrowsClockwise, ChartLine, Clock, ArrowsLeftRight, PencilSimple,
  Cloud, Path, Bell, X, XCircle,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer, ReferenceLine } from "recharts";

const STATUS_COLOR = { online: "#34C759", offline: "#FF3B30", degraded: "#FF9500", filtered: "#FFCC00", unknown: "#555", pending: "#555" };

function fmt(n, suffix = "") {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${typeof n === "number" ? Math.round(n * 10) / 10 : n}${suffix}`;
}

function fmtUptime(p) {
  if (p === null || p === undefined) return "—";
  return `${p.toFixed(p >= 99 ? 2 : 1)}%`;
}

function slaColor(p) {
  if (p === null || p === undefined) return "#888";
  if (p >= 99.9) return "#34C759";
  if (p >= 99) return "#A3E635";
  if (p >= 95) return "#FFCC00";
  if (p >= 80) return "#FF9500";
  return "#FF3B30";
}

function timeAgo(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const diffMin = Math.round((Date.now() - d.getTime()) / 60000);
    if (diffMin < 1) return "ora";
    if (diffMin < 60) return `${diffMin}min fa`;
    const h = Math.round(diffMin / 60);
    if (h < 24) return `${h}h fa`;
    return `${Math.round(h / 24)}g fa`;
  } catch { return "—"; }
}

// =================== HERO CARD ===================
function HeroCard({ clientName, diagnosis, gateway, isOnline }) {
  const isOk = isOnline;
  const color = isOk ? "#34C759" : "#FF3B30";
  return (
    <div className="rounded-2xl border-2 overflow-hidden" style={{ borderColor: `${color}50`, background: `linear-gradient(180deg, ${color}08 0%, transparent 60%)` }} data-testid="wan-hero-card">
      <div className="flex items-center justify-between gap-4 flex-wrap px-4 sm:px-6 py-4 sm:py-5 border-l-[4px]" style={{ borderColor: color }}>
        <div className="flex items-center gap-3 sm:gap-4 min-w-0 flex-1">
          <div className="w-10 h-10 sm:w-11 sm:h-11 rounded-xl flex items-center justify-center shrink-0" style={{ background: `${color}15` }}>
            <CheckCircle size={24} weight="bold" style={{ color }} />
          </div>
          <div className="min-w-0">
            <h2 className="text-xl sm:text-2xl font-bold tracking-tight truncate" style={{ color }} data-testid="wan-hero-client-name">{clientName}</h2>
            <p className="text-[11px] sm:text-[12px] mt-0.5 truncate" style={{ color: `${color}cc` }} data-testid="wan-hero-diagnosis">{diagnosis || (isOk ? "Connettività OK" : "Stato in attesa di probe...")}</p>
          </div>
        </div>
        {gateway && (
          <div className="px-4 py-2.5 rounded-lg border" style={{ borderColor: gateway.reachable ? "#34C75940" : "#FF3B3040", background: gateway.reachable ? "#34C75908" : "#FF3B3008" }} data-testid="wan-hero-isp-badge">
            <div className="flex items-center gap-2">
              <Globe size={16} weight="bold" style={{ color: gateway.reachable ? "#34C759" : "#FF3B30" }} />
              <div>
                <div className="text-[11px] font-bold tracking-wide" style={{ color: gateway.reachable ? "#34C759" : "#FF3B30" }}>
                  ISP {gateway.reachable ? "ONLINE" : "DOWN"}
                </div>
                <div className="text-[10px] font-mono opacity-70">
                  {gateway.ip} {gateway.latency_ms != null ? `${gateway.latency_ms}ms` : ""}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// =================== TARGET CARD (firewall/router) ===================
function TargetCard({ target, onDelete, onHistory }) {
  const navigate = useNavigate();
  const r = target.result;
  const color = STATUS_COLOR[r?.status] || "#555";
  const Icon = target.device_type === "firewall" ? ShieldCheck : HardDrives;
  return (
    <div className="rounded-xl border bg-[var(--bg-panel)] p-3" style={{ borderColor: `${color}30` }} data-testid={`wan-target-card-${target.id}`}>
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 rounded-full animate-pulse" style={{ background: color, boxShadow: `0 0 10px ${color}` }}></div>
        <Icon size={16} weight="bold" style={{ color }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-[var(--text-primary)] truncate">{target.label}</span>
            <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase border" style={{ color, borderColor: `${color}50`, background: `${color}10` }}>
              {r?.status?.toUpperCase() || "PENDING"}
            </span>
          </div>
          <div className="text-[10px] font-mono text-[var(--text-muted)] mt-0.5">{target.public_ip}</div>
        </div>
        <div className="text-right">
          {r?.ping?.latency_ms != null && (
            <div className="text-base font-bold tabular-nums" style={{ color }}>
              {r.ping.latency_ms}<span className="text-[9px] font-normal opacity-70">ms</span>
            </div>
          )}
          <div className="text-[8px] uppercase tracking-wider opacity-60">
            {r?.ping?.reachable ? "ICMP" : r?.ports?.find(p => p.open) ? `TCP:${r.ports.find(p => p.open).port}` : "—"}
          </div>
        </div>
        <div className="flex items-center gap-1 ml-1">
          <button onClick={() => onHistory(target)} className="text-[9px] px-2 py-0.5 rounded border border-indigo-500/40 hover:bg-indigo-500/10 text-indigo-300" title="Storico" data-testid={`wan-history-btn-${target.id}`}>
            <ChartLine size={11} weight="bold" />
          </button>
          {target.public_ip && (
            <button
              onClick={() => navigate(`/tools/path-trace?target=${encodeURIComponent(target.public_ip)}`)}
              className="text-[9px] px-2 py-0.5 rounded border border-cyan-500/40 hover:bg-cyan-500/10 text-cyan-300"
              title={`Traccia percorso verso ${target.public_ip}`}
              data-testid={`wan-trace-btn-${target.id}`}
            >
              <Path size={11} weight="bold" />
            </button>
          )}
          <AlertRulesButton target={target} />
          <button onClick={() => onDelete(target)} className="p-1 rounded hover:bg-red-500/15 text-red-400" title="Rimuovi" data-testid={`wan-target-delete-${target.id}`}>
            <Trash size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

// =================== INSIGHTS PANEL ===================
function InsightsPanel({ target }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchInsights = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/external-monitor/insights/${target.id}?days=30`);
      setData(r.data);
    } catch (e) {
      setData(null);
    } finally { setLoading(false); }
  }, [target.id]);

  useEffect(() => { fetchInsights(); const i = setInterval(fetchInsights, 60000); return () => clearInterval(i); }, [fetchInsights]);

  const sparkData = useMemo(() => {
    if (!data?.sparkline_24h) return [];
    return data.sparkline_24h.map(p => ({
      t: new Date(p.t).getTime(),
      latency: p.online ? p.latency : null,
      loss: p.loss || 0,
      online: p.online ? 1 : 0,
    }));
  }, [data]);

  if (loading) {
    return <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 text-[10px] text-[var(--text-muted)]">Caricamento insight…</div>;
  }

  if (!data || data.samples === 0) {
    return (
      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 text-center text-[10px] text-[var(--text-muted)]">
        <ChartLine size={20} className="mx-auto mb-1 opacity-40" />
        Nessuno storico ancora — attendi qualche minuto per i primi sample.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid={`wan-insights-${target.id}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ChartLine size={14} weight="bold" className="text-indigo-400" />
          <h4 className="text-[11px] font-bold uppercase tracking-wider text-indigo-300">Insight 24h · SLA 30 giorni</h4>
        </div>
        <span className="text-[9px] text-[var(--text-muted)]">{data.samples} sample</span>
      </div>

      {/* SLA bar */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "Oggi", v: data.uptime_today, key: "today" },
          { label: "7 giorni", v: data.uptime_7d, key: "7d" },
          { label: "30 giorni", v: data.uptime_30d, key: "30d" },
        ].map(b => (
          <div key={b.key} className="rounded-lg border bg-[var(--bg-card)] p-2.5" style={{ borderColor: `${slaColor(b.v)}30` }} data-testid={`wan-sla-${b.key}-${target.id}`}>
            <div className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">{b.label}</div>
            <div className="text-lg font-black tabular-nums mt-0.5" style={{ color: slaColor(b.v) }}>{fmtUptime(b.v)}</div>
            <div className="h-1 rounded-full bg-[var(--bg-border)] mt-1 overflow-hidden">
              <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(b.v || 0, 100)}%`, background: slaColor(b.v) }}></div>
            </div>
          </div>
        ))}
      </div>

      {/* Latency stats */}
      <div className="grid grid-cols-4 gap-2 pt-1">
        <Stat label="Avg" value={fmt(data.latency.avg, "ms")} color="#6366F1" />
        <Stat label="P95" value={fmt(data.latency.p95, "ms")} color="#A855F7" />
        <Stat label="Jitter" value={fmt(data.latency.jitter, "ms")} color="#06B6D4" />
        <Stat label="Loss" value={fmt(data.loss_pct_avg, "%")} color={data.loss_pct_avg > 1 ? "#FF9500" : "#34C759"} />
      </div>

      {/* Sparkline */}
      {sparkData.length > 0 && (
        <div className="h-24 mt-1" data-testid={`wan-sparkline-${target.id}`}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={sparkData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={`spark-${target.id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366F1" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#6366F1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" hide />
              <YAxis hide domain={["auto", "auto"]} />
              <RTooltip
                contentStyle={{ background: "#0a0d14", border: "1px solid #1f2937", borderRadius: 6, fontSize: 10 }}
                labelFormatter={(v) => new Date(v).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}
                formatter={(v, n) => [n === "latency" ? `${v}ms` : `${v}%`, n === "latency" ? "Latenza" : "Loss"]}
              />
              <Area type="monotone" dataKey="latency" stroke="#6366F1" fill={`url(#spark-${target.id})`} strokeWidth={1.5} isAnimationActive={false} />
              {data.latency.avg && <ReferenceLine y={data.latency.avg} stroke="#888" strokeDasharray="2 2" />}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Down periods last 24h */}
      {data.down_count > 0 && (
        <div className="text-[10px] text-amber-400/80 border-t border-[var(--bg-border)] pt-2">
          <Warning size={11} weight="bold" className="inline -mt-0.5 mr-1" />
          {data.down_count} {data.down_count === 1 ? "interruzione" : "interruzioni"} negli ultimi 30 giorni · MTTR {fmt(data.mttr_min, " min")} · downtime totale {fmt(data.total_down_minutes, " min")}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div className="rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] px-2 py-1.5">
      <div className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">{label}</div>
      <div className="text-sm font-bold tabular-nums mt-0.5" style={{ color }}>{value}</div>
    </div>
  );
}

// =================== GEO/ISP CARD ===================
function GeoIspCard({ ip }) {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    if (!ip) { setLoading(false); return; }
    axios.get(`${API}/external-monitor/geo-ip/${encodeURIComponent(ip)}`)
      .then(r => alive && setInfo(r.data))
      .catch(() => alive && setInfo(null))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [ip]);

  if (loading) return <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3 text-[10px] text-[var(--text-muted)]">Geo-IP lookup…</div>;
  if (!info || info.error) return null;

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid={`wan-geoip-${ip}`}>
      <div className="flex items-center gap-2 mb-2">
        <MapPin size={13} weight="bold" className="text-emerald-400" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-300">ISP / Geo</span>
      </div>
      <div className="space-y-1.5 text-[11px]">
        <KV label="ISP" value={info.isp} />
        <KV label="Org" value={info.org} />
        <KV label="ASN" value={info.asn_name ? `${info.asn} (${info.asn_name})` : info.asn} />
        <KV label="Località" value={[info.city, info.region, info.country_code].filter(Boolean).join(", ")} />
      </div>
    </div>
  );
}

function KV({ label, value }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-3">
      <span className="text-[var(--text-muted)] text-[9px] uppercase tracking-wider">{label}</span>
      <span className="text-[var(--text-primary)] font-mono text-[10px] truncate text-right">{value}</span>
    </div>
  );
}

// =================== DNS HEALTH CARD ===================
function DnsHealthCard({ targetId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const runCheck = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/external-monitor/dns-health/${targetId}`);
      setData(r.data);
    } catch (e) {
      toast.error("Errore DNS health check");
    } finally { setLoading(false); }
  }, [targetId]);

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid={`wan-dns-${targetId}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Pulse size={13} weight="bold" className="text-cyan-400" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">DNS Health</span>
        </div>
        <button onClick={runCheck} disabled={loading} className="text-[9px] px-2 py-0.5 rounded border border-cyan-500/40 hover:bg-cyan-500/10 text-cyan-300 disabled:opacity-50" data-testid={`wan-dns-check-${targetId}`}>
          {loading ? "Check…" : data ? "Re-check" : "Esegui"}
        </button>
      </div>
      {!data && !loading && (
        <div className="text-[10px] text-[var(--text-muted)] py-3 text-center">
          Clicca "Esegui" per testare la risoluzione DNS su Google/Cloudflare/Quad9.
        </div>
      )}
      {data && (
        <div className="space-y-1.5">
          {data.resolvers.map((r, i) => (
            <div key={i} className="flex items-center justify-between text-[10px] py-1 border-b border-[var(--bg-border)] last:border-0">
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full" style={{ background: r.ok ? "#34C759" : "#FF3B30" }}></div>
                <span className="font-bold text-[var(--text-primary)]">{r.name}</span>
                <span className="font-mono text-[var(--text-muted)] text-[9px]">{r.ip}</span>
              </div>
              <span className="tabular-nums font-mono" style={{ color: r.ok ? "#34C759" : "#FF3B30" }}>
                {r.latency_ms != null ? `${r.latency_ms}ms` : "FAIL"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// =================== PUBLIC IP HISTORY ===================
function PublicIpHistoryCard({ targetId, currentIp }) {
  const [hist, setHist] = useState([]);
  useEffect(() => {
    let alive = true;
    axios.get(`${API}/external-monitor/public-ip-history/${targetId}?limit=10`)
      .then(r => alive && setHist(r.data.changes || []))
      .catch(() => {});
    return () => { alive = false; };
  }, [targetId]);

  if (hist.length <= 1) {
    return (
      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid={`wan-ip-history-${targetId}`}>
        <div className="flex items-center gap-2 mb-2">
          <ArrowsClockwise size={13} weight="bold" className="text-amber-400" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-amber-300">IP pubblico</span>
        </div>
        <div className="text-[11px] font-mono text-[var(--text-primary)]">{currentIp}</div>
        <div className="text-[9px] text-[var(--text-muted)] mt-1">Stabile — nessun cambio rilevato.</div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3" data-testid={`wan-ip-history-${targetId}`}>
      <div className="flex items-center gap-2 mb-2">
        <ArrowsClockwise size={13} weight="bold" className="text-amber-400" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-amber-300">Cambi IP pubblico ({hist.length})</span>
      </div>
      <div className="space-y-1.5 max-h-32 overflow-y-auto">
        {hist.map((c, i) => (
          <div key={c.id} className="text-[10px] flex items-center gap-2">
            <Clock size={10} className="text-amber-400" />
            <span className="text-[var(--text-muted)] w-16">{timeAgo(c.changed_at)}</span>
            <span className="font-mono text-[var(--text-primary)]">{c.previous_ip || "—"}</span>
            <ArrowsLeftRight size={9} className="text-amber-400" />
            <span className="font-mono text-amber-200">{c.public_ip}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// =================== SPEEDTEST CARD ===================
function SpeedtestCard({ clientId }) {
  const [hist, setHist] = useState([]);
  const [running, setRunning] = useState(false);
  const fetchHist = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/external-monitor/speedtest-history/${clientId}?limit=5`);
      setHist(r.data.history || []);
    } catch {}
  }, [clientId]);
  useEffect(() => { fetchHist(); const i = setInterval(fetchHist, 30000); return () => clearInterval(i); }, [fetchHist]);

  const runSpeedtest = async () => {
    setRunning(true);
    try {
      const r = await axios.post(`${API}/external-monitor/speedtest/${clientId}`);
      toast.success(`Speedtest avviato su ${r.data.agent?.hostname || "agent"}`);
      setTimeout(fetchHist, 5000);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore avvio speedtest");
    } finally {
      setRunning(false);
    }
  };

  const last = hist[0];
  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid="wan-speedtest-card">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Gauge size={13} weight="bold" className="text-purple-400" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-purple-300">Speedtest</span>
        </div>
        <button onClick={runSpeedtest} disabled={running} className="text-[9px] px-2 py-0.5 rounded border border-purple-500/40 hover:bg-purple-500/10 text-purple-300 disabled:opacity-50" data-testid="wan-speedtest-run">
          {running ? "Avvio…" : "Esegui ora"}
        </button>
      </div>
      {!last && (
        <div className="text-[10px] text-[var(--text-muted)] py-3 text-center">
          Nessuno speedtest eseguito.<br />
          <span className="text-[9px] opacity-60">Richiede agent v4.18+ con comando speedtest.</span>
        </div>
      )}
      {last && (
        <div className="space-y-2">
          {last.status === "running" && (
            <div className="text-[10px] text-amber-300 text-center py-2">
              <ArrowClockwise size={12} className="animate-spin inline mr-1" />
              In corso… ({timeAgo(last.requested_at)})
            </div>
          )}
          {last.status === "completed" && (
            <>
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Download" value={fmt(last.download_mbps, " Mb/s")} color="#22c55e" />
                <Stat label="Upload" value={fmt(last.upload_mbps, " Mb/s")} color="#3b82f6" />
                <Stat label="Ping" value={fmt(last.ping_ms, "ms")} color="#f59e0b" />
              </div>
              <div className="text-[9px] text-[var(--text-muted)] flex items-center justify-between">
                <span>{last.server || ""}</span>
                <span>{timeAgo(last.completed_at)}</span>
              </div>
            </>
          )}
          {last.status === "failed" && (
            <div className="text-[10px] text-red-400 text-center py-2">
              Errore: {last.error || "ignoto"} ({timeAgo(last.completed_at)})
            </div>
          )}
        </div>
      )}
      {hist.length > 1 && (
        <div className="mt-3 pt-2 border-t border-[var(--bg-border)] space-y-1">
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-1">Storico</div>
          {hist.slice(1).map(h => (
            <div key={h.id} className="text-[10px] flex items-center justify-between font-mono">
              <span className="text-[var(--text-muted)]">{timeAgo(h.completed_at || h.requested_at)}</span>
              <span className="text-emerald-300">↓{fmt(h.download_mbps)}</span>
              <span className="text-blue-300">↑{fmt(h.upload_mbps)}</span>
              <span className="text-amber-300">{fmt(h.ping_ms, "ms")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// =================== SAAS REACHABILITY ===================
function SaasReachabilityCard({ clientId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const run = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/external-monitor/saas-reachability/${clientId}`);
      setData(r.data);
    } catch (e) {
      toast.error("Errore SaaS reachability");
    } finally { setLoading(false); }
  }, [clientId]);

  useEffect(() => { run(); /* once on mount */ }, [run]);

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid="wan-saas-card">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Cloud size={13} weight="bold" className="text-sky-400" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-sky-300">Cloud SaaS Reachability</span>
        </div>
        <button onClick={run} disabled={loading} className="text-[9px] px-2 py-0.5 rounded border border-sky-500/40 hover:bg-sky-500/10 text-sky-300 disabled:opacity-50" data-testid="wan-saas-refresh">
          {loading ? "Check…" : "Re-check"}
        </button>
      </div>
      {data && (
        <>
          <div className="text-[9px] text-[var(--text-muted)] mb-2">
            {data.summary.healthy}/{data.summary.total} servizi raggiungibili
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {data.services.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px] p-1.5 rounded border" style={{ borderColor: s.ok ? "#34C75930" : "#FF3B3030", background: s.ok ? "#34C75908" : "#FF3B3008" }} data-testid={`wan-saas-${s.icon}`}>
                <div className="w-1.5 h-1.5 rounded-full" style={{ background: s.ok ? "#34C759" : "#FF3B30" }}></div>
                <span className="flex-1 truncate font-bold text-[var(--text-primary)]">{s.name}</span>
                <span className="tabular-nums font-mono" style={{ color: s.ok ? "#34C759" : "#FF3B30" }}>
                  {s.ok ? `${s.tcp_ms}ms` : "DOWN"}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
      {!data && !loading && (
        <div className="text-[10px] text-[var(--text-muted)] py-2 text-center">Caricamento…</div>
      )}
    </div>
  );
}

// =================== MULTI-ISP ===================
function MultiIspCard({ clientId }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    axios.get(`${API}/external-monitor/multi-isp/${clientId}`)
      .then(r => alive && setData(r.data))
      .catch(() => {});
    return () => { alive = false; };
  }, [clientId]);

  if (!data || !data.multi_isp) return null;
  return (
    <div className="rounded-xl border border-purple-500/30 bg-purple-500/5 p-3" data-testid="wan-multi-isp">
      <div className="flex items-center gap-2 mb-2">
        <ArrowsLeftRight size={13} weight="bold" className="text-purple-400" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-purple-300">Multi-ISP ({data.isp_count})</span>
      </div>
      <div className="space-y-1.5">
        {data.isps.map((isp, i) => (
          <div key={i} className="flex items-center justify-between text-[10px] p-1.5 rounded bg-[var(--bg-card)]" data-testid={`wan-isp-line-${i}`}>
            <span className="font-mono text-[var(--text-primary)]">{isp.gateway_ip}</span>
            <div className="flex items-center gap-2">
              <span className="text-[9px] text-[var(--text-muted)]">{isp.target_labels.join(", ")}</span>
              <span className="tabular-nums font-bold" style={{ color: isp.reachable ? "#34C759" : "#FF3B30" }}>
                {isp.reachable ? `${isp.latency_ms ?? "?"}ms` : "DOWN"}
              </span>
            </div>
          </div>
        ))}
      </div>
      {data.failover_events.length > 0 && (
        <div className="mt-2 pt-2 border-t border-purple-500/20 text-[9px] text-purple-300/80">
          {data.failover_events.length} eventi failover ultime 24h
        </div>
      )}
    </div>
  );
}

// =================== TRACEROUTE ===================
const ISP_PALETTE = ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#60a5fa", "#fb923c", "#e879f9"];

function TracerouteCard({ targets, clientId }) {
  const [rows, setRows] = useState(null);     // [{hop, ip, rtt_ms, timeout, geo}]
  const [loading, setLoading] = useState(false);
  const [info, setInfo] = useState("");
  const [ranAt, setRanAt] = useState(null);
  const [selTarget, setSelTarget] = useState(targets[0]?.public_ip || "1.1.1.1");
  const [diag, setDiag] = useState(null);       // risultato fault-diagnose (verdetto colpa)
  const [diagLoading, setDiagLoading] = useState(false);
  const lsKey = `wan_trace_last_${clientId}_${selTarget}`;

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(lsKey) || "null");
      if (saved) { setRows(saved.rows); setInfo(saved.info); setRanAt(saved.ranAt); }
      else { setRows(null); setInfo(""); setRanAt(null); }
    } catch { /* noop */ }
  }, [lsKey]);

  const ispColor = useMemo(() => {
    const m = {}; let i = 0;
    (rows || []).forEach(r => { const k = r.geo?.isp; if (k && !(k in m)) { m[k] = ISP_PALETTE[i % ISP_PALETTE.length]; i++; } });
    return m;
  }, [rows]);

  const isPub = (ip) => ip && !/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.|169\.254\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)/.test(ip);

  const run = async () => {
    setLoading(true); setRows(null); setInfo(""); setDiag(null);
    try {
      const token = localStorage.getItem("noc_token");
      const hdr = { headers: { Authorization: `Bearer ${token}` } };
      const ag = await axios.get(`${API}/agents`, hdr);
      const agList = Array.isArray(ag.data) ? ag.data : (ag.data?.agents || []);
      const live = agList.filter(a => a.live);
      const probe = live.find(a => a.client_id === clientId) || live.find(a => a.client_id === "__global__") || live[0];
      if (!probe) { setInfo("Nessuna sonda-agent connessa."); return; }
      const r = await axios.post(`${API}/agents/${probe.agent_id}/command`,
        { name: "net_trace", args: { target: selTarget, mode: "icmp", max_hops: 20, count: 3 }, timeout: 45 },
        { ...hdr, timeout: 60000 });
      const reply = r.data.reply || {}; const res = reply.result || reply.Result || reply;
      const list = (res.hops || []).map(h => ({ hop: h.hop, ip: h.timeout ? null : (h.ip || h.host), rtt_ms: h.timeout ? null : (h.avg_ms != null ? Math.round(h.avg_ms * 10) / 10 : null), timeout: h.timeout, geo: null }));
      // geo per hop pubblico
      const pubIps = [...new Set(list.filter(x => isPub(x.ip)).map(x => x.ip))];
      const geoMap = Object.fromEntries(await Promise.all(pubIps.map(async ip => {
        try { const g = await axios.get(`${API}/external-monitor/geo-ip/${encodeURIComponent(ip)}`, hdr); return [ip, g.data]; } catch { return [ip, null]; }
      })));
      list.forEach(x => { if (isPub(x.ip)) x.geo = geoMap[x.ip]; });
      const now = new Date().toISOString();
      const infoTxt = `${res.tool || "trace"} · ${list.length} hop · ${res.reached ? "raggiunta" : "NON raggiunta"} · sonda ${probe.client_id === "__global__" ? "globale" : "cliente"}`;
      setRows(list); setInfo(infoTxt); setRanAt(now);
      try { localStorage.setItem(lsKey, JSON.stringify({ rows: list, info: infoTxt, ranAt: now })); } catch { /* noop */ }
    } catch (e) {
      const msg = e.code === "ECONNABORTED" ? "Timeout: trace oltre 60s" : (e.response?.data?.detail || "Errore traceroute");
      toast.error(msg); setInfo(msg);
    } finally { setLoading(false); }
  };

  const geoHops = (rows || []).filter(r => r.geo && r.geo.lat != null && r.geo.lon != null);

  const runDiag = async () => {
    setDiagLoading(true); setDiag(null);
    try {
      const token = localStorage.getItem("noc_token");
      const hdr = { headers: { Authorization: `Bearer ${token}` } };
      const r = await axios.post(`${API}/external-monitor/fault-diagnose`,
        { client_id: clientId, target: selTarget, mode: "icmp" },
        { ...hdr, timeout: 120000 });
      setDiag(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Diagnosi colpa fallita");
    } finally { setDiagLoading(false); }
  };

  const BLAME_STYLE = {
    "OK": { bg: "bg-emerald-500/10", br: "border-emerald-500/40", tx: "text-emerald-300" },
    "Cliente": { bg: "bg-amber-500/10", br: "border-amber-500/40", tx: "text-amber-300" },
    "ISP": { bg: "bg-rose-500/10", br: "border-rose-500/40", tx: "text-rose-300" },
    "Sito destinazione": { bg: "bg-violet-500/10", br: "border-violet-500/40", tx: "text-violet-300" },
    "Sonda": { bg: "bg-slate-500/10", br: "border-slate-500/40", tx: "text-slate-300" },
  };

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3" data-testid="wan-traceroute-card">
      <div className="flex items-center gap-2 mb-2">
        <Path size={13} weight="bold" className="text-orange-400" />
        <span className="text-[10px] font-bold uppercase tracking-wider text-orange-300">Traceroute (via sonda)</span>
        {ranAt && <span className="ml-auto text-[9px] text-[var(--text-muted)]">ultimo: {new Date(ranAt).toLocaleString("it-IT")}</span>}
      </div>
      <div className="flex gap-2 mb-2">
        {targets.length > 1 ? (
          <select value={selTarget} onChange={e => setSelTarget(e.target.value)} className="h-7 text-[10px] font-mono bg-[var(--bg-card)] border border-[var(--bg-border)] rounded px-1 flex-1" data-testid="wan-traceroute-target-select">
            {targets.map(t => <option key={t.id || t.public_ip} value={t.public_ip}>{t.label || t.public_ip} · {t.public_ip}</option>)}
          </select>
        ) : (
          <Input value={selTarget} onChange={e => setSelTarget(e.target.value)} placeholder="IP o hostname" className="h-7 text-[10px] font-mono bg-[var(--bg-card)] border-[var(--bg-border)]" data-testid="wan-traceroute-input" />
        )}
        <button onClick={run} disabled={loading || !selTarget} className="text-[9px] px-2 rounded border border-orange-500/40 hover:bg-orange-500/10 text-orange-300 disabled:opacity-50" data-testid="wan-traceroute-run">{loading ? "…" : "Esegui"}</button>
        <button onClick={runDiag} disabled={diagLoading || !selTarget} className="text-[9px] px-2 rounded border border-rose-500/40 hover:bg-rose-500/10 text-rose-300 disabled:opacity-50" data-testid="wan-fault-diagnose-run" title="Traceroute multi-ancora + verdetto automatico su chi è la colpa del disservizio">{diagLoading ? "…" : "⚖️ Diagnosi colpa"}</button>
      </div>
      {info && <div className="text-[9px] text-[var(--text-muted)] mb-1">{info}</div>}

      {/* Verdetto automatico "di chi è la colpa" (multi-ancora) */}
      {diag && diag.combined && (() => {
        const st = BLAME_STYLE[diag.combined.blame] || BLAME_STYLE["ISP"];
        return (
          <div className={`rounded-lg border ${st.br} ${st.bg} p-2.5 mb-2`} data-testid="wan-fault-verdict">
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-[10px] font-bold uppercase tracking-wider ${st.tx}`} data-testid="wan-fault-blame">
                Colpa: {diag.combined.blame}
              </span>
              <span className="text-[9px] px-1.5 rounded-full bg-black/30 text-[var(--text-muted)]">confidenza {diag.combined.confidence}</span>
              <span className={`ml-auto text-[9px] font-semibold ${st.tx}`}>{diag.combined.headline}</span>
            </div>
            <div className="text-[10px] text-[var(--text-secondary)] leading-snug mb-1.5">{diag.combined.verdict}</div>
            <div className="flex flex-wrap gap-1.5">
              {(diag.traces || []).map((t, i) => (
                <span key={i} className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--bg-border)] bg-[var(--bg-card)] font-mono flex items-center gap-1" data-testid={`wan-fault-anchor-${i}`}>
                  {t.is_client ? "🎯" : "🌐"} {t.target}
                  <span className={t.reached ? "text-emerald-400" : "text-rose-400"}>{t.reached ? "OK" : "DOWN"}</span>
                </span>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Mini-mappa geografica del percorso */}
      {geoHops.length > 0 && (
        <svg viewBox="0 0 360 180" className="w-full rounded-md mb-2 bg-[#0b1220] border border-[var(--bg-border)]" style={{ height: 120 }} data-testid="wan-traceroute-map">
          <polyline fill="none" stroke="#334155" strokeWidth="1" strokeDasharray="3 3"
            points={geoHops.map(h => `${h.geo.lon + 180},${90 - h.geo.lat}`).join(" ")} />
          {geoHops.map((h, i) => (
            <g key={i}>
              <circle cx={h.geo.lon + 180} cy={90 - h.geo.lat} r="3.2" fill={ispColor[h.geo.isp] || "#94a3b8"} stroke="#0b1220" strokeWidth="0.8" />
            </g>
          ))}
        </svg>
      )}

      {rows && rows.length > 0 && (
        <div className="space-y-0.5 max-h-52 overflow-y-auto">
          {rows.map((h, i) => (
            <div key={i} className="flex items-center gap-2 text-[10px] py-0.5 border-b border-[var(--bg-border)]/40 last:border-0">
              <span className="w-4 text-orange-400 font-mono">{h.hop || "?"}</span>
              <span className="w-1.5 h-3 rounded-sm flex-shrink-0" style={{ background: h.geo?.isp ? (ispColor[h.geo.isp] || "#94a3b8") : "transparent" }} />
              <span className="font-mono text-[var(--text-primary)] w-28 truncate">{h.timeout ? <span className="text-rose-400">* * *</span> : (h.ip || "*")}</span>
              <span className="flex-1 text-[9px] text-[var(--text-muted)] truncate">
                {h.timeout ? "" : h.geo ? `${h.geo.city ? h.geo.city + ", " : ""}${h.geo.country || ""}${h.geo.isp ? " · " + h.geo.isp : ""}` : (isPub(h.ip) ? "" : "rete locale")}
              </span>
              <span className="tabular-nums text-[var(--text-muted)] font-mono">{h.rtt_ms != null ? `${h.rtt_ms}ms` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// =================== ALERT RULES DIALOG ===================
function AlertRulesButton({ target }) {
  const [open, setOpen] = useState(false);
  const [rule, setRule] = useState({
    target_id: target.id, enabled: false,
    latency_warn_ms: null, latency_crit_ms: null,
    loss_warn_pct: null, loss_crit_pct: null,
    uptime_warn_pct: null,
    notify_email: null, notify_telegram_chat_id: null,
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    axios.get(`${API}/external-monitor/alert-rules/${target.id}`)
      .then(r => setRule({ ...rule, ...r.data, target_id: target.id }))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, target.id]);

  const save = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/external-monitor/alert-rules/${target.id}`, rule);
      toast.success("Regole alert salvate");
      setOpen(false);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally { setSaving(false); }
  };

  return (
    <>
      <button onClick={() => setOpen(true)} className="text-[9px] px-2 py-0.5 rounded border border-amber-500/40 hover:bg-amber-500/10 text-amber-300" title="Configura alert" data-testid={`wan-alert-rules-btn-${target.id}`}>
        <Bell size={11} weight="bold" className="inline -mt-0.5 mr-1" /> Alert
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-lg" data-testid="wan-alert-rules-dialog">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <Bell size={16} weight="bold" className="text-amber-400" /> Alert rules — {target.label}
            </DialogTitle>
            <DialogDescription className="text-[var(--text-muted)] text-xs">
              Soglie personalizzate per latenza / packet loss / uptime. Genera alert quando superate per 3 cicli consecutivi.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-[11px] text-[var(--text-primary)] cursor-pointer">
              <input type="checkbox" checked={rule.enabled} onChange={e => setRule({ ...rule, enabled: e.target.checked })} data-testid="alert-rules-enabled" />
              Abilita regole personalizzate (sovrascrive default)
            </label>
            <div className="grid grid-cols-2 gap-2">
              <NumField label="Latenza WARN (ms)" value={rule.latency_warn_ms} onChange={v => setRule({ ...rule, latency_warn_ms: v })} placeholder="50" />
              <NumField label="Latenza CRIT (ms)" value={rule.latency_crit_ms} onChange={v => setRule({ ...rule, latency_crit_ms: v })} placeholder="200" />
              <NumField label="Loss WARN (%)" value={rule.loss_warn_pct} onChange={v => setRule({ ...rule, loss_warn_pct: v })} placeholder="2" step="0.1" />
              <NumField label="Loss CRIT (%)" value={rule.loss_crit_pct} onChange={v => setRule({ ...rule, loss_crit_pct: v })} placeholder="10" step="0.1" />
              <NumField label="Uptime WARN < (%)" value={rule.uptime_warn_pct} onChange={v => setRule({ ...rule, uptime_warn_pct: v })} placeholder="99.5" step="0.1" />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px] uppercase text-[var(--text-muted)]">Email notifiche</Label>
              <Input value={rule.notify_email || ""} onChange={e => setRule({ ...rule, notify_email: e.target.value || null })} placeholder="alerts@cliente.it" className="h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="alert-rules-email" />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px] uppercase text-[var(--text-muted)]">Telegram chat_id</Label>
              <Input value={rule.notify_telegram_chat_id || ""} onChange={e => setRule({ ...rule, notify_telegram_chat_id: e.target.value || null })} placeholder="-100123456789" className="h-8 text-xs font-mono bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="alert-rules-telegram" />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setOpen(false)} variant="outline">Annulla</Button>
            <Button onClick={save} disabled={saving} className="bg-amber-600 hover:bg-amber-700 text-white" data-testid="alert-rules-save">
              {saving ? "Salvataggio…" : "Salva"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function NumField({ label, value, onChange, placeholder, step }) {
  return (
    <div>
      <Label className="text-[10px] uppercase text-[var(--text-muted)]">{label}</Label>
      <Input
        type="number" step={step || "1"}
        value={value ?? ""}
        onChange={e => onChange(e.target.value === "" ? null : Number(e.target.value))}
        placeholder={placeholder}
        className="h-8 text-xs font-mono bg-[var(--bg-panel)] border-[var(--bg-border)]"
      />
    </div>
  );
}

// =================== HISTORY CHART 7d/30d ===================
function HistoryChartDialog({ target, open, onOpenChange }) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    axios.get(`${API}/external-monitor/history-bucket/${target.id}?days=${days}`)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [open, target.id, days]);

  const chartData = useMemo(() => {
    if (!data?.buckets) return [];
    return data.buckets.map(b => ({
      t: new Date(b.t).getTime(),
      latency: b.avg_latency,
      uptime: b.uptime_pct,
      loss: b.avg_loss,
    }));
  }, [data]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-4xl" data-testid="wan-history-dialog">
        <DialogHeader>
          <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
            <ChartLine size={16} weight="bold" className="text-indigo-400" /> Storico — {target.label}
          </DialogTitle>
          <DialogDescription className="text-[var(--text-muted)] text-xs">
            Aggregati per bucket: 1d=5min, 7d=1h, 30d=6h
          </DialogDescription>
        </DialogHeader>
        <div className="flex gap-2 mb-3">
          {[1, 7, 30].map(d => (
            <button key={d} onClick={() => setDays(d)} className={`text-[10px] px-3 py-1 rounded border ${days === d ? "bg-indigo-600 text-white border-indigo-700" : "border-[var(--bg-border)] text-[var(--text-muted)] hover:bg-indigo-500/10"}`} data-testid={`wan-history-days-${d}`}>
              {d === 1 ? "Oggi" : `${d}gg`}
            </button>
          ))}
        </div>
        {loading && <div className="text-center py-12 text-[var(--text-muted)] text-xs">Caricamento…</div>}
        {!loading && data && (
          <>
            <div className="text-[10px] text-[var(--text-muted)] mb-2">
              {data.total_samples} sample totali · {data.buckets.length} bucket
            </div>
            <div className="space-y-3">
              {/* Latenza */}
              <div>
                <div className="text-[10px] uppercase tracking-wider text-indigo-300 mb-1">Latenza media (ms)</div>
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#6366F1" stopOpacity={0.5} />
                          <stop offset="100%" stopColor="#6366F1" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="t" tickFormatter={t => new Date(t).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit" })} stroke="#666" fontSize={9} />
                      <YAxis stroke="#666" fontSize={9} />
                      <CartesianGrid stroke="#1f2937" />
                      <RTooltip contentStyle={{ background: "#0a0d14", border: "1px solid #1f2937", borderRadius: 6, fontSize: 10 }} labelFormatter={v => new Date(v).toLocaleString("it-IT")} />
                      <Area type="monotone" dataKey="latency" stroke="#6366F1" fill="url(#g1)" strokeWidth={1.5} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
              {/* Uptime */}
              <div>
                <div className="text-[10px] uppercase tracking-wider text-emerald-300 mb-1">Uptime (%)</div>
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="g2" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#10B981" stopOpacity={0.5} />
                          <stop offset="100%" stopColor="#10B981" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="t" tickFormatter={t => new Date(t).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" })} stroke="#666" fontSize={9} />
                      <YAxis stroke="#666" fontSize={9} domain={[0, 100]} />
                      <CartesianGrid stroke="#1f2937" />
                      <RTooltip contentStyle={{ background: "#0a0d14", border: "1px solid #1f2937", borderRadius: 6, fontSize: 10 }} labelFormatter={v => new Date(v).toLocaleString("it-IT")} />
                      <Area type="monotone" dataKey="uptime" stroke="#10B981" fill="url(#g2)" strokeWidth={1.5} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

// =================== MAIN COMPONENT ===================
export default function WanClientTab({ targets, clientId, clientName, onRefresh }) {
  const [showAdd, setShowAdd] = useState(false);
  const [showAttach, setShowAttach] = useState(false);
  const [allTargets, setAllTargets] = useState([]);
  const [allClients, setAllClients] = useState({});
  const [loadingAttach, setLoadingAttach] = useState(false);
  const [attaching, setAttaching] = useState(null);
  const [diagnosis, setDiagnosis] = useState(null);
  const [saving, setSaving] = useState(false);
  const emptyForm = {
    label: "", device_type: "firewall", public_ip: "", gateway_ip: "",
    check_ports: "443", check_ping: true,
  };
  const [form, setForm] = useState(emptyForm);
  const [historyTarget, setHistoryTarget] = useState(null);

  const fetchDiagnosis = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/external-monitor/status/${clientId}`);
      setDiagnosis(r.data.diagnosis);
    } catch {}
  }, [clientId]);
  useEffect(() => { fetchDiagnosis(); const i = setInterval(fetchDiagnosis, 30000); return () => clearInterval(i); }, [fetchDiagnosis]);

  const firewalls = targets.filter(t => t.device_type === "firewall");
  const routers = targets.filter(t => t.device_type === "router");
  const others = targets.filter(t => t.device_type !== "firewall" && t.device_type !== "router");

  // Trova gateway info per hero card
  const gatewayInfo = useMemo(() => {
    for (const t of targets) {
      const r = t.result;
      if (r?.gateway_ping) {
        return {
          ip: r.gateway_ip || t.gateway_ip,
          reachable: r.gateway_ping.reachable,
          latency_ms: r.gateway_ping.latency_ms,
        };
      }
    }
    return null;
  }, [targets]);

  // is anything online?
  const anyOnline = targets.some(t => ["online", "filtered", "degraded"].includes(t.result?.status));
  const allOnline = targets.length > 0 && targets.every(t => ["online", "filtered"].includes(t.result?.status));

  const handleAdd = async () => {
    if (!form.label || !form.public_ip) { toast.error("Label e IP pubblico obbligatori"); return; }
    setSaving(true);
    try {
      const ports = form.check_ports.split(",").map(p => parseInt(p.trim())).filter(p => !isNaN(p) && p > 0);
      await axios.post(`${API}/external-monitor/targets`, {
        client_id: clientId, label: form.label, device_type: form.device_type,
        public_ip: form.public_ip, gateway_ip: form.gateway_ip || null,
        check_ports: ports, check_ping: form.check_ping,
      });
      toast.success(`Target WAN "${form.label}" aggiunto`);
      setForm(emptyForm);
      setShowAdd(false);
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    } finally { setSaving(false); }
  };

  const handleDelete = async (t) => {
    if (!window.confirm(`Eliminare il target "${t.label}" (${t.public_ip})?`)) return;
    try {
      await axios.delete(`${API}/external-monitor/targets/${t.id}`);
      toast.success("Target eliminato");
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    }
  };

  const openAttach = async () => {
    setShowAttach(true);
    setLoadingAttach(true);
    try {
      const [tRes, cRes] = await Promise.all([
        axios.get(`${API}/external-monitor/targets`),
        axios.get(`${API}/clients`),
      ]);
      setAllTargets((tRes.data?.targets || []).filter(t => t.client_id !== clientId));
      const map = {};
      (cRes.data || []).forEach(c => { map[c.id] = c.name; });
      setAllClients(map);
    } catch {
      toast.error("Errore caricamento target esistenti");
    } finally { setLoadingAttach(false); }
  };

  const attachTarget = async (target) => {
    setAttaching(target.id);
    try {
      await axios.put(`${API}/external-monitor/targets/${target.id}`, { client_id: clientId });
      toast.success(`Target "${target.label}" agganciato a ${clientName}`);
      setShowAttach(false);
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore aggancio");
    } finally { setAttaching(null); }
  };

  return (
    <div className="space-y-4" data-testid="wan-client-tab">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-[10px] text-[var(--text-muted)]">
          {targets.length === 0
            ? "Nessun target WAN configurato — aggiungi firewall/router pubblici per monitorare la connettività esterna."
            : `${targets.length} target WAN monitorati — ICMP + TCP + Gateway ISP · Speedtest · DNS · Geo-IP`}
        </p>
        <div className="flex gap-2">
          <Button onClick={onRefresh} variant="outline" className="h-8 text-xs gap-1 border-[var(--bg-border)]" data-testid="wan-refresh-btn">
            <ArrowClockwise size={13} weight="bold" /> Aggiorna
          </Button>
          <Button onClick={openAttach} variant="outline" className="h-8 text-xs gap-1 border-indigo-500/40 hover:bg-indigo-500/10 text-indigo-300" data-testid="attach-wan-target-btn">
            <Globe size={13} weight="bold" /> Aggancia esistente
          </Button>
          <Button onClick={() => { setForm(emptyForm); setShowAdd(true); }} className="bg-indigo-600 hover:bg-indigo-700 text-white h-8 text-xs gap-1" data-testid="add-wan-target-btn">
            <Plus size={13} weight="bold" /> Aggiungi Target WAN
          </Button>
        </div>
      </div>

      {/* HERO */}
      {targets.length > 0 && (
        <HeroCard
          clientName={clientName}
          diagnosis={diagnosis?.diagnosis_text}
          gateway={gatewayInfo}
          isOnline={allOnline || anyOnline}
        />
      )}

      {targets.length === 0 ? (
        <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] py-12 text-center text-[var(--text-muted)]">
          <Globe size={36} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm font-bold">Nessun target WAN configurato per {clientName}</p>
          <p className="text-[10px] mt-1 opacity-70">Clicca "Aggiungi Target WAN" per iniziare il monitoraggio dell'IP pubblico</p>
        </div>
      ) : (
        <>
          {/* DEVICE GROUPS — adaptive layout:
              - Se solo firewall O solo router: layout 2 colonne (lista target | insights)
              - Se entrambi: due card side-by-side, ognuna con i suoi target+insights */}
          {firewalls.length > 0 && routers.length > 0 ? (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid="wan-firewalls-group">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={14} weight="bold" className="text-indigo-400" />
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-300">Firewall</h3>
                  <div className="flex-1 h-px bg-indigo-500/15"></div>
                  <span className="text-[9px] text-indigo-300/70">{firewalls.length}</span>
                </div>
                <div className="space-y-2">
                  {firewalls.map(t => <TargetCard key={t.id} target={t} onDelete={handleDelete} onHistory={setHistoryTarget} />)}
                </div>
                {firewalls.map(t => <InsightsPanel key={`ins-${t.id}`} target={t} />)}
              </div>
              <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid="wan-routers-group">
                <div className="flex items-center gap-2">
                  <HardDrives size={14} weight="bold" className="text-cyan-400" />
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-300">Router</h3>
                  <div className="flex-1 h-px bg-cyan-500/15"></div>
                  <span className="text-[9px] text-cyan-300/70">{routers.length}</span>
                </div>
                <div className="space-y-2">
                  {routers.map(t => <TargetCard key={t.id} target={t} onDelete={handleDelete} onHistory={setHistoryTarget} />)}
                </div>
                {routers.map(t => <InsightsPanel key={`ins-${t.id}`} target={t} />)}
              </div>
            </div>
          ) : (firewalls.length > 0 || routers.length > 0) && (
            // SINGOLO GRUPPO: target cards a sinistra, insights a destra (riempie tutto lo spazio)
            <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid={firewalls.length > 0 ? "wan-firewalls-group" : "wan-routers-group"}>
              <div className="flex items-center gap-2">
                {firewalls.length > 0 ? <ShieldCheck size={14} weight="bold" className="text-indigo-400" /> : <HardDrives size={14} weight="bold" className="text-cyan-400" />}
                <h3 className={`text-[10px] font-bold uppercase tracking-[0.18em] ${firewalls.length > 0 ? "text-indigo-300" : "text-cyan-300"}`}>
                  {firewalls.length > 0 ? "Firewall" : "Router"}
                </h3>
                <div className={`flex-1 h-px ${firewalls.length > 0 ? "bg-indigo-500/15" : "bg-cyan-500/15"}`}></div>
                <span className={`text-[9px] ${firewalls.length > 0 ? "text-indigo-300/70" : "text-cyan-300/70"}`}>
                  {firewalls.length + routers.length}
                </span>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(260px,380px),1fr] gap-3">
                <div className="space-y-2">
                  {(firewalls.length > 0 ? firewalls : routers).map(t => (
                    <TargetCard key={t.id} target={t} onDelete={handleDelete} onHistory={setHistoryTarget} />
                  ))}
                </div>
                <div className="space-y-3">
                  {(firewalls.length > 0 ? firewalls : routers).map(t => (
                    <InsightsPanel key={`ins-${t.id}`} target={t} />
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* OTHERS (rare) */}
          {others.length > 0 && (
            <div className="space-y-2">
              {others.map(t => (
                <div key={t.id} className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3">
                  <TargetCard target={t} onDelete={handleDelete} onHistory={setHistoryTarget} />
                </div>
              ))}
            </div>
          )}

          {/* MULTI-ISP (mostrato solo se >=2 linee) */}
          <MultiIspCard clientId={clientId} />

          {/* INTELLIGENCE GRID: GEO / DNS / IP HISTORY / SPEEDTEST */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {targets.slice(0, 1).map(t => (
              <GeoIspCard key={`geo-${t.id}`} ip={t.public_ip} />
            ))}
            {targets.slice(0, 1).map(t => (
              <DnsHealthCard key={`dns-${t.id}`} targetId={t.id} />
            ))}
            {targets.slice(0, 1).map(t => (
              <PublicIpHistoryCard key={`iph-${t.id}`} targetId={t.id} currentIp={t.public_ip} />
            ))}
            <SpeedtestCard clientId={clientId} />
          </div>

          {/* FASE 2: SaaS Reachability + Traceroute */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <SaasReachabilityCard clientId={clientId} />
            <TracerouteCard targets={targets} clientId={clientId} />
          </div>
        </>
      )}

      {/* ADD DIALOG */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-lg" data-testid="add-wan-dialog">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <Globe size={16} weight="bold" className="text-indigo-400" /> Aggiungi Target WAN
            </DialogTitle>
            <DialogDescription className="text-[var(--text-muted)] text-xs">
              Monitora un firewall/router pubblico di {clientName}.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-[10px] uppercase text-[var(--text-muted)]">Nome</Label>
              <Input value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} placeholder="Firewall Sede" className="h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="wan-label-input" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-[10px] uppercase text-[var(--text-muted)]">Tipo</Label>
                <Select value={form.device_type} onValueChange={(v) => setForm({ ...form, device_type: v })}>
                  <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] h-8 text-xs" data-testid="wan-type-select"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                    <SelectItem value="firewall">Firewall</SelectItem>
                    <SelectItem value="router">Router</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[10px] uppercase text-[var(--text-muted)]">IP Pubblico</Label>
                <Input value={form.public_ip} onChange={e => setForm({ ...form, public_ip: e.target.value })} placeholder="x.x.x.x" className="h-8 text-xs font-mono bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="wan-public-ip-input" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-[10px] uppercase text-[var(--text-muted)]">Gateway ISP (opz.)</Label>
                <Input value={form.gateway_ip} onChange={e => setForm({ ...form, gateway_ip: e.target.value })} placeholder="next-hop ISP" className="h-8 text-xs font-mono bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="wan-gateway-input" />
              </div>
              <div>
                <Label className="text-[10px] uppercase text-[var(--text-muted)]">Porte TCP</Label>
                <Input value={form.check_ports} onChange={e => setForm({ ...form, check_ports: e.target.value })} placeholder="443,80" className="h-8 text-xs font-mono bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="wan-ports-input" />
              </div>
            </div>
            <label className="flex items-center gap-2 text-[11px] text-[var(--text-muted)] cursor-pointer">
              <input type="checkbox" checked={form.check_ping} onChange={e => setForm({ ...form, check_ping: e.target.checked })} data-testid="wan-ping-checkbox" />
              Esegui anche Ping ICMP
            </label>
          </div>
          <DialogFooter>
            <Button onClick={() => setShowAdd(false)} variant="outline">Annulla</Button>
            <Button onClick={handleAdd} disabled={saving} className="bg-indigo-600 hover:bg-indigo-700 text-white" data-testid="wan-save-btn">
              {saving ? "Salvataggio…" : "Aggiungi"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ATTACH DIALOG */}
      <Dialog open={showAttach} onOpenChange={setShowAttach}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-2xl" data-testid="attach-wan-dialog">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <Globe size={16} weight="bold" className="text-indigo-400" /> Aggancia target a {clientName}
            </DialogTitle>
            <DialogDescription className="text-[var(--text-muted)] text-xs">
              Mostra tutti i target del sistema NON assegnati a {clientName}. Cliccando riassegni il target a questo cliente.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {loadingAttach ? (
              <div className="text-center py-6 text-[var(--text-muted)] text-xs">Caricamento…</div>
            ) : allTargets.length === 0 ? (
              <div className="text-center py-6 text-[var(--text-muted)] text-xs">Nessun target da agganciare.</div>
            ) : allTargets.map(t => (
              <button key={t.id} onClick={() => attachTarget(t)} disabled={attaching === t.id} className="w-full text-left flex items-center gap-3 p-2 rounded border border-[var(--bg-border)] hover:bg-indigo-500/10 hover:border-indigo-500/40 transition-all disabled:opacity-50" data-testid={`attach-wan-${t.id}`}>
                {t.device_type === "firewall" ? <ShieldCheck size={14} className="text-indigo-400" /> : <HardDrives size={14} className="text-cyan-400" />}
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-bold text-[var(--text-primary)]">{t.label}</div>
                  <div className="text-[10px] font-mono text-[var(--text-muted)]">{t.public_ip}</div>
                </div>
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">{allClients[t.client_id] || "orfano"}</span>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {/* HISTORY CHART DIALOG */}
      {historyTarget && (
        <HistoryChartDialog
          target={historyTarget}
          open={!!historyTarget}
          onOpenChange={(o) => { if (!o) setHistoryTarget(null); }}
        />
      )}
    </div>
  );
}
