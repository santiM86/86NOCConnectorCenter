import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Monitor, Globe, ArrowClockwise, X, ShieldCheck, Warning,
  CaretLeft, ArrowSquareOut, House,
} from "@phosphor-icons/react";

/**
 * WebConsoleTabs — modello srcDoc (v2-compatibile, pulito).
 * Il connector restituisce HTML (auto-follow JS redirect + inlining CSS/IMG in v3.2.0+).
 * L'iframe riceve l'HTML via srcDoc. Click/submit intercettati via postMessage.
 * Per device complessi: pulsante "Apri in nuova tab" → usa architettura LIVE proxy.
 */

const WebConsoleContext = createContext(null);

export function useWebConsoleTabs() {
  const ctx = useContext(WebConsoleContext);
  if (!ctx) throw new Error("useWebConsoleTabs must be used within WebConsoleTabsProvider");
  return ctx;
}

export function WebConsoleTabsProvider({ children }) {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [minimized, setMinimized] = useState(false);
  const sessionsRef = useRef([]);
  const abortsRef = useRef({});

  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  const updateSession = useCallback((id, patch) => {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, ...patch } : s));
  }, []);

  const _runSession = useCallback(async (id, clientId, deviceIp, port, path, controller, opts = {}) => {
    const t0 = performance.now();
    const session = sessionsRef.current.find(s => s.id === id);
    const sessionId = session?.sessionId || id;
    const method = opts.method || "GET";
    const body = opts.body || "";
    try {
      const reqRes = await axios.post(
        `${API}/connector/web-proxy/request`,
        {
          client_id: clientId, device_ip: deviceIp,
          port: port || 80, path: path || "/",
          method, session_id: sessionId, body, body_encoding: "text",
          headers: opts.contentType ? { "Content-Type": opts.contentType } : {},
        },
        { signal: controller.signal }
      );
      const requestId = reqRes.data?.request_id;
      if (!requestId) throw new Error("Backend senza request_id");
      updateSession(id, { progress: 30, requestId, sessionId });

      const resp = await axios.get(
        `${API}/connector/web-proxy/response/${requestId}?wait=25`,
        { signal: controller.signal, timeout: 30000 }
      );
      const loadTime = performance.now() - t0;

      if (resp.data.status !== "completed" || !resp.data.response) {
        let hint = "Verifica che il servizio <b>86NocConnector</b> sia attivo e il dispositivo raggiungibile.";
        let errorLabel = "Connettore non risponde";
        try {
          const st = await axios.get(`${API}/connector/status`);
          const row = Array.isArray(st.data) ? st.data.find(r => r.client_id === clientId) : null;
          if (row) {
            const v = row.connector_version || "?";
            const isOld = /^(1\.|2\.|3\.0\.[0-2]$|3\.1\.[0-6]$)/.test(v);
            if (row.is_offline) {
              errorLabel = `Connettore OFFLINE (ultimo: ${row.last_seen ? new Date(row.last_seen).toLocaleString("it-IT") : "?"})`;
              hint = `Il connector <b>${row.hostname || ""}</b> (v${v}) risulta offline.`;
            } else if (isOld) {
              errorLabel = `Connettore v${v} obsoleto`;
              hint = `Per la Web Console serve <b>v3.2.0+</b>. Aggiorna dal tray.`;
            }
          }
        } catch (_) {}
        updateSession(id, {
          loading: false, progress: 100,
          html: `<div style="padding:40px;text-align:center;font-family:system-ui"><h2 style="color:#FF3B30;margin-bottom:12px">${errorLabel}</h2><p style="color:#888;line-height:1.6">${hint}</p></div>`,
          error: errorLabel, loadTime,
        });
        return;
      }

      const r = resp.data.response;
      updateSession(id, {
        loading: false, progress: 100,
        html: r.body || "",
        title: r.title || `${deviceIp}:${port}${path}`,
        error: r.error, statusCode: r.status_code,
        loadTime,
      });
    } catch (e) {
      if (axios.isCancel(e) || e.name === "CanceledError" || e.name === "AbortError") return;
      const loadTime = performance.now() - t0;
      const status = e.response?.status;
      const detail = e.response?.data?.detail;
      let errLabel = detail || e.message || "Errore sconosciuto";
      let html = `<div style="padding:40px;text-align:center;font-family:system-ui"><h2 style="color:#FF3B30;margin-bottom:12px">Errore</h2><p style="color:#888;line-height:1.6">${errLabel}</p></div>`;
      if (status === 403 && /not authorized/i.test(detail || "")) {
        errLabel = "Dispositivo non censito";
        html = `<div style="padding:40px;text-align:center;font-family:system-ui;max-width:480px;margin:0 auto"><h2 style="color:#FF3B30;margin-bottom:12px">Dispositivo non censito</h2><p style="color:#aaa;line-height:1.6">Il dispositivo <b style="color:#fff">${deviceIp}:${port}</b> non risulta registrato per questo cliente.</p></div>`;
      } else if (status === 401) errLabel = "Sessione scaduta";
      else if (status === 404) errLabel = "Richiesta scaduta";
      updateSession(id, { loading: false, progress: 100, html, error: errLabel, loadTime });
    } finally {
      delete abortsRef.current[id];
    }
  }, [updateSession]);

  const open = useCallback((clientId, deviceIp, port, path) => {
    const existing = sessionsRef.current.find(s => s.deviceIp === deviceIp && s.port === port);
    if (existing) {
      setActiveId(existing.id);
      setMinimized(false);
      return existing.id;
    }
    const id = `wc-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
    const newSession = {
      id, clientId, deviceIp, port: port || 80, path: path || "/",
      title: `${deviceIp}:${port}`, loading: true, progress: 10,
      html: null, error: null, loadTime: null, sessionId: id,
    };
    setSessions(prev => [...prev, newSession]);
    setActiveId(id);
    setMinimized(false);
    const controller = new AbortController();
    abortsRef.current[id] = controller;
    _runSession(id, clientId, deviceIp, port, path, controller);
    return id;
  }, [_runSession]);

  const reload = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s) return;
    if (abortsRef.current[id]) { try { abortsRef.current[id].abort(); } catch {} }
    const controller = new AbortController();
    abortsRef.current[id] = controller;
    updateSession(id, { loading: true, progress: 10, html: null, error: null, loadTime: null });
    _runSession(id, s.clientId, s.deviceIp, s.port, s.path, controller);
  }, [_runSession, updateSession]);

  const navigate = useCallback((id, newPath, opts = {}) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s) return;
    if (abortsRef.current[id]) { try { abortsRef.current[id].abort(); } catch {} }
    const controller = new AbortController();
    abortsRef.current[id] = controller;
    updateSession(id, { loading: true, progress: 10, html: null, error: null, loadTime: null, path: newPath });
    _runSession(id, s.clientId, s.deviceIp, s.port, newPath, controller, opts);
  }, [_runSession, updateSession]);

  const close = useCallback((id) => {
    if (abortsRef.current[id]) { try { abortsRef.current[id].abort(); } catch {} delete abortsRef.current[id]; }
    setSessions(prev => prev.filter(s => s.id !== id));
    setActiveId(prev => {
      if (prev !== id) return prev;
      const remaining = sessionsRef.current.filter(s => s.id !== id);
      return remaining.length ? remaining[remaining.length - 1].id : null;
    });
  }, []);

  const setActive = useCallback((id) => { setActiveId(id); setMinimized(false); }, []);
  const minimize = useCallback(() => setMinimized(true), []);
  const closeAll = useCallback(() => {
    Object.values(abortsRef.current).forEach(c => { try { c.abort(); } catch {} });
    abortsRef.current = {};
    setSessions([]);
    setActiveId(null);
  }, []);
  const goHome = useCallback((id) => navigate(id, "/"), [navigate]);

  // Apri in NUOVA tab usando l'architettura LIVE proxy (bypass srcDoc limits)
  const openExternal = useCallback(async (id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s) return;
    try {
      const res = await axios.post(`${API}/web-console/session`, {
        device_ip: s.deviceIp, port: s.port,
      });
      if (res.data?.iframe_url) {
        window.open(res.data.iframe_url, "_blank", "noopener");
      }
    } catch (e) {
      alert("Impossibile aprire sessione esterna: " + (e.response?.data?.detail || e.message));
    }
  }, []);

  // Intercept postMessage da iframe (click/submit interceptor v3.1.7+)
  useEffect(() => {
    const handler = (event) => {
      const d = event.data;
      if (!d || typeof d !== "object" || !activeId) return;
      if (d.type === "argus-proxy-navigate") {
        let p = String(d.path || "/");
        p = p.replace(/^https?:\/\/[^/]+/i, "").replace(/^__ARGUS_PROXY__/, "");
        if (!p.startsWith("/")) p = "/" + p;
        navigate(activeId, p, { method: d.method || "GET", body: d.body || "", contentType: d.contentType });
      } else if (d.type === "proxy-navigate") { // retro-compat v3.1.6
        let p = d.path;
        if (d.baseUrl && p.startsWith(d.baseUrl)) p = p.replace(d.baseUrl, "");
        if (!p.startsWith("/")) p = "/" + p;
        navigate(activeId, p);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [activeId, navigate]);

  const value = {
    sessions, activeId, minimized,
    open, reload, navigate, close, setActive, minimize, closeAll, goHome, openExternal,
  };
  return (
    <WebConsoleContext.Provider value={value}>
      {children}
      <WebConsoleDock />
    </WebConsoleContext.Provider>
  );
}

/* ==================== UI ==================== */

function WebConsoleDock() {
  const { sessions, activeId, minimized } = useWebConsoleTabs();
  if (sessions.length === 0) return null;
  const active = sessions.find(s => s.id === activeId);
  if (minimized || !active) return <MinimizedDock />;
  return <ActiveConsole session={active} />;
}

function MinimizedDock() {
  const { sessions, setActive, close, closeAll } = useWebConsoleTabs();
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 items-end" data-testid="web-console-dock-minimized">
      <div className="bg-[#0f0f17]/95 backdrop-blur-xl border border-[#2a2a3e] rounded-xl shadow-2xl p-2 flex flex-col gap-1 max-w-[280px]">
        <div className="flex items-center justify-between px-2 pt-1 pb-2 border-b border-[#1e1e2e]">
          <div className="flex items-center gap-2">
            <Globe size={14} className="text-indigo-400" />
            <span className="text-[10px] font-bold text-white/60 uppercase">Web Console</span>
            <span className="text-[9px] text-white/30 font-mono">({sessions.length})</span>
          </div>
          <button onClick={closeAll} className="p-1 rounded hover:bg-red-500/10 text-white/30 hover:text-red-400" title="Chiudi tutte" data-testid="web-console-close-all">
            <X size={12} />
          </button>
        </div>
        {sessions.map(s => (
          <div key={s.id} className="flex items-center gap-1 group">
            <button onClick={() => setActive(s.id)} className="flex-1 text-left px-2 py-1.5 rounded-lg hover:bg-indigo-500/10" data-testid={`web-console-tab-${s.deviceIp}`}>
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.loading ? "bg-amber-400 animate-pulse" : s.error ? "bg-red-400" : "bg-emerald-400"}`} />
                <span className="text-[11px] text-white/80 font-mono truncate">{s.deviceIp}:{s.port}</span>
              </div>
              {s.title && s.title !== `${s.deviceIp}:${s.port}` && (
                <span className="text-[9px] text-white/30 truncate block ml-3.5">{s.title}</span>
              )}
            </button>
            <button onClick={() => close(s.id)} className="p-1 rounded hover:bg-red-500/10 text-white/20 hover:text-red-400 opacity-0 group-hover:opacity-100">
              <X size={10} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActiveConsole({ session }) {
  const { sessions, setActive, close, reload, goHome, minimize, openExternal } = useWebConsoleTabs();
  return (
    <div className="fixed inset-0 md:inset-4 z-50 flex flex-col bg-[#0d0d12] md:rounded-2xl overflow-hidden border border-[#2a2a3e] shadow-2xl shadow-black/50" data-testid="web-console-active">
      <div className="flex items-center gap-2 px-3 py-2 bg-[#12121a] border-b border-[#1e1e2e] flex-shrink-0">
        <div className="flex items-center gap-1.5 mr-2">
          <button onClick={() => close(session.id)} className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400" title="Chiudi" data-testid="web-console-close" />
          <button onClick={minimize} className="w-3 h-3 rounded-full bg-amber-500 hover:bg-amber-400" title="Minimizza" data-testid="web-console-minimize" />
          <div className="w-3 h-3 rounded-full bg-emerald-500/50" />
        </div>
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <ShieldCheck size={14} className="text-emerald-400 flex-shrink-0" />
          <div className="flex flex-col min-w-0">
            <span className="text-[11px] text-white/80 font-mono truncate">{session.deviceIp}:{session.port}</span>
            {session.title && session.title !== `${session.deviceIp}:${session.port}` && (
              <span className="text-[9px] text-white/40 truncate">{session.title}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {session.loadTime && !session.loading && (
            <span className="text-[9px] text-white/30 font-mono px-2">
              {session.loadTime < 1000 ? `${Math.round(session.loadTime)}ms` : `${(session.loadTime / 1000).toFixed(2)}s`}
            </span>
          )}
          <button onClick={() => openExternal(session.id)} className="p-1.5 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors" title="Apri in nuova tab (LIVE proxy)" data-testid="web-console-open-external">
            <ArrowSquareOut size={14} />
          </button>
          <button onClick={() => goHome(session.id)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Home" data-testid="web-console-home">
            <House size={14} />
          </button>
          <button onClick={() => reload(session.id)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Ricarica" data-testid="web-console-reload">
            <ArrowClockwise size={14} />
          </button>
        </div>
      </div>

      {sessions.length > 1 && (
        <div className="flex items-center gap-1 px-2 py-1 bg-[#0f0f17] border-b border-[#1e1e2e] overflow-x-auto flex-shrink-0">
          {sessions.map(s => (
            <button key={s.id} onClick={() => setActive(s.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-md flex-shrink-0 text-[10px] font-mono ${
                s.id === session.id ? "bg-[#1a1a2e] text-white border-t border-l border-r border-[#2a2a3e]" : "bg-transparent text-white/40 hover:text-white/70 hover:bg-white/5"
              }`}>
              <span className={`w-1 h-1 rounded-full ${s.loading ? "bg-amber-400" : s.error ? "bg-red-400" : "bg-emerald-400"}`} />
              {s.deviceIp}:{s.port}
              <X size={10} onClick={(e) => { e.stopPropagation(); close(s.id); }} className="ml-1 opacity-40 hover:opacity-100 hover:text-red-400" />
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 bg-white overflow-auto relative">
        {session.loading ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0d0d12]/90 z-10 backdrop-blur-sm">
            <div className="relative">
              <div className="w-12 h-12 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin" />
              <Monitor size={20} className="text-indigo-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
            </div>
            <div className="text-center mt-4">
              <p className="text-white/70 text-sm font-medium">Caricamento {session.deviceIp}...</p>
              <p className="text-white/30 text-[10px] mt-2 font-mono">via 86NocConnector</p>
            </div>
          </div>
        ) : session.error && !session.html ? (
          <div className="flex items-center justify-center h-full bg-[#0d0d12] p-6">
            <div className="text-center max-w-md">
              <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                <Warning size={28} className="text-red-400" />
              </div>
              <p className="text-red-400 font-bold text-lg mb-2">Connessione Fallita</p>
              <p className="text-white/60 text-sm leading-relaxed">{session.error}</p>
              <button onClick={() => reload(session.id)} className="mt-4 px-4 py-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-xs font-bold hover:bg-indigo-500/20">
                Riprova
              </button>
            </div>
          </div>
        ) : (
          <iframe
            srcDoc={(session.html || "").replace(/__ARGUS_PROXY__/g, "")}
            className="w-full h-full border-0"
            title="Web Console"
            sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
            data-testid="web-console-iframe"
          />
        )}
      </div>

      <div className="flex items-center justify-between px-3 py-1 border-t border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-[9px] text-white/30 font-mono">{session.deviceIp}:{session.port}</span>
          {session.path && session.path !== "/" && (
            <span className="text-[9px] text-white/20 truncate max-w-[220px] font-mono">{session.path}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full ${session.loading ? "bg-amber-400 animate-pulse" : session.error ? "bg-red-400" : "bg-emerald-400"}`} />
          <span className="text-[9px] text-white/30">
            {session.loading ? "Caricamento..." : session.error ? "Errore" : "Connesso"}
          </span>
        </div>
      </div>
    </div>
  );
}
