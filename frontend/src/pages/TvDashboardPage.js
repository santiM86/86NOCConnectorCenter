import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import "./TvDashboard.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_INTERVAL = 15000;

// Web Audio API alarm system
function useAlarmSystem() {
  const audioCtxRef = useRef(null);
  const prevStateRef = useRef({ offlineIPs: new Set(), alertIDs: new Set() });
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [lastAlarm, setLastAlarm] = useState(null);

  const initAudio = useCallback(() => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtxRef.current.state === "suspended") {
      audioCtxRef.current.resume();
    }
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

    // New offline devices
    const newOffline = [...currentOfflineIPs].filter(ip => !prev.offlineIPs.has(ip));
    // New critical alerts
    const newCritical = data.alerts.filter(a => a.severity === "critical" && !prev.alertIDs.has(a.id));

    if (prev.offlineIPs.size > 0 || prev.alertIDs.size > 0) {
      if (newOffline.length > 0) {
        playTone(880, 0.2, 3, "square"); // triple beep urgente
        const names = data.offline_devices.filter(d => newOffline.includes(d.ip)).map(d => d.name);
        setLastAlarm({ type: "offline", message: `OFFLINE: ${names.join(", ")}`, time: new Date() });
      } else if (newCritical.length > 0) {
        playTone(660, 0.3, 2, "sawtooth"); // double beep critico
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
  const { soundEnabled, initAudio, checkAlarms, lastAlarm } = useAlarmSystem();

  useEffect(() => {
    fetchData();
    const dataInterval = setInterval(fetchData, REFRESH_INTERVAL);
    const clockInterval = setInterval(() => setClock(new Date()), 1000);
    return () => { clearInterval(dataInterval); clearInterval(clockInterval); };
  }, []);

  // Check alarms when data changes
  useEffect(() => {
    if (data) checkAlarms(data);
  }, [data, checkAlarms]);

  // Ticker auto-scroll
  useEffect(() => {
    if (!data?.ticker?.length) return;
    const interval = setInterval(() => {
      setTickerOffset(prev => prev - 1);
    }, 40);
    return () => clearInterval(interval);
  }, [data?.ticker?.length]);

  const fetchData = () => {
    axios.get(`${API}/tv/dashboard`).then(r => setData(r.data)).catch(() => {});
  };

  if (!data) return (
    <div className="tv-loading" onClick={initAudio}>
      <div className="tv-loading-pulse" />
      <p>Connessione al NOC...</p>
    </div>
  );

  const g = data.global_stats;
  const hasProblems = g.total_offline > 0 || g.critical_alerts > 0;
  const allGood = g.total_offline === 0 && g.total_alerts === 0;

  return (
    <div className="tv-root" data-testid="tv-dashboard">
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
      <header className="tv-header">
        <div className="tv-header-left">
          <div className="tv-logo">NOC</div>
          <div>
            <h1 className="tv-title">86BIT NOC Center</h1>
            <p className="tv-subtitle">Network Operations Center</p>
          </div>
        </div>
        <div className="tv-header-right">
          <button
            className={`tv-sound-btn ${soundEnabled ? "tv-sound-on" : ""}`}
            onClick={initAudio}
            data-testid="tv-sound-toggle"
            title={soundEnabled ? "Audio attivo" : "Clicca per abilitare l'audio"}
          >
            {soundEnabled ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14"/>
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>
              </svg>
            )}
            <span className="tv-sound-label">{soundEnabled ? "AUDIO ON" : "AUDIO OFF"}</span>
          </button>
          <div className={`tv-global-status ${allGood ? "tv-status-ok" : hasProblems ? "tv-status-critical" : "tv-status-warn"}`}>
            <span className="tv-status-dot" />
            {allGood ? "TUTTI OPERATIVI" : hasProblems ? "ATTENZIONE" : "IN MONITORAGGIO"}
          </div>
          <div className="tv-clock">
            <span className="tv-clock-time">{clock.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
            <span className="tv-clock-date">{clock.toLocaleDateString("it-IT", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</span>
          </div>
        </div>
      </header>

      {/* GLOBAL STATS BAR */}
      <div className="tv-stats-bar" data-testid="tv-stats-bar">
        <StatBlock label="DISPOSITIVI" value={g.total_devices} color="var(--tv-blue)" />
        <StatBlock label="ONLINE" value={g.total_online} color="var(--tv-green)" />
        <StatBlock label="OFFLINE" value={g.total_offline} color={g.total_offline > 0 ? "var(--tv-red)" : "var(--tv-dim)"} pulse={g.total_offline > 0} />
        <StatBlock label="CRITICI" value={g.critical_alerts} color={g.critical_alerts > 0 ? "var(--tv-red)" : "var(--tv-dim)"} pulse={g.critical_alerts > 0} />
        <StatBlock label="ALERT" value={g.total_alerts} color={g.total_alerts > 0 ? "var(--tv-amber)" : "var(--tv-dim)"} />
        <StatBlock label="INCIDENTI" value={g.open_incidents} color={g.open_incidents > 0 ? "var(--tv-orange)" : "var(--tv-dim)"} />
        <StatBlock label="STAMPANTI" value={g.total_printers} color="var(--tv-purple)" />
        <StatBlock label="TONER" value={g.low_toner_count} color={g.low_toner_count > 0 ? "var(--tv-amber)" : "var(--tv-dim)"} />
      </div>

      {/* MAIN CONTENT - 3 columns */}
      <div className="tv-main" data-testid="tv-main-content">
        {/* LEFT: Client cards + Connectors */}
        <div className="tv-col-left">
          <SectionTitle>Stato Clienti</SectionTitle>
          <div className="tv-clients-grid">
            {data.clients.map(client => (
              <ClientCard key={client.id} client={client} />
            ))}
            {data.clients.length === 0 && <div className="tv-empty">Nessun cliente</div>}
          </div>

          {/* Connectors status */}
          {data.connectors.length > 0 && (
            <>
              <SectionTitle>Connettori</SectionTitle>
              <div className="tv-connectors-grid">
                {data.connectors.map((c, i) => (
                  <div key={i} className={`tv-connector-chip ${c.online ? "" : "tv-connector-off"}`} data-testid={`tv-connector-${i}`}>
                    <span className="tv-conn-dot" style={{ background: c.online ? "var(--tv-green)" : "var(--tv-red)" }} />
                    <span className="tv-conn-name">{c.client_name}</span>
                    <span className="tv-conn-host">{c.hostname}</span>
                    <span className="tv-conn-ver">{c.version}</span>
                    <span className="tv-conn-time">{c.last_seen}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* CENTER: Offline Devices (most critical) */}
        <div className="tv-col-center">
          <SectionTitle count={data.offline_devices.length} countColor="var(--tv-red)">
            Dispositivi Offline
          </SectionTitle>
          <div className="tv-offline-list" data-testid="tv-offline-devices">
            {data.offline_devices.length === 0 ? (
              <div className="tv-all-ok">
                <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="var(--tv-green)" strokeWidth="1.5">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <p className="tv-all-ok-text">Tutti i dispositivi<br/>sono operativi</p>
              </div>
            ) : (
              data.offline_devices.map((d, i) => (
                <div key={i} className="tv-offline-row" data-testid={`tv-offline-${d.ip}`}>
                  <div className="tv-offline-indicator">
                    <span className="tv-offline-pulse" />
                  </div>
                  <div className="tv-offline-info">
                    <span className="tv-offline-name">{d.name}</span>
                    <span className="tv-offline-ip">{d.ip}</span>
                  </div>
                  <div className="tv-offline-meta">
                    <span className="tv-offline-client">{d.client_name}</span>
                    <span className="tv-offline-since">{d.down_since ? `da ${d.down_since}` : ""}</span>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Incidents */}
          {data.incidents.length > 0 && (
            <>
              <SectionTitle count={data.incidents.length} countColor="var(--tv-orange)">
                Incidenti Aperti
              </SectionTitle>
              <div className="tv-incidents-list" data-testid="tv-incidents">
                {data.incidents.map((inc, i) => (
                  <div key={i} className="tv-incident-row" data-testid={`tv-incident-${inc.id}`}>
                    <span className={`tv-inc-priority tv-inc-${inc.priority}`}>
                      {inc.priority === "critical" ? "P1" : inc.priority === "high" ? "P2" : inc.priority === "medium" ? "P3" : "P4"}
                    </span>
                    <div className="tv-inc-info">
                      <span className="tv-inc-title">{inc.title}</span>
                      <span className="tv-inc-meta">{inc.client_name} &middot; {inc.time_ago}</span>
                    </div>
                    <span className={`tv-inc-status tv-inc-status-${inc.status}`}>
                      {inc.status === "open" ? "APERTO" : "IN CORSO"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* RIGHT: Alerts + Toner */}
        <div className="tv-col-right">
          <SectionTitle count={data.alerts.length} countColor="var(--tv-amber)">
            Alert Attivi
          </SectionTitle>
          <div className="tv-alerts-list" data-testid="tv-alerts-panel">
            {data.alerts.length === 0 ? (
              <div className="tv-all-ok tv-all-ok-sm">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="var(--tv-green)" strokeWidth="2">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <p>Nessun alert</p>
              </div>
            ) : (
              data.alerts.map((alert, i) => (
                <AlertRow key={alert.id || i} alert={alert} />
              ))
            )}
          </div>

          {/* Low Toner */}
          {data.low_toner.length > 0 && (
            <>
              <SectionTitle count={data.low_toner.length} countColor="var(--tv-amber)">
                Consumabili Bassi
              </SectionTitle>
              <div className="tv-toner-list">
                {data.low_toner.map((t, i) => (
                  <div key={i} className="tv-toner-row">
                    <div className="tv-toner-bar-wrap">
                      <div className="tv-toner-bar" style={{
                        width: `${t.level_pct}%`,
                        background: t.level_pct <= 5 ? "var(--tv-red)" : t.color_hex || "var(--tv-amber)"
                      }} />
                    </div>
                    <span className="tv-toner-pct" style={{ color: t.level_pct <= 5 ? "var(--tv-red)" : "var(--tv-amber)" }}>{t.level_pct}%</span>
                    <span className="tv-toner-name">{t.supply_name}</span>
                    <span className="tv-toner-printer">{t.printer_name}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* TICKER FOOTER */}
      <footer className="tv-footer" data-testid="tv-ticker">
        <div className="tv-footer-left">
          <span className="tv-footer-live">LIVE</span>
          <span className="tv-footer-info">{g.total_clients} clienti &middot; {g.total_devices} dispositivi &middot; Aggiornamento: {new Date(data.timestamp).toLocaleTimeString("it-IT")}</span>
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

function SectionTitle({ children, count, countColor }) {
  return (
    <h2 className="tv-section-title">
      {children}
      {count > 0 && <span className="tv-section-count" style={{ background: countColor }}>{count}</span>}
    </h2>
  );
}

function StatBlock({ label, value, color, pulse }) {
  return (
    <div className={`tv-stat ${pulse ? "tv-pulse" : ""}`} style={{ borderColor: color }}>
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
          <span className="tv-status-dot-sm" style={{ background: c.connector_online ? "var(--tv-green)" : "var(--tv-red)" }} />
          {c.connector_online ? "CONNESSO" : "OFFLINE"}
        </div>
      </div>

      <div className="tv-client-metrics">
        <div className="tv-client-health">
          <svg viewBox="0 0 36 36" className="tv-health-ring">
            <path d="M18 2.0845a 15.9155 15.9155 0 0 1 0 31.831a 15.9155 15.9155 0 0 1 0 -31.831"
              fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="3" />
            <path d="M18 2.0845a 15.9155 15.9155 0 0 1 0 31.831a 15.9155 15.9155 0 0 1 0 -31.831"
              fill="none" stroke={healthColor} strokeWidth="3"
              strokeDasharray={`${c.health_pct}, 100`}
              strokeLinecap="round" />
          </svg>
          <span className="tv-health-value" style={{ color: healthColor }}>{c.health_pct}%</span>
        </div>

        <div className="tv-client-counts">
          <div className="tv-count-row">
            <span className="tv-count-dot" style={{ background: "var(--tv-green)" }} />
            <span className="tv-count-val">{c.online}</span>
            <span className="tv-count-label">online</span>
          </div>
          <div className="tv-count-row">
            <span className="tv-count-dot" style={{ background: c.offline > 0 ? "var(--tv-red)" : "var(--tv-dim)" }} />
            <span className="tv-count-val" style={{ color: c.offline > 0 ? "var(--tv-red)" : "inherit" }}>{c.offline}</span>
            <span className="tv-count-label">offline</span>
          </div>
          {c.alert_count > 0 && (
            <div className="tv-count-row">
              <span className="tv-count-dot" style={{ background: c.critical_alerts > 0 ? "var(--tv-red)" : "var(--tv-amber)" }} />
              <span className="tv-count-val" style={{ color: c.critical_alerts > 0 ? "var(--tv-red)" : "var(--tv-amber)" }}>{c.alert_count}</span>
              <span className="tv-count-label">alert</span>
            </div>
          )}
          {c.printer_count > 0 && (
            <div className="tv-count-row">
              <span className="tv-count-dot" style={{ background: "var(--tv-purple)" }} />
              <span className="tv-count-val">{c.printer_count}</span>
              <span className="tv-count-label">stampanti</span>
            </div>
          )}
        </div>
      </div>

      {c.last_heartbeat && (
        <div className="tv-client-heartbeat">
          Heartbeat: {c.last_heartbeat} {c.connector_version && `(v${c.connector_version})`}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert }) {
  const severityConfig = {
    critical: { color: "var(--tv-red)", label: "CRITICO", bg: "rgba(239,68,68,0.08)" },
    high: { color: "var(--tv-orange)", label: "ALTO", bg: "rgba(249,115,22,0.06)" },
    medium: { color: "var(--tv-amber)", label: "MEDIO", bg: "rgba(245,158,11,0.05)" },
    low: { color: "var(--tv-blue)", label: "BASSO", bg: "rgba(59,130,246,0.05)" },
  };
  const cfg = severityConfig[alert.severity] || severityConfig.low;

  return (
    <div className="tv-alert-row" style={{ borderLeftColor: cfg.color, background: cfg.bg }} data-testid={`tv-alert-${alert.id}`}>
      <div className="tv-alert-left">
        <span className="tv-alert-severity" style={{ color: cfg.color }}>{cfg.label}</span>
        <span className="tv-alert-time">{alert.time_ago}</span>
      </div>
      <div className="tv-alert-content">
        <div className="tv-alert-top">
          <span className="tv-alert-device">{alert.device_name}</span>
          <span className="tv-alert-ip">{alert.device_ip}</span>
          <span className="tv-alert-client">{alert.client_name}</span>
        </div>
        <div className="tv-alert-msg">{alert.title}{alert.message ? `: ${alert.message}` : ""}</div>
      </div>
    </div>
  );
}
