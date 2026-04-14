import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import {
  WifiHigh, WifiSlash, Warning, CheckCircle, ShieldCheck,
  Bell, ArrowClockwise, CaretRight, Printer, Globe,
} from "@phosphor-icons/react";

/**
 * MobileDashboard - Vista mobile essenziale per tecnici in movimento.
 * Mostra per ogni cliente: health, dispositivi ON/OFF, alert, WAN status.
 * Un tap sul cliente apre i dettagli.
 */
export default function MobileDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetch = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/tv/dashboard`);
      setData(r.data);
    } catch {} finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch();
    const i = setInterval(fetch, 15000);
    return () => clearInterval(i);
  }, [fetch]);

  if (loading) return (
    <div className="flex items-center justify-center h-[60vh] text-[var(--text-muted)] text-sm">
      <ArrowClockwise size={16} className="animate-spin mr-2" /> Caricamento...
    </div>
  );

  if (!data) return null;

  const g = data.global_stats;
  const hasProblems = g.total_offline > 0 || g.critical_alerts > 0;

  return (
    <div className="mobile-dash" data-testid="mobile-dashboard">
      {/* Global status bar */}
      <div className={`mobile-status ${hasProblems ? "mobile-status-bad" : "mobile-status-ok"}`} data-testid="mobile-global-status">
        <div className="mobile-status-icon">
          {hasProblems ? <Warning size={18} weight="bold" /> : <CheckCircle size={18} weight="bold" />}
        </div>
        <div className="mobile-status-text">
          {hasProblems ? "ATTENZIONE" : "TUTTO OPERATIVO"}
        </div>
        <button onClick={fetch} className="mobile-refresh-btn" data-testid="mobile-refresh">
          <ArrowClockwise size={14} />
        </button>
      </div>

      {/* Quick stats */}
      <div className="mobile-quick-stats" data-testid="mobile-quick-stats">
        <div className="mobile-qs">
          <span className="mobile-qs-v">{g.total_devices}</span>
          <span className="mobile-qs-l">Dispositivi</span>
        </div>
        <div className="mobile-qs">
          <span className="mobile-qs-v" style={{ color: "#34C759" }}>{g.total_online}</span>
          <span className="mobile-qs-l">Online</span>
        </div>
        <div className="mobile-qs">
          <span className="mobile-qs-v" style={{ color: g.total_offline > 0 ? "#FF3B30" : "#333" }}>{g.total_offline}</span>
          <span className="mobile-qs-l">Offline</span>
        </div>
        <div className="mobile-qs">
          <span className="mobile-qs-v" style={{ color: g.total_alerts > 0 ? "#FFCC00" : "#333" }}>{g.total_alerts}</span>
          <span className="mobile-qs-l">Alert</span>
        </div>
      </div>

      {/* Client cards */}
      <div className="mobile-clients" data-testid="mobile-clients-list">
        {data.clients.map(c => (
          <MobileClientCard key={c.id} client={c} navigate={navigate} />
        ))}
      </div>

      {/* Offline devices (if any) */}
      {data.offline_devices.length > 0 && (
        <div className="mobile-offline-section" data-testid="mobile-offline-section">
          <div className="mobile-section-header">
            <WifiSlash size={14} className="text-red-400" />
            <span>Dispositivi Offline ({data.offline_devices.length})</span>
          </div>
          {data.offline_devices.map((d, i) => (
            <div key={i} className="mobile-offline-row" data-testid={`mobile-offline-${d.ip}`}>
              <span className="mobile-off-dot" />
              <div className="mobile-off-info">
                <span className="mobile-off-name">{d.name}</span>
                <span className="mobile-off-detail">{d.ip} — {d.client_name}</span>
              </div>
              {d.down_since && <span className="mobile-off-since">{d.down_since}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Low toner */}
      {data.low_toner.length > 0 && (
        <div className="mobile-toner-section" data-testid="mobile-toner-section">
          <div className="mobile-section-header">
            <Printer size={14} className="text-amber-400" />
            <span>Consumabili Bassi ({data.low_toner.length})</span>
          </div>
          {data.low_toner.map((t, i) => (
            <div key={i} className="mobile-toner-row">
              <div className="mobile-toner-bar-bg">
                <div className="mobile-toner-bar" style={{ width: `${t.level_pct}%`, background: t.level_pct <= 5 ? "#FF3B30" : t.color_hex || "#FFCC00" }} />
              </div>
              <span className="mobile-toner-pct" style={{ color: t.level_pct <= 5 ? "#FF3B30" : "#FFCC00" }}>{t.level_pct}%</span>
              <span className="mobile-toner-name">{t.supply_name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MobileClientCard({ client, navigate }) {
  const c = client;
  const hp = c.health_pct;
  const hColor = hp >= 90 ? "#34C759" : hp >= 70 ? "#FFCC00" : hp >= 50 ? "#FF9500" : "#FF3B30";
  const hasIssue = c.offline > 0 || c.critical_alerts > 0;
  const wan = c.wan_targets || [];
  const wanOk = c.wan_diagnosis === "ok" || c.wan_diagnosis === "not_configured";

  return (
    <div
      className={`mobile-client ${hasIssue ? "mobile-client-bad" : ""}`}
      onClick={() => navigate("/network-status")}
      data-testid={`mobile-client-${c.id}`}
    >
      {/* Top row: name + health */}
      <div className="mobile-client-top">
        <div className="mobile-client-left">
          <span className="mobile-client-name">{c.name}</span>
          <div className="mobile-client-tags">
            <span className={`mobile-tag ${c.connector_online ? "mobile-tag-green" : "mobile-tag-red"}`}>
              {c.connector_online ? "CONN" : "NO CONN"}
            </span>
            {wan.length > 0 && (
              <span className={`mobile-tag ${wanOk ? "mobile-tag-green" : "mobile-tag-red"}`}>
                <Globe size={9} className="inline mr-0.5" />WAN {wanOk ? "OK" : "!"}
              </span>
            )}
          </div>
        </div>
        <div className="mobile-client-health" style={{ color: hColor }}>
          <svg viewBox="0 0 36 36" width="44" height="44">
            <circle cx="18" cy="18" r="15.9" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="3" />
            <circle cx="18" cy="18" r="15.9" fill="none" stroke={hColor} strokeWidth="3"
              strokeDasharray={`${hp}, 100`} strokeLinecap="round"
              style={{ transform: "rotate(-90deg)", transformOrigin: "50% 50%" }} />
          </svg>
          <span className="mobile-health-val">{hp}%</span>
        </div>
      </div>

      {/* Metrics */}
      <div className="mobile-client-metrics">
        <div className="mobile-cm">
          <WifiHigh size={12} style={{ color: "#34C759" }} />
          <span className="mobile-cm-v" style={{ color: "#34C759" }}>{c.online}</span>
          <span className="mobile-cm-l">on</span>
        </div>
        <div className="mobile-cm">
          <WifiSlash size={12} style={{ color: c.offline > 0 ? "#FF3B30" : "#333" }} />
          <span className="mobile-cm-v" style={{ color: c.offline > 0 ? "#FF3B30" : "#333" }}>{c.offline}</span>
          <span className="mobile-cm-l">off</span>
        </div>
        <div className="mobile-cm">
          <Bell size={12} style={{ color: c.alert_count > 0 ? "#FFCC00" : "#333" }} />
          <span className="mobile-cm-v" style={{ color: c.alert_count > 0 ? "#FFCC00" : "#333" }}>{c.alert_count}</span>
          <span className="mobile-cm-l">alert</span>
        </div>
        <div className="mobile-cm">
          <Printer size={12} style={{ color: c.printer_count > 0 ? "#AF52DE" : "#333" }} />
          <span className="mobile-cm-v" style={{ color: c.printer_count > 0 ? "#AF52DE" : "#333" }}>{c.printer_count}</span>
          <span className="mobile-cm-l">stamp</span>
        </div>
        <CaretRight size={14} className="text-[#333] ml-auto" />
      </div>

      {/* Offline devices inline */}
      {c.problem_devices && c.problem_devices.length > 0 && (
        <div className="mobile-client-problems">
          {c.problem_devices.slice(0, 3).map((d, i) => (
            <div key={i} className="mobile-prob-row">
              <span className="mobile-prob-dot" />
              <span className="mobile-prob-name">{d.name}</span>
              <span className="mobile-prob-ip">{d.ip}</span>
            </div>
          ))}
          {c.problem_devices.length > 3 && (
            <span className="mobile-prob-more">+{c.problem_devices.length - 3} altri offline</span>
          )}
        </div>
      )}

      {/* WAN targets inline */}
      {wan.length > 0 && (
        <div className="mobile-client-wan">
          {wan.map((w, i) => (
            <div key={i} className="mobile-wan-row">
              <span className={`mobile-wan-dot mobile-wan-dot-${w.status}`} />
              <span className="mobile-wan-label">{w.label}</span>
              {w.latency_ms != null && (
                <span className="mobile-wan-lat" style={{ color: w.latency_ms > 100 ? "#FF3B30" : "#34C759" }}>
                  {w.latency_ms}ms
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
