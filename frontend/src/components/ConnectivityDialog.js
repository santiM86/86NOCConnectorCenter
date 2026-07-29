import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Pulse, WifiHigh, WifiSlash, Timer, ArrowsClockwise, Warning,
  CheckCircle, Lightning, ChartLineUp, ArrowDown,
} from "@phosphor-icons/react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";

const PERIODS = [
  { key: "1h", label: "1h" },
  { key: "6h", label: "6h" },
  { key: "24h", label: "24h" },
  { key: "7d", label: "7g" },
  { key: "30d", label: "30g" },
];

const fmtTime = (iso, period) => {
  try {
    const d = new Date(iso);
    if (period === "1h" || period === "6h" || period === "24h")
      return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit" });
  } catch { return iso; }
};

const SEV = {
  ok:   { c: "#34C759", bg: "bg-emerald-500/10", br: "border-emerald-500/30", tx: "text-emerald-300", label: "Connettività sana" },
  warn: { c: "#FFCC00", bg: "bg-amber-500/10",   br: "border-amber-500/30",   tx: "text-amber-300",   label: "Problemi lievi rilevati" },
  crit: { c: "#FF3B30", bg: "bg-red-500/10",      br: "border-red-500/30",     tx: "text-red-300",     label: "Connettività critica" },
};

function Stat({ icon: Icon, label, value, unit, tone = "text-white", testid }) {
  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-2.5" data-testid={testid}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
        {Icon && <Icon size={12} />} {label}
      </div>
      <div className={`mt-1 font-bold text-lg leading-none ${tone}`}>
        {value ?? "—"}{value != null && unit ? <span className="text-[11px] font-medium text-[var(--text-muted)] ml-0.5">{unit}</span> : ""}
      </div>
    </div>
  );
}

export default function ConnectivityDialog({ deviceIp, clientId, deviceName, open, onClose }) {
  const [period, setPeriod] = useState("24h");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const fetchReport = useCallback(async () => {
    if (!deviceIp) return;
    setLoading(true);
    try {
      const { data } = await axios.get(
        `${API}/devices/by-ip/${encodeURIComponent(deviceIp)}/connectivity-report`,
        { params: { period, client_id: clientId } }
      );
      setReport(data);
    } catch (e) {
      toast.error("Errore caricamento report connettività");
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [deviceIp, clientId, period]);

  useEffect(() => {
    if (open) { setTestResult(null); fetchReport(); }
  }, [open, fetchReport]);

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data } = await axios.post(
        `${API}/devices/by-ip/${encodeURIComponent(deviceIp)}/connectivity-test`,
        { client_id: clientId, count: 12 }
      );
      setTestResult(data);
      toast.success("Test completato");
      fetchReport();
    } catch (e) {
      toast.error(`Test fallito: ${e.response?.data?.detail || e.message}`);
    } finally {
      setTesting(false);
    }
  };

  const sev = SEV[report?.severity || "ok"];
  const chartData = (report?.series || []).map(p => ({
    t: p.ts,
    latency: p.latency_avg,
    loss: p.loss_avg,
    up: p.up_ratio != null ? Math.round(p.up_ratio * 100) : null,
  }));

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose?.()}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="connectivity-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-white">
            <Pulse size={18} weight="bold" className="text-cyan-400" />
            Connettività — {deviceName || deviceIp}
            <span className="text-[11px] font-mono text-[var(--text-muted)]">{deviceIp}</span>
          </DialogTitle>
        </DialogHeader>

        {/* Toolbar periodo + test */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex gap-1" data-testid="connectivity-period-selector">
            {PERIODS.map(p => (
              <button
                key={p.key}
                onClick={() => setPeriod(p.key)}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors ${
                  period === p.key
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--bg-border)] hover:text-white"
                }`}
                data-testid={`connectivity-period-${p.key}`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <Button
            onClick={runTest}
            disabled={testing}
            className="h-8 bg-cyan-600 hover:bg-cyan-500 text-white text-[12px] gap-1.5"
            data-testid="connectivity-run-test-btn"
          >
            {testing ? <ArrowsClockwise size={13} className="animate-spin" /> : <Lightning size={13} weight="bold" />}
            {testing ? "Test in corso…" : "Esegui test ora"}
          </Button>
        </div>

        {/* Risultato test on-demand */}
        {testResult && (
          <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3" data-testid="connectivity-test-result">
            <div className="text-[11px] font-semibold text-cyan-300 mb-2 flex items-center gap-1.5">
              <Lightning size={12} weight="bold" /> Test istantaneo · agent {testResult.agent?.hostname || "?"}
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center">
              <div><div className="text-[9px] text-[var(--text-muted)] uppercase">Inviati</div><div className="font-bold text-white">{testResult.stats.sent}</div></div>
              <div><div className="text-[9px] text-[var(--text-muted)] uppercase">Ricevuti</div><div className="font-bold text-white">{testResult.stats.received}</div></div>
              <div><div className="text-[9px] text-[var(--text-muted)] uppercase">Loss</div><div className={`font-bold ${testResult.stats.loss_pct > 0 ? "text-red-300" : "text-emerald-300"}`}>{testResult.stats.loss_pct}%</div></div>
              <div><div className="text-[9px] text-[var(--text-muted)] uppercase">Min</div><div className="font-bold text-white">{testResult.stats.min_ms ?? "—"}<span className="text-[9px]">ms</span></div></div>
              <div><div className="text-[9px] text-[var(--text-muted)] uppercase">Media</div><div className="font-bold text-white">{testResult.stats.avg_ms ?? "—"}<span className="text-[9px]">ms</span></div></div>
              <div><div className="text-[9px] text-[var(--text-muted)] uppercase">Max</div><div className="font-bold text-white">{testResult.stats.max_ms ?? "—"}<span className="text-[9px]">ms</span></div></div>
            </div>
            <div className="flex gap-0.5 mt-2 flex-wrap" data-testid="connectivity-test-packets">
              {testResult.packets.map(p => (
                <span
                  key={p.seq}
                  title={p.reachable ? `#${p.seq} · ${p.latency_ms ?? "?"}ms · ${p.method}` : `#${p.seq} · ${p.error || "no reply"}`}
                  className={`w-4 h-4 rounded-sm ${p.reachable ? "bg-emerald-500" : "bg-red-500"}`}
                />
              ))}
            </div>
          </div>
        )}

        {loading && !report ? (
          <div className="py-12 text-center text-[var(--text-muted)] text-sm">Caricamento…</div>
        ) : !report || report.samples === 0 ? (
          <div className="py-12 text-center text-[var(--text-muted)] text-sm" data-testid="connectivity-empty">
            Nessuno storico ping ancora disponibile per questo periodo.<br />
            <span className="text-[11px]">Lo storico si popola automaticamente ad ogni ciclo di polling dell'agent. Usa "Esegui test ora" per un check immediato.</span>
          </div>
        ) : (
          <>
            {/* Banner severità */}
            <div className={`rounded-lg border p-3 flex items-center gap-2 ${sev.bg} ${sev.br}`} data-testid="connectivity-severity-banner">
              {report.severity === "ok" ? <CheckCircle size={18} weight="fill" className={sev.tx} />
                : <Warning size={18} weight="fill" className={sev.tx} />}
              <span className={`font-semibold text-sm ${sev.tx}`}>{sev.label}</span>
              {report.currently_down && (
                <span className="ml-auto flex items-center gap-1 text-red-300 text-[11px] font-bold">
                  <WifiSlash size={13} weight="bold" /> ATTUALMENTE OFFLINE
                </span>
              )}
            </div>

            {/* Statistiche */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat icon={WifiHigh} label="Uptime" value={report.uptime_pct} unit="%" testid="connectivity-stat-uptime"
                tone={report.uptime_pct >= 99.5 ? "text-emerald-300" : report.uptime_pct >= 95 ? "text-amber-300" : "text-red-300"} />
              <Stat icon={Timer} label="Latenza media" value={report.latency.avg} unit="ms" testid="connectivity-stat-latency"
                tone={report.latency.avg == null ? "text-white" : report.latency.avg < 30 ? "text-emerald-300" : report.latency.avg < 100 ? "text-amber-300" : "text-red-300"} />
              <Stat icon={ChartLineUp} label="Latenza p95" value={report.latency.p95} unit="ms" testid="connectivity-stat-p95" />
              <Stat icon={ArrowsClockwise} label="Jitter" value={report.latency.jitter} unit="ms" testid="connectivity-stat-jitter" />
              <Stat icon={ArrowDown} label="Packet loss" value={report.loss.avg} unit="%" testid="connectivity-stat-loss"
                tone={report.loss.avg == null ? "text-white" : report.loss.avg < 2 ? "text-emerald-300" : report.loss.avg < 10 ? "text-amber-300" : "text-red-300"} />
              <Stat icon={WifiSlash} label="Disconnessioni" value={report.disconnections} testid="connectivity-stat-disconnections"
                tone={report.disconnections > 0 ? "text-red-300" : "text-emerald-300"} />
              <Stat icon={Timer} label="MTTR" value={report.mttr_min} unit="min" testid="connectivity-stat-mttr" />
              <Stat icon={Pulse} label="Campioni" value={report.samples} testid="connectivity-stat-samples" />
            </div>

            {/* Grafico latenza */}
            <div>
              <div className="text-[11px] font-semibold text-[var(--text-muted)] mb-1 flex items-center gap-1.5">
                <Timer size={12} /> Latenza (ms)
              </div>
              <div className="h-40 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="conn-lat" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#22D3EE" stopOpacity={0.5} />
                        <stop offset="100%" stopColor="#22D3EE" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="t" tickFormatter={(t) => fmtTime(t, period)} stroke="#666" fontSize={9} minTickGap={40} />
                    <YAxis stroke="#666" fontSize={9} width={32} />
                    <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                    <RTooltip
                      contentStyle={{ background: "#0a0d14", border: "1px solid #1f2937", borderRadius: 6, fontSize: 10 }}
                      labelFormatter={(v) => new Date(v).toLocaleString("it-IT")}
                      formatter={(val) => [`${val} ms`, "Latenza"]}
                    />
                    <ReferenceLine y={30} stroke="#FFCC00" strokeDasharray="4 4" />
                    <ReferenceLine y={100} stroke="#FF3B30" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="latency" stroke="#22D3EE" fill="url(#conn-lat)" strokeWidth={1.6} isAnimationActive={false} connectNulls />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Grafico packet loss */}
            <div>
              <div className="text-[11px] font-semibold text-[var(--text-muted)] mb-1 flex items-center gap-1.5">
                <ArrowDown size={12} /> Packet loss (%)
              </div>
              <div className="h-28 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="conn-loss" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#FF3B30" stopOpacity={0.5} />
                        <stop offset="100%" stopColor="#FF3B30" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="t" tickFormatter={(t) => fmtTime(t, period)} stroke="#666" fontSize={9} minTickGap={40} />
                    <YAxis stroke="#666" fontSize={9} width={32} domain={[0, 100]} />
                    <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                    <RTooltip
                      contentStyle={{ background: "#0a0d14", border: "1px solid #1f2937", borderRadius: 6, fontSize: 10 }}
                      labelFormatter={(v) => new Date(v).toLocaleString("it-IT")}
                      formatter={(val) => [`${val}%`, "Loss"]}
                    />
                    <Area type="monotone" dataKey="loss" stroke="#FF3B30" fill="url(#conn-loss)" strokeWidth={1.4} isAnimationActive={false} connectNulls />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Finestre di down */}
            {report.down_windows?.length > 0 && (
              <div data-testid="connectivity-down-windows">
                <div className="text-[11px] font-semibold text-[var(--text-muted)] mb-1 flex items-center gap-1.5">
                  <WifiSlash size={12} /> Interruzioni ({report.down_windows.length})
                </div>
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {report.down_windows.slice().reverse().map((w, i) => (
                    <div key={i} className="flex items-center justify-between text-[11px] rounded bg-red-500/5 border border-red-500/20 px-2 py-1">
                      <span className="text-[var(--text-muted)]">
                        {new Date(w.start).toLocaleString("it-IT")} {w.ongoing ? "→ in corso" : `→ ${new Date(w.end).toLocaleTimeString("it-IT")}`}
                      </span>
                      <span className={`font-bold ${w.ongoing ? "text-red-300" : "text-amber-300"}`}>
                        {w.ongoing ? "IN CORSO" : `${w.duration_min} min`}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
