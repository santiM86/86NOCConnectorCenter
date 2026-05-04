/**
 * Switch Ports Detail Page - Nebula-style
 * ========================================
 * Vista porta-per-porta in stile HPE Instant On / Cisco Meraki:
 * - Grid 8 colonne con icone contestuali (PoE, AP, Switch, Cloud, Device)
 * - Click su porta -> pannello dettaglio (speed, PoE W/Class, Rx/Tx live, neighbor)
 * - Donut 24h (in/out totals dai counter HC)
 * - Filtri: tutte / up / down / admin-down / con neighbor / PoE attivo
 * - Responsive nativo (mobile + desktop)
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  ArrowsClockwise, Lightning, WifiHigh, Stack, Cloud, Desktop,
  Prohibit, Plugs, ArrowDown, ArrowUp, Cpu, CaretUp, CaretDown,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import PortCableView from "@/components/PortCableView";
import PortFlapHistory from "@/components/PortFlapHistory";

// ----- formatters -----
function fmtSpeed(mbps) {
  if (!mbps || mbps <= 0) return "—";
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(mbps % 1000 ? 1 : 0)} Gbps`;
  return `${mbps} Mbps`;
}
function fmtBps(bps) {
  if (!bps || bps <= 0) return "0 bps";
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(2)} Gbps`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(2)} Mbps`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(2)} kbps`;
  return `${bps} bps`;
}
function fmtPps(pps) {
  if (!pps || pps <= 0) return "0 pps";
  if (pps >= 1e6) return `${(pps / 1e6).toFixed(1)}M pps`;
  if (pps >= 1e3) return `${(pps / 1e3).toFixed(1)}k pps`;
  return `${pps} pps`;
}
function fmtBytes(b) {
  const n = Number(b || 0);
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)} TB`;
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(2)} KB`;
  return `${n} B`;
}
const POE_CLASS_W = { 1: 4.0, 2: 7.0, 3: 15.4, 4: 30.0, 5: 60.0 };
function poeClassLabel(c) {
  if (!c || c < 1 || c > 5) return null;
  return `Classe ${c - 1} (${POE_CLASS_W[c]} W)`;
}
// Estrae label fisica della porta dal nome SNMP.
// Esempi: "GigabitEthernet5/0/1" -> "1", "Ten-GigabitEthernet5/0/49" -> "49",
// "1/1/1" -> "1", "Gi0/1" -> "1", "Ethernet1/1" -> "1", fallback idx SNMP.
function portLabel(name, idx) {
  if (!name) return String(idx ?? "");
  const s = String(name).trim();
  // Prende l'ultimo numero dopo uno "/" se presente
  const m = s.match(/\/(\d+)\s*$/);
  if (m) return m[1];
  // Altrimenti l'ultima sequenza di cifre nel nome
  const m2 = s.match(/(\d+)\s*$/);
  if (m2) return m2[1];
  return String(idx ?? "");
}

// ----- port icon -----
function PortIcon({ p, size = 22 }) {
  const t = p.port_type;
  const cls = "text-emerald-50";
  if (t === "disabled") return <Prohibit size={size} className="text-neutral-400" weight="bold" />;
  if (t === "empty") return null;
  if (t === "poe") return <Lightning size={size} className={cls} weight="fill" />;
  if (t === "ap") return <WifiHigh size={size} className={cls} weight="bold" />;
  if (t === "switch") return <Stack size={size} className={cls} weight="bold" />;
  if (t === "cloud") return <Cloud size={size} className={cls} weight="bold" />;
  if (t === "device") return <Desktop size={size} className={cls} weight="bold" />;
  // link_up generic
  return <Plugs size={size} className={cls} weight="bold" />;
}

function PortTile({ p, onClick, active }) {
  const isDisabled = p.admin === 2;
  const isUp = p.oper === 1 && p.admin === 1;
  const isPoe = p.poe_status === 3;

  let bg = "bg-neutral-700/40 border-neutral-600";
  if (isDisabled) bg = "bg-neutral-800/60 border-neutral-700";
  else if (isUp) {
    bg = isPoe
      ? "bg-emerald-500 border-emerald-300 shadow-emerald-400/40 shadow-md"
      : "bg-emerald-500 border-emerald-300";
  } else bg = "bg-neutral-700/30 border-neutral-600";

  return (
    <button
      onClick={onClick}
      data-testid={`switch-port-tile-${p.idx}`}
      title={`Porta ${p.idx} · ${p.name} · ${p.oper_status}/${p.admin_status}${p.neighbor?.remote_sys_name ? "\n→ " + p.neighbor.remote_sys_name : ""}`}
      className={`relative flex flex-col items-center group`}
    >
      {/* Numero porta sopra (chip nero) - label fisica invece di ifIndex SNMP */}
      <span className="bg-neutral-900 text-neutral-100 text-[10px] font-semibold rounded-full px-1.5 py-[1px] mb-0.5 min-w-[22px] text-center">
        {portLabel(p.name, p.idx)}
      </span>
      {/* Tile */}
      <div className={`flex items-center justify-center w-11 h-11 sm:w-12 sm:h-12 rounded-md border transition-all ${bg} ${active ? "ring-2 ring-cyan-300 scale-110" : "group-hover:scale-105"}`}>
        <PortIcon p={p} />
      </div>
    </button>
  );
}

function PortDetailPanel({ p, onClose, onOpenCable, deviceIp }) {
  if (!p) return null;
  const isUp = p.oper === 1 && p.admin === 1;
  const isPoe = p.poe_status === 3;
  const className = poeClassLabel(p.poe_class);
  const totalIn = Number(p.in_octets || 0);
  const totalOut = Number(p.out_octets || 0);
  const totalAll = totalIn + totalOut;
  // Donut percentages
  const inPct = totalAll > 0 ? Math.round((totalIn / totalAll) * 100) : 0;
  const outPct = 100 - inPct;

  const speedClass = p.speed_mbps >= 1000 ? "bg-emerald-500/30 border-emerald-400 text-emerald-200" : "bg-amber-500/20 border-amber-400 text-amber-200";

  return (
    <div className="noc-panel p-4 space-y-3" data-testid={`switch-port-detail-${p.idx}`}>
      <div className="flex items-baseline justify-between">
        <h3 className="text-base font-bold">Porta {portLabel(p.name, p.idx)} <span className="text-[var(--text-muted)] text-xs font-mono">· {p.name}</span></h3>
        <div className="flex items-center gap-2">
          {onOpenCable && (
            <button
              onClick={onOpenCable}
              className="text-[11px] px-2 py-1 rounded bg-cyan-500/15 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-400/30 flex items-center gap-1 transition-colors"
              data-testid={`switch-port-cable-view-${p.idx}`}
              title="Apri vista cavo con diagramma switch → device"
            >
              ↯ Vista Cavo
            </button>
          )}
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-xs">Chiudi ✕</button>
        </div>
      </div>

      {/* Flap history 24h (micro-sparkline) */}
      {deviceIp && (
        <div className="flex items-center justify-between gap-2 border-b border-[var(--bg-border)] pb-2">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-semibold">Storia flap 24h</span>
          <PortFlapHistory deviceIp={deviceIp} idx={p.idx} hours={24} />
        </div>
      )}

      {/* Status row */}
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        {isUp ? (
          <span className={`px-2 py-1 rounded border font-mono ${speedClass}`}>
            {fmtSpeed(p.speed_mbps)} / Full-duplex
          </span>
        ) : p.admin === 2 ? (
          <span className="px-2 py-1 rounded border bg-neutral-700/40 border-neutral-600 text-neutral-200 font-mono">ADMIN-DOWN</span>
        ) : (
          <span className="px-2 py-1 rounded border bg-red-500/15 border-red-400/40 text-red-300 font-mono">DOWN</span>
        )}
        {isPoe && (
          <span className="px-2 py-1 rounded border bg-amber-400/20 border-amber-300/50 text-amber-200 flex items-center gap-1 font-mono">
            <Lightning size={12} weight="fill" /> PoE attivo {className && `· ${className}`}
          </span>
        )}
        {p.alias && <span className="text-[10px] text-[var(--text-muted)] italic">{p.alias}</span>}
      </div>

      {/* Traffico live */}
      {isUp && (
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div className="flex items-center gap-2 noc-panel-inset px-2 py-1.5 rounded">
            <ArrowDown size={14} className="text-cyan-300" weight="bold" />
            <div>
              <div className="font-mono">{fmtBps(p.rx_bps)}</div>
              <div className="text-[9px] text-[var(--text-muted)]">{fmtPps(p.rx_pps)}</div>
            </div>
          </div>
          <div className="flex items-center gap-2 noc-panel-inset px-2 py-1.5 rounded">
            <ArrowUp size={14} className="text-violet-300" weight="bold" />
            <div>
              <div className="font-mono">{fmtBps(p.tx_bps)}</div>
              <div className="text-[9px] text-[var(--text-muted)]">{fmtPps(p.tx_pps)}</div>
            </div>
          </div>
        </div>
      )}

      {/* Neighbor */}
      {p.neighbor && (
        <div className="flex items-start gap-2 text-[11px] border-t border-[var(--bg-border)] pt-2">
          <PortIcon p={p} size={16} />
          <div className="flex-1 min-w-0">
            <div className="text-[9px] text-[var(--text-muted)] uppercase flex items-center gap-1">
              Connesso a
              {p.neighbor.match_source === "lldp" && (
                <span className="px-1 py-0 rounded bg-emerald-500/20 text-emerald-300 text-[8px] font-bold tracking-wider">LLDP</span>
              )}
              {p.neighbor.match_source === "mac_managed" && (
                <span className="px-1 py-0 rounded bg-cyan-500/20 text-cyan-300 text-[8px] font-bold tracking-wider">MAC</span>
              )}
              {p.neighbor.match_source === "mac_oui" && (
                <span className="px-1 py-0 rounded bg-amber-500/20 text-amber-300 text-[8px] font-bold tracking-wider">OUI</span>
              )}
              {p.neighbor.match_source === "mac_unknown" && (
                <span className="px-1 py-0 rounded bg-neutral-500/20 text-neutral-300 text-[8px] font-bold tracking-wider">MAC?</span>
              )}
            </div>
            <div className="font-semibold text-cyan-300 truncate">
              {p.neighbor.remote_device_name || p.neighbor.remote_sys_name || "(senza nome)"}
            </div>
            <div className="text-[10px] text-[var(--text-muted)] font-mono break-all">
              {p.neighbor.remote_port_desc && <span>porta {p.neighbor.remote_port_desc} </span>}
              {p.neighbor.remote_port_id && !p.neighbor.remote_port_desc && <span>{p.neighbor.remote_port_id} </span>}
              {p.neighbor.remote_ip && <span>· {p.neighbor.remote_ip} </span>}
              {p.neighbor.remote_chassis_id && !p.neighbor.remote_ip && <span>· {p.neighbor.remote_chassis_id}</span>}
            </div>
            {p.neighbor.remote_sys_desc && (
              <div className="text-[10px] text-[var(--text-muted)] italic truncate">{p.neighbor.remote_sys_desc}</div>
            )}
          </div>
        </div>
      )}

      {/* Counters totali */}
      <div className="border-t border-[var(--bg-border)] pt-2">
        <div className="text-[9px] text-[var(--text-muted)] uppercase mb-1">Trasferito (totali contatore)</div>
        {/* Mini donut SVG */}
        <div className="flex items-center gap-3">
          <svg viewBox="0 0 36 36" className="w-16 h-16 -rotate-90">
            <circle cx="18" cy="18" r="15.9" fill="transparent" stroke="#1f2937" strokeWidth="3.5" />
            <circle cx="18" cy="18" r="15.9" fill="transparent" stroke="#0e7490" strokeWidth="3.5"
              strokeDasharray={`${inPct} ${100 - inPct}`} strokeDashoffset="0" strokeLinecap="round" />
            <circle cx="18" cy="18" r="15.9" fill="transparent" stroke="#22d3ee" strokeWidth="3.5"
              strokeDasharray={`${outPct} ${100 - outPct}`} strokeDashoffset={-inPct} strokeLinecap="round" />
          </svg>
          <div className="text-[11px] flex-1 space-y-0.5">
            <div className="flex items-center gap-1.5"><span className="w-2 h-2 bg-cyan-700 rounded-sm" /> Scaricati <span className="font-mono ml-auto">{fmtBytes(totalIn)}</span></div>
            <div className="flex items-center gap-1.5"><span className="w-2 h-2 bg-cyan-300 rounded-sm" /> Caricati <span className="font-mono ml-auto">{fmtBytes(totalOut)}</span></div>
            <div className="flex items-center gap-1.5 border-t border-[var(--bg-border)] pt-0.5"><span className="text-[var(--text-muted)]">Trasferiti</span> <span className="font-mono ml-auto">{fmtBytes(totalAll)}</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ----- Page -----
export default function SwitchPortsPage() {
  const { deviceIp } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [cableView, setCableView] = useState(null);
  // Ordinamento tabella (header cliccabili)
  const [sortBy, setSortBy] = useState("idx");     // idx|name|status|speed|rx|tx|poe|neighbor
  const [sortDir, setSortDir] = useState("asc");   // asc|desc
  // Flag "solo accese" della tabella completa
  const [tableOnlyUp, setTableOnlyUp] = useState(false);

  const toggleSort = (col) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("asc");
    }
  };

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/devices/${encodeURIComponent(deviceIp)}/switch-ports`);
      setData(r.data);
      // Aggiorna selected con dati freschi
      if (selected) {
        const fresh = (r.data?.ports || []).find(x => x.idx === selected.idx);
        if (fresh) setSelected(fresh);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento");
    } finally {
      setLoading(false);
    }
  }, [deviceIp]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { reload(); }, [reload]);
  // Auto-refresh ogni 30s per traffico live
  useEffect(() => {
    const i = setInterval(() => reload(), 30000);
    return () => clearInterval(i);
  }, [reload]);

  const ports = useMemo(() => {
    if (!data?.ports) return [];
    return data.ports.filter(p => {
      if (filter === "up") return p.oper === 1 && p.admin === 1;
      if (filter === "down") return p.oper !== 1 && p.admin === 1;
      if (filter === "admin_down") return p.admin === 2;
      if (filter === "with_neighbor") return !!p.neighbor;
      if (filter === "poe") return p.poe_status === 3;
      return true;
    });
  }, [data, filter]);

  // Ports ordinati + filtrati per la tabella completa (solo-UP toggle)
  const tablePorts = useMemo(() => {
    let list = tableOnlyUp
      ? ports.filter((p) => p.oper === 1 && p.admin === 1)
      : ports;
    const dir = sortDir === "asc" ? 1 : -1;
    const keyFn = {
      idx: (p) => p.idx || 0,
      name: (p) => (p.name || "").toLowerCase(),
      status: (p) => (p.admin === 2 ? 2 : p.oper === 1 ? 0 : 1),  // UP<DOWN<ADMIN
      speed: (p) => p.speed_mbps || 0,
      rx: (p) => p.rx_bps || 0,
      tx: (p) => p.tx_bps || 0,
      poe: (p) => p.poe_status === 3 ? 1 : 0,
      neighbor: (p) => (p.neighbor?.remote_device_name || p.neighbor?.remote_sys_name || "").toLowerCase(),
    }[sortBy] || ((p) => p.idx || 0);
    return [...list].sort((a, b) => {
      const ka = keyFn(a);
      const kb = keyFn(b);
      if (ka < kb) return -1 * dir;
      if (ka > kb) return 1 * dir;
      return 0;
    });
  }, [ports, sortBy, sortDir, tableOnlyUp]);

  const SortIcon = ({ col }) => {
    if (sortBy !== col) return <CaretUp size={9} className="opacity-30 inline ml-0.5" />;
    return sortDir === "asc"
      ? <CaretUp size={9} className="inline ml-0.5 text-cyan-300" />
      : <CaretDown size={9} className="inline ml-0.5 text-cyan-300" />;
  };

  if (loading && !data) return <div className="p-6 text-[var(--text-muted)] text-sm">Caricamento…</div>;
  if (!data) return <div className="p-6 text-[var(--text-muted)] text-sm">Nessun dato</div>;

  const t = data.totals || {};

  return (
    <div className="p-3 md:p-6 max-w-6xl mx-auto space-y-4" data-testid="switch-ports-page">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-lg" data-testid="switch-ports-back">←</button>
        <div className="min-w-0 flex-1">
          <h1 className="text-base md:text-lg font-bold truncate">Dettagli switch · <span className="font-mono text-cyan-300">{data.device_ip}</span></h1>
          <p className="text-[10px] text-[var(--text-muted)] flex flex-wrap gap-x-2 gap-y-0.5">
            <span>{t.total} porte</span>
            <span className="text-emerald-300">{t.up} up</span>
            <span className="text-red-300">{t.down} down</span>
            <span className="text-neutral-400">{t.admin_down} admin-down</span>
            {(t.poe_active > 0) && <span className="text-amber-300 flex items-center gap-0.5"><Lightning size={10} weight="fill" /> {t.poe_active} PoE</span>}
            {(t.with_neighbor > 0) && <span className="text-cyan-300">{t.with_neighbor} con neighbor</span>}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={reload} className="h-7 gap-1 text-[11px]" data-testid="switch-ports-refresh"><ArrowsClockwise size={12} /> Refresh</Button>
      </div>

      {/* Tab "Stato" (in stile Nebula) */}
      <div className="flex border-b border-[var(--bg-border)] text-[12px]">
        <button className="px-4 py-2 border-b-2 border-emerald-400 text-emerald-300 font-semibold" data-testid="switch-ports-tab-stato">Stato</button>
        <button className="px-4 py-2 text-[var(--text-muted)] cursor-not-allowed" disabled title="Disponibile in futura versione">Reti</button>
        <button className="px-4 py-2 text-[var(--text-muted)] cursor-not-allowed" disabled title="Disponibile in futura versione">Aggregazioni</button>
      </div>

      {/* Filtri */}
      <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
        {[
          { id: "all", label: `Tutte ${t.total || 0}`, color: "cyan" },
          { id: "up", label: `Up ${t.up || 0}`, color: "emerald" },
          { id: "down", label: `Down ${t.down || 0}`, color: "red" },
          { id: "admin_down", label: `Admin-down ${t.admin_down || 0}`, color: "neutral" },
          { id: "poe", label: `PoE ${t.poe_active || 0}`, color: "amber" },
          { id: "with_neighbor", label: `LLDP ${t.with_neighbor || 0}`, color: "cyan" },
        ].map(f => {
          const active = filter === f.id;
          const cls = f.color === "emerald" ? (active ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-emerald-500/30 text-emerald-300/70")
            : f.color === "red" ? (active ? "bg-red-500/20 border-red-400 text-red-300" : "border-red-500/30 text-red-300/70")
            : f.color === "amber" ? (active ? "bg-amber-500/20 border-amber-400 text-amber-300" : "border-amber-500/30 text-amber-300/70")
            : f.color === "neutral" ? (active ? "bg-neutral-500/30 border-neutral-400 text-neutral-200" : "border-neutral-500/30 text-[var(--text-muted)]")
            : (active ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : "border-cyan-500/30 text-cyan-300/70");
          return (
            <button key={f.id} onClick={() => setFilter(f.id)} className={`px-3 py-1 rounded-md border font-semibold ${cls}`} data-testid={`port-filter-${f.id}`}>
              {f.label}
            </button>
          );
        })}
      </div>

      {/* Matrice porte Nebula-style */}
      <div className="noc-panel p-3 md:p-4">
        {/* Group in row of 8 (typical switch layout) */}
        <div className="flex flex-wrap gap-1.5 sm:gap-2">
          {ports.map(p => (
            <PortTile key={p.idx} p={p} active={selected?.idx === p.idx} onClick={() => setSelected(p)} />
          ))}
        </div>
        {ports.length === 0 && <div className="text-center text-[11px] text-[var(--text-muted)] py-3">Nessuna porta con questo filtro</div>}
        {/* Legenda */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-muted)] mt-3 pt-3 border-t border-[var(--bg-border)]">
          <span className="flex items-center gap-1"><Lightning size={11} weight="fill" className="text-emerald-400" /> PoE attivo</span>
          <span className="flex items-center gap-1"><WifiHigh size={11} weight="bold" className="text-emerald-400" /> Access Point</span>
          <span className="flex items-center gap-1"><Stack size={11} weight="bold" className="text-emerald-400" /> Switch uplink</span>
          <span className="flex items-center gap-1"><Cloud size={11} weight="bold" className="text-emerald-400" /> Internet/Router</span>
          <span className="flex items-center gap-1"><Desktop size={11} weight="bold" className="text-emerald-400" /> Dispositivo</span>
          <span className="flex items-center gap-1"><Plugs size={11} weight="bold" className="text-emerald-400" /> Link up</span>
          <span className="flex items-center gap-1"><Prohibit size={11} weight="bold" className="text-neutral-400" /> Disabilitata / non usata</span>
        </div>
      </div>

      {/* Pannello dettaglio porta selezionata */}
      {selected && <PortDetailPanel p={selected} onClose={() => setSelected(null)} onOpenCable={() => setCableView(selected)} deviceIp={data.device_ip} />}

      {/* Modale Vista Cavo */}
      {cableView && (
        <PortCableView
          p={cableView}
          switchIp={data.device_ip}
          switchName={data.device_name}
          clientId={data.client_id}
          onRefresh={reload}
          onClose={() => setCableView(null)}
        />
      )}

      {/* Tabella riepilogo (collassabile su mobile) */}
      <details className="noc-panel" open>
        <summary className="cursor-pointer px-3 py-2 text-[12px] font-semibold border-b border-[var(--bg-border)] hover:bg-[var(--bg-hover)] flex items-center gap-3">
          <span>Tabella completa ({tablePorts.length}{tableOnlyUp ? `/${ports.length}` : ""})</span>
          <label
            className="ml-auto flex items-center gap-1.5 text-[10px] font-normal text-[var(--text-secondary)] cursor-pointer"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              type="checkbox"
              checked={tableOnlyUp}
              onChange={(e) => setTableOnlyUp(e.target.checked)}
              className="accent-emerald-400"
              data-testid="switch-ports-only-up"
            />
            <span>Solo porte accese (UP)</span>
          </label>
        </summary>
        <div className="overflow-x-auto">
          <table className="noc-table w-full text-[11px]" data-testid="switch-ports-table">
            <thead>
              <tr>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("idx")} data-testid="sort-idx">
                  # <SortIcon col="idx" />
                </th>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("name")} data-testid="sort-name">
                  Nome <SortIcon col="name" />
                </th>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("status")} data-testid="sort-status">
                  Stato <SortIcon col="status" />
                </th>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("speed")} data-testid="sort-speed">
                  Speed <SortIcon col="speed" />
                </th>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("rx")} data-testid="sort-rx">
                  Rx <SortIcon col="rx" />
                </th>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("tx")} data-testid="sort-tx">
                  Tx <SortIcon col="tx" />
                </th>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("poe")} data-testid="sort-poe">
                  PoE <SortIcon col="poe" />
                </th>
                <th className="cursor-pointer hover:text-cyan-300 select-none" onClick={() => toggleSort("neighbor")} data-testid="sort-neighbor">
                  Connesso a <SortIcon col="neighbor" />
                </th>
              </tr>
            </thead>
            <tbody>
              {tablePorts.map(p => {
                const isUp = p.oper === 1 && p.admin === 1;
                const isPoe = p.poe_status === 3;
                return (
                  <tr key={p.idx} data-testid={`switch-port-row-${p.idx}`}
                      className={`cursor-pointer ${selected?.idx === p.idx ? "bg-cyan-500/10" : ""}`}
                      onClick={() => setSelected(p)}>
                    <td className="font-mono font-semibold">{portLabel(p.name, p.idx)}</td>
                    <td className="font-mono text-[10px]">{p.name}</td>
                    <td>
                      {p.admin === 2 ? (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-neutral-600/30 text-neutral-200 border border-neutral-400/30">ADMIN-DOWN</span>
                      ) : isUp ? (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">UP</span>
                      ) : (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30">DOWN</span>
                      )}
                    </td>
                    <td className="font-mono text-[10px]">{fmtSpeed(p.speed_mbps)}</td>
                    <td className="font-mono text-[10px] text-cyan-300">{fmtBps(p.rx_bps)}</td>
                    <td className="font-mono text-[10px] text-violet-300">{fmtBps(p.tx_bps)}</td>
                    <td>
                      {isPoe ? (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-400/20 text-amber-200 border border-amber-300/40 flex items-center gap-0.5 w-fit">
                          <Lightning size={9} weight="fill" /> {p.poe_class > 0 ? `Class ${p.poe_class - 1}` : "ON"}
                        </span>
                      ) : <span className="text-[10px] text-[var(--text-muted)]">—</span>}
                    </td>
                    <td>
                      {p.neighbor ? (
                        <div className="flex items-start gap-1.5 text-[10px]">
                          <PortIcon p={p} size={13} />
                          <div className="flex flex-col leading-tight min-w-0">
                            {/* Riga 1: NOME (grassetto) + badge sorgente match */}
                            <div className="flex items-center gap-1 flex-wrap">
                              {p.neighbor.remote_ip ? (
                                <Link to={`/devices/${encodeURIComponent(p.neighbor.remote_ip)}`}
                                      className="font-bold text-[11px] text-cyan-200 hover:text-cyan-100 hover:underline truncate max-w-[220px]"
                                      onClick={(e) => e.stopPropagation()}
                                      data-testid={`port-neighbor-name-${p.idx}`}>
                                  {p.neighbor.remote_device_name || p.neighbor.remote_sys_name || p.neighbor.remote_ip}
                                </Link>
                              ) : (
                                <span className={`font-bold text-[11px] truncate max-w-[220px] ${p.neighbor.match_source === "mac_oui" ? "text-amber-200" : "text-neutral-100"}`}
                                      data-testid={`port-neighbor-name-${p.idx}`}>
                                  {p.neighbor.remote_device_name || p.neighbor.remote_sys_name || "(sconosciuto)"}
                                </span>
                              )}
                              {p.neighbor.match_source === "lldp" && (
                                <span className="px-1 rounded bg-emerald-500/20 text-emerald-300 text-[8px] font-bold" title="LLDP">L</span>
                              )}
                              {p.neighbor.match_source === "datto_rmm" && (
                                <span className="px-1 rounded bg-fuchsia-500/20 text-fuchsia-300 text-[8px] font-bold" title="Datto RMM">DATTO</span>
                              )}
                              {p.neighbor.match_source === "mac_managed" && (
                                <span className="px-1 rounded bg-cyan-500/20 text-cyan-300 text-[8px] font-bold" title="Managed">M</span>
                              )}
                              {p.neighbor.match_source === "mac_manual" && (
                                <span className="px-1 rounded bg-violet-500/20 text-violet-300 text-[8px] font-bold" title="Binding manuale">B</span>
                              )}
                              {p.neighbor.match_source === "mac_fdb_trunk" && (
                                <span className="px-1 rounded bg-sky-500/20 text-sky-300 text-[8px] font-bold" title="Trunk FDB">T</span>
                              )}
                              {p.neighbor.match_source === "mac_oui" && (
                                <span className="px-1 rounded bg-amber-500/20 text-amber-300 text-[8px] font-bold" title="OUI vendor">V</span>
                              )}
                            </div>
                            {/* Riga 2: IP */}
                            {p.neighbor.remote_ip && (
                              <span className="text-[9px] font-mono text-[var(--text-secondary)]">
                                IP: <span className="text-cyan-300">{p.neighbor.remote_ip}</span>
                              </span>
                            )}
                            {/* Riga 3: MAC (remote_chassis_id contiene il MAC su LLDP/datto/mac_managed) */}
                            {p.neighbor.remote_chassis_id && /[0-9a-f]{2}[:.-][0-9a-f]{2}/i.test(p.neighbor.remote_chassis_id) && (
                              <span className="text-[9px] font-mono text-[var(--text-secondary)]">
                                MAC: <span className="text-neutral-300">{p.neighbor.remote_chassis_id}</span>
                              </span>
                            )}
                            {/* Riga 4: porta remota di collegamento */}
                            {(p.neighbor.remote_port_desc || p.neighbor.remote_port_id) && (
                              <span className="text-[9px] font-mono text-[var(--text-secondary)]">
                                porta: <span className="text-violet-300">{p.neighbor.remote_port_desc || p.neighbor.remote_port_id}</span>
                              </span>
                            )}
                          </div>
                        </div>
                      ) : (
                        <span className="text-[10px] text-[var(--text-muted)] italic">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
