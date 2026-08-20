import { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";
import {
  ShieldCheck, MagnifyingGlass, ArrowsClockwise, WifiHigh, WifiSlash,
  Warning, CaretDown, CaretUp, Circle, Cpu,
} from "@phosphor-icons/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_MS = 15000;
const COL = { green: "#2fd85f", amber: "#ffbf00", red: "#ff4136", orange: "#ff9500", mute: "#7c8698" };

function clientState(c) {
  const wanDown = (c.wan_targets || []).some((w) => w.status === "offline");
  const level = (c.offline > 0 || c.critical_alerts > 0 || wanDown || c.health_pct < 50)
    ? "crit" : (c.high_alerts > 0 || c.alert_count > 0 || c.health_pct < 90) ? "warn" : "ok";
  const score = c.offline * 10 + c.critical_alerts * 8 + c.high_alerts * 3 + (wanDown ? 40 : 0) + (100 - c.health_pct) * 0.4;
  let headline = "Operativo";
  if (wanDown) headline = "WAN DOWN";
  else if (c.offline > 0) headline = `${c.offline} offline`;
  else if (c.critical_alerts > 0) headline = `${c.critical_alerts} critici`;
  else if (c.alert_count > 0) headline = `${c.alert_count} alert`;
  return { level, score, wanDown, headline };
}
const lc = (l) => (l === "crit" ? COL.red : l === "warn" ? COL.amber : COL.green);

export default function MobileConsolePage() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [open, setOpen] = useState({});
  const [loading, setLoading] = useState(false);
  const [updated, setUpdated] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/tv/dashboard`);
      setData(r.data);
      setUpdated(new Date());
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, REFRESH_MS); return () => clearInterval(t); }, [load]);

  const alertsByClient = useMemo(() => {
    const m = {};
    (data?.alerts || []).forEach((a) => { (m[a.client_id || ""] ||= []).push(a); });
    return m;
  }, [data]);
  const offlineByClient = useMemo(() => {
    const m = {};
    (data?.offline_devices || []).forEach((d) => { (m[d.client_name || ""] ||= []).push(d); });
    return m;
  }, [data]);

  const clients = useMemo(() => {
    if (!data?.clients) return [];
    let list = data.clients.map((c) => ({ ...c, _s: clientState(c) }));
    if (q.trim()) list = list.filter((c) => c.name.toLowerCase().includes(q.trim().toLowerCase()));
    if (onlyProblems) list = list.filter((c) => c._s.level !== "ok");
    return list.sort((a, b) => b._s.score - a._s.score);
  }, [data, q, onlyProblems]);

  const g = data?.global_stats;
  const problems = data ? data.clients.filter((c) => clientState(c).level !== "ok").length : 0;
  const globalLevel = !g ? "ok" : (g.total_offline > 0 || g.critical_alerts > 0) ? "crit" : (g.total_alerts > 0 || problems > 0) ? "warn" : "ok";

  return (
    <div className="min-h-screen bg-[#05060a] text-[#eef2f8] pb-8" data-testid="mobile-console">
      {/* Sticky header */}
      <div className="sticky top-0 z-20 bg-[#0a0d14]/95 backdrop-blur border-b border-[#1c2130]">
        <div className="flex items-center gap-2 px-4 pt-3 pb-2">
          <div className="w-8 h-8 rounded-lg grid place-items-center font-black text-[#04121f]" style={{ background: "linear-gradient(135deg,#2fd85f,#0aa5ff)" }}>A</div>
          <div className="flex-1 min-w-0">
            <p className="font-extrabold text-[15px] leading-none">ARGUS <span className="text-[10px] font-medium text-[#7c8698]">NOC</span></p>
            <p className="text-[10px] text-[#7c8698] mt-0.5">{updated ? `agg. ${updated.toLocaleTimeString("it-IT")}` : "…"}</p>
          </div>
          <span className="text-[11px] font-bold px-2.5 py-1 rounded-full" style={{ color: lc(globalLevel), background: `${lc(globalLevel)}1f` }} data-testid="mobile-global-status">
            {globalLevel === "ok" ? "TUTTO OK" : globalLevel === "crit" ? "ATTENZIONE" : "MONITOR"}
          </span>
          <button onClick={load} className="p-2 -mr-1 text-[#7c8698]" data-testid="mobile-refresh" aria-label="Aggiorna">
            <ArrowsClockwise size={18} weight="bold" className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Global KPI strip */}
        {g && (
          <div className="grid grid-cols-4 gap-px bg-[#1c2130] border-y border-[#1c2130]">
            {[
              { l: "ONLINE", v: g.total_online, c: COL.green },
              { l: "OFFLINE", v: g.total_offline, c: g.total_offline > 0 ? COL.red : "#4a4a55" },
              { l: "ALERT", v: g.total_alerts, c: g.total_alerts > 0 ? COL.amber : "#4a4a55" },
              { l: "CLIENTI KO", v: problems, c: problems > 0 ? COL.orange : COL.green },
            ].map((k) => (
              <div key={k.l} className="bg-[#0a0d14] py-2 text-center" data-testid={`mobile-kpi-${k.l.toLowerCase().replace(/\s+/g, "-")}`}>
                <p className="text-[22px] font-extrabold leading-none tabular-nums" style={{ color: k.c }}>{k.v}</p>
                <p className="text-[8px] text-[#7c8698] tracking-wider mt-1">{k.l}</p>
              </div>
            ))}
          </div>
        )}

        {/* Filter bar */}
        <div className="flex items-center gap-2 px-4 py-2">
          <div className="flex-1 flex items-center gap-2 bg-[#10151f] border border-[#1c2130] rounded-full px-3 py-1.5">
            <MagnifyingGlass size={15} className="text-[#7c8698]" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca azienda…"
              className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-[#5a6273]" data-testid="mobile-search" />
          </div>
          <button onClick={() => setOnlyProblems((v) => !v)}
            className={`text-[11px] font-bold px-3 py-2 rounded-full whitespace-nowrap ${onlyProblems ? "bg-[#ff4136]/15 text-[#ff4136]" : "bg-[#10151f] text-[#7c8698]"}`}
            data-testid="mobile-filter-problems">
            Solo problemi
          </button>
        </div>
      </div>

      {/* Client list */}
      <div className="px-3 pt-2 space-y-2" data-testid="mobile-clients">
        {!data && <p className="text-center text-[#7c8698] py-10 text-sm">Caricamento…</p>}
        {data && clients.length === 0 && <p className="text-center text-[#7c8698] py-10 text-sm">Nessuna azienda</p>}
        {clients.map((c) => {
          const s = c._s;
          const col = lc(s.level);
          const isOpen = !!open[c.id];
          const offs = (c.problem_devices && c.problem_devices.length ? c.problem_devices : offlineByClient[c.name]) || [];
          const alerts = (alertsByClient[c.id] || []).filter((a) => a.severity === "critical" || a.severity === "high");
          const wanList = c.wan_targets || [];
          const wan = wanList.find((w) => w.status === "offline") || wanList[0];
          return (
            <div key={c.id} className="rounded-2xl bg-[#0d1017] border border-[#1c2130] overflow-hidden"
              style={{ borderLeft: `5px solid ${col}` }} data-testid={`mobile-client-${c.id}`}>
              {/* Card header (tap to expand) */}
              <button onClick={() => setOpen((p) => ({ ...p, [c.id]: !p[c.id] }))}
                className="w-full flex items-center gap-3 px-3.5 py-3 text-left active:bg-[#141a26]" data-testid={`mobile-client-toggle-${c.id}`}>
                {/* health ring */}
                <div className="w-12 h-12 rounded-full grid place-items-center shrink-0 relative"
                  style={{ background: `conic-gradient(${col} ${c.health_pct}%, #1c2130 0)` }}>
                  <div className="w-9 h-9 rounded-full bg-[#0d1017] grid place-items-center">
                    <span className="text-[12px] font-extrabold" style={{ color: col }}>{c.health_pct}<span className="text-[7px]">%</span></span>
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-extrabold text-[16px] leading-tight truncate">{c.name}</p>
                  <p className="text-[13px] font-bold leading-tight mt-0.5" style={{ color: col }}>{s.headline}</p>
                </div>
                {/* quick chips */}
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <div className="flex items-center gap-1.5">
                    {c.offline > 0 && <Chip icon={WifiSlash} v={c.offline} c={COL.red} />}
                    {c.alert_count > 0 && <Chip icon={Warning} v={c.alert_count} c={COL.amber} />}
                    {wan && (
                      <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ color: wan.status === "offline" ? COL.red : COL.green, background: wan.status === "offline" ? `${COL.red}1f` : `${COL.green}1a` }}>
                        WAN {wan.status === "offline" ? "DOWN" : "OK"}
                      </span>
                    )}
                  </div>
                  {isOpen ? <CaretUp size={14} className="text-[#7c8698]" /> : <CaretDown size={14} className="text-[#7c8698]" />}
                </div>
              </button>

              {/* Expanded detail */}
              {isOpen && (
                <div className="px-3.5 pb-3 pt-1 space-y-2.5 border-t border-[#1c2130]" data-testid={`mobile-client-detail-${c.id}`}>
                  <div className="grid grid-cols-3 gap-2 pt-2">
                    {[["ONLINE", c.online, COL.green], ["OFFLINE", c.offline, c.offline > 0 ? COL.red : "#4a4a55"], ["ALERT", c.alert_count, c.alert_count > 0 ? COL.amber : "#4a4a55"]].map(([l, v, cc]) => (
                      <div key={l} className="rounded-lg bg-[#10151f] py-1.5 text-center">
                        <p className="text-[17px] font-extrabold tabular-nums" style={{ color: cc }}>{v}</p>
                        <p className="text-[8px] text-[#7c8698] tracking-wider">{l}</p>
                      </div>
                    ))}
                  </div>

                  {wan && (
                    <div className="flex items-center gap-2 text-[12px] rounded-lg bg-[#10151f] px-3 py-2">
                      {wan.status === "offline" ? <WifiSlash size={15} style={{ color: COL.red }} /> : <WifiHigh size={15} style={{ color: COL.green }} />}
                      <span className="font-bold" style={{ color: wan.status === "offline" ? COL.red : COL.green }}>WAN {wan.status === "offline" ? "DOWN" : "OK"}</span>
                      {wan.public_ip && <span className="font-mono text-[#7c8698] ml-auto">{wan.public_ip}</span>}
                      {wan.latency_ms != null && <span className="font-mono font-bold" style={{ color: wan.latency_ms > 100 ? COL.red : wan.latency_ms > 50 ? COL.amber : COL.green }}>{wan.latency_ms}ms</span>}
                    </div>
                  )}

                  {offs.length > 0 && (
                    <div>
                      <p className="text-[9px] uppercase tracking-widest text-[#7c8698] mb-1">Dispositivi offline ({offs.length})</p>
                      <div className="space-y-1">
                        {offs.slice(0, 6).map((d, i) => (
                          <div key={i} className="flex items-center gap-2 text-[12px] rounded-lg bg-[#ff4136]/10 px-2.5 py-1.5">
                            <Circle size={8} weight="fill" style={{ color: COL.red }} />
                            <span className="font-semibold truncate">{d.name}</span>
                            <span className="font-mono text-[#7c8698] ml-auto text-[11px]">{d.ip}</span>
                            {d.down_since && <span className="text-[10px] text-[#7c8698]">{d.down_since}</span>}
                          </div>
                        ))}
                        {offs.length > 6 && <p className="text-[10px] text-[#7c8698] pl-1">+{offs.length - 6} altri</p>}
                      </div>
                    </div>
                  )}

                  {alerts.length > 0 && (
                    <div>
                      <p className="text-[9px] uppercase tracking-widest text-[#7c8698] mb-1">Alert ({alerts.length})</p>
                      <div className="space-y-1">
                        {alerts.slice(0, 5).map((a, i) => (
                          <div key={i} className="flex items-start gap-2 text-[12px] rounded-lg bg-[#10151f] px-2.5 py-1.5">
                            <span className="text-[8px] font-black px-1.5 py-0.5 rounded shrink-0 mt-0.5" style={{ color: "#fff", background: a.severity === "critical" ? COL.red : COL.orange }}>
                              {a.severity === "critical" ? "CRIT" : "HIGH"}
                            </span>
                            <span className="leading-snug">{a.title}</span>
                          </div>
                        ))}
                        {alerts.length > 5 && <p className="text-[10px] text-[#7c8698] pl-1">+{alerts.length - 5} altri</p>}
                      </div>
                    </div>
                  )}

                  <div className="flex items-center gap-3 text-[10px] text-[#7c8698] pt-1">
                    <span className="flex items-center gap-1"><ShieldCheck size={12} /> {c.total_devices} disp.</span>
                    {c.printer_count > 0 && <span>{c.printer_count} stamp.</span>}
                    {c.ilo_server_count > 0 && <span className="flex items-center gap-1"><Cpu size={12} /> {c.ilo_server_count} iLO</span>}
                    <span className="ml-auto" style={{ color: c.connector_online ? COL.green : COL.mute }}>{c.connector_online ? "Sonda OK" : "No sonda"}</span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Chip({ icon: Icon, v, c }) {
  return (
    <span className="flex items-center gap-0.5 text-[11px] font-extrabold px-1.5 py-0.5 rounded" style={{ color: c, background: `${c}1a` }}>
      <Icon size={12} weight="bold" />{v}
    </span>
  );
}
