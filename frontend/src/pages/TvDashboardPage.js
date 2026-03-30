import { useState, useEffect, useRef } from "react";
import axios from "axios";
import "./TvDashboard.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_INTERVAL = 15000;

export default function TvDashboardPage() {
  const [data, setData] = useState(null);
  const [clock, setClock] = useState(new Date());
  const [alertScroll, setAlertScroll] = useState(0);
  const tickerRef = useRef(null);

  useEffect(() => {
    fetchData();
    const dataInterval = setInterval(fetchData, REFRESH_INTERVAL);
    const clockInterval = setInterval(() => setClock(new Date()), 1000);
    return () => { clearInterval(dataInterval); clearInterval(clockInterval); };
  }, []);

  // Auto-scroll alerts
  useEffect(() => {
    if (!data?.alerts?.length) return;
    const interval = setInterval(() => {
      setAlertScroll(prev => (prev + 1) % Math.max(data.alerts.length, 1));
    }, 4000);
    return () => clearInterval(interval);
  }, [data?.alerts?.length]);

  const fetchData = () => {
    axios.get(`${API}/tv/dashboard`).then(r => setData(r.data)).catch(() => {});
  };

  if (!data) return (
    <div className="tv-loading">
      <div className="tv-loading-pulse" />
      <p>Connessione al NOC...</p>
    </div>
  );

  const g = data.global_stats;
  const hasProblems = g.total_offline > 0 || g.critical_alerts > 0;
  const allGood = g.total_offline === 0 && g.total_alerts === 0;

  return (
    <div className="tv-root" data-testid="tv-dashboard">
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
        <StatBlock label="ALERT CRITICI" value={g.critical_alerts} color={g.critical_alerts > 0 ? "var(--tv-red)" : "var(--tv-dim)"} pulse={g.critical_alerts > 0} />
        <StatBlock label="ALERT TOTALI" value={g.total_alerts} color={g.total_alerts > 0 ? "var(--tv-amber)" : "var(--tv-dim)"} />
        <StatBlock label="INCIDENTI" value={g.open_incidents} color={g.open_incidents > 0 ? "var(--tv-orange)" : "var(--tv-dim)"} />
        <StatBlock label="STAMPANTI" value={g.total_printers} color="var(--tv-purple)" />
        <StatBlock label="TONER BASSO" value={g.low_toner_count} color={g.low_toner_count > 0 ? "var(--tv-amber)" : "var(--tv-dim)"} />
      </div>

      {/* MAIN CONTENT */}
      <div className="tv-main">
        {/* CLIENT GRID */}
        <div className="tv-clients-section" data-testid="tv-clients-grid">
          <h2 className="tv-section-title">Stato Clienti</h2>
          <div className="tv-clients-grid">
            {data.clients.map(client => (
              <ClientCard key={client.id} client={client} />
            ))}
            {data.clients.length === 0 && (
              <div className="tv-empty">Nessun cliente configurato</div>
            )}
          </div>
        </div>

        {/* ALERTS PANEL */}
        <div className="tv-alerts-section" data-testid="tv-alerts-panel">
          <h2 className="tv-section-title">
            Alert Attivi
            {data.alerts.length > 0 && <span className="tv-alert-count">{data.alerts.length}</span>}
          </h2>
          <div className="tv-alerts-list" ref={tickerRef}>
            {data.alerts.length === 0 ? (
              <div className="tv-no-alerts">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--tv-green)" strokeWidth="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                <p>Nessun alert attivo</p>
              </div>
            ) : (
              data.alerts.map((alert, i) => (
                <AlertRow key={alert.id || i} alert={alert} highlight={i === alertScroll} />
              ))
            )}
          </div>

          {/* Low Toner Section */}
          {data.low_toner.length > 0 && (
            <div className="tv-toner-section">
              <h3 className="tv-toner-title">Consumabili Bassi</h3>
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
          )}
        </div>
      </div>

      {/* BOTTOM STATUS BAR */}
      <footer className="tv-footer">
        <span>Auto-refresh: {REFRESH_INTERVAL / 1000}s</span>
        <span>Ultimo aggiornamento: {new Date(data.timestamp).toLocaleTimeString("it-IT")}</span>
        <span>{g.total_clients} clienti monitorati</span>
      </footer>
    </div>
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
        <div className="tv-client-health" style={{ "--health-color": healthColor, "--health-pct": `${c.health_pct}%` }}>
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
        </div>
      </div>

      {/* Problem devices list */}
      {c.problem_devices.length > 0 && (
        <div className="tv-client-problems">
          {c.problem_devices.map((d, i) => (
            <div key={i} className="tv-problem-device">
              <span className="tv-problem-icon">&#x25CF;</span>
              <span className="tv-problem-name">{d.name}</span>
              <span className="tv-problem-ip">{d.ip}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert, highlight }) {
  const severityConfig = {
    critical: { color: "var(--tv-red)", bg: "rgba(239,68,68,0.12)", label: "CRITICO" },
    high: { color: "var(--tv-orange)", bg: "rgba(249,115,22,0.10)", label: "ALTO" },
    medium: { color: "var(--tv-amber)", bg: "rgba(245,158,11,0.08)", label: "MEDIO" },
    low: { color: "var(--tv-blue)", bg: "rgba(59,130,246,0.08)", label: "BASSO" },
  };
  const cfg = severityConfig[alert.severity] || severityConfig.low;

  return (
    <div className={`tv-alert-row ${highlight ? "tv-alert-highlight" : ""}`}
      style={{ borderLeftColor: cfg.color, background: highlight ? cfg.bg : "transparent" }}
      data-testid={`tv-alert-${alert.id}`}>
      <span className="tv-alert-severity" style={{ color: cfg.color }}>{cfg.label}</span>
      <span className="tv-alert-device">{alert.device_name || alert.device_ip}</span>
      <span className="tv-alert-msg">{alert.title || alert.value || alert.message}</span>
      <span className="tv-alert-time">
        {alert.created_at ? new Date(alert.created_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }) : ""}
      </span>
    </div>
  );
}
