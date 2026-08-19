import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import axios from "axios";
import "./TvDashboard.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_INTERVAL = 15000;

/* ---------- Audio alarm ---------- */
function useAlarmSystem() {
  const audioCtxRef = useRef(null);
  const prevRef = useRef({ offIPs: new Set(), altIDs: new Set() });
  const [soundOn, setSoundOn] = useState(false);
  const [alarm, setAlarm] = useState(null);
  const init = useCallback(() => {
    if (!audioCtxRef.current) audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtxRef.current.state === "suspended") audioCtxRef.current.resume();
    setSoundOn(true);
  }, []);
  const beep = useCallback((f, d, n = 1, t = "square") => {
    const ctx = audioCtxRef.current; if (!ctx || ctx.state === "suspended") return;
    const now = ctx.currentTime;
    for (let i = 0; i < n; i++) {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = t; o.frequency.value = f;
      g.gain.setValueAtTime(0.12, now + i * (d + 0.1));
      g.gain.exponentialRampToValueAtTime(0.001, now + i * (d + 0.1) + d);
      o.connect(g); g.connect(ctx.destination);
      o.start(now + i * (d + 0.1)); o.stop(now + i * (d + 0.1) + d);
    }
  }, []);
  const check = useCallback((data) => {
    if (!soundOn || !data) return;
    const p = prevRef.current;
    const cO = new Set((data.offline_devices || []).map(d => d.ip));
    const cA = new Set((data.alerts || []).map(a => a.id));
    const nO = [...cO].filter(ip => !p.offIPs.has(ip));
    const nC = (data.alerts || []).filter(a => a.severity === "critical" && !p.altIDs.has(a.id));
    if (p.offIPs.size > 0 || p.altIDs.size > 0) {
      if (nO.length > 0) { beep(880, 0.2, 3); setAlarm({ t: "off", m: `NUOVO OFFLINE: ${data.offline_devices.filter(d => nO.includes(d.ip)).map(d => d.name).join(", ")}`, ts: Date.now() }); }
      else if (nC.length > 0) { beep(660, 0.3, 2, "sawtooth"); setAlarm({ t: "crit", m: `NUOVO ALERT CRITICO: ${nC[0].device_name || nC[0].title}`, ts: Date.now() }); }
    }
    prevRef.current = { offIPs: cO, altIDs: cA };
  }, [soundOn, beep]);
  return { soundOn, init, check, alarm };
}

/* ---------- Client severity model ---------- */
function clientState(c) {
  const wanDown = (c.wan_targets || []).some(w => w.status === "offline");
  const crit = c.offline > 0 || c.critical_alerts > 0 || wanDown || c.health_pct < 50;
  const warn = c.high_alerts > 0 || c.alert_count > 0 || c.health_pct < 90;
  const level = crit ? "crit" : warn ? "warn" : "ok";
  const score = (c.offline * 10) + (c.critical_alerts * 8) + (c.high_alerts * 3)
    + (wanDown ? 40 : 0) + (100 - c.health_pct) * 0.4;
  // Headline: the single most important thing to see from far
  let headline = "OPERATIVO";
  if (wanDown) headline = "WAN DOWN";
  else if (c.offline > 0) headline = `${c.offline} OFFLINE`;
  else if (c.critical_alerts > 0) headline = `${c.critical_alerts} CRITICI`;
  else if (c.alert_count > 0) headline = `${c.alert_count} ALERT`;
  return { level, score, wanDown, headline };
}

export default function TvDashboardPage() {
  const [data, setData] = useState(null);
  const [clock, setClock] = useState(new Date());
  const [tickerX, setTickerX] = useState(0);
  const { soundOn, init, check, alarm } = useAlarmSystem();

  useEffect(() => {
    load();
    const a = setInterval(load, REFRESH_INTERVAL);
    const b = setInterval(() => setClock(new Date()), 1000);
    return () => { clearInterval(a); clearInterval(b); };
  }, []);
  useEffect(() => { if (data) check(data); }, [data, check]);
  useEffect(() => {
    if (!data?.ticker?.length) return;
    const i = setInterval(() => setTickerX(p => p - 1), 40);
    return () => clearInterval(i);
  }, [data?.ticker?.length]);

  const load = () => axios.get(`${API}/tv/dashboard`).then(r => setData(r.data)).catch(() => {});

  const sortedClients = useMemo(() => {
    if (!data?.clients) return [];
    return [...data.clients].map(c => ({ ...c, _s: clientState(c) }))
      .sort((a, b) => b._s.score - a._s.score);
  }, [data]);

  const alertsByClient = useMemo(() => {
    const m = {};
    (data?.alerts || []).forEach(a => { (m[a.client_id || ""] ||= []).push(a); });
    return m;
  }, [data]);

  if (!data) return <div className="tv-boot" onClick={init}><div className="tv-boot-spin" /><p>CONNESSIONE AD ARGUS…</p></div>;

  const g = data.global_stats;
  const problems = sortedClients.filter(c => c._s.level !== "ok").length;
  const globalLevel = g.total_offline > 0 || g.critical_alerts > 0 ? "crit"
    : (g.total_alerts > 0 || problems > 0) ? "warn" : "ok";

  return (
    <div className={`tv tv-${globalLevel}`} data-testid="tv-dashboard" onClick={!soundOn ? init : undefined}>
      {alarm && (Date.now() - alarm.ts < 20000) && (
        <div className={`tv-alarm ${alarm.t === "off" ? "tv-alarm-red" : "tv-alarm-orange"}`} data-testid="tv-alarm-banner">{alarm.m}</div>
      )}

      {/* ===== TOP BAR ===== */}
      <header className="tv-top" data-testid="tv-header">
        <div className="tv-top-l">
          <div className="tv-brand">A</div>
          <div className="tv-brand-txt">
            <span className="tv-brand-name">ARGUS</span>
            <span className="tv-brand-sub">NOC · Live</span>
          </div>
        </div>

        <div className="tv-kpis">
          <Kpi label="DISPOSITIVI" value={g.total_devices} />
          <Kpi label="ONLINE" value={g.total_online} color="#2fd85f" />
          <Kpi label="OFFLINE" value={g.total_offline} color="#ff4136" pulse={g.total_offline > 0} />
          <Kpi label="ALERT" value={g.total_alerts} color={g.total_alerts > 0 ? "#ffbf00" : "#4a4a55"} />
          <Kpi label="CRITICI" value={g.critical_alerts} color="#ff4136" pulse={g.critical_alerts > 0} />
          <Kpi label="CLIENTI KO" value={problems} color={problems > 0 ? "#ff9500" : "#2fd85f"} />
        </div>

        <div className="tv-top-r">
          <div className={`tv-status tv-status-${globalLevel}`} data-testid="tv-global-status">
            <span className="tv-status-dot" />
            {globalLevel === "ok" ? "TUTTO OK" : globalLevel === "crit" ? "ATTENZIONE" : "MONITOR"}
          </div>
          <button className={`tv-snd ${soundOn ? "tv-snd-on" : ""}`} onClick={init} data-testid="tv-sound-toggle">
            {soundOn ? "♪ ON" : "♪ OFF"}
          </button>
          <div className="tv-time" data-testid="tv-clock">
            <span className="tv-time-h">{clock.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</span>
            <span className="tv-time-d">{clock.toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "short" })}</span>
          </div>
        </div>
      </header>

      {/* ===== CLIENT GRID ===== */}
      <main className="tv-grid" data-testid="tv-clients-grid">
        {sortedClients.map(c => (
          <ClientTile key={c.id} c={c} alerts={alertsByClient[c.id] || []} />
        ))}
        {sortedClients.length === 0 && <div className="tv-empty">NESSUN CLIENTE CONFIGURATO</div>}
      </main>

      {/* ===== TICKER ===== */}
      <footer className="tv-foot" data-testid="tv-ticker">
        <span className="tv-live"><span className="tv-live-dot" />LIVE</span>
        <span className="tv-foot-info">{g.total_clients} clienti · {g.total_devices} disp. · agg. {new Date(data.timestamp).toLocaleTimeString("it-IT")}</span>
        {data.ticker.length > 0 && (
          <div className="tv-marquee">
            <div className="tv-marquee-track" style={{ transform: `translateX(${tickerX}px)` }}>
              {data.ticker.concat(data.ticker).map((ev, i) => (
                <span key={i} className="tv-marquee-item">
                  <span className={`tv-dot tv-dot-${ev.severity}`} />
                  <b>{ev.client_name}</b> — {ev.message}
                  <span className="tv-marquee-time">{ev.time_ago}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </footer>
    </div>
  );
}

/* ---------- Top KPI ---------- */
function Kpi({ label, value, color = "#fff", pulse }) {
  return (
    <div className={`tv-kpi ${pulse ? "tv-kpi-pulse" : ""}`} data-testid={`tv-stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <span className="tv-kpi-v" style={{ color }}>{value}</span>
      <span className="tv-kpi-l">{label}</span>
    </div>
  );
}

/* ---------- Client tile (glanceable) ---------- */
function ClientTile({ c, alerts }) {
  const s = c._s;
  const hp = c.health_pct;
  const ringColor = s.level === "crit" ? "#ff4136" : s.level === "warn" ? "#ffbf00" : "#2fd85f";
  const wanList = c.wan_targets || [];
  const wan = wanList.find(w => w.status === "offline") || wanList.find(w => w.status && w.status !== "online") || wanList[0];
  const topAlert = alerts.find(a => a.severity === "critical") || alerts.find(a => a.severity === "high");

  return (
    <div className={`tv-tile tv-tile-${s.level} ${s.level === "crit" ? "tv-tile-flash" : ""}`} data-testid={`tv-client-${c.id}`}>
      {/* header */}
      <div className="tv-tile-head">
        <h2 className="tv-tile-name" title={c.name}>{c.name}</h2>
        <div className="tv-tile-badges">
          {c.printer_count > 0 && <span className="tv-b tv-b-mute">{c.printer_count}🖨</span>}
          <span className={`tv-b ${c.connector_online ? "tv-b-on" : "tv-b-off"}`}>{c.connector_online ? "SONDA" : "NO SONDA"}</span>
        </div>
      </div>

      {/* body: ring + headline + counts */}
      <div className="tv-tile-body">
        <div className="tv-ring" style={{ "--rc": ringColor, "--pct": hp }}>
          <span className="tv-ring-v" style={{ color: ringColor }}>{hp}<small>%</small></span>
        </div>
        <div className="tv-tile-main">
          <div className={`tv-headline tv-headline-${s.level}`} data-testid={`tv-headline-${c.id}`}>{s.headline}</div>
          <div className="tv-counts">
            <span className="tv-count"><b style={{ color: "#2fd85f" }}>{c.online}</b> ON</span>
            <span className="tv-count"><b style={{ color: c.offline > 0 ? "#ff4136" : "#555" }}>{c.offline}</b> OFF</span>
            <span className="tv-count"><b style={{ color: c.alert_count > 0 ? "#ffbf00" : "#555" }}>{c.alert_count}</b> ALERT</span>
          </div>
        </div>
      </div>

      {/* WAN line */}
      {wan && (
        <div className={`tv-wan tv-wan-${wan.status}`} data-testid={`tv-tile-wan-${c.id}`}>
          <span className={`tv-wan-dot tv-wan-dot-${wan.status}`} />
          <span className="tv-wan-txt">WAN {wan.status === "offline" ? "DOWN" : (wan.status === "online" ? "OK" : wan.status?.toUpperCase())}</span>
          {wan.public_ip && <span className="tv-wan-ip">{wan.public_ip}</span>}
          {wan.latency_ms != null && (
            <span className="tv-wan-lat" style={{ color: wan.latency_ms > 100 ? "#ff4136" : wan.latency_ms > 50 ? "#ffbf00" : "#2fd85f" }}>{wan.latency_ms}ms</span>
          )}
        </div>
      )}

      {/* top problem line (one line only) */}
      {topAlert && (
        <div className="tv-toppb" data-testid={`tv-tile-topalert-${c.id}`}>
          <span className={`tv-toppb-sev tv-toppb-${topAlert.severity}`}>{topAlert.severity === "critical" ? "CRIT" : "HIGH"}</span>
          <span className="tv-toppb-msg">{topAlert.title}</span>
        </div>
      )}
    </div>
  );
}
