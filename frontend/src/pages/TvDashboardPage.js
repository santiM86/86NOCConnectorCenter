import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import "./TvDashboard.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_INTERVAL = 15000;

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
    const cO = new Set(data.offline_devices.map(d => d.ip));
    const cA = new Set(data.alerts.map(a => a.id));
    const nO = [...cO].filter(ip => !p.offIPs.has(ip));
    const nC = data.alerts.filter(a => a.severity === "critical" && !p.altIDs.has(a.id));
    if (p.offIPs.size > 0 || p.altIDs.size > 0) {
      if (nO.length > 0) { beep(880, 0.2, 3); setAlarm({ t: "off", m: `OFFLINE: ${data.offline_devices.filter(d => nO.includes(d.ip)).map(d => d.name).join(", ")}`, ts: Date.now() }); }
      else if (nC.length > 0) { beep(660, 0.3, 2, "sawtooth"); setAlarm({ t: "crit", m: `CRITICO: ${nC[0].device_name || nC[0].title}`, ts: Date.now() }); }
    }
    prevRef.current = { offIPs: cO, altIDs: cA };
  }, [soundOn, beep]);
  return { soundOn, init, check, alarm };
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

  if (!data) return <div className="tv-boot" onClick={init}><div className="tv-boot-spin" /><p>CONNESSIONE AD ARGUS...</p></div>;

  const g = data.global_stats;
  const critical = g.total_offline > 0 || g.critical_alerts > 0;
  const ok = g.total_offline === 0 && g.total_alerts === 0;
  const clients = data.clients;
  // Build per-client alert/toner maps
  const alertsByClient = {};
  data.alerts.forEach(a => {
    const cid = a.client_id || "";
    if (!alertsByClient[cid]) alertsByClient[cid] = [];
    alertsByClient[cid].push(a);
  });
  const tonerByClient = {};
  data.low_toner.forEach(t => {
    const cn = t.client_name || "";
    if (!tonerByClient[cn]) tonerByClient[cn] = [];
    tonerByClient[cn].push(t);
  });
  const offlineByClient = {};
  data.offline_devices.forEach(d => {
    const cn = d.client_name || "";
    if (!offlineByClient[cn]) offlineByClient[cn] = [];
    offlineByClient[cn].push(d);
  });

  return (
    <div className="tv" data-testid="tv-dashboard" onClick={!soundOn ? init : undefined}>
      {/* Alarm flash */}
      {alarm && (Date.now() - alarm.ts < 20000) && (
        <div className={`tv-alarm ${alarm.t === "off" ? "tv-alarm-red" : "tv-alarm-orange"}`} data-testid="tv-alarm-banner">{alarm.m}</div>
      )}

      {/* === TOP BAR === */}
      <div className="tv-top" data-testid="tv-header">
        <div className="tv-top-l">
          <div className="tv-brand">A</div>
          <span className="tv-brand-name">Argus</span>
        </div>
        <div className="tv-top-c">
          <Pill label="DISPOSITIVI" value={g.total_devices} />
          <Pill label="ONLINE" value={g.total_online} color="#34C759" />
          <Pill label="OFFLINE" value={g.total_offline} color={g.total_offline > 0 ? "#FF3B30" : "#333"} pulse={g.total_offline > 0} />
          <Pill label="ALERT" value={g.total_alerts} color={g.total_alerts > 0 ? "#FFCC00" : "#333"} />
          <Pill label="CRITICI" value={g.critical_alerts} color={g.critical_alerts > 0 ? "#FF3B30" : "#333"} pulse={g.critical_alerts > 0} />
        </div>
        <div className="tv-top-r">
          <div className={`tv-status ${ok ? "tv-status-ok" : critical ? "tv-status-crit" : "tv-status-warn"}`} data-testid="tv-global-status">
            <span className="tv-status-dot" />
            {ok ? "OK" : critical ? "ATTENZIONE" : "MONITOR"}
          </div>
          <button className={`tv-snd ${soundOn ? "tv-snd-on" : ""}`} onClick={init} data-testid="tv-sound-toggle">
            {soundOn ? "AUDIO ON" : "AUDIO OFF"}
          </button>
          <div className="tv-time" data-testid="tv-clock">
            <span className="tv-time-h">{clock.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
            <span className="tv-time-d">{clock.toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "short" })}</span>
          </div>
        </div>
      </div>

      {/* === CLIENT TILES - THE ENTIRE SCREEN === */}
      <div className={`tv-grid tv-grid-${Math.min(clients.length, 6)}`} data-testid="tv-clients-grid">
        {clients.map(c => (
          <ClientTile
            key={c.id}
            client={c}
            alerts={alertsByClient[c.id] || []}
            toner={tonerByClient[c.name] || []}
            offline={offlineByClient[c.name] || []}
          />
        ))}
        {clients.length === 0 && <div className="tv-empty">NESSUN CLIENTE CONFIGURATO</div>}
      </div>

      {/* === FOOTER TICKER === */}
      <div className="tv-foot" data-testid="tv-ticker">
        <span className="tv-live">LIVE</span>
        <span className="tv-foot-info">{g.total_clients} clienti &middot; {g.total_devices} dispositivi &middot; {new Date(data.timestamp).toLocaleTimeString("it-IT")}</span>
        {data.ticker.length > 0 && (
          <div className="tv-marquee">
            <div className="tv-marquee-track" style={{ transform: `translateX(${tickerX}px)` }}>
              {data.ticker.concat(data.ticker).map((ev, i) => (
                <span key={i} className="tv-marquee-item">
                  <span className={`tv-dot tv-dot-${ev.severity}`} />
                  {ev.client_name} — {ev.message}
                  <span className="tv-marquee-time">{ev.time_ago}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* === Pill stat in top bar === */
function Pill({ label, value, color = "#fff", pulse }) {
  return (
    <div className={`tv-pill ${pulse ? "tv-pill-pulse" : ""}`} data-testid={`tv-stat-${label.toLowerCase()}`}>
      <span className="tv-pill-v" style={{ color }}>{value}</span>
      <span className="tv-pill-l">{label}</span>
    </div>
  );
}

/* === THE BIG CLIENT TILE === */
function ClientTile({ client, alerts, toner, offline }) {
  const c = client;
  const hp = c.health_pct;
  const hColor = hp >= 90 ? "#34C759" : hp >= 70 ? "#FFCC00" : hp >= 50 ? "#FF9500" : "#FF3B30";
  const hasIssue = c.offline > 0 || c.critical_alerts > 0;
  const critAlerts = alerts.filter(a => a.severity === "critical" || a.severity === "high");
  const sevColors = { critical: "#FF3B30", high: "#FF9500", medium: "#FFCC00", low: "#007AFF" };
  const onlineDevices = c.online_devices || [];
  const offlineDevices = c.problem_devices || offline;

  return (
    <div className={`tv-tile ${hasIssue ? "tv-tile-bad" : ""}`} data-testid={`tv-client-${c.id}`}>
      <div className="tv-tile-head">
        <div className="tv-tile-name-row">
          <h2 className="tv-tile-name">{c.name}</h2>
          <span className={`tv-tile-conn ${c.connector_online ? "tv-tile-conn-on" : "tv-tile-conn-off"}`}>
            <span className="tv-tile-conn-dot" /> {c.connector_online ? "CONNESSO" : "OFFLINE"}
          </span>
        </div>
        <div className="tv-tile-health" style={{ color: hColor }}>
          <svg viewBox="0 0 36 36" className="tv-tile-ring">
            <circle cx="18" cy="18" r="15.9" fill="none" stroke="#222" strokeWidth="3" />
            <circle cx="18" cy="18" r="15.9" fill="none" stroke={hColor} strokeWidth="3"
              strokeDasharray={`${hp}, 100`} strokeLinecap="round"
              style={{ transform: "rotate(-90deg)", transformOrigin: "50% 50%" }} />
          </svg>
          <span className="tv-tile-hp">{hp}<small>%</small></span>
        </div>
      </div>

      <div className="tv-tile-stats">
        <div className="tv-tile-stat"><span className="tv-tile-stat-v" style={{ color: "#34C759" }}>{c.online}</span><span className="tv-tile-stat-l">ONLINE</span></div>
        <div className="tv-tile-stat"><span className="tv-tile-stat-v" style={{ color: c.offline > 0 ? "#FF3B30" : "#333" }}>{c.offline}</span><span className="tv-tile-stat-l">OFFLINE</span></div>
        <div className="tv-tile-stat"><span className="tv-tile-stat-v" style={{ color: c.alert_count > 0 ? "#FFCC00" : "#333" }}>{c.alert_count}</span><span className="tv-tile-stat-l">ALERT</span></div>
        <div className="tv-tile-stat"><span className="tv-tile-stat-v" style={{ color: c.printer_count > 0 ? "#AF52DE" : "#333" }}>{c.printer_count}</span><span className="tv-tile-stat-l">STAMP.</span></div>
      </div>

      {/* DEVICE MAP: every single device */}
      <div className="tv-tile-devices" data-testid={`tv-tile-devices-${c.id}`}>
        <div className="tv-tile-sec-label">DISPOSITIVI ({c.total_devices})</div>
        <div className="tv-tile-dev-list">
          {offlineDevices.map((d, i) => (
            <div key={`off-${i}`} className="tv-tile-dev tv-tile-dev-off">
              <span className="tv-tile-dev-dot-off" /><span className="tv-tile-dev-name">{d.name}</span><span className="tv-tile-dev-ip">{d.ip}</span>
              {d.down_since && <span className="tv-tile-dev-since">{d.down_since}</span>}
            </div>
          ))}
          {onlineDevices.map((d, i) => (
            <div key={`on-${i}`} className="tv-tile-dev">
              <span className="tv-tile-dev-dot-on" /><span className="tv-tile-dev-name">{d.name}</span><span className="tv-tile-dev-ip">{d.ip}</span>
            </div>
          ))}
        </div>
      </div>

      {/* WAN Status for this client */}
      {c.wan_targets && c.wan_targets.length > 0 && (
        <div className="tv-tile-wan" data-testid={`tv-tile-wan-${c.id}`}>
          <div className="tv-tile-sec-label">
            CONNETTIVITA' WAN
            {c.wan_diagnosis && c.wan_diagnosis !== "not_configured" && (
              <span className={`tv-tile-wan-diag tv-tile-wan-${c.wan_diagnosis}`}>{c.wan_diagnosis === "ok" ? "OK" : c.wan_diagnosis_text}</span>
            )}
          </div>
          <div className="tv-tile-wan-list">
            {c.wan_targets.map((w, i) => (
              <div key={i} className={`tv-tile-wan-row tv-tile-wan-${w.status}`}>
                <span className={`tv-tile-wan-dot tv-tile-wan-dot-${w.status}`} />
                <span className="tv-tile-wan-label">{w.label}</span>
                <span className="tv-tile-wan-type">{w.device_type === "firewall" ? "FW" : "RT"}</span>
                <span className="tv-tile-wan-ip">{w.public_ip}</span>
                {w.latency_ms !== null && w.latency_ms !== undefined && (
                  <span className="tv-tile-wan-lat" style={{ color: w.latency_ms > 100 ? "#FF3B30" : w.latency_ms > 50 ? "#FFCC00" : "#34C759" }}>
                    {w.latency_ms}ms
                  </span>
                )}
                {w.status === "offline" && <span className="tv-tile-wan-down">DOWN</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Critical alerts */}
      {critAlerts.length > 0 && (
        <div className="tv-tile-alerts" data-testid={`tv-tile-alerts-${c.id}`}>
          <div className="tv-tile-sec-label">ALERT CRITICI ({critAlerts.length})</div>
          {critAlerts.slice(0, 5).map((a, i) => (
            <div key={i} className="tv-tile-alert-row" style={{ borderLeftColor: sevColors[a.severity] || "#FFCC00" }}>
              <span className="tv-tile-alert-sev" style={{ color: sevColors[a.severity] }}>{a.severity === "critical" ? "CRIT" : "HIGH"}</span>
              <span className="tv-tile-alert-msg">{a.title}{a.message ? `: ${a.message}` : ""}</span>
            </div>
          ))}
          {critAlerts.length > 5 && <div className="tv-tile-alert-more">+{critAlerts.length - 5} altri</div>}
        </div>
      )}

      {/* Toner */}
      {toner.length > 0 && (
        <div className="tv-tile-toner" data-testid={`tv-tile-toner-${c.id}`}>
          <div className="tv-tile-sec-label">CONSUMABILI ({toner.length})</div>
          {toner.map((t, i) => (
            <div key={i} className="tv-tile-toner-row">
              <div className="tv-tile-toner-bar-bg"><div className="tv-tile-toner-bar" style={{ width: `${t.level_pct}%`, background: t.level_pct <= 5 ? "#FF3B30" : t.color_hex || "#FFCC00" }} /></div>
              <span className="tv-tile-toner-pct" style={{ color: t.level_pct <= 5 ? "#FF3B30" : "#FFCC00" }}>{t.level_pct}%</span>
              <span className="tv-tile-toner-name">{t.supply_name}</span>
              <span className="tv-tile-toner-printer">{t.printer_name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
