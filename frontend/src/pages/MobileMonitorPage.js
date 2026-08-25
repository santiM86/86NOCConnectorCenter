import { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";
import "./MobileMonitor.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOKEN_KEY = "argus_mobile_token";
const REVOKED_KEY = "argus_mobile_revoked";
const REFRESH_MS = 8000;

const WAN_COLOR = { online: "#22c55e", filtered: "#eab308", degraded: "#eab308", offline: "#ef4444", unknown: "#7688a0" };
const WAN_LABEL = { online: "OK", filtered: "FILTRATA", degraded: "DEGRADATA", offline: "OFFLINE", unknown: "N/D" };

function issues(c) {
  const vital = c.vital_down || [];
  const wan = c.wan_targets || [];
  const wanOffline = wan.filter((w) => w.status === "offline");
  const wanDegraded = wan.filter((w) => w.status === "degraded");
  const bk = c.backup || null;
  const bkFail = bk ? bk.failed || 0 : 0;
  const bkMiss = bk ? bk.missing || 0 : 0;
  const bkWarn = bk ? bk.warning || 0 : 0;
  const crit = vital.length > 0 || wanOffline.length > 0 || bkFail > 0 || c.connector_online === false;
  const warn = wanDegraded.length > 0 || bkMiss > 0 || bkWarn > 0;
  const lvl = crit ? "crit" : warn ? "warn" : "ok";
  const score = vital.length * 100 + wanOffline.length * 60 + bkFail * 40 + (c.connector_online === false ? 55 : 0) + bkMiss * 15 + wanDegraded.length * 10 + bkWarn * 5;
  return { vital, wan, wanOffline, wanDegraded, bk, bkFail, bkMiss, bkWarn, crit, warn, lvl, score };
}

export default function MobileMonitorPage() {
  const [token, setTokenState] = useState(null);
  const [data, setData] = useState(null);
  const [tech, setTech] = useState(null);
  const [error, setError] = useState(() => (localStorage.getItem(REVOKED_KEY) ? "revoked" : null));
  const [selected, setSelected] = useState(null); // client id
  const [clock, setClock] = useState(new Date());
  // Suggerimento iOS "Aggiungi alla Home" (solo Safari iOS, non gia' installata)
  const [showA2HS, setShowA2HS] = useState(false);
  useEffect(() => {
    const ua = window.navigator.userAgent || "";
    const isIos = /iphone|ipad|ipod/i.test(ua);
    const isStandalone = window.navigator.standalone === true ||
      window.matchMedia?.("(display-mode: standalone)")?.matches;
    const dismissed = localStorage.getItem("argus_mobile_a2hs_dismissed");
    if (isIos && !isStandalone && !dismissed) setShowA2HS(true);
  }, []);

  // 1) Cattura il token dall'URL e lo persiste. Su iOS la web-app "aggiunta alla
  //    Home" (standalone) ha memoria SEPARATA da Safari: per non richiedere
  //    l'accesso a ogni avvio teniamo il token in 3 posti — hash dell'URL (così
  //    l'icona in Home lo cattura), localStorage e un COOKIE a lunga durata
  //    (condiviso tra Safari e la web-app). Lettura: hash → localStorage → cookie.
  useEffect(() => {
    const getCookie = (k) => {
      const m = document.cookie.match(new RegExp("(?:^|; )" + k + "=([^;]+)"));
      return m ? decodeURIComponent(m[1]) : null;
    };
    let t = null;
    const hm = (window.location.hash || "").match(/[#&]t=([^&]+)/);
    if (hm) t = decodeURIComponent(hm[1]);
    if (!t) t = new URLSearchParams(window.location.search).get("t");
    if (t) {
      localStorage.setItem(TOKEN_KEY, t);
      localStorage.removeItem(REVOKED_KEY);
      document.cookie = `${TOKEN_KEY}=${encodeURIComponent(t)}; path=/; max-age=31536000; SameSite=Lax`;
      setError(null);
      // NON rimuoviamo l'hash: se l'utente aggiunge alla Home ora, l'icona
      // salverà /m#t=TOKEN e la web-app partirà già autenticata.
      setTokenState(t);
    } else {
      setTokenState(localStorage.getItem(TOKEN_KEY) || getCookie(TOKEN_KEY));
    }
  }, []);

  const load = useCallback(async (tk) => {
    try {
      const [dash, me] = await Promise.all([
        axios.get(`${API}/mobile/dashboard`, { headers: { "X-Mobile-Token": tk } }),
        tech ? Promise.resolve({ data: tech }) : axios.get(`${API}/mobile/me`, { headers: { "X-Mobile-Token": tk } }),
      ]);
      setData(dash.data);
      if (!tech && me?.data) setTech(me.data);
      setError(null);
    } catch (e) {
      if (e.response?.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.setItem(REVOKED_KEY, "1");
        document.cookie = `${TOKEN_KEY}=; path=/; max-age=0`;
        setError("revoked");
        setTokenState(null);
      }
    }
  }, [tech]);

  useEffect(() => {
    if (!token) return;
    load(token);
    const a = setInterval(() => load(token), REFRESH_MS);
    const b = setInterval(() => setClock(new Date()), 1000);
    return () => { clearInterval(a); clearInterval(b); };
  }, [token, load]);

  const clients = useMemo(() => {
    if (!data?.clients) return [];
    const rank = { crit: 0, warn: 1, ok: 2 };
    return data.clients
      .map((c) => ({ ...c, _i: issues(c) }))
      .sort((a, b) => (rank[a._i.lvl] - rank[b._i.lvl]) || (b._i.score - a._i.score) || a.name.localeCompare(b.name));
  }, [data]);

  const totals = useMemo(() => {
    let vital = 0, wanOff = 0, bkFail = 0, involved = 0;
    (data?.clients || []).forEach((c) => {
      const i = issues(c);
      vital += i.vital.length; wanOff += i.wanOffline.length; bkFail += i.bkFail;
      if (i.crit || i.warn) involved += 1;
    });
    return { vital, wanOff, bkFail, involved };
  }, [data]);

  const hasCrit = clients.some((c) => c._i.crit);
  const sel = selected ? clients.find((c) => c.id === selected) : null;
  const selAlerts = sel ? (data?.alerts || []).filter((a) => a.client_id === sel.id) : [];

  // --- GATE: nessun token o revocato -------------------------------------
  if (!token) {
    return (
      <div className="mm-boot" data-testid="mobile-gate">
        <div className="logo">A</div>
        <div className="big">ARGUS · Accesso Mobile</div>
        {error === "revoked" ? (
          <div className="sub">Questo telefono è stato <b>scollegato</b>. Chiedi un nuovo QR dalla tua area ARGUS
            (Impostazioni → Accesso Mobile) e riscansionalo.</div>
        ) : (
          <div className="sub">Per agganciare il telefono, apri <b>ARGUS → Impostazioni → Accesso Mobile</b> dal PC
            e inquadra il tuo QR personale. Da quel momento resterai connesso senza password.</div>
        )}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mm-boot" data-testid="mobile-loading">
        <div className="mm-spin" />
        <div className="sub">Connessione ad ARGUS…</div>
      </div>
    );
  }

  return (
    <div className="mm" data-testid="mobile-monitor">
      <header className="mm-head">
        <div className="mm-logo">A</div>
        <div>
          <div className="mm-htitle">ARGUS</div>
          <div className="mm-hsub">NOC · MOBILE</div>
        </div>
        <div className="mm-hright">
          <span className={`mm-live ${hasCrit ? "crit" : "ok"}`}>● {hasCrit ? "ATTENZIONE" : "REGOLARE"}</span>
          <div className="mm-tech" data-testid="mobile-tech-name">{tech?.name || "Tecnico"} · {clock.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</div>
          {data.vital_repoll?.count > 0 && data.vital_repoll?.last && (
            <div className="mm-repoll"><i />re-poll vitali {new Date(data.vital_repoll.last).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</div>
          )}
        </div>
      </header>

      <div className="mm-scroll">
        {/* Summary */}
        <div className="mm-chips">
          <div className={`mm-chip ${totals.vital ? "crit" : "ok"}`} data-testid="mobile-chip-vital"><div className="n">{totals.vital}</div><div className="l">Vitali down</div></div>
          <div className={`mm-chip ${totals.wanOff ? "crit" : "ok"}`}><div className="n">{totals.wanOff}</div><div className="l">WAN offline</div></div>
          <div className={`mm-chip ${totals.bkFail ? "crit" : "ok"}`}><div className="n">{totals.bkFail}</div><div className="l">Backup falliti</div></div>
          <div className={`mm-chip ${totals.involved ? "warn" : "ok"}`}><div className="n">{totals.involved}</div><div className="l">Clienti coinvolti</div></div>
        </div>

        {/* Critical banners (oggi) */}
        {((data.isp_outages || []).length > 0 || (data.security_incidents || []).length > 0) && (
          <div className="mm-banner" data-testid="mobile-banner">
            {(data.isp_outages || []).map((o) => (
              <div key={o.id} className="row"><span className="tag">OPERATORE</span><span>{o.title}</span>
                {(o.clients || []).length > 0 && <span className="clients">{(o.clients || []).slice(0, 3).join(", ")}</span>}</div>
            ))}
            {(data.security_incidents || []).map((s) => (
              <div key={s.id} className="row"><span className="tag sec">SICUREZZA</span><span>{s.title}</span><span className="clients">{s.client_name}</span></div>
            ))}
          </div>
        )}

        {/* Companies */}
        <div className="mm-sec-t">
          <span>Tutte le aziende ({clients.length})</span>
          <span className="mm-legend"><i className="ok" />ok <i className="warn" />warn <i className="crit" />down</span>
        </div>

        {clients.length === 0 ? (
          <div className="mm-empty"><div className="ic">✓</div><div>Nessuna azienda monitorata.</div></div>
        ) : (
          <div className="mm-list">
            {clients.map((c) => (
              <div key={c.id} className={`mm-row ${c._i.lvl}`} data-testid="mobile-client-row" onClick={() => setSelected(c.id)}>
                <span className={`mm-dot ${c._i.lvl}`} />
                <span className="nm">{c.name}</span>
                <span className="tags">
                  {c.connector_online === false && <span className="mm-pill nosonda">NO SONDA</span>}
                  {c._i.vital.length > 0 && <span className="mm-pill crit">{c._i.vital.length} vitali</span>}
                  {c._i.wanOffline.length > 0 && <span className="mm-pill crit">WAN</span>}
                  {c._i.bkFail > 0 && <span className="mm-pill crit">{c._i.bkFail} bk</span>}
                  {c._i.lvl === "warn" && !c._i.crit && <span className="mm-pill warn">warning</span>}
                </span>
                <span className="mm-chev">›</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Suggerimento iOS: aggiungi ARGUS alla Home come app a schermo intero */}
      {showA2HS && (
        <div className="mm-a2hs" data-testid="mobile-a2hs">
          <span className="mm-a2hs-ic">A</span>
          <span className="mm-a2hs-txt">
            Aggiungi ARGUS alla Home: tocca <b>Condividi</b> <span className="mm-a2hs-share">⬆</span> e poi <b>«Aggiungi a Home»</b> <u>da questa pagina</u>. Resterai connesso senza reinserire l'accesso.
          </span>
          <button className="mm-a2hs-x" data-testid="mobile-a2hs-dismiss"
            onClick={() => { localStorage.setItem("argus_mobile_a2hs_dismissed", "1"); setShowA2HS(false); }}>×</button>
        </div>
      )}

      {/* Detail sheet */}
      {sel && (
        <div className="mm-sheet-wrap" onClick={() => setSelected(null)} data-testid="mobile-detail-sheet">
          <div className="mm-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="mm-sheet-grip" />
            <div className="mm-sheet-head">
              <span className={`mm-dot ${sel._i.lvl}`} />
              <span className="nm" data-testid="mobile-detail-name">{sel.name}</span>
              <button className="mm-sheet-x" onClick={() => setSelected(null)} data-testid="mobile-detail-close">×</button>
            </div>
            <div className="mm-sheet-body">
              {/* Stat grid */}
              <div className="mm-block">
                <div className="mm-stat-grid">
                  <div className="mm-stat"><div className="n" style={{ color: "var(--mm-ok)" }}>{sel.online}</div><div className="l">Online</div></div>
                  <div className="mm-stat"><div className="n" style={{ color: sel._i.vital.length ? "var(--mm-crit)" : "var(--mm-txt)" }}>{sel._i.vital.length}</div><div className="l">Vitali giù</div></div>
                  <div className="mm-stat"><div className="n" style={{ color: sel.alert_count ? "var(--mm-warn)" : "var(--mm-txt)" }}>{sel.alert_count || 0}</div><div className="l">Alert</div></div>
                  <div className="mm-stat"><div className="n">{sel.health_pct ?? 0}%</div><div className="l">Salute</div></div>
                </div>
              </div>

              {/* Vitali */}
              <div className="mm-block">
                <div className="mm-block-t">Dispositivi vitali</div>
                {sel.connector_online === false && <div className="mm-item" style={{ borderColor: "rgba(239,68,68,.4)" }}><b style={{ color: "#fca5a5" }}>SONDA OFFLINE</b><span style={{ color: "var(--mm-mut)", fontSize: 11 }}>cliente non monitorato</span></div>}
                {(sel._i.vital || []).length === 0 ? (
                  <div className="mm-ok-line">✓ Tutti i vitali operativi</div>
                ) : sel._i.vital.map((v, k) => (
                  <div key={k} className="mm-item"><span className="mm-dot crit" /><b>{v.name || v.ip}</b><span className="when">giù da {v.down_since || "?"}</span></div>
                ))}
              </div>

              {/* WAN */}
              <div className="mm-block">
                <div className="mm-block-t">WAN / Linee</div>
                {(sel.wan_targets || []).length === 0 ? (
                  <div className="mm-mut-line">Non configurata</div>
                ) : sel.wan_targets.map((w, k) => (
                  <div key={k} className="mm-wan">
                    <span className="mm-dot" style={{ background: WAN_COLOR[w.status] || WAN_COLOR.unknown }} />
                    <span>{w.label || w.device_type || "WAN"}</span>
                    {w.nebula_monitored && <span style={{ fontSize: 8, color: "#38bdf8", fontWeight: 800 }}>NEBULA</span>}
                    {w.latency_ms != null && !w.nebula_monitored && <span style={{ fontSize: 10, color: "var(--mm-mut)" }}>{Math.round(w.latency_ms)}ms</span>}
                    <span className="st" style={{ color: WAN_COLOR[w.status] || WAN_COLOR.unknown }}>{WAN_LABEL[w.status] || (w.status || "").toUpperCase()}</span>
                  </div>
                ))}
              </div>

              {/* Backup */}
              <div className="mm-block">
                <div className="mm-block-t">Backup</div>
                {!sel.backup ? (
                  <div className="mm-mut-line">Non monitorato</div>
                ) : (sel.backup.failed || sel.backup.missing || sel.backup.warning) ? (
                  <div className="mm-item">
                    {sel.backup.failed > 0 && <b style={{ color: "#fca5a5" }}>{sel.backup.failed} falliti</b>}
                    {sel.backup.missing > 0 && <span style={{ color: "#fde68a" }}>{sel.backup.missing} mancanti</span>}
                    {sel.backup.warning > 0 && <span style={{ color: "#fde68a" }}>{sel.backup.warning} warning</span>}
                    <span style={{ marginLeft: "auto", color: "var(--mm-mut)", fontSize: 11 }}>/ {sel.backup.total} VM</span>
                  </div>
                ) : (
                  <div className="mm-ok-line">✓ {sel.backup.ok}/{sel.backup.total} VM ok</div>
                )}
              </div>

              {/* Alert attivi */}
              {selAlerts.length > 0 && (
                <div className="mm-block">
                  <div className="mm-block-t">Alert attivi ({selAlerts.length})</div>
                  {selAlerts.slice(0, 12).map((a, k) => (
                    <div key={k} className="mm-item">
                      <span className="mm-dot" style={{ background: a.severity === "critical" ? "var(--mm-crit)" : a.severity === "high" ? "#f97316" : "var(--mm-warn)" }} />
                      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.title || a.message}</span>
                      <span style={{ fontSize: 10, color: "var(--mm-mut)" }}>{a.time_ago}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
