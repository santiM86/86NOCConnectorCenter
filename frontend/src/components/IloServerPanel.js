import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Power, ArrowClockwise, Lightning, Cpu, HardDrives, Network,
  Warning, CircleNotch, ListBullets, Lightbulb,
} from "@phosphor-icons/react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import HealthBadge from "@/components/HealthBadge";

/* ==========================================================================
   IloServerPanel — vista premium per singolo server iLO/Redfish.
   Mostra: stato alimentazione + azioni power + UID LED + POST state,
   grafici storici (potenza/temperatura) sempre visibili, health matrix
   sottosistemi, inventario preciso (CPU/DIMM/Dischi/NIC) e log IML/SEL inline.
   ========================================================================== */

const fmtDateTick = (t) => {
  try {
    return new Date(t).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
};

export default function IloServerPanel({ s, clientId, defaultOpen = false }) {
  const ip = s.device_ip;
  const [metrics, setMetrics] = useState(null);
  const [range, setRange] = useState(360); // minuti
  const [powerBusy, setPowerBusy] = useState(false);
  const [ledBusy, setLedBusy] = useState(false);
  const [ledState, setLedState] = useState(s.indicator_led || null);
  const [powerState, setPowerState] = useState(s.power_state || null);
  const timerRef = useRef(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/redfish/metrics/${ip}?minutes=${range}`);
      setMetrics(res.data);
    } catch { /* silenzioso: il server potrebbe non avere ancora telemetria */ }
  }, [ip, range]);

  useEffect(() => {
    fetchMetrics();
    timerRef.current = setInterval(fetchMetrics, 30000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [fetchMetrics]);

  const subsystems = metrics?.latest?.subsystems || {};
  const powerSeries = (metrics?.series?.power_watts || []).map((p) => ({ t: p.t, W: p.v }));
  const tempSeries = mergeTempSeries(metrics?.series);

  const doPowerAction = async (action, label, danger) => {
    if (danger && !window.confirm(`Confermi "${label}" sul server ${s.device_name} (${ip})?\n\nQuesta è un'azione hardware reale sul server fisico.`)) return;
    setPowerBusy(true);
    try {
      const res = await axios.post(`${API}/devices/${ip}/power-action`, { action, client_id: clientId });
      if (res.data?.success) {
        toast.success(`Comando "${label}" inviato al server`);
        setTimeout(refreshPowerState, 4000);
      } else {
        toast.error(res.data?.error || `Errore azione ${label}`);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || `Errore azione ${label}`);
    } finally {
      setPowerBusy(false);
    }
  };

  const refreshPowerState = async (notify = false) => {
    try {
      const res = await axios.get(`${API}/devices/${ip}/power-state`, { params: { client_id: clientId } });
      if (res.data?.success) {
        setPowerState(res.data.power_state);
        if (res.data.indicator_led) setLedState(res.data.indicator_led);
        if (notify) toast.success(`Stato aggiornato: ${res.data.power_state}`);
      } else if (notify) {
        toast.error(res.data?.error || "Impossibile leggere lo stato alimentazione");
      }
    } catch (e) {
      if (notify) toast.error(e.response?.data?.detail || "Errore lettura stato alimentazione");
    }
  };

  const toggleUid = async () => {
    const next = (ledState === "Lit" || ledState === "Blinking") ? "Off" : "Lit";
    setLedBusy(true);
    try {
      const res = await axios.post(`${API}/devices/${ip}/uid-led`, { state: next, client_id: clientId });
      if (res.data?.success) {
        setLedState(next);
        toast.success(`UID LED ${next === "Off" ? "spento" : "acceso"}`);
      } else {
        toast.error(res.data?.error || "Errore UID LED");
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore UID LED");
    } finally {
      setLedBusy(false);
    }
  };

  const isOn = (powerState || "").toLowerCase() === "on";
  const uidOn = ledState === "Lit" || ledState === "Blinking";

  // Inventario
  const cpus = s.processors && s.processors.length ? s.processors : [];
  const cpuSummary = s.processor_summary;
  const dimms = (s.memory_dimms || []).filter((d) => (d.size_gb || d.capacity_mb) > 0);
  const drives = (s.storage_controllers || []).flatMap((c) => (c.drives || []).map((d) => ({ ...d, ctrl: c.name })));
  const nics = s.network_adapters || [];

  return (
    <div className="noc-panel overflow-hidden" data-testid={`ilo-panel-${ip}`}>
      {/* ===== Header con stato + azioni ===== */}
      <div className="p-4 border-b border-[var(--bg-border)] bg-gradient-to-r from-cyan-500/[0.04] to-transparent">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${isOn ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`} title={`Power: ${powerState || "?"}`} />
              <h3 className="text-base font-bold text-[var(--text-primary)] truncate" data-testid={`ilo-panel-name-${ip}`}>{s.device_name}</h3>
              <PowerStateChip state={powerState} />
              <PostStateChip state={s.post_state} />
            </div>
            <p className="text-[11px] text-[var(--text-muted)] font-mono mt-1">
              {ip} · {s.server_model || "?"} {s.serial_number ? `· S/N ${s.serial_number}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* UID LED */}
            <button
              onClick={toggleUid}
              disabled={ledBusy}
              className={`h-8 px-2.5 rounded-md border text-[11px] font-semibold flex items-center gap-1.5 transition-colors ${
                uidOn ? "bg-blue-500/20 border-blue-400/50 text-blue-300" : "border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              }`}
              title="Accendi/spegni il UID LED fisico del server (per identificarlo in rack)"
              data-testid={`ilo-uid-toggle-${ip}`}
            >
              {ledBusy ? <CircleNotch size={13} className="animate-spin" /> : <Lightbulb size={13} weight={uidOn ? "fill" : "regular"} />}
              UID {uidOn ? "ON" : "OFF"}
            </button>
            {/* Power actions */}
            <PowerActionMenu isOn={isOn} busy={powerBusy} onAction={doPowerAction} ip={ip} />
            <button
              onClick={() => refreshPowerState(true)}
              className="h-8 w-8 rounded-md border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-cyan-400 flex items-center justify-center"
              title="Aggiorna stato alimentazione"
              data-testid={`ilo-refresh-power-${ip}`}
            >
              <ArrowClockwise size={14} />
            </button>
          </div>
        </div>

        {/* Health matrix sottosistemi */}
        {Object.keys(subsystems).length > 0 && (
          <div className="mt-3 flex items-center gap-3 flex-wrap">
            <span className="text-[9px] uppercase tracking-[0.15em] text-[var(--text-muted)]">Sottosistemi</span>
            <HealthBadge subsystems={subsystems} size="md" testId={`ilo-subsystems-${ip}`} />
          </div>
        )}
      </div>

      {/* ===== Grafici storici sempre visibili ===== */}
      <div className="p-4 border-b border-[var(--bg-border)]">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-cyan-400">Andamento hardware</span>
          <div className="flex items-center gap-1">
            {[{ v: 60, l: "1h" }, { v: 360, l: "6h" }, { v: 1440, l: "24h" }].map((r) => (
              <button key={r.v} onClick={() => setRange(r.v)}
                className={`h-6 px-2 rounded text-[10px] font-medium transition-colors ${range === r.v ? "bg-cyan-500/20 text-cyan-300" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}
                data-testid={`ilo-range-${r.v}-${ip}`}>
                {r.l}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="Potenza (W)" testid={`ilo-chart-power-${ip}`}>
            {powerSeries.length > 1 ? (
              <ResponsiveContainer width="100%" height={150}>
                <AreaChart data={powerSeries} margin={{ top: 5, right: 8, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`pw-${ip}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.5} />
                      <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.03} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                  <XAxis dataKey="t" tickFormatter={fmtDateTick} stroke="rgba(255,255,255,0.3)" style={{ fontSize: 9 }} tickLine={false} minTickGap={40} />
                  <YAxis stroke="rgba(255,255,255,0.3)" style={{ fontSize: 9 }} tickLine={false} width={40} />
                  <Tooltip contentStyle={tooltipStyle} labelFormatter={(t) => new Date(t).toLocaleString("it-IT")} formatter={(v) => [`${v} W`, "Potenza"]} />
                  <Area type="monotone" dataKey="W" stroke="#f59e0b" strokeWidth={2} fill={`url(#pw-${ip})`} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <ChartEmpty />}
          </ChartCard>
          <ChartCard title="Temperatura (°C)" testid={`ilo-chart-temp-${ip}`}>
            {tempSeries.length > 1 ? (
              <ResponsiveContainer width="100%" height={150}>
                <AreaChart data={tempSeries} margin={{ top: 5, right: 8, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`tm-${ip}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#ef4444" stopOpacity={0.45} />
                      <stop offset="100%" stopColor="#ef4444" stopOpacity={0.03} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                  <XAxis dataKey="t" tickFormatter={fmtDateTick} stroke="rgba(255,255,255,0.3)" style={{ fontSize: 9 }} tickLine={false} minTickGap={40} />
                  <YAxis stroke="rgba(255,255,255,0.3)" style={{ fontSize: 9 }} tickLine={false} width={40} domain={["dataMin - 3", "dataMax + 3"]} />
                  <Tooltip contentStyle={tooltipStyle} labelFormatter={(t) => new Date(t).toLocaleString("it-IT")} />
                  <ReferenceLine y={75} stroke="#ef4444" strokeDasharray="4 4" strokeOpacity={0.5} />
                  <Area type="monotone" dataKey="max" name="Max" stroke="#ef4444" strokeWidth={2} fill={`url(#tm-${ip})`} />
                  <Area type="monotone" dataKey="inlet" name="Inlet" stroke="#38bdf8" strokeWidth={1.5} fillOpacity={0} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <ChartEmpty />}
          </ChartCard>
        </div>
      </div>

      {/* ===== Inventario preciso ===== */}
      <div className="p-4 space-y-4">
        {/* CPU */}
        <InvSection icon={Cpu} title="Processori (CPU)" count={cpus.length || (cpuSummary?.count || 0)}>
          {cpus.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {cpus.map((c, i) => (
                <div key={i} className="rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] p-2.5" data-testid={`ilo-cpu-${ip}-${i}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-[var(--text-primary)]">{c.socket || `CPU ${i + 1}`}</span>
                    <HealthDot h={c.health} />
                  </div>
                  <p className="text-[11px] text-[var(--text-secondary)] mt-0.5 truncate" title={c.model}>{c.model || "—"}</p>
                  <div className="flex items-center gap-3 mt-1 text-[10px] text-[var(--text-muted)] font-mono">
                    {c.cores != null && <span>{c.cores}C{c.threads ? `/${c.threads}T` : ""}</span>}
                    {c.speed_mhz != null && <span>{(c.speed_mhz / 1000).toFixed(1)} GHz</span>}
                  </div>
                </div>
              ))}
            </div>
          ) : cpuSummary?.model ? (
            <p className="text-[11px] text-[var(--text-secondary)]">
              {cpuSummary.count || "?"}× {cpuSummary.model} {cpuSummary.cores ? `· ${cpuSummary.cores} core totali` : ""}
            </p>
          ) : <EmptyRow text="Dettaglio CPU non riportato dalla iLO" />}
        </InvSection>

        {/* DIMM */}
        <InvSection icon={Warning} title={`Memoria — ${s.total_memory_gb != null ? s.total_memory_gb + " GB" : "?"}`} count={`${dimms.length} DIMM`} hideIcon>
          {dimms.length > 0 ? (
            <InvTable
              headers={["Banco / Slot", "Capacità", "Velocità", "Tipo", "Part Number", "Stato"]}
              rows={dimms.map((d) => [
                d.name || "?",
                d.size_gb ? `${d.size_gb} GB` : (d.capacity_mb ? `${Math.round(d.capacity_mb / 1024)} GB` : "?"),
                d.speed_mhz ? `${d.speed_mhz} MHz` : "—",
                `${d.type || "—"}${d.rank ? ` · ${d.rank}R` : ""}`,
                <span key="pn" className="font-mono text-[10px]" title={d.manufacturer || ""}>{d.part_number || "—"}</span>,
                <HealthTag key="h" h={d.health || d.status} />,
              ])}
              testid={`ilo-dimm-table-${ip}`}
            />
          ) : <EmptyRow text="Nessun DIMM riportato" />}
        </InvSection>

        {/* Dischi */}
        <InvSection icon={HardDrives} title="Dischi fisici" count={drives.length}>
          {drives.length > 0 ? (
            <InvTable
              headers={["Slot", "Modello", "Capacità", "Tipo", "RPM", "Ore", "Temp", "Usura/Predict", "Stato"]}
              rows={drives.map((d) => [
                d.slot != null ? `${String(d.slot).match(/^\d+$/) ? "#" : ""}${d.slot}` : "—",
                <span key="m" title={d.serial ? `S/N ${d.serial}` : ""}>{d.model || d.name || "?"}</span>,
                d.capacity_gb ? `${d.capacity_gb >= 1000 ? (d.capacity_gb / 1000).toFixed(1) + " TB" : d.capacity_gb + " GB"}` : "—",
                `${d.media_type || "?"}${d.interface_type ? " · " + d.interface_type : ""}`,
                (d.rotation_rpm ? `${d.rotation_rpm >= 1000 ? Math.round(d.rotation_rpm / 1000) + "K" : d.rotation_rpm}` : (d.media_type === "SSD" ? "SSD" : "—")),
                d.hours_used != null ? `${d.hours_used}h` : "—",
                d.temp_celsius != null ? `${d.temp_celsius}°C` : "—",
                d.failure_predicted
                  ? <span key="w" className="text-rose-400 font-bold text-[10px]">⚠ Predetto</span>
                  : (d.wear_percent != null
                      ? <span key="w" className={`text-[10px] font-semibold ${d.wear_percent >= 90 ? "text-rose-400" : d.wear_percent >= 70 ? "text-amber-400" : "text-emerald-400/70"}`}>{d.wear_percent}%</span>
                      : <span key="w" className="text-emerald-400/70 text-[10px]">OK</span>),
                <HealthTag key="h" h={d.health} />,
              ])}
              testid={`ilo-drive-table-${ip}`}
            />
          ) : <EmptyRow text="Nessun disco riportato (controller o timeout Storage)" />}
        </InvSection>

        {/* NIC */}
        <InvSection icon={Network} title="Interfacce di rete" count={nics.length}>
          {nics.length > 0 ? (
            <InvTable
              headers={["Nome", "MAC", "IPv4", "VLAN", "Velocità", "Link"]}
              rows={nics.map((n) => [
                n.name || "NIC",
                <span key="mac" className="font-mono">{n.mac || "—"}</span>,
                <span key="ip" className="font-mono">{n.ipv4 || "—"}</span>,
                n.vlan != null ? `VLAN ${n.vlan}` : "—",
                n.speed_mbps ? `${n.speed_mbps >= 1000 ? (n.speed_mbps / 1000) + " Gbps" : n.speed_mbps + " Mbps"}` : "—",
                <LinkTag key="l" status={n.link_status} />,
              ])}
              testid={`ilo-nic-table-${ip}`}
            />
          ) : <EmptyRow text="Nessuna NIC riportata" />}
        </InvSection>

        {/* Firmware */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
          <FwBadge label="BIOS" value={s.bios_version} />
          <FwBadge label="iLO FW" value={s.ilo_firmware} />
          <FwBadge label="iLO License" value={s.ilo_license} />
          <FwBadge label="UUID" value={s.uuid} mono />
        </div>

        {/* Log eventi hardware IML/SEL inline */}
        <IloEventLog ip={ip} clientId={clientId} defaultOpen={defaultOpen} />
      </div>
    </div>
  );
}

/* ---------- Log eventi IML/SEL inline ---------- */
function IloEventLog({ ip, clientId, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  const [events, setEvents] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/servers/ilo-events/${ip}`, { params: { client_id: clientId, limit: 40 } });
      setEvents(res.data?.events || []);
    } catch (e) {
      setEvents([]);
      toast.error(e.response?.data?.detail || "Errore lettura eventi IML/SEL");
    } finally {
      setLoading(false);
    }
  };

  const toggle = () => {
    const n = !open;
    setOpen(n);
    if (n && events === null) load();
  };

  const sevColor = (s) => {
    const l = (s || "").toLowerCase();
    if (l.includes("crit") || l.includes("fatal")) return "#ef4444";
    if (l.includes("warn") || l.includes("degrad")) return "#f59e0b";
    return "#10b981";
  };

  return (
    <div className="rounded-md border border-[var(--bg-border)]">
      <button onClick={toggle} className="w-full flex items-center justify-between px-3 py-2 hover:bg-[var(--bg-hover)] transition-colors" data-testid={`ilo-events-toggle-${ip}`}>
        <span className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-[var(--text-secondary)]">
          <ListBullets size={13} weight="bold" /> Log eventi hardware (IML / SEL)
          {events && <span className="text-[9px] font-normal text-[var(--text-muted)]">· {events.length}</span>}
        </span>
        <span className="text-[10px] text-[var(--text-muted)]">{open ? "Nascondi" : "Mostra"}</span>
      </button>
      {open && (
        <div className="border-t border-[var(--bg-border)] p-2 max-h-72 overflow-auto" data-testid={`ilo-events-list-${ip}`}>
          {loading ? (
            <div className="text-center py-4 text-[11px] text-[var(--text-muted)]"><CircleNotch size={16} className="animate-spin inline mr-1" /> Lettura eventi…</div>
          ) : !events || events.length === 0 ? (
            <p className="text-[11px] text-[var(--text-muted)] text-center py-3">Nessun evento hardware disponibile (o LogService non esposto dalla iLO).</p>
          ) : (
            <div className="space-y-1">
              {events.map((ev, i) => (
                <div key={i} className="flex items-start gap-2 px-2 py-1.5 rounded bg-[var(--bg-card)]" data-testid={`ilo-event-${ip}-${i}`}>
                  <span className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0" style={{ background: sevColor(ev.severity) }} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] text-[var(--text-primary)] leading-snug">{ev.message || ev.subject || "—"}</p>
                    <p className="text-[9px] text-[var(--text-muted)] font-mono mt-0.5">
                      {ev.created ? new Date(ev.created).toLocaleString("it-IT") : ""} {ev.sensor ? `· ${ev.sensor}` : ""}
                    </p>
                  </div>
                  <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded flex-shrink-0" style={{ color: sevColor(ev.severity), background: `${sevColor(ev.severity)}18` }}>
                    {(ev.severity || "info").toUpperCase()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- Power action menu ---------- */
function PowerActionMenu({ isOn, busy, onAction, ip }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const actions = isOn
    ? [
        { a: "GracefulShutdown", l: "Spegnimento ordinato", danger: true, color: "#f59e0b" },
        { a: "ForceRestart", l: "Riavvio forzato", danger: true, color: "#f59e0b" },
        { a: "ForceOff", l: "Spegnimento forzato", danger: true, color: "#ef4444" },
        { a: "PushPowerButton", l: "Premi pulsante power", danger: true, color: "#94a3b8" },
      ]
    : [
        { a: "On", l: "Accendi server", danger: false, color: "#10b981" },
        { a: "PushPowerButton", l: "Premi pulsante power", danger: true, color: "#94a3b8" },
      ];

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        disabled={busy}
        className="h-8 px-3 rounded-md bg-rose-500/15 border border-rose-500/40 text-rose-300 text-[11px] font-semibold flex items-center gap-1.5 hover:bg-rose-500/25 transition-colors"
        data-testid={`ilo-power-menu-${ip}`}
        title="Azioni alimentazione (accendi/spegni/riavvia il server fisico)"
      >
        {busy ? <CircleNotch size={13} className="animate-spin" /> : <Power size={13} weight="bold" />}
        Power
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-52 rounded-md border border-[var(--bg-border)] bg-[var(--bg-panel)] shadow-xl z-20 py-1" data-testid={`ilo-power-options-${ip}`}>
          {actions.map((act) => (
            <button
              key={act.a}
              onClick={() => { setOpen(false); onAction(act.a, act.l, act.danger); }}
              className="w-full text-left px-3 py-1.5 text-[11px] hover:bg-[var(--bg-hover)] flex items-center gap-2"
              style={{ color: act.color }}
              data-testid={`ilo-power-action-${act.a}-${ip}`}
            >
              <Lightning size={11} weight="bold" /> {act.l}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Piccoli helper UI ---------- */
function PowerStateChip({ state }) {
  const on = (state || "").toLowerCase() === "on";
  const off = (state || "").toLowerCase() === "off";
  if (!state) return null;
  return (
    <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${on ? "bg-emerald-500/15 text-emerald-400" : off ? "bg-slate-500/20 text-slate-400" : "bg-amber-500/15 text-amber-400"}`}>
      {on ? "Acceso" : off ? "Spento" : state}
    </span>
  );
}

function PostStateChip({ state }) {
  if (!state) return null;
  const l = state.toLowerCase();
  const finished = l.includes("finished") || l.includes("complete") || l.includes("oscomplete") || l === "poweron";
  return (
    <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${finished ? "bg-cyan-500/15 text-cyan-400" : "bg-amber-500/15 text-amber-400"}`} title={`POST / boot state: ${state}`}>
      {finished ? "OS attivo" : state}
    </span>
  );
}

function HealthDot({ h }) {
  const l = (h || "").toLowerCase();
  const c = l === "ok" ? "#10b981" : (l === "warning" || l === "degraded") ? "#f59e0b" : (l === "critical" || l === "failed") ? "#ef4444" : "#475569";
  return <span className="w-2 h-2 rounded-full inline-block" style={{ background: c }} title={h || "unknown"} />;
}

function HealthTag({ h }) {
  const l = (h || "").toLowerCase();
  const c = ["ok", ""].includes(l) ? "#10b981" : (l === "warning" || l === "degraded") ? "#f59e0b" : "#ef4444";
  return <span className="text-[9px] font-bold uppercase" style={{ color: c }}>{(h || "OK").toUpperCase()}</span>;
}

function LinkTag({ status }) {
  const up = (status || "").toLowerCase().includes("up");
  return <span className="text-[9px] font-bold uppercase" style={{ color: up ? "#10b981" : "#64748b" }}>{up ? "LINK UP" : (status || "DOWN").toUpperCase()}</span>;
}

function ChartCard({ title, children, testid }) {
  return (
    <div className="rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] p-2.5" data-testid={testid}>
      <p className="text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{title}</p>
      {children}
    </div>
  );
}

function ChartEmpty() {
  return <div className="h-[150px] flex items-center justify-center text-[10px] text-[var(--text-muted)]">In attesa di telemetria storica…</div>;
}

function InvSection({ icon: Icon, title, count, children, hideIcon }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        {!hideIcon && Icon && <Icon size={13} weight="bold" className="text-cyan-400" />}
        <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-secondary)]">{title}</span>
        <span className="text-[9px] text-[var(--text-muted)]">· {count}</span>
      </div>
      {children}
    </div>
  );
}

function InvTable({ headers, rows, testid }) {
  return (
    <div className="overflow-x-auto rounded-md border border-[var(--bg-border)]">
      <table className="w-full text-[11px]" data-testid={testid}>
        <thead>
          <tr className="bg-[var(--bg-card)]">
            {headers.map((h, i) => (
              <th key={i} className="text-left px-2.5 py-1.5 text-[9px] uppercase tracking-wider text-[var(--text-muted)] font-semibold whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-[var(--bg-border)] hover:bg-[var(--bg-hover)]">
              {r.map((cell, j) => (
                <td key={j} className="px-2.5 py-1.5 text-[var(--text-secondary)] whitespace-nowrap">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyRow({ text }) {
  return <p className="text-[11px] text-[var(--text-muted)] italic">{text}</p>;
}

function FwBadge({ label, value, mono }) {
  return (
    <div className="p-2 rounded bg-[var(--bg-card)] border border-[var(--bg-border)]">
      <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
      <p className={`text-[11px] text-[var(--text-primary)] ${mono ? "font-mono truncate" : ""}`} title={value}>{value || "N/D"}</p>
    </div>
  );
}

const tooltipStyle = { background: "#0d1117", border: "1px solid rgba(6,182,212,0.4)", borderRadius: 6, fontSize: 11 };

/* Unisce max/avg/inlet temp in una sola serie per il grafico. */
function mergeTempSeries(series) {
  if (!series) return [];
  const byT = {};
  (series.max_temperature || []).forEach((p) => { byT[p.t] = { t: p.t, max: p.v }; });
  (series.inlet_temperature || []).forEach((p) => { byT[p.t] = { ...(byT[p.t] || { t: p.t }), inlet: p.v }; });
  return Object.values(byT).sort((a, b) => new Date(a.t) - new Date(b.t));
}
