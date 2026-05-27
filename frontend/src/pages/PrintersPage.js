import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Printer, Warning, CheckCircle, XCircle, Drop,
  FileText, ArrowClockwise, Globe, CaretDown, CaretUp,
  WifiHigh, WifiSlash, Stack, Info, DownloadSimple, PencilSimple,
  Clock, CurrencyEur, MapPin, Barcode, FloppyDisk, X as XIcon
} from "@phosphor-icons/react";

export default function PrintersPage() {
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [extDashboard, setExtDashboard] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [loading, setLoading] = useState(true);
  const [forecastMap, setForecastMap] = useState({});
  const [editingPrinter, setEditingPrinter] = useState(null);

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
    Promise.all([
      axios.get(`${API}/printers/dashboard/${clientId}`),
      axios.get(`${API}/printers/${clientId}/dashboard-extended`),
    ]).then(([d, ed]) => {
      setDashboard(d.data);
      setExtDashboard(ed.data);
    }).catch(() => {
      setDashboard(null);
      setExtDashboard(null);
    }).finally(() => setLoading(false));
  };

  const seedDemo = async () => {
    try {
      await axios.post(`${API}/printers/seed-demo/${clientId}`);
      toast.success("Dati demo stampanti caricati");
      fetchDashboard();
    } catch { toast.error("Errore"); }
  };

  const fetchForecast = async (ip) => {
    if (forecastMap[ip]) return;  // gia' caricato
    try {
      const r = await axios.get(`${API}/printers/${clientId}/${ip}/forecast`);
      setForecastMap(prev => ({ ...prev, [ip]: r.data }));
    } catch (e) {
      // forecast e' opzionale, non spammiamo errori
    }
  };

  const toggleExpand = (ip) => {
    const next = expanded === ip ? null : ip;
    setExpanded(next);
    if (next) fetchForecast(next);
  };

  const exportCsv = async () => {
    if (!clientId) return;
    try {
      const res = await axios.get(`${API}/printers/${clientId}/export-csv`, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `argus_stampanti_${clientId.slice(0,8)}_${new Date().toISOString().slice(0,10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
      toast.success("CSV scaricato");
    } catch (e) {
      toast.error("Errore export CSV");
    }
  };

  const printers = dashboard?.printers || [];
  const eur = (n) => `${(n || 0).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="printers-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)]">Gestione Stampanti</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Monitoraggio toner, contatori pagine, forecast esaurimento, costi</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={exportCsv}
            disabled={printers.length === 0}
            className="h-8 px-3 rounded-lg bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-emerald-400 hover:border-emerald-500/30 text-xs flex items-center gap-1 transition-colors disabled:opacity-40"
            data-testid="export-csv-btn"
            title="Esporta il parco stampanti in CSV (volumi, supplies, costi 30gg)">
            <DownloadSimple size={14} /> Export CSV
          </button>
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
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <StatCard label="Stampanti" value={dashboard.total} icon={<Printer size={16} />} color="indigo" />
          <StatCard label="Online" value={dashboard.online} icon={<WifiHigh size={16} />} color="emerald" />
          <StatCard label="Offline" value={dashboard.offline} icon={<WifiSlash size={16} />} color="red" />
          <StatCard label="Toner Basso" value={dashboard.low_toner_count} icon={<Warning size={16} />} color="amber" />
          <StatCard label="Pagine Tot." value={formatNumber(dashboard.total_pages)} icon={<FileText size={16} />} color="zinc" />
          <StatCard
            label="Costo 30gg"
            value={eur(extDashboard?.estimated_monthly_cost)}
            icon={<CurrencyEur size={16} />}
            color="emerald"
          />
        </div>
      )}

      {/* Extended dashboard: Page breakdown + Cost top + Critical supplies + Locations */}
      {extDashboard && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Page breakdown */}
          <div className="noc-panel p-3" data-testid="page-breakdown-panel">
            <h4 className="text-[10px] uppercase tracking-widest text-indigo-400 font-semibold mb-2 flex items-center gap-1">
              <FileText size={12} /> Pagine per Tipo
            </h4>
            <div className="space-y-1.5 text-xs">
              <BreakdownRow label="Bianco/Nero" value={formatNumber(extDashboard.page_breakdown.bw)} pct={100 - extDashboard.page_breakdown.color_ratio} color="#64748B" />
              <BreakdownRow label="Colore" value={formatNumber(extDashboard.page_breakdown.color)} pct={extDashboard.page_breakdown.color_ratio} color="#A855F7" />
              <BreakdownRow label="Fronte/Retro" value={formatNumber(extDashboard.page_breakdown.duplex)} color="#06B6D4" />
              {extDashboard.page_breakdown.large_format > 0 && <BreakdownRow label="Formato Grande" value={formatNumber(extDashboard.page_breakdown.large_format)} color="#F59E0B" />}
              {extDashboard.page_breakdown.scan > 0 && <BreakdownRow label="Scan" value={formatNumber(extDashboard.page_breakdown.scan)} color="#10B981" />}
              {extDashboard.page_breakdown.fax > 0 && <BreakdownRow label="Fax" value={formatNumber(extDashboard.page_breakdown.fax)} color="#EC4899" />}
            </div>
          </div>

          {/* Top cost printers */}
          <div className="noc-panel p-3 md:col-span-2" data-testid="cost-breakdown-panel">
            <h4 className="text-[10px] uppercase tracking-widest text-emerald-400 font-semibold mb-2 flex items-center gap-1">
              <CurrencyEur size={12} /> Top Stampanti per Costo (30gg)
            </h4>
            {extDashboard.cost_breakdown_top10?.length > 0 ? (
              <div className="space-y-1.5 text-xs">
                {extDashboard.cost_breakdown_top10.slice(0, 5).map((c, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-[var(--text-primary)] truncate flex-1" title={`${c.device_name} • ${c.location || 'no sede'}`}>
                      {c.device_name}
                    </span>
                    <span className="text-[var(--text-muted)] font-mono text-[10px]">{formatNumber(c.pages_30d)} pag</span>
                    <span className="text-emerald-400 font-mono font-bold w-[60px] text-right">{eur(c.cost_30d)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-[var(--text-muted)] italic">Imposta CPP sulle stampanti per vedere i costi (modifica metadata icona ✏️)</p>
            )}
          </div>

          {/* Supplies critical */}
          <div className="noc-panel p-3" data-testid="critical-supplies-panel">
            <h4 className="text-[10px] uppercase tracking-widest text-red-400 font-semibold mb-2 flex items-center gap-1">
              <Clock size={12} /> Esaurimento Imminente (≤10gg)
            </h4>
            {extDashboard.supplies_critical?.length > 0 ? (
              <div className="space-y-1.5 text-xs">
                {extDashboard.supplies_critical.slice(0, 5).map((s, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: s.color_hex || "#9CA3AF" }} />
                    <span className="text-[var(--text-primary)] truncate flex-1 text-[10px]" title={s.device_name}>{s.supply_name}</span>
                    <span className="text-red-400 font-mono font-bold text-[10px]">{s.days_remaining}gg</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-[var(--text-muted)] italic">Tutti i consumabili sopra la soglia critica.</p>
            )}
          </div>
        </div>
      )}

      {/* Low Toner Alerts (legacy) */}
      {dashboard?.low_toner?.length > 0 && (
        <div className="noc-panel p-3 border-l-2 border-l-amber-500">
          <h3 className="text-[10px] uppercase tracking-widest text-amber-400 font-semibold mb-2 flex items-center gap-1">
            <Warning size={12} weight="fill" /> Avvisi Toner Basso (≤15%)
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
              forecast={forecastMap[p.device_ip]}
              expanded={expanded === p.device_ip}
              onToggle={() => toggleExpand(p.device_ip)}
              onEditMetadata={() => setEditingPrinter(p)}
            />
          ))}
        </div>
      )}

      {editingPrinter && (
        <EditMetadataModal
          printer={editingPrinter}
          clientId={clientId}
          onClose={() => setEditingPrinter(null)}
          onSaved={() => { setEditingPrinter(null); fetchDashboard(); }}
        />
      )}
    </div>
  );
}

function PrinterCard({ printer, expanded, onToggle, forecast, onEditMetadata }) {
  const p = printer;
  const isOnline = p.reachable;
  const supplies = p.supplies || [];
  const toners = supplies.filter(s => s.type === "toner" || s.color_name !== "unknown");
  const trays = p.trays || [];
  const alerts = p.alert_messages || [];

  // Mappa nome supply → forecast info per badge inline
  const forecastByName = {};
  for (const s of (forecast?.supplies || [])) {
    if (s.name) forecastByName[s.name.toLowerCase().trim()] = s;
  }

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
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
              {p.model || p.device_ip} | {p.device_ip}
              {p.location && <span className="ml-1.5 text-cyan-400/70"><MapPin size={9} className="inline" /> {p.location}</span>}
              {p.asset_tag && <span className="ml-1.5 text-purple-400/70"><Barcode size={9} className="inline" /> {p.asset_tag}</span>}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="text-right">
            <p className="text-sm font-bold text-[var(--text-primary)] font-mono">{formatNumber(p.page_count || 0)}</p>
            <p className="text-[9px] text-[var(--text-muted)]">pagine</p>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onEditMetadata?.(); }}
            className="p-1.5 rounded hover:bg-cyan-500/15 text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
            title="Modifica metadata (asset, sede, costo/pagina, contratto)"
            data-testid={`edit-metadata-${p.device_ip}`}
          >
            <PencilSimple size={12} weight="bold" />
          </button>
          {expanded ? <CaretUp size={14} className="text-[var(--text-muted)]" /> : <CaretDown size={14} className="text-[var(--text-muted)]" />}
        </div>
      </div>

      {/* Toner Bars (always visible) */}
      {toners.length > 0 && (
        <div className="px-3 pb-2 flex gap-1.5">
          {toners.map((s, i) => (
            <TonerBar key={i} supply={s} compact forecast={forecastByName[(s.name||"").toLowerCase().trim()]} />
          ))}
        </div>
      )}

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-[var(--bg-border)] p-3 space-y-3 bg-[var(--bg-deep)] animate-fade-in">
          {/* Supply Details with forecast */}
          <div>
            <h4 className="text-[10px] uppercase tracking-widest text-indigo-400 font-semibold mb-2">Consumabili</h4>
            <div className="space-y-2">
              {supplies.map((s, i) => (
                <TonerBar key={i} supply={s} forecast={forecastByName[(s.name||"").toLowerCase().trim()]} />
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

          {/* Counters extended */}
          <div>
            <h4 className="text-[10px] uppercase tracking-widest text-indigo-400 font-semibold mb-2">Contatori Pagine</h4>
            <div className="grid grid-cols-3 md:grid-cols-4 gap-2">
              <CounterBox label="Totale" value={formatNumber(p.page_count || 0)} />
              <CounterBox label="B&W" value={formatNumber(Math.max(0, (p.page_count||0) - (p.color_page_count||0)))} />
              <CounterBox label="Colore" value={formatNumber(p.color_page_count || 0)} />
              <CounterBox label="Fronte/Retro" value={formatNumber(p.duplex_count || 0)} />
              {(p.large_format_count > 0) && <CounterBox label="Formato Grande" value={formatNumber(p.large_format_count)} />}
              {(p.scan_count > 0) && <CounterBox label="Scan" value={formatNumber(p.scan_count)} />}
              {(p.fax_count > 0) && <CounterBox label="Fax" value={formatNumber(p.fax_count)} />}
            </div>
          </div>

          {/* CPP / Cost */}
          {(p.cpp_bw || p.cpp_color) && (
            <div className="flex items-center gap-4 text-[10px] bg-emerald-500/5 border border-emerald-500/20 rounded p-2">
              <CurrencyEur size={12} className="text-emerald-400" />
              <span className="text-[var(--text-muted)]">Cost/Pag:</span>
              {p.cpp_bw > 0 && <span className="text-emerald-400 font-mono">B&W <b>{(p.cpp_bw*1000).toFixed(1)}€/1000</b></span>}
              {p.cpp_color > 0 && <span className="text-emerald-400 font-mono">Color <b>{(p.cpp_color*1000).toFixed(1)}€/1000</b></span>}
              {p.contract_ref && <span className="ml-auto text-cyan-400">Contratto: {p.contract_ref}</span>}
            </div>
          )}

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
          <div className="flex items-center gap-4 text-[10px] text-[var(--text-muted)] pt-1 border-t border-[var(--bg-border)] flex-wrap">
            {p.serial && <span>S/N: {p.serial}</span>}
            {p.cost_center && <span>CdC: {p.cost_center}</span>}
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

function TonerBar({ supply, compact = false, forecast = null }) {
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
  // Forecast badge color: rosso se ≤7gg, ambra se ≤21gg, neutro altrimenti
  const days = forecast?.days_remaining;
  const fcColor = days == null ? null : days <= 7 ? "text-red-400" : days <= 21 ? "text-amber-400" : "text-emerald-400/80";
  const fcLabel = days == null
    ? (forecast?.reason === "recently_refilled" ? "ricaricato" : forecast?.reason === "insufficient_history" ? "—" : null)
    : `~${days < 1 ? "<1" : Math.round(days)}gg`;

  if (compact) {
    return (
      <div className="flex-1 min-w-[40px]" title={`${name}: ${level}%${days ? ` • esaurimento ~${Math.round(days)}gg` : ''}`}>
        <div className="h-2 rounded-full bg-[var(--bg-deep)] overflow-hidden">
          <div className="h-full rounded-full transition-all" style={{ width: `${level}%`, background: barColor }} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: hex }} />
      <span className="text-[10px] text-[var(--text-secondary)] w-[140px] truncate" title={name}>{name}</span>
      <div className="flex-1 h-2.5 rounded-full bg-[var(--bg-card)] border border-[var(--bg-border)] overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${level}%`, background: barColor }} />
      </div>
      <span className={`text-[10px] font-mono font-bold w-[36px] text-right ${level <= 5 ? "text-red-400" : level <= 15 ? "text-amber-400" : "text-[var(--text-primary)]"}`}>{level}%</span>
      {fcLabel && (
        <span
          className={`text-[9px] font-mono font-bold w-[50px] text-right ${fcColor || "text-[var(--text-muted)]"}`}
          title={
            forecast?.reason === "recently_refilled" ? "Supply ricaricato di recente"
            : forecast?.daily_pct ? `Consumo medio ${forecast.daily_pct.toFixed(2)}%/gg (basato su ${forecast.samples} snapshot in ${forecast.days_observed}gg)`
            : "Storico insufficiente"
          }
        >
          {fcLabel}
        </span>
      )}
    </div>
  );
}

function BreakdownRow({ label, value, pct = null, color }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
      <span className="text-[var(--text-secondary)] flex-1 text-[11px]">{label}</span>
      <span className="text-[var(--text-primary)] font-mono font-bold text-[10px]">{value}</span>
      {pct != null && <span className="text-[var(--text-muted)] text-[9px] w-[34px] text-right">{pct.toFixed(0)}%</span>}
    </div>
  );
}

function EditMetadataModal({ printer, clientId, onClose, onSaved }) {
  const [form, setForm] = useState({
    asset_tag: printer.asset_tag || "",
    location: printer.location || "",
    cost_center: printer.cost_center || "",
    cpp_bw: printer.cpp_bw ?? "",
    cpp_color: printer.cpp_color ?? "",
    contract_ref: printer.contract_ref || "",
    notes: printer.notes || "",
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        asset_tag: form.asset_tag || null,
        location: form.location || null,
        cost_center: form.cost_center || null,
        cpp_bw: form.cpp_bw === "" ? null : Number(form.cpp_bw),
        cpp_color: form.cpp_color === "" ? null : Number(form.cpp_color),
        contract_ref: form.contract_ref || null,
        notes: form.notes || null,
      };
      await axios.put(`${API}/printers/${clientId}/${printer.device_ip}/metadata`, payload);
      toast.success("Metadata salvati");
      onSaved?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in" data-testid="edit-printer-metadata-modal" onClick={onClose}>
      <div className="bg-[var(--bg-card)] border border-[var(--bg-border)] rounded-lg max-w-lg w-full p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--bg-border)] pb-3">
          <div>
            <h3 className="font-heading text-sm font-bold text-[var(--text-primary)]">Modifica Metadata Stampante</h3>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{printer.device_name || printer.device_ip} • {printer.device_ip}</p>
          </div>
          <button onClick={onClose} className="p-1 text-[var(--text-muted)] hover:text-red-400" data-testid="edit-metadata-close-btn">
            <XIcon size={16} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <Field label="Numero Cespite / Asset Tag" icon={<Barcode size={11} />}>
            <input
              type="text" value={form.asset_tag}
              onChange={(e) => setForm({ ...form, asset_tag: e.target.value })}
              placeholder="es. AST-2024-001"
              className="w-full h-7 px-2 rounded bg-[var(--bg-deep)] border border-[var(--bg-border)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 text-[11px]"
              data-testid="field-asset-tag"
            />
          </Field>
          <Field label="Sede / Ufficio / Piano" icon={<MapPin size={11} />}>
            <input
              type="text" value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              placeholder="es. Sede Roma, Piano 2"
              className="w-full h-7 px-2 rounded bg-[var(--bg-deep)] border border-[var(--bg-border)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 text-[11px]"
              data-testid="field-location"
            />
          </Field>
          <Field label="Centro di Costo">
            <input
              type="text" value={form.cost_center}
              onChange={(e) => setForm({ ...form, cost_center: e.target.value })}
              placeholder="es. CdC-IT-2024"
              className="w-full h-7 px-2 rounded bg-[var(--bg-deep)] border border-[var(--bg-border)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 text-[11px]"
              data-testid="field-cost-center"
            />
          </Field>
          <Field label="Riferimento Contratto MPS">
            <input
              type="text" value={form.contract_ref}
              onChange={(e) => setForm({ ...form, contract_ref: e.target.value })}
              placeholder="es. MPS-2024-XYZ"
              className="w-full h-7 px-2 rounded bg-[var(--bg-deep)] border border-[var(--bg-border)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 text-[11px]"
              data-testid="field-contract-ref"
            />
          </Field>
          <Field label="Costo Pagina B&W (€)" icon={<CurrencyEur size={11} />}>
            <input
              type="number" step="0.001" min="0" max="10"
              value={form.cpp_bw}
              onChange={(e) => setForm({ ...form, cpp_bw: e.target.value })}
              placeholder="es. 0.008"
              className="w-full h-7 px-2 rounded bg-[var(--bg-deep)] border border-[var(--bg-border)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 text-[11px] font-mono"
              data-testid="field-cpp-bw"
            />
          </Field>
          <Field label="Costo Pagina Colore (€)" icon={<CurrencyEur size={11} />}>
            <input
              type="number" step="0.001" min="0" max="10"
              value={form.cpp_color}
              onChange={(e) => setForm({ ...form, cpp_color: e.target.value })}
              placeholder="es. 0.062"
              className="w-full h-7 px-2 rounded bg-[var(--bg-deep)] border border-[var(--bg-border)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 text-[11px] font-mono"
              data-testid="field-cpp-color"
            />
          </Field>
          <div className="col-span-2">
            <Field label="Note">
              <textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="Note libere..."
                rows={2}
                maxLength={2000}
                className="w-full px-2 py-1 rounded bg-[var(--bg-deep)] border border-[var(--bg-border)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-cyan-500 text-[11px] resize-none"
                data-testid="field-notes"
              />
            </Field>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--bg-border)] pt-3">
          <button onClick={onClose} disabled={saving}
            className="h-7 px-3 rounded border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)] text-[11px]"
            data-testid="edit-metadata-cancel-btn">
            Annulla
          </button>
          <button onClick={save} disabled={saving}
            className="h-7 px-3 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] flex items-center gap-1 disabled:opacity-50"
            data-testid="edit-metadata-save-btn">
            <FloppyDisk size={12} /> {saving ? "Salvataggio…" : "Salva"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, icon, children }) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-1 flex items-center gap-1">
        {icon} {label}
      </label>
      {children}
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
