import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import axios from "axios";
import "./TvDashboard.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_INTERVAL = 15000;
const POPUP_TTL_MS = 30000; // popup allarmi critici a schermo per 30s

/* ---------- Audio alarm + popup criticals ---------- */
function useAlarmSystem() {
  const audioCtxRef = useRef(null);
  const prevRef = useRef({ offIPs: new Set(), altIDs: new Set(), primed: false });
  const [soundOn, setSoundOn] = useState(false);
  const [popups, setPopups] = useState([]); // {id, kind, client, title, ts}
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
      g.gain.setValueAtTime(0.16, now + i * (d + 0.12));
      g.gain.exponentialRampToValueAtTime(0.001, now + i * (d + 0.12) + d);
      o.connect(g); g.connect(ctx.destination);
      o.start(now + i * (d + 0.12)); o.stop(now + i * (d + 0.12) + d);
    }
  }, []);
  const pushPopup = useCallback((kind, client, title) => {
    setPopups(prev => {
      const fresh = prev.filter(p => Date.now() - p.ts < POPUP_TTL_MS);
      // dedup: stesso client+titolo già a schermo
      if (fresh.some(p => p.client === client && p.title === title)) return fresh;
      const next = [...fresh, { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, kind, client, title, ts: Date.now() }];
      return next.slice(-3); // max 3 popup contemporanei
    });
  }, []);
  const dismiss = useCallback((id) => setPopups(prev => prev.filter(p => p.id !== id)), []);
  const check = useCallback((data) => {
    if (!data) return;
    const p = prevRef.current;
    const cO = new Set((data.offline_devices || []).map(d => d.ip));
    const cA = new Set((data.alerts || []).filter(a => a.severity === "critical").map(a => a.id));
    // Primo giro: solo baseline, niente popup/suono (evita valanga all'apertura)
    if (!p.primed) {
      prevRef.current = { offIPs: cO, altIDs: cA, primed: true };
      return;
    }
    const newOff = (data.offline_devices || []).filter(d => !p.offIPs.has(d.ip));
    const newCrit = (data.alerts || []).filter(a => a.severity === "critical" && !p.altIDs.has(a.id));
    let any = false;
    newCrit.forEach(a => { pushPopup("crit", a.client_name || "—", a.title || a.device_name || "Allarme critico"); any = true; });
    newOff.forEach(d => { pushPopup("off", d.client_name || "—", `${d.name || d.ip} OFFLINE`); any = true; });
    if (any && soundOn) {
      // sirena: alterna due toni, ripetuta
      beep(880, 0.28, 3, "sawtooth");
      setTimeout(() => beep(620, 0.28, 3, "square"), 200);
    }
    prevRef.current = { offIPs: cO, altIDs: cA, primed: true };
  }, [soundOn, beep, pushPopup]);
  // Auto-dismiss dopo POPUP_TTL_MS
  useEffect(() => {
    if (popups.length === 0) return;
    const t = setInterval(() => {
      setPopups(prev => prev.filter(p => Date.now() - p.ts < POPUP_TTL_MS));
    }, 1000);
    return () => clearInterval(t);
  }, [popups.length]);
  const testAlarm = useCallback(() => {
    pushPopup("crit", "TEST · Cliente Demo", "PROBLEMA DI DORSALE: SWITCH01 → SWITCH02");
    if (soundOn) { beep(880, 0.28, 3, "sawtooth"); setTimeout(() => beep(620, 0.28, 3, "square"), 200); }
  }, [pushPopup, soundOn, beep]);
  return { soundOn, init, check, popups, dismiss, testAlarm };
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
  const { soundOn, init, check, popups, dismiss, testAlarm } = useAlarmSystem();

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

  const problemClients = useMemo(() => sortedClients.filter(c => c._s.level !== "ok"), [sortedClients]);
  const okClients = useMemo(() => sortedClients.filter(c => c._s.level === "ok")
    .sort((a, b) => a.name.localeCompare(b.name)), [sortedClients]);

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
      {/* ===== POPUP GRANDI CENTRALI — allarmi critici (auto 30s) ===== */}
      {popups.length > 0 && (
        <div className="tv-popups" data-testid="tv-critical-popups">
          {popups.map(pp => (
            <div key={pp.id} className={`tv-popup tv-popup-${pp.kind}`} data-testid="tv-critical-popup">
              <button className="tv-popup-x" onClick={(e) => { e.stopPropagation(); dismiss(pp.id); }} data-testid="tv-popup-dismiss" aria-label="Chiudi">×</button>
              <div className="tv-popup-badge">{pp.kind === "off" ? "DISPOSITIVO OFFLINE" : "ALLARME CRITICO"}</div>
              <div className="tv-popup-client" data-testid="tv-popup-client">{pp.client}</div>
              <div className="tv-popup-title" data-testid="tv-popup-title">{pp.title}</div>
              <div className="tv-popup-foot">
                <span className="tv-popup-pulse" />
                {new Date(pp.ts).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </div>
            </div>
          ))}
        </div>
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
          <button className="tv-snd tv-test" onClick={(e) => { e.stopPropagation(); if (!soundOn) init(); testAlarm(); }} data-testid="tv-test-alarm" title="Prova popup + suono allarme">
            TEST
          </button>
          <div className="tv-time" data-testid="tv-clock">
            <span className="tv-time-h">{clock.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</span>
            <span className="tv-time-d">{clock.toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "short" })}</span>
          </div>
        </div>
      </header>

      {/* ===== CLIENT AREA (triage: problemi in evidenza, operativi densi) ===== */}
      <main className="tv-body" data-testid="tv-clients-grid">
        {problemClients.length > 0 && (
          <section className="tv-sec tv-sec-prob">
            <div className="tv-sec-h tv-sec-h-prob">
              <span className="tv-sec-dot tv-sec-dot-prob" /> DA GESTIRE <b>{problemClients.length}</b>
              <span className="tv-sec-hint">clienti con anomalie · in ordine di gravità</span>
            </div>
            <div className="tv-prob-grid">
              {problemClients.map(c => (
                <ProblemCard key={c.id} c={c} alerts={alertsByClient[c.id] || []} />
              ))}
            </div>
          </section>
        )}

        <section className="tv-sec tv-sec-ok">
          <div className="tv-sec-h tv-sec-h-ok">
            <span className="tv-sec-dot tv-sec-dot-ok" /> OPERATIVI <b>{okClients.length}</b>
          </div>
          {okClients.length > 0 ? (
            <div className="tv-ok-grid">
              {okClients.map(c => (
                <div key={c.id} className="tv-ok-chip" data-testid={`tv-client-${c.id}`}
                     title={`${c.name} · ${c.online}/${c.total_devices} online`}>
                  <span className="tv-ok-dot" />
                  <span className="tv-ok-name">{c.name}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="tv-ok-none">Nessun cliente pienamente operativo</div>
          )}
        </section>

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

/* ---------- Problem card (compatta, triage-first) ---------- */
function ProblemCard({ c, alerts }) {
  const s = c._s;
  const color = s.level === "crit" ? "#ff4136" : "#ffbf00";
  const wanList = c.wan_targets || [];
  const wan = wanList.find(w => w.status === "offline") || wanList.find(w => w.status && w.status !== "online") || wanList[0];
  const topAlert = alerts.find(a => a.severity === "critical") || alerts.find(a => a.severity === "high");

  return (
    <div className={`tv-pcard tv-pcard-${s.level} ${s.level === "crit" ? "tv-pcard-flash" : ""}`}
         data-testid={`tv-client-${c.id}`} style={{ "--pc": color }}>
      <div className="tv-pcard-top">
        <span className="tv-pcard-name" title={c.name}>{c.name}</span>
        {!c.connector_online && <span className="tv-pcard-nosonda">NO SONDA</span>}
      </div>

      <div className="tv-pcard-mid">
        <div className={`tv-pcard-headline tv-headline-${s.level}`} data-testid={`tv-headline-${c.id}`}>{s.headline}</div>
        <div className="tv-pcard-counts">
          <span><b style={{ color: "#2fd85f" }}>{c.online}</b> ON</span>
          <span><b style={{ color: c.offline > 0 ? "#ff4136" : "#4a4a55" }}>{c.offline}</b> OFF</span>
          <span><b style={{ color: c.alert_count > 0 ? "#ffbf00" : "#4a4a55" }}>{c.alert_count}</b> AL</span>
          {c.critical_alerts > 0 && <span><b style={{ color: "#ff4136" }}>{c.critical_alerts}</b> CR</span>}
        </div>
      </div>

      {wan && (
        <div className={`tv-pcard-wan tv-wan-${wan.status}`} data-testid={`tv-tile-wan-${c.id}`}>
          <span className={`tv-wan-dot tv-wan-dot-${wan.status}`} />
          <span className="tv-pcard-wan-txt">WAN {wan.status === "offline" ? "DOWN" : (wan.status === "online" ? "OK" : (wan.status || "").toUpperCase())}</span>
          {wan.latency_ms != null && (
            <span className="tv-pcard-lat" style={{ color: wan.latency_ms > 100 ? "#ff4136" : wan.latency_ms > 50 ? "#ffbf00" : "#2fd85f" }}>{wan.latency_ms}ms</span>
          )}
        </div>
      )}

      {topAlert && (
        <div className="tv-pcard-alert" data-testid={`tv-tile-topalert-${c.id}`}>
          <span className={`tv-toppb-sev tv-toppb-${topAlert.severity}`}>{topAlert.severity === "critical" ? "CRIT" : "HIGH"}</span>
          <span className="tv-pcard-alert-msg">{topAlert.title}</span>
        </div>
      )}
    </div>
  );
}
