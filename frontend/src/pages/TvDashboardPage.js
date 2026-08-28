import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import axios from "axios";
import "./TvDashboard.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_INTERVAL = 5000;
const POPUP_TTL_MS = 30000;

/* ---------- Audio alarm + popup criticals ---------- */
function useAlarmSystem() {
  const audioCtxRef = useRef(null);
  const prevRef = useRef({ vitalKeys: new Set(), bkKeys: new Set(), primed: false });
  const [soundOn, setSoundOn] = useState(false);
  const [popups, setPopups] = useState([]);
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
      if (fresh.some(p => p.client === client && p.title === title)) return fresh;
      return [...fresh, { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, kind, client, title, ts: Date.now() }].slice(-3);
    });
  }, []);
  const dismiss = useCallback((id) => setPopups(prev => prev.filter(p => p.id !== id)), []);
  const check = useCallback((data) => {
    if (!data) return;
    const p = prevRef.current;
    const vitalKeys = new Set();
    const bkKeys = new Set();
    const wanKeys = new Set();
    const sondaKeys = new Set();
    (data.clients || []).forEach(c => {
      (c.vital_down || []).forEach(v => vitalKeys.add(`${c.id}:${v.ip}`));
      if (c.backup && (c.backup.failed || 0) > 0) bkKeys.add(`${c.id}:bk`);
      (c.wan_targets || []).filter(w => w.status === "offline").forEach(w => wanKeys.add(`${c.id}:${w.public_ip}`));
      if (c.connector_online === false) sondaKeys.add(c.id);
    });
    const ispKeys = new Set((data.isp_outages || []).map(o => o.id));
    const secKeys = new Set((data.security_incidents || []).map(s => s.id));
    const newDevKeys = new Set((data.new_devices || []).map(d => d.id));
    if (!p.primed) { prevRef.current = { vitalKeys, bkKeys, wanKeys, sondaKeys, ispKeys, secKeys, newDevKeys, primed: true }; return; }
    const has = (set, k) => (set || new Set()).has(k);
    let any = false;
    (data.clients || []).forEach(c => {
      (c.vital_down || []).forEach(v => {
        if (!has(p.vitalKeys, `${c.id}:${v.ip}`)) { pushPopup("off", c.name, `VITALE DOWN — ${v.name || v.ip}`); any = true; }
      });
      (c.wan_targets || []).filter(w => w.status === "offline").forEach(w => {
        if (!has(p.wanKeys, `${c.id}:${w.public_ip}`)) { pushPopup("off", c.name, `WAN OFFLINE — ${w.label || w.public_ip}`); any = true; }
      });
      if (c.backup && (c.backup.failed || 0) > 0 && !has(p.bkKeys, `${c.id}:bk`)) {
        pushPopup("crit", c.name, `BACKUP FALLITO — ${c.backup.failed} VM`); any = true;
      }
      if (c.connector_online === false && !has(p.sondaKeys, c.id)) {
        pushPopup("off", c.name, `SONDA OFFLINE — cliente non monitorato`); any = true;
      }
    });
    (data.isp_outages || []).forEach(o => {
      if (!has(p.ispKeys, o.id)) { pushPopup("crit", (o.clients || []).slice(0, 3).join(", ") || "Più clienti", `GUASTO OPERATORE — ${o.title}`); any = true; }
    });
    (data.security_incidents || []).forEach(s => {
      if (!has(p.secKeys, s.id)) { pushPopup("crit", s.client_name, `SICUREZZA — ${s.title}`); any = true; }
    });
    (data.new_devices || []).forEach(d => {
      if (!has(p.newDevKeys, d.id)) { pushPopup("new", d.client_name, `NUOVO DISPOSITIVO — ${d.vendor} (${d.mac})`); any = true; }
    });
    if (any && soundOn) { beep(880, 0.28, 3, "sawtooth"); setTimeout(() => beep(620, 0.28, 3, "square"), 200); }
    prevRef.current = { vitalKeys, bkKeys, wanKeys, sondaKeys, ispKeys, secKeys, newDevKeys, primed: true };
  }, [soundOn, beep, pushPopup]);
  useEffect(() => {
    if (popups.length === 0) return;
    const t = setInterval(() => setPopups(prev => prev.filter(p => Date.now() - p.ts < POPUP_TTL_MS)), 1000);
    return () => clearInterval(t);
  }, [popups.length]);
  const testAlarm = useCallback(() => {
    pushPopup("off", "TEST · Cliente Demo", "VITALE DOWN — SRV-DC01");
    if (soundOn) { beep(880, 0.28, 3, "sawtooth"); setTimeout(() => beep(620, 0.28, 3, "square"), 200); }
  }, [pushPopup, soundOn, beep]);
  return { soundOn, init, check, popups, dismiss, testAlarm };
}

/* ---------- Client issue model (SOLO vitali / WAN / backup) ---------- */
function issues(c) {
  const vital = c.vital_down || [];
  const wan = c.wan_targets || [];
  const wanOffline = wan.filter(w => w.status === "offline");
  const wanDegraded = wan.filter(w => w.status === "degraded");
  const bk = c.backup || null;
  const bkFail = bk ? (bk.failed || 0) : 0;
  const bkMiss = bk ? (bk.missing || 0) : 0;
  const bkWarn = bk ? (bk.warning || 0) : 0;
  const crit = vital.length > 0 || wanOffline.length > 0 || bkFail > 0;
  const warn = wanDegraded.length > 0 || bkMiss > 0 || bkWarn > 0;
  const has = crit || warn;
  const score = vital.length * 100 + wanOffline.length * 60 + bkFail * 40 + bkMiss * 15 + wanDegraded.length * 10 + bkWarn * 5;
  return { vital, wan, wanOffline, wanDegraded, bk, bkFail, bkMiss, bkWarn, crit, warn, has, score };
}

const WAN_COLOR = { online: "#22c55e", filtered: "#eab308", degraded: "#eab308", offline: "#ef4444", unknown: "#6b7280" };
const WAN_LABEL = { online: "OK", filtered: "FILTRATA", degraded: "DEGRADATA", offline: "OFFLINE", unknown: "N/D" };

export default function TvDashboardPage() {
  const [data, setData] = useState(null);
  const [clock, setClock] = useState(new Date());
  const { soundOn, init, check, popups, dismiss, testAlarm } = useAlarmSystem();

  useEffect(() => {
    load();
    const a = setInterval(load, REFRESH_INTERVAL);
    const b = setInterval(() => setClock(new Date()), 1000);
    return () => { clearInterval(a); clearInterval(b); };
  }, []);
  useEffect(() => { if (data) check(data); }, [data, check]);
  const load = () => axios.get(`${API}/tv/dashboard`).then(r => setData(r.data)).catch(() => {});

  const clients = useMemo(() => {
    if (!data?.clients) return [];
    return data.clients.map(c => ({ ...c, _i: issues(c) }))
      .filter(c => c._i.has)
      .sort((a, b) => b._i.score - a._i.score);
  }, [data]);

  const allClients = useMemo(() => {
    if (!data?.clients) return [];
    const rank = { crit: 0, warn: 1, ok: 2 };
    return data.clients.map(c => {
      const i = issues(c);
      const lvl = i.crit ? "crit" : i.warn ? "warn" : "ok";
      return { ...c, _i: i, _lvl: lvl };
    }).sort((a, b) => (rank[a._lvl] - rank[b._lvl]) || a.name.localeCompare(b.name));
  }, [data]);

  const totals = useMemo(() => {
    let vital = 0, wanOff = 0, bkFail = 0, bkMiss = 0;
    (data?.clients || []).forEach(c => {
      const i = issues(c);
      vital += i.vital.length; wanOff += i.wanOffline.length; bkFail += i.bkFail; bkMiss += i.bkMiss;
    });
    return { vital, wanOff, bkFail, bkMiss, clientsIssue: clients.length };
  }, [data, clients.length]);

  const hasCrit = clients.some(c => c._i.crit);

  if (!data) return <div className="tv-boot" onClick={init}><div className="tv-boot-spin" /><p>CONNESSIONE AD ARGUS…</p></div>;

  return (
    <div className="tvx" data-testid="tv-dashboard" onClick={!soundOn ? init : undefined}>
      {/* Critical popups */}
      {popups.length > 0 && (
        <div className="tv-popups" data-testid="tv-critical-popups">
          {popups.map(pp => (
            <div key={pp.id} className={`tv-popup tv-popup-${pp.kind}`} data-testid="tv-critical-popup">
              <button className="tv-popup-x" onClick={(e) => { e.stopPropagation(); dismiss(pp.id); }} data-testid="tv-popup-dismiss" aria-label="Chiudi">×</button>
              <div className="tv-popup-badge">{
                pp.title.startsWith("WAN") ? "SEDE / WAN OFFLINE"
                : pp.title.startsWith("BACKUP") ? "BACKUP FALLITO"
                : pp.title.startsWith("SONDA") ? "SONDA OFFLINE"
                : pp.title.startsWith("GUASTO OPERATORE") ? "GUASTO OPERATORE (ISP)"
                : pp.title.startsWith("SICUREZZA") ? "INCIDENTE SICUREZZA"
                : "DISPOSITIVO VITALE OFFLINE"
              }</div>
              <div className="tv-popup-client" data-testid="tv-popup-client">{pp.client}</div>
              <div className="tv-popup-title" data-testid="tv-popup-title">{pp.title}</div>
            </div>
          ))}
        </div>
      )}

      {/* Header */}
      <header className="tvx-head">
        <div className="tvx-brand">
          <div className="tvx-logo">A</div>
          <div>
            <div className="tvx-title">ARGUS</div>
            <div className="tvx-sub">NOC · LIVE WALLBOARD</div>
          </div>
        </div>
        <div className="tvx-stats">
          <Stat n={totals.vital} label="VITALI DOWN" tone={totals.vital ? "crit" : "ok"} />
          <Stat n={totals.wanOff} label="WAN OFFLINE" tone={totals.wanOff ? "crit" : "ok"} />
          <Stat n={totals.bkFail} label="BACKUP FALLITI" tone={totals.bkFail ? "crit" : "ok"} />
          <Stat n={totals.bkMiss} label="BACKUP MANCANTI" tone={totals.bkMiss ? "warn" : "ok"} />
          <Stat n={totals.clientsIssue} label="CLIENTI COINVOLTI" tone={totals.clientsIssue ? "warn" : "ok"} />
        </div>
        <div className="tvx-right">
          <span className={`tvx-live ${hasCrit ? "crit" : "ok"}`}>● {hasCrit ? "ATTENZIONE" : "REGOLARE"}</span>
          {data.vital_repoll && data.vital_repoll.count > 0 && data.vital_repoll.last && (
            <div className="tvx-repoll" data-testid="tv-vital-repoll" title={`Re-poll SNMP forzato ogni 2 min su ${data.vital_repoll.count} dispositivi vitali`}>
              <span className="tvx-repoll-dot" />
              <span className="tvx-repoll-lbl">RE-POLL VITALI</span>
              <span className="tvx-repoll-time">
                {new Date(data.vital_repoll.last).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}
                <em> · {data.vital_repoll.time_ago}</em>
              </span>
            </div>
          )}
          <button className="tvx-btn" onClick={(e) => { e.stopPropagation(); init(); }} data-testid="tv-sound-toggle">{soundOn ? "♪ ON" : "♪ OFF"}</button>
          <button className="tvx-btn" onClick={(e) => { e.stopPropagation(); testAlarm(); }} data-testid="tv-test-alarm">TEST</button>
          <div className="tvx-clock">
            <div className="tvx-time">{clock.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</div>
            <div className="tvx-date">{clock.toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "short" }).toUpperCase()}</div>
          </div>
        </div>
      </header>

      {/* Banner PERSISTENTE outage operatore + sicurezza (solo eventi di oggi) */}
      {((data.isp_outages || []).length > 0 || (data.security_incidents || []).length > 0) && (
        <div className="tvx-isp-banner" data-testid="tv-isp-banner">
          {(data.isp_outages || []).map(o => (
            <div key={o.id} className="tvx-isp-row" data-testid="tv-isp-banner-row">
              <span className="tvx-isp-dot" />
              <span className="tvx-isp-tag">GUASTO OPERATORE</span>
              <span className="tvx-isp-name">{o.title}</span>
              {(o.clients || []).length > 0 && (
                <span className="tvx-isp-clients">Clienti a rischio: {(o.clients || []).join(", ")}</span>
              )}
            </div>
          ))}
          {(data.security_incidents || []).map(s => (
            <div key={s.id} className="tvx-isp-row tvx-sec-row" data-testid="tv-sec-banner-row">
              <span className="tvx-isp-dot" />
              <span className="tvx-isp-tag tvx-sec-tag">SICUREZZA</span>
              <span className="tvx-isp-name">{s.title}</span>
              <span className="tvx-isp-clients">{s.client_name}</span>
            </div>
          ))}
        </div>
      )}

      {/* Roster: TUTTE le aziende (verde=ok, rosso=down, giallo=warning) */}
      <section className="tvx-roster" data-testid="tv-roster">
        <div className="tvx-roster-h">
          <span>TUTTE LE AZIENDE ({allClients.length})</span>
          <span className="tvx-legend">
            <i className="ok" /> OK <i className="warn" /> Warning <i className="crit" /> Down
          </span>
        </div>
        <ul className="tvx-roster-list">
          {allClients.map(c => (
            <li key={c.id} className={`tvx-roster-item ${c._lvl}`} data-testid="tv-roster-item" title={c.name}>
              <span className="dot" />
              <span className="nm">{c.name}</span>
              {c._lvl !== "ok" && (
                <span className="tag">
                  {c._i.vital.length ? `${c._i.vital.length} vitali` : c._i.wanOffline.length ? "WAN" : c._i.bkFail ? `${c._i.bkFail} backup` : c._i.bkMiss ? "backup" : "warn"}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* Grid dettaglio problemi */}
      {clients.length === 0 ? (
        <div className="tvx-empty">
          <div className="tvx-empty-icon">✓</div>
          <div>Nessun problema attivo su vitali, WAN o backup. Tutto regolare.</div>
        </div>
      ) : (
        <div className="tvx-grid" data-testid="tv-client-grid">
          {clients.map(c => {
            const i = c._i;
            return (
              <div key={c.id} className={`tvx-card ${i.crit ? "crit" : "warn"}`} data-testid="tv-client-card">
                <div className="tvx-card-head">
                  <span className="tvx-card-name" data-testid="tv-client-name">{c.name}</span>
                  {!c.connector_online && <span className="tvx-badge nosonda">NO SONDA</span>}
                </div>

                {/* VITALI DOWN */}
                <div className="tvx-sec">
                  <div className="tvx-sec-h">DISPOSITIVI VITALI</div>
                  {i.vital.length === 0 ? (
                    <div className="tvx-ok">✓ Tutti i vitali operativi</div>
                  ) : (
                    <div className="tvx-list">
                      {i.vital.slice(0, 6).map((v, k) => (
                        <div key={k} className="tvx-item crit" data-testid="tv-vital-down">
                          <span className="dot" /> <b>{v.name || v.ip}</b>
                          <span className="tvx-when">giù da {v.down_since || "?"}</span>
                        </div>
                      ))}
                      {i.vital.length > 6 && <div className="tvx-more">+{i.vital.length - 6} altri</div>}
                    </div>
                  )}
                </div>

                {/* WAN */}
                <div className="tvx-sec">
                  <div className="tvx-sec-h">WAN</div>
                  {i.wan.length === 0 ? (
                    <div className="tvx-muted">Non configurata</div>
                  ) : (
                    <div className="tvx-wan">
                      {i.wan.map((w, k) => (
                        <span key={k} className="tvx-wan-pill" data-testid="tv-wan-pill">
                          <span className="dot" style={{ background: WAN_COLOR[w.status] || WAN_COLOR.unknown }} />
                          {w.label || w.device_type || "WAN"}
                          <b style={{ color: WAN_COLOR[w.status] || WAN_COLOR.unknown }}>{WAN_LABEL[w.status] || w.status?.toUpperCase()}</b>
                          {w.nebula_monitored && <span className="tvx-neb" title="Stato dal cloud Nebula">NEBULA</span>}
                          {w.latency_ms != null && !w.nebula_monitored && <span className="tvx-lat">{Math.round(w.latency_ms)}ms</span>}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* BACKUP */}
                <div className="tvx-sec">
                  <div className="tvx-sec-h" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    BACKUP
                    {i.bk?.source && (
                      <span
                        data-testid={`tv-backup-tag-${i.bk.source}`}
                        style={{
                          fontSize: 9, fontWeight: 800, padding: "1px 5px", borderRadius: 3,
                          color: i.bk.source === "vm" ? "#c4b5fd" : "#7dd3fc",
                          background: i.bk.source === "vm" ? "rgba(167,139,250,0.2)" : "rgba(56,189,248,0.2)",
                        }}
                      >
                        {i.bk.source === "vm" ? "VM" : "365"}
                      </span>
                    )}
                  </div>
                  {!i.bk ? (
                    <div className="tvx-muted">Non monitorato</div>
                  ) : (i.bkFail || i.bkMiss || i.bkWarn) ? (
                    <div className="tvx-bk">
                      {i.bkFail > 0 && <span className="tvx-chip crit" data-testid="tv-backup-fail">{i.bkFail} FALLITI</span>}
                      {i.bkMiss > 0 && <span className="tvx-chip warn">{i.bkMiss} MANCANTI</span>}
                      {i.bkWarn > 0 && <span className="tvx-chip warn">{i.bkWarn} WARNING</span>}
                      <span className="tvx-bk-tot">/ {i.bk.total} {i.bk.source === "vm" ? "VM" : "job"}</span>
                    </div>
                  ) : (
                    <div className="tvx-ok">✓ {i.bk.ok}/{i.bk.total} {i.bk.source === "vm" ? "VM" : "job"} ok</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Stat({ n, label, tone }) {
  return (
    <div className={`tvx-stat ${tone}`}>
      <div className="tvx-stat-n">{n}</div>
      <div className="tvx-stat-l">{label}</div>
    </div>
  );
}
