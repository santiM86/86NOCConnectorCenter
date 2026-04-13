import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import "./TvDashboard.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_INTERVAL = 15000;

function useAlarmSystem() {
  const audioCtxRef = useRef(null);
  const prevStateRef = useRef({ offlineIPs: new Set(), alertIDs: new Set() });
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [lastAlarm, setLastAlarm] = useState(null);

  const initAudio = useCallback(() => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtxRef.current.state === "suspended") audioCtxRef.current.resume();
    setSoundEnabled(true);
  }, []);

  const playTone = useCallback((freq, duration, count = 1, type = "square") => {
    const ctx = audioCtxRef.current;
    if (!ctx || ctx.state === "suspended") return;
    const now = ctx.currentTime;
    for (let i = 0; i < count; i++) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = type;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.15, now + i * (duration + 0.1));
      gain.gain.exponentialRampToValueAtTime(0.001, now + i * (duration + 0.1) + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + i * (duration + 0.1));
      osc.stop(now + i * (duration + 0.1) + duration);
    }
  }, []);

  const checkAlarms = useCallback((data) => {
    if (!soundEnabled || !data) return;
    const prev = prevStateRef.current;
    const currentOfflineIPs = new Set(data.offline_devices.map(d => d.ip));
    const currentAlertIDs = new Set(data.alerts.map(a => a.id));
    const newOffline = [...currentOfflineIPs].filter(ip => !prev.offlineIPs.has(ip));
    const newCritical = data.alerts.filter(a => a.severity === "critical" && !prev.alertIDs.has(a.id));
    if (prev.offlineIPs.size > 0 || prev.alertIDs.size > 0) {
      if (newOffline.length > 0) {
        playTone(880, 0.2, 3, "square");
        const names = data.offline_devices.filter(d => newOffline.includes(d.ip)).map(d => d.name);
        setLastAlarm({ type: "offline", message: `OFFLINE: ${names.join(", ")}`, time: new Date() });
      } else if (newCritical.length > 0) {
        playTone(660, 0.3, 2, "sawtooth");
        setLastAlarm({ type: "critical", message: `CRITICO: ${newCritical[0].device_name || newCritical[0].title}`, time: new Date() });
      }
    }
    prevStateRef.current = { offlineIPs: currentOfflineIPs, alertIDs: currentAlertIDs };
  }, [soundEnabled, playTone]);

  return { soundEnabled, initAudio, checkAlarms, lastAlarm };
}

export default function TvDashboardPage() {
  const [data, setData] = useState(null);
  const [clock, setClock] = useState(new Date());
  const [tickerOffset, setTickerOffset] = useState(0);
  const [refreshPct, setRefreshPct] = useState(0);
  const { soundEnabled, initAudio, checkAlarms, lastAlarm } = useAlarmSystem();

  useEffect(() => {
    fetchData();
    const dataInterval = setInterval(fetchData, REFRESH_INTERVAL);
    const clockInterval = setInterval(() => setClock(new Date()), 1000);
    // Refresh progress bar
    const refreshInterval = setInterval(() => {
      setRefreshPct(prev => {
        const next = prev + (100 / (REFRESH_INTERVAL / 1000));
        return next >= 100 ? 0 : next;
      });
    }, 1000);
    return () => { clearInterval(dataInterval); clearInterval(clockInterval); clearInterval(refreshInterval); };
  }, []);

  useEffect(() => { if (data) checkAlarms(data); }, [data, checkAlarms]);

  useEffect(() => {
    if (!data?.ticker?.length) return;
    const interval = setInterval(() => setTickerOffset(prev => prev - 1), 40);
    return () => clearInterval(interval);
  }, [data?.ticker?.length]);

  const fetchData = () => {
    axios.get(`${API}/tv/dashboard`).then(r => { setData(r.data); setRefreshPct(0); }).catch(() => {});
  };

  if (!data) return (
    <div className="tv-loading" onClick={initAudio}>
      <div className="tv-loading-pulse" />
      <p>CONNESSIONE AL NOC...</p>
    </div>
  );

  const g = data.global_stats;
  const hasProblems = g.total_offline > 0 || g.critical_alerts > 0;
  const allGood = g.total_offline === 0 && g.total_alerts === 0;

  return (
    <div className="tv-root" data-testid="tv-dashboard" onClick={!soundEnabled ? initAudio : undefined}>
      {/* ALARM BANNER */}
      {lastAlarm && (Date.now() - lastAlarm.time.getTime() < 30000) && (
        <div className={`tv-alarm-banner tv-alarm-${lastAlarm.type}`} data-testid="tv-alarm-banner">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
          <span>{lastAlarm.message}</span>
        </div>
      )}

      {/* HEADER */}
      <header className="tv-header" data-testid="tv-header">
        <div className="tv-header-left">
          <div className="tv-logo">NOC</div>
          <div>
            <h1 className="tv-title">86BIT NOC CENTER</h1>
            <p className="tv-subtitle">Network Operations</p>
          </div>
        </div>
        <div className="tv-header-right">
          <button className={`tv-sound-btn ${soundEnabled ? "tv-sound-on" : ""}`} onClick={initAudio} data-testid="tv-sound-toggle">
            {soundEnabled ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>
              </svg>
            )}
            <span className="tv-sound-label">{soundEnabled ? "ON" : "OFF"}</span>
          </button>

          <div className={`tv-global-status ${allGood ? "tv-status-ok" : hasProblems ? "tv-status-critical" : "tv-status-warn"}`} data-testid="tv-global-status">
            <span className="tv-status-dot" />
            {allGood ? "OPERATIVO" : hasProblems ? "ATTENZIONE" : "MONITORAGGIO"}
          </div>

          <div>
            <div className="tv-refresh-bar"><div className="tv-refresh-progress" style={{ width: `${refreshPct}%` }} /></div>
          </div>

          <div className="tv-clock" data-testid="tv-clock">
            <span className="tv-clock-time">{clock.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
            <span className="tv-clock-date">{clock.toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "short" })}</span>
          </div>
        </div>
      </header>

      {/* STATS BAR */}
      <div className="tv-stats-bar" data-testid="tv-stats-bar">
        <StatBlock label="Dispositivi" value={g.total_devices} color="white" />
        <StatBlock label="Online" value={g.total_online} color="var(--tv-green)" />
        <StatBlock label="Offline" value={g.total_offline} color={g.total_offline > 0 ? "var(--tv-red)" : "var(--tv-dim)"} pulse={g.total_offline > 0} />
        <StatBlock label="Alert Critici" value={g.critical_alerts} color={g.critical_alerts > 0 ? "var(--tv-red)" : "var(--tv-dim)"} pulse={g.critical_alerts > 0} />
        <StatBlock label="Alert Totali" value={g.total_alerts} color={g.total_alerts > 0 ? "var(--tv-amber)" : "var(--tv-dim)"} />
        <StatBlock label="Incidenti" value={g.open_incidents} color={g.open_incidents > 0 ? "var(--tv-orange)" : "var(--tv-dim)"} />
      </div>

      {/* MAIN: Left sidebar + Right client grid */}
      <div className="tv-main" data-testid="tv-main-content">
        {/* LEFT: Offline Devices + Alerts */}
        <div className="tv-col-left">
          <div className={`tv-offline-panel ${data.offline_devices.length === 0 ? "tv-offline-clear" : ""}`} data-testid="tv-offline-panel">
            <div className="tv-offline-header">
              <span className="tv-offline-title">{data.offline_devices.length === 0 ? "Tutti Operativi" : "Dispositivi Offline"}</span>
              <span className="tv-offline-count">{data.offline_devices.length === 0 ? "\u2713" : data.offline_devices.length}</span>
            </div>
            <div className="tv-offline-list" data-testid="tv-offline-devices">
              {data.offline_devices.length === 0 ? (
                <div className="tv-all-ok">
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--tv-green)" strokeWidth="1.5">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
                  </svg>
                  <p className="tv-all-ok-text">Nessun dispositivo offline</p>
                </div>
              ) : (
                data.offline_devices.map((d, i) => (
                  <div key={i} className="tv-offline-row" data-testid={`tv-offline-${d.ip}`}>
                    <span className="tv-offline-pulse" />
                    <div className="tv-offline-info">
                      <span className="tv-offline-name">{d.name}</span>
                      <span className="tv-offline-ip">{d.ip}</span>
                    </div>
                    <div className="tv-offline-meta">
                      <span className="tv-offline-client">{d.client_name}</span>
                      {d.down_since && <span className="tv-offline-since">da {d.down_since}</span>}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Alert panel */}
          {data.alerts.length > 0 && (
            <div className="tv-alerts-panel" data-testid="tv-alerts-panel">
              <div className="tv-alerts-header">
                <span className="tv-alerts-title">Alert Attivi</span>
                <span className="tv-alerts-count">{data.alerts.length}</span>
              </div>
              <div className="tv-alerts-list">
                {data.alerts.map((a, i) => (
                  <AlertRow key={a.id || i} alert={a} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: Client health cards grid */}
        <div className="tv-col-right" data-testid="tv-clients-grid">
          {data.clients.map(client => (
            <ClientCard key={client.id} client={client} />
          ))}
        </div>
      </div>

      {/* TICKER FOOTER */}
      <footer className="tv-footer" data-testid="tv-ticker">
        <div className="tv-footer-left">
          <span className="tv-footer-live">LIVE</span>
          <span className="tv-footer-info">{g.total_clients} clienti &middot; {g.total_devices} disp. &middot; {new Date(data.timestamp).toLocaleTimeString("it-IT")}</span>
        </div>
        {data.ticker.length > 0 && (
          <div className="tv-ticker-wrap">
            <div className="tv-ticker" style={{ transform: `translateX(${tickerOffset}px)` }}>
              {data.ticker.concat(data.ticker).map((ev, i) => (
                <span key={i} className="tv-ticker-item">
                  <span className={`tv-ticker-sev tv-sev-${ev.severity}`}>&#9679;</span>
                  <span className="tv-ticker-msg">{ev.client_name} &mdash; {ev.message}</span>
                  <span className="tv-ticker-time">{ev.time_ago}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </footer>
    </div>
  );
}

function StatBlock({ label, value, color, pulse }) {
  return (
    <div className={`tv-stat ${pulse ? "tv-pulse" : ""}`} data-testid={`tv-stat-${label.toLowerCase().replace(/\s/g, "-")}`}>
      <span className="tv-stat-value" style={{ color }}>{value}</span>
      <span className="tv-stat-label">{label}</span>
    </div>
  );
}

function ClientCard({ client }) {
  const c = client;
  const hasIssues = c.offline > 0 || c.critical_alerts > 0;
  const healthColor = c.health_pct >= 90 ? "var(--tv-green)" : c.health_pct >= 50 ? "var(--tv-amber)" : "var(--tv-red)";

  return (
    <div className={`tv-client-card ${hasIssues ? "tv-client-problem" : ""}`} data-testid={`tv-client-${c.id}`}>
      <div className="tv-client-header">
        <h3 className="tv-client-name">{c.name}</h3>
        <div className="tv-client-connector" style={{ color: c.connector_online ? "var(--tv-green)" : "var(--tv-red)" }}>
          <span className="tv-conn-dot-sm" style={{ background: c.connector_online ? "var(--tv-green)" : "var(--tv-red)" }} />
          {c.connector_online ? "CONN" : "OFF"}
        </div>
      </div>
      <div className="tv-client-body">
        <div className="tv-client-health">
          <svg viewBox="0 0 36 36" className="tv-health-ring">
            <path d="M18 2.0845a 15.9155 15.9155 0 0 1 0 31.831a 15.9155 15.9155 0 0 1 0 -31.831"
              fill="none" stroke="#2A2A2A" strokeWidth="3" />
            <path d="M18 2.0845a 15.9155 15.9155 0 0 1 0 31.831a 15.9155 15.9155 0 0 1 0 -31.831"
              fill="none" stroke={healthColor} strokeWidth="3" strokeDasharray={`${c.health_pct}, 100`} strokeLinecap="round" />
          </svg>
          <span className="tv-health-value" style={{ color: healthColor }}>{c.health_pct}%</span>
        </div>
        <div className="tv-client-metrics">
          <div className="tv-metric">
            <span className="tv-metric-val" style={{ color: "var(--tv-green)" }}>{c.online}</span>
            <span className="tv-metric-label">ON</span>
          </div>
          <div className="tv-metric">
            <span className="tv-metric-val" style={{ color: c.offline > 0 ? "var(--tv-red)" : "var(--tv-dim)" }}>{c.offline}</span>
            <span className="tv-metric-label">OFF</span>
          </div>
          {c.alert_count > 0 && (
            <div className="tv-metric">
              <span className="tv-metric-val" style={{ color: c.critical_alerts > 0 ? "var(--tv-red)" : "var(--tv-amber)" }}>{c.alert_count}</span>
              <span className="tv-metric-label">ALERT</span>
            </div>
          )}
          {c.printer_count > 0 && (
            <div className="tv-metric">
              <span className="tv-metric-val" style={{ color: "var(--tv-purple)" }}>{c.printer_count}</span>
              <span className="tv-metric-label">PRINT</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AlertRow({ alert }) {
  const colors = {
    critical: { c: "var(--tv-red)", l: "CRIT" },
    high: { c: "var(--tv-orange)", l: "HIGH" },
    medium: { c: "var(--tv-amber)", l: "MED" },
    low: { c: "var(--tv-blue)", l: "LOW" },
  };
  const cfg = colors[alert.severity] || colors.low;
  return (
    <div className="tv-alert-row" style={{ borderLeftColor: cfg.c, background: `${cfg.c}08` }} data-testid={`tv-alert-${alert.id}`}>
      <span className="tv-alert-sev" style={{ color: cfg.c }}>{cfg.l}</span>
      <div className="tv-alert-body">
        <span className="tv-alert-device">{alert.device_name} <span style={{ color: "var(--tv-text-dim)", fontSize: "9px" }}>{alert.device_ip}</span></span>
        <div className="tv-alert-msg">{alert.title}{alert.message ? `: ${alert.message}` : ""}</div>
      </div>
      <div className="tv-alert-meta">
        <div style={{ color: "var(--tv-blue)", fontSize: "9px", fontWeight: 700 }}>{alert.client_name}</div>
        <div>{alert.time_ago}</div>
      </div>
    </div>
  );
}
