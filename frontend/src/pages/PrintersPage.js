import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Printer, Warning, CheckCircle, XCircle, Drop,
  FileText, ArrowClockwise, Globe, CaretDown, CaretUp,
  WifiHigh, WifiSlash, Stack, Info
} from "@phosphor-icons/react";

export default function PrintersPage() {
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/clients`).then(r => {
      const c = r.data?.clients || r.data || [];
      setClients(c);
      if (c.length > 0) setClientId(c[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!clientId) return;
    fetchDashboard();
  }, [clientId]);

  const fetchDashboard = () => {
    setLoading(true);
    axios.get(`${API}/printers/dashboard/${clientId}`)
      .then(r => setDashboard(r.data))
      .catch(() => setDashboard(null))
      .finally(() => setLoading(false));
  };

  const seedDemo = async () => {
    try {
      await axios.post(`${API}/printers/seed-demo/${clientId}`);
      toast.success("Dati demo stampanti caricati");
      fetchDashboard();
    } catch { toast.error("Errore"); }
  };

  const printers = dashboard?.printers || [];

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="printers-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)]">Gestione Stampanti</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Monitoraggio toner, contatori pagine e stato</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchDashboard}
            className="h-8 px-3 rounded-lg bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)] text-xs flex items-center gap-1 transition-colors"
            data-testid="refresh-printers-btn">
            <ArrowClockwise size={14} /> Aggiorna
          </button>
          {printers.length === 0 && !loading && (
            <button onClick={seedDemo}
              className="h-8 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs flex items-center gap-1 transition-colors"
              data-testid="seed-demo-btn">
              <Printer size={14} /> Carica Demo
            </button>
          )}
        </div>
      </div>

      {/* Stats */}
      {dashboard && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="Stampanti" value={dashboard.total} icon={<Printer size={16} />} color="indigo" />
          <StatCard label="Online" value={dashboard.online} icon={<WifiHigh size={16} />} color="emerald" />
          <StatCard label="Offline" value={dashboard.offline} icon={<WifiSlash size={16} />} color="red" />
          <StatCard label="Toner Basso" value={dashboard.low_toner_count} icon={<Warning size={16} />} color="amber" />
          <StatCard label="Pagine Totali" value={formatNumber(dashboard.total_pages)} icon={<FileText size={16} />} color="zinc" />
        </div>
      )}

      {/* Low Toner Alerts */}
      {dashboard?.low_toner?.length > 0 && (
        <div className="noc-panel p-3 border-l-2 border-l-amber-500">
          <h3 className="text-[10px] uppercase tracking-widest text-amber-400 font-semibold mb-2 flex items-center gap-1">
            <Warning size={12} weight="fill" /> Avvisi Toner Basso
          </h3>
          <div className="space-y-1.5">
            {dashboard.low_toner.map((t, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className={`font-mono font-bold ${t.level_pct <= 5 ? "text-red-400" : "text-amber-400"}`}>{t.level_pct}%</span>
                <span className="text-[var(--text-primary)]">{t.supply_name}</span>
                <span className="text-[var(--text-muted)]">su</span>
                <span className="text-[var(--text-secondary)]">{t.printer_name}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Printer Grid */}
      {loading ? (
        <div className="text-center py-12 text-[var(--text-muted)] text-xs">Caricamento...</div>
      ) : printers.length === 0 ? (
        <div className="noc-panel p-12 text-center">
          <Printer size={48} className="mx-auto text-[var(--text-muted)] opacity-30 mb-3" />
          <p className="text-sm text-[var(--text-muted)]">Nessuna stampante monitorata</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">Aggiungi stampanti con tipo "printer" o carica dati demo</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {printers.map(p => (
            <PrinterCard
              key={p.device_ip}
              printer={p}
              expanded={expanded === p.device_ip}
              onToggle={() => setExpanded(expanded === p.device_ip ? null : p.device_ip)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PrinterCard({ printer, expanded, onToggle }) {
  const p = printer;
  const isOnline = p.reachable;
  const supplies = p.supplies || [];
  const toners = supplies.filter(s => s.type === "toner" || s.color_name !== "unknown");
  const otherSupplies = supplies.filter(s => s.type !== "toner" && s.color_name === "unknown");
  const trays = p.trays || [];
  const alerts = p.alert_messages || [];

  return (
    <div className={`noc-panel overflow-hidden transition-all ${!isOnline ? "opacity-70" : ""}`}
      data-testid={`printer-card-${p.device_ip}`}>
      {/* Header */}
      <div className="p-3 flex items-start justify-between cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
        onClick={onToggle}>
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${isOnline ? "bg-indigo-500/15 text-indigo-400" : "bg-red-500/15 text-red-400"}`}>
            <Printer size={20} weight="fill" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-bold text-[var(--text-primary)] truncate">{p.device_name || p.device_ip}</h3>
              <span className={`flex-shrink-0 inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded font-medium ${isOnline ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${isOnline ? "bg-emerald-400" : "bg-red-400"}`} />
                {isOnline ? (p.printer_status || "Online") : "Offline"}
              </span>
            </div>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{p.model || p.device_ip} | {p.device_ip}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="text-right">
            <p className="text-sm font-bold text-[var(--text-primary)] font-mono">{formatNumber(p.page_count || 0)}</p>
            <p className="text-[9px] text-[var(--text-muted)]">pagine</p>
          </div>
          {expanded ? <CaretUp size={14} className="text-[var(--text-muted)]" /> : <CaretDown size={14} className="text-[var(--text-muted)]" />}
        </div>
      </div>

      {/* Toner Bars (always visible) */}
      {toners.length > 0 && (
        <div className="px-3 pb-2 flex gap-1.5">
          {toners.map((s, i) => (
            <TonerBar key={i} supply={s} compact />
          ))}
        </div>
      )}

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-[var(--bg-border)] p-3 space-y-3 bg-[var(--bg-deep)] animate-fade-in">
          {/* Supply Details */}
          <div>
            <h4 className="text-[10px] uppercase tracking-widest text-indigo-400 font-semibold mb-2">Consumabili</h4>
            <div className="space-y-2">
              {supplies.map((s, i) => (
                <TonerBar key={i} supply={s} />
              ))}
            </div>
          </div>

          {/* Trays */}
          {trays.length > 0 && (
            <div>
              <h4 className="text-[10px] uppercase tracking-widest text-indigo-400 font-semibold mb-2">Vassoi Carta</h4>
              <div className="grid grid-cols-2 gap-2">
                {trays.map((t, i) => {
                  const trayPct = t.capacity > 0 ? Math.round((t.level / t.capacity) * 100) : 0;
                  const trayColor = t.status === "empty" ? "bg-red-500" : t.status === "low" ? "bg-amber-500" : "bg-emerald-500";
                  return (
                    <div key={i} className="rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] p-2">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-[10px] text-[var(--text-secondary)]"><Stack size={10} className="inline mr-1" />{t.name}</span>
                        <span className="text-[10px] font-mono text-[var(--text-muted)]">{t.level}/{t.capacity}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-[var(--bg-deep)] overflow-hidden">
                        <div className={`h-full rounded-full transition-all ${trayColor}`} style={{ width: `${trayPct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Counters */}
          <div>
            <h4 className="text-[10px] uppercase tracking-widest text-indigo-400 font-semibold mb-2">Contatori</h4>
            <div className="grid grid-cols-3 gap-2">
              <CounterBox label="Totale" value={formatNumber(p.page_count || 0)} />
              <CounterBox label="Colore" value={formatNumber(p.color_page_count || 0)} />
              <CounterBox label="Fronte/Retro" value={formatNumber(p.duplex_count || 0)} />
            </div>
          </div>

          {/* Alerts */}
          {alerts.length > 0 && (
            <div>
              <h4 className="text-[10px] uppercase tracking-widest text-red-400 font-semibold mb-1">Alert</h4>
              {alerts.map((a, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[10px] text-red-400">
                  <Warning size={10} weight="fill" /> {a}
                </div>
              ))}
            </div>
          )}

          {/* Info */}
          <div className="flex items-center gap-4 text-[10px] text-[var(--text-muted)] pt-1 border-t border-[var(--bg-border)]">
            {p.serial && <span>S/N: {p.serial}</span>}
            {p.last_poll && <span>Ultimo poll: {new Date(p.last_poll).toLocaleString("it-IT")}</span>}
          </div>

          {/* Actions */}
          <button onClick={() => window.open(`http://${p.device_ip}`, "_blank")}
            className="w-full h-7 rounded-md text-[10px] font-medium bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-600/30 transition-colors flex items-center justify-center gap-1"
            data-testid={`printer-web-${p.device_ip}`}>
            <Globe size={12} /> Apri Pagina Web Stampante
          </button>
        </div>
      )}
    </div>
  );
}

function TonerBar({ supply, compact = false }) {
  const level = supply.level_pct;
  const hex = supply.color_hex || "#9e9e9e";
  const name = supply.name || "?";

  if (level === null || level === undefined) {
    return compact ? null : (
      <div className="flex items-center gap-2 text-[10px]">
        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: hex }} />
        <span className="text-[var(--text-secondary)] flex-1">{name}</span>
        <span className="text-[var(--text-muted)]">{supply.level_text || "N/A"}</span>
      </div>
    );
  }

  const barColor = level <= 5 ? "#ef4444" : level <= 15 ? "#f59e0b" : hex;

  if (compact) {
    return (
      <div className="flex-1 min-w-[40px]" title={`${name}: ${level}%`}>
        <div className="h-2 rounded-full bg-[var(--bg-deep)] overflow-hidden">
          <div className="h-full rounded-full transition-all" style={{ width: `${level}%`, background: barColor }} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: hex }} />
      <span className="text-[10px] text-[var(--text-secondary)] w-[160px] truncate">{name}</span>
      <div className="flex-1 h-2.5 rounded-full bg-[var(--bg-card)] border border-[var(--bg-border)] overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${level}%`, background: barColor }} />
      </div>
      <span className={`text-[10px] font-mono font-bold w-[36px] text-right ${level <= 5 ? "text-red-400" : level <= 15 ? "text-amber-400" : "text-[var(--text-primary)]"}`}>{level}%</span>
    </div>
  );
}

function StatCard({ label, value, icon, color }) {
  const cls = {
    indigo: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
    emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    red: "text-red-400 bg-red-500/10 border-red-500/20",
    amber: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    zinc: "text-zinc-400 bg-zinc-500/10 border-zinc-500/20",
  };
  return (
    <div className={`rounded-lg p-3 border ${cls[color]}`} data-testid={`printer-stat-${label.toLowerCase()}`}>
      <div className="mb-1">{icon}</div>
      <p className="font-heading text-xl font-bold leading-none">{value}</p>
      <p className="text-[10px] uppercase tracking-widest mt-1 opacity-70">{label}</p>
    </div>
  );
}

function CounterBox({ label, value }) {
  return (
    <div className="rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] p-2 text-center">
      <p className="font-mono text-sm font-bold text-[var(--text-primary)]">{value}</p>
      <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
    </div>
  );
}

function formatNumber(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}
