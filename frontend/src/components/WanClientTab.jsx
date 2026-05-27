import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Globe, ShieldCheck, HardDrives, WifiHigh, Lightning, Plus, Trash,
  ArrowClockwise, CheckCircle, Warning, MapPin, Pulse, Gauge,
  ArrowsClockwise, ChartLine, Clock, ArrowsLeftRight, PencilSimple,
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
      <div className="flex items-center justify-between px-6 py-5 border-l-[4px]" style={{ borderColor: color }}>
        <div className="flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ background: `${color}15` }}>
            <CheckCircle size={26} weight="bold" style={{ color }} />
          </div>
          <div>
            <h2 className="text-2xl font-bold tracking-tight" style={{ color }} data-testid="wan-hero-client-name">{clientName}</h2>
            <p className="text-[12px] mt-0.5" style={{ color: `${color}cc` }} data-testid="wan-hero-diagnosis">{diagnosis || (isOk ? "Connettività OK" : "Stato in attesa di probe...")}</p>
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
function TargetCard({ target, onDelete }) {
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
        <button onClick={() => onDelete(target)} className="p-1 rounded hover:bg-red-500/15 text-red-400 ml-1" title="Rimuovi" data-testid={`wan-target-delete-${target.id}`}>
          <Trash size={12} />
        </button>
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
          {/* DEVICE GROUPS (firewall + router) */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {firewalls.length > 0 && (
              <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid="wan-firewalls-group">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={14} weight="bold" className="text-indigo-400" />
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-300">Firewall</h3>
                  <div className="flex-1 h-px bg-indigo-500/15"></div>
                  <span className="text-[9px] text-indigo-300/70">{firewalls.length}</span>
                </div>
                <div className="space-y-2">
                  {firewalls.map(t => <TargetCard key={t.id} target={t} onDelete={handleDelete} />)}
                </div>
                {firewalls.map(t => <InsightsPanel key={`ins-${t.id}`} target={t} />)}
              </div>
            )}
            {routers.length > 0 && (
              <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid="wan-routers-group">
                <div className="flex items-center gap-2">
                  <HardDrives size={14} weight="bold" className="text-cyan-400" />
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-300">Router</h3>
                  <div className="flex-1 h-px bg-cyan-500/15"></div>
                  <span className="text-[9px] text-cyan-300/70">{routers.length}</span>
                </div>
                <div className="space-y-2">
                  {routers.map(t => <TargetCard key={t.id} target={t} onDelete={handleDelete} />)}
                </div>
                {routers.map(t => <InsightsPanel key={`ins-${t.id}`} target={t} />)}
              </div>
            )}
          </div>

          {/* OTHERS (rare) */}
          {others.length > 0 && (
            <div className="space-y-2">
              {others.map(t => (
                <div key={t.id} className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-3">
                  <TargetCard target={t} onDelete={handleDelete} />
                </div>
              ))}
            </div>
          )}

          {/* INTELLIGENCE GRID: GEO / DNS / IP HISTORY / SPEEDTEST */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
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
    </div>
  );
}
