import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { usePwa } from "@/components/PwaProvider";
import {
  Warning, CheckCircle, ArrowClockwise,
  CaretDown, Globe, PlugsConnected, Plugs, ShieldCheck, Funnel,
  BellRinging, BellSlash, Bell,
} from "@phosphor-icons/react";

/**
 * MobileDashboard — vista telefono per tecnici sul campo.
 * Mostra SOLO l'essenziale, scoping VITAL-ONLY (fonte /api/overview/clients):
 *   - stato salute cliente (semaforo) + connettore
 *   - stato linea WAN/Internet
 *   - dispositivi VITALI su/giù (offline in cima)
 *   - alert attivi (all'espansione)
 * Clienti ordinati problemi-first dal backend. Tap = espandi in linea.
 */

const HEALTH = {
  critical: { color: "#FF3B30", label: "CRITICO" },
  warning: { color: "#FFCC00", label: "DA CONTROLLARE" },
  attention: { color: "#FF9500", label: "ATTENZIONE" },
  ok: { color: "#34C759", label: "OK" },
};

const WAN_DOWN = new Set(["isp_down", "router_down", "firewall_down", "offline"]);
const WAN_WARN = new Set(["degraded", "firewall_degraded", "router_degraded", "pending"]);

function wanView(status) {
  if (!status || status === "not_configured") return null;
  if (WAN_DOWN.has(status)) return { cls: "red", label: "WAN GIÙ" };
  if (WAN_WARN.has(status)) return { cls: "amber", label: "WAN !" };
  return { cls: "green", label: "WAN OK" };
}

const SEV_COLOR = { critical: "#FF3B30", high: "#FF9500", medium: "#FFCC00", low: "#8E8E93" };
const STATUS_COLOR = {
  online: "#34C759", active: "#34C759", offline: "#FF3B30", inactive: "#FF3B30",
  stale: "#FFCC00", pending: "#FFCC00", unknown: "#636366",
};
const STATUS_LABEL = {
  online: "online", active: "online", offline: "OFFLINE", inactive: "OFFLINE",
  stale: "incerto", pending: "in attesa", unknown: "n/d",
};
const statusColor = (s) => STATUS_COLOR[s] || "#34C759";
const statusLabel = (s) => STATUS_LABEL[s] || "online";
const isDownStatus = (s) => s === "offline" || s === "inactive";

export default function MobileDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const navigate = useNavigate();
  const pwa = usePwa();

  // --- Notifiche push (tecnico riceve alert critici anche ad app chiusa) ---
  const [notifMsg, setNotifMsg] = useState("");
  const [notifBusy, setNotifBusy] = useState(false);
  const notifPerm = pwa?.notificationPermission || "default";

  const flash = useCallback((m) => {
    setNotifMsg(m);
    setTimeout(() => setNotifMsg(""), 3200);
  }, []);

  const handleNotif = useCallback(async () => {
    if (!pwa) return;
    if (notifBusy) return;
    if (notifPerm === "denied") {
      flash("Notifiche bloccate. Abilitale dalle impostazioni del browser/telefono.");
      return;
    }
    setNotifBusy(true);
    try {
      if (notifPerm !== "granted") {
        const perm = await pwa.requestNotificationPermission();
        if (perm !== "granted") { flash("Permesso notifiche negato."); return; }
      }
      const sub = await pwa.subscribeToPush();
      if (notifPerm === "granted") {
        const r = await pwa.sendTestPush();
        flash(r?.success ? "Notifica di test inviata ✓" : "Impossibile inviare il test.");
      } else {
        flash(sub ? "Notifiche attivate ✓ Riceverai gli alert critici." : "Attivazione non riuscita.");
      }
    } finally {
      setNotifBusy(false);
    }
  }, [pwa, notifPerm, notifBusy, flash]);

  const fetchData = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/overview/clients`);
      setData(r.data);
      setUpdatedAt(new Date());
    } catch { /* keep previous data */ } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const i = setInterval(fetchData, 15000);
    return () => clearInterval(i);
  }, [fetchData]);

  // --- Pull-to-refresh nativo ---
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const startY = useRef(0);
  const pulling = useRef(false);
  const THRESHOLD = 64;

  const scroller = () => document.querySelector(".main-content") || document.scrollingElement;

  const onTouchStart = (e) => {
    const sc = scroller();
    if (sc && sc.scrollTop <= 0 && !refreshing) {
      startY.current = e.touches[0].clientY;
      pulling.current = true;
    } else {
      pulling.current = false;
    }
  };
  const onTouchMove = (e) => {
    if (!pulling.current || refreshing) return;
    const dy = e.touches[0].clientY - startY.current;
    if (dy > 0) {
      setPull(Math.min(dy * 0.5, 90)); // resistenza + cap
    } else {
      setPull(0);
    }
  };
  const onTouchEnd = async () => {
    if (!pulling.current) return;
    pulling.current = false;
    if (pull >= THRESHOLD) {
      setRefreshing(true);
      setPull(THRESHOLD);
      await fetchData();
      setRefreshing(false);
    }
    setPull(0);
  };

  const g = data?.global;
  const clients = useMemo(() => {
    const list = data?.clients || [];
    return onlyProblems ? list.filter((c) => c.health === "critical" || c.health === "warning") : list;
  }, [data, onlyProblems]);

  if (loading) {
    return (
      <div className="mdash-loading" data-testid="mobile-dashboard-loading">
        <ArrowClockwise size={18} className="animate-spin" /> Caricamento…
      </div>
    );
  }
  if (!data) return null;

  const hasProblems = (g?.clients_critical || 0) > 0 || (g?.clients_warning || 0) > 0;
  const banner = (g?.clients_critical || 0) > 0
    ? { cls: "bad", txt: `${g.clients_critical} client${g.clients_critical > 1 ? "i" : "e"} in stato critico` }
    : (g?.clients_warning || 0) > 0
      ? { cls: "warn", txt: `${g.clients_warning} client${g.clients_warning > 1 ? "i" : "e"} da controllare` }
      : { cls: "ok", txt: "Tutti i clienti operativi" };

  return (
    <div
      className="mdash"
      data-testid="mobile-dashboard"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {/* Pull-to-refresh indicator */}
      <div className="mdash-ptr" style={{ height: pull }} data-testid="mobile-ptr">
        <ArrowClockwise
          size={20}
          className={refreshing ? "animate-spin" : ""}
          style={{ opacity: Math.min(pull / THRESHOLD, 1), transform: `rotate(${pull * 3}deg)` }}
        />
        {pull >= THRESHOLD && !refreshing && <span className="mdash-ptr-txt">Rilascia per aggiornare</span>}
      </div>

      {/* Banner stato globale */}
      <div className={`mdash-banner mdash-banner-${banner.cls}`} data-testid="mobile-global-status">
        <div className="mdash-banner-icon">
          {hasProblems ? <Warning size={20} weight="fill" /> : <CheckCircle size={20} weight="fill" />}
        </div>
        <div className="mdash-banner-body">
          <span className="mdash-banner-title">{banner.txt}</span>
          <span className="mdash-banner-sub">
            {g?.devices_online}/{g?.total_devices} vitali online
            {updatedAt && <> · agg. {updatedAt.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</>}
          </span>
        </div>
        <button
          onClick={handleNotif}
          className={`mdash-bell ${notifPerm === "granted" ? "on" : notifPerm === "denied" ? "off" : ""}`}
          data-testid="mobile-notif-btn"
          aria-label="Notifiche push"
          disabled={notifBusy}
        >
          {notifBusy ? <ArrowClockwise size={18} className="animate-spin" />
            : notifPerm === "granted" ? <BellRinging size={18} weight="fill" />
            : notifPerm === "denied" ? <BellSlash size={18} />
            : <Bell size={18} />}
        </button>
        <button onClick={fetchData} className="mdash-refresh" data-testid="mobile-refresh" aria-label="Aggiorna">
          <ArrowClockwise size={18} />
        </button>
      </div>

      {/* Feedback notifiche */}
      {notifMsg && (
        <div className="mdash-notif-msg" data-testid="mobile-notif-msg">{notifMsg}</div>
      )}


      {/* Riepilogo semafori */}
      <div className="mdash-summary" data-testid="mobile-summary">
        <SummaryPill value={g?.clients_critical || 0} label="Critici" color="#FF3B30" active />
        <SummaryPill value={g?.clients_warning || 0} label="Warning" color="#FFCC00" />
        <SummaryPill value={g?.clients_ok || 0} label="OK" color="#34C759" />
        <button
          className={`mdash-filter ${onlyProblems ? "on" : ""}`}
          onClick={() => setOnlyProblems((v) => !v)}
          data-testid="mobile-filter-problems"
        >
          <Funnel size={14} weight={onlyProblems ? "fill" : "regular"} />
          <span>Solo problemi</span>
        </button>
      </div>

      {/* Lista clienti */}
      <div className="mdash-list" data-testid="mobile-clients-list">
        {clients.length === 0 && (
          <div className="mdash-empty" data-testid="mobile-empty">
            <ShieldCheck size={30} weight="duotone" />
            <span>{onlyProblems ? "Nessun problema in corso 🎉" : "Nessun cliente"}</span>
          </div>
        )}
        {clients.map((c) => (
          <ClientCard key={c.id} c={c} navigate={navigate} />
        ))}
      </div>
    </div>
  );
}

function SummaryPill({ value, label, color, active }) {
  const dim = value === 0 && !active;
  return (
    <div className="mdash-sum" style={{ opacity: dim ? 0.45 : 1 }}>
      <span className="mdash-sum-v" style={{ color: value > 0 ? color : "var(--text-secondary)" }}>{value}</span>
      <span className="mdash-sum-l">{label}</span>
    </div>
  );
}

function ClientCard({ c, navigate }) {
  const [open, setOpen] = useState(false);
  const h = HEALTH[c.health] || HEALTH.ok;
  const isBad = c.health === "critical" || c.health === "warning";
  const dev = c.devices || {};
  const vTotal = dev.vital_total || 0;
  const vOnline = dev.vital_online || 0;
  const vOffline = dev.vital_offline || 0;
  const conn = c.connector_online;
  const wan = wanView(c.wan?.status);
  const alerts = c.alerts || {};
  const alertBadge = (alerts.critical || 0) + (alerts.high || 0);
  const vitalList = c.detail?.vital_list || [];
  const wanTargets = c.detail?.wan_targets || [];
  const recentAlerts = c.detail?.recent_alerts || [];

  return (
    <div className={`mdash-card ${isBad ? "bad" : ""}`} data-testid={`mobile-client-${c.id}`}>
      <button className="mdash-card-head" onClick={() => setOpen((v) => !v)} data-testid={`mobile-client-toggle-${c.id}`}>
        <span className={`mdash-dot ${c.health === "critical" ? "pulse" : ""}`} style={{ background: h.color }} />
        <div className="mdash-card-info">
          <span className="mdash-card-name">{c.name}</span>
          <div className="mdash-badges">
            {conn === true && <span className="mdash-badge green"><PlugsConnected size={10} weight="bold" />CONN</span>}
            {conn === false && <span className="mdash-badge red"><Plugs size={10} weight="bold" />NO CONN</span>}
            {wan && <span className={`mdash-badge ${wan.cls}`}><Globe size={10} weight="bold" />{wan.label}</span>}
            <span className={`mdash-badge ${vOffline > 0 ? "red" : "green"}`}>
              {vOnline}/{vTotal} vitali
            </span>
          </div>
        </div>
        {alertBadge > 0 && (
          <span className="mdash-alert-badge" data-testid={`mobile-client-alerts-${c.id}`}>{alertBadge}</span>
        )}
        <CaretDown size={16} className={`mdash-chevron ${open ? "open" : ""}`} />
      </button>

      {open && (
        <div className="mdash-card-body" data-testid={`mobile-client-detail-${c.id}`}>
          {/* Dispositivi vitali */}
          <div className="mdash-section-title">Dispositivi vitali ({vTotal})</div>
          {vitalList.length === 0 && <div className="mdash-none">Nessun dispositivo vitale configurato</div>}
          {vitalList.map((d, i) => (
            <div key={i} className="mdash-row" data-testid={`mobile-vital-${c.id}-${i}`}>
              <span className={`mdash-rdot ${isDownStatus(d.status) ? "pulse" : ""}`} style={{ background: statusColor(d.status) }} />
              <div className="mdash-rinfo">
                <span className="mdash-rname">{d.name}</span>
                <span className="mdash-rip">{d.ip}</span>
              </div>
              <span className="mdash-rstatus" style={{ color: statusColor(d.status) }}>
                {statusLabel(d.status)}
              </span>
            </div>
          ))}

          {/* WAN */}
          {wanTargets.length > 0 && (
            <>
              <div className="mdash-section-title">Linea Internet / WAN</div>
              {wanTargets.map((w, i) => {
                const down = WAN_DOWN.has(w.status) || w.status === "offline";
                const warn = WAN_WARN.has(w.status);
                const color = down ? "#FF3B30" : warn ? "#FFCC00" : "#34C759";
                return (
                  <div key={i} className="mdash-row" data-testid={`mobile-wan-${c.id}-${i}`}>
                    <span className={`mdash-rdot ${down ? "pulse" : ""}`} style={{ background: color }} />
                    <div className="mdash-rinfo">
                      <span className="mdash-rname">{w.label || w.device_type || "WAN"}</span>
                      {w.ip && <span className="mdash-rip">{w.ip}</span>}
                    </div>
                    {w.latency_ms != null
                      ? <span className="mdash-rstatus" style={{ color: w.latency_ms > 100 ? "#FFCC00" : "#34C759" }}>{w.latency_ms}ms</span>
                      : <span className="mdash-rstatus" style={{ color }}>{down ? "GIÙ" : warn ? "!" : "OK"}</span>}
                  </div>
                );
              })}
            </>
          )}

          {/* Alert attivi */}
          {recentAlerts.length > 0 && (
            <>
              <div className="mdash-section-title">Alert attivi ({alerts.total || recentAlerts.length})</div>
              {recentAlerts.map((a, i) => (
                <div key={i} className="mdash-row" data-testid={`mobile-alert-${c.id}-${i}`}>
                  <span className="mdash-rdot" style={{ background: SEV_COLOR[a.severity] || SEV_COLOR.low }} />
                  <div className="mdash-rinfo">
                    <span className="mdash-rname">{a.title || "Alert"}</span>
                    {a.device_name && <span className="mdash-rip">{a.device_name}</span>}
                  </div>
                  <span className="mdash-rstatus" style={{ color: SEV_COLOR[a.severity] || SEV_COLOR.low }}>
                    {(a.severity || "").toUpperCase()}
                  </span>
                </div>
              ))}
            </>
          )}

          <button className="mdash-open-full" onClick={() => navigate("/network-status")} data-testid={`mobile-client-full-${c.id}`}>
            Apri dettaglio completo
          </button>
        </div>
      )}
    </div>
  );
}
