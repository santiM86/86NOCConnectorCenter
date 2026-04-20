import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Monitor, Globe, ArrowClockwise, X, ShieldCheck, Warning,
  Minus, CaretLeft, CaretRight, House,
} from "@phosphor-icons/react";

/**
 * WebConsoleTabs v2 — Architettura LIVE pulita.
 * Ogni tab e' un iframe con src="/api/web-proxy/live/{session}/{ip}/{port}/".
 * Il browser gestisce nativamente tutto: navigazione, CSS/JS/img/XHR, cookie, POST form.
 * Noi intercettiamo solo <title> changes per la status bar.
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
  const iframeRefs = useRef({});

  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  const updateSession = useCallback((id, patch) => {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, ...patch } : s));
  }, []);

  const open = useCallback(async (clientId, deviceIp, port, path) => {
    // Re-usa sessione esistente per stesso (deviceIp, port)
    const existing = sessionsRef.current.find(s => s.deviceIp === deviceIp && s.port === port);
    if (existing) {
      setActiveId(existing.id);
      setMinimized(false);
      return existing.id;
    }

    try {
      const res = await axios.post(`${API}/web-console/session`, {
        device_ip: deviceIp,
        port: port || 80,
      });
      const { session_id, iframe_url } = res.data;
      const fullUrl = iframe_url + (path && path !== "/" ? path.replace(/^\//, "") : "");
      const newSession = {
        id: session_id,
        clientId, deviceIp,
        port: port || 80,
        path: path || "/",
        iframeSrc: fullUrl,
        title: `${deviceIp}:${port}`,
        loading: true,
        error: null,
        loadedAt: null,
        t0: performance.now(),
      };
      setSessions(prev => [...prev, newSession]);
      setActiveId(session_id);
      setMinimized(false);
      return session_id;
    } catch (e) {
      const detail = e.response?.data?.detail || e.message;
      const status = e.response?.status;
      let errorMsg = detail;
      if (status === 403 && /not authorized/i.test(detail || "")) {
        errorMsg = `Dispositivo ${deviceIp} non registrato per questo cliente.`;
      } else if (status === 401) {
        errorMsg = "Sessione scaduta. Ricarica la pagina.";
      }
      // Crea una "sessione errore" per UX
      const errId = `err-${Date.now()}`;
      setSessions(prev => [...prev, {
        id: errId, clientId, deviceIp, port: port || 80, path: path || "/",
        iframeSrc: null, title: deviceIp, loading: false, error: errorMsg,
      }]);
      setActiveId(errId);
      setMinimized(false);
      return errId;
    }
  }, []);

  const reload = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s) return;
    const iframe = iframeRefs.current[id];
    if (iframe) {
      updateSession(id, { loading: true, t0: performance.now() });
      iframe.src = s.iframeSrc + (s.iframeSrc.includes("?") ? "&" : "?") + "_reload=" + Date.now();
    }
  }, [updateSession]);

  const navigate = useCallback((id, newPath) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s) return;
    const iframe = iframeRefs.current[id];
    if (iframe) {
      const basePath = `/api/web-proxy/live/${s.id}/${s.deviceIp}/${s.port}`;
      const cleanNew = newPath.startsWith("/") ? newPath : "/" + newPath;
      updateSession(id, { loading: true, t0: performance.now(), path: newPath });
      iframe.src = basePath + cleanNew;
    }
  }, [updateSession]);

  const goHome = useCallback((id) => {
    navigate(id, "/");
  }, [navigate]);

  const close = useCallback((id) => {
    delete iframeRefs.current[id];
    setSessions(prev => prev.filter(s => s.id !== id));
    setActiveId(prev => {
      if (prev !== id) return prev;
      const remaining = sessionsRef.current.filter(s => s.id !== id);
      return remaining.length ? remaining[remaining.length - 1].id : null;
    });
  }, []);

  const setActive = useCallback((id) => {
    setActiveId(id);
    setMinimized(false);
  }, []);

  const minimize = useCallback(() => setMinimized(true), []);

  const closeAll = useCallback(() => {
    iframeRefs.current = {};
    setSessions([]);
    setActiveId(null);
  }, []);

  // Listener postMessage da iframe (title update)
  useEffect(() => {
    const handler = (event) => {
      const d = event.data;
      if (!d || typeof d !== "object") return;
      if (d.type === "argus-title" && d.title && activeId) {
        // Trova quale sessione corrisponde al source iframe
        for (const [sid, iframe] of Object.entries(iframeRefs.current)) {
          if (iframe && iframe.contentWindow === event.source) {
            updateSession(sid, { title: d.title });
            break;
          }
        }
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [activeId, updateSession]);

  const setIframeRef = useCallback((id, el) => {
    if (el) iframeRefs.current[id] = el;
    else delete iframeRefs.current[id];
  }, []);

  const onIframeLoad = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    updateSession(id, {
      loading: false,
      loadedAt: new Date(),
      loadTime: s?.t0 ? Math.round(performance.now() - s.t0) : null,
    });
  }, [updateSession]);

  const value = {
    sessions, activeId, minimized,
    open, reload, navigate, close, setActive, minimize, closeAll, goHome,
    setIframeRef, onIframeLoad,
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
      <div className="bg-[#0f0f17]/95 backdrop-blur-xl border border-[#2a2a3e] rounded-xl shadow-2xl shadow-indigo-500/10 p-2 flex flex-col gap-1 max-w-[280px]">
        <div className="flex items-center justify-between px-2 pt-1 pb-2 border-b border-[#1e1e2e]">
          <div className="flex items-center gap-2">
            <Globe size={14} className="text-indigo-400" />
            <span className="text-[10px] font-bold text-white/60 uppercase tracking-wider">Web Console</span>
            <span className="text-[9px] text-white/30 font-mono">({sessions.length})</span>
          </div>
          <button onClick={closeAll} className="p-1 rounded hover:bg-red-500/10 text-white/30 hover:text-red-400" title="Chiudi tutte" data-testid="web-console-close-all">
            <X size={12} />
          </button>
        </div>
        {sessions.map(s => (
          <div key={s.id} className="flex items-center gap-1 group">
            <button onClick={() => setActive(s.id)}
              className="flex-1 text-left px-2 py-1.5 rounded-lg hover:bg-indigo-500/10 transition-colors"
              data-testid={`web-console-tab-${s.deviceIp}`}>
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.loading ? "bg-amber-400 animate-pulse" : s.error ? "bg-red-400" : "bg-emerald-400"}`}></span>
                <span className="text-[11px] text-white/80 font-mono truncate">{s.deviceIp}:{s.port}</span>
              </div>
              {s.title && s.title !== `${s.deviceIp}:${s.port}` && (
                <span className="text-[9px] text-white/30 truncate block ml-3.5">{s.title}</span>
              )}
            </button>
            <button onClick={() => close(s.id)} className="p-1 rounded hover:bg-red-500/10 text-white/20 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity">
              <X size={10} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActiveConsole({ session }) {
  const { sessions, setActive, close, reload, goHome, minimize, setIframeRef, onIframeLoad } = useWebConsoleTabs();
  const onReload = () => reload(session.id);
  return (
    <div className="fixed inset-0 md:inset-4 z-50 flex flex-col bg-[#0d0d12] md:rounded-2xl overflow-hidden border border-[#2a2a3e] shadow-2xl shadow-black/50" data-testid="web-console-active">
      {/* Titlebar macOS-style */}
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
              {session.loadTime < 1000 ? `${session.loadTime}ms` : `${(session.loadTime / 1000).toFixed(2)}s`}
            </span>
          )}
          <button onClick={() => goHome(session.id)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80 transition-colors" title="Home" data-testid="web-console-home">
            <House size={14} />
          </button>
          <button onClick={onReload} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80 transition-colors" title="Ricarica" data-testid="web-console-reload">
            <ArrowClockwise size={14} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      {sessions.length > 1 && (
        <div className="flex items-center gap-1 px-2 py-1 bg-[#0f0f17] border-b border-[#1e1e2e] overflow-x-auto flex-shrink-0">
          {sessions.map(s => (
            <button key={s.id} onClick={() => setActive(s.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-md flex-shrink-0 transition-colors text-[10px] font-mono ${
                s.id === session.id
                  ? "bg-[#1a1a2e] text-white border-t border-l border-r border-[#2a2a3e]"
                  : "bg-transparent text-white/40 hover:text-white/70 hover:bg-white/5"
              }`}>
              <span className={`w-1 h-1 rounded-full ${s.loading ? "bg-amber-400" : s.error ? "bg-red-400" : "bg-emerald-400"}`}></span>
              {s.deviceIp}:{s.port}
              <X size={10} onClick={(e) => { e.stopPropagation(); close(s.id); }} className="ml-1 opacity-40 hover:opacity-100 hover:text-red-400" />
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 bg-white overflow-auto relative">
        {session.error ? (
          <div className="flex items-center justify-center h-full bg-[#0d0d12] p-6 md:p-8">
            <div className="text-center max-w-md">
              <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                <Warning size={28} className="text-red-400" />
              </div>
              <p className="text-red-400 font-bold text-lg mb-2">Connessione Fallita</p>
              <p className="text-white/60 text-sm leading-relaxed">{session.error}</p>
              <button onClick={onReload}
                className="mt-4 px-4 py-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-xs font-bold hover:bg-indigo-500/20 transition-colors">
                Riprova
              </button>
            </div>
          </div>
        ) : (
          <>
            {session.loading && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0d0d12]/90 z-10 backdrop-blur-sm">
                <div className="relative">
                  <div className="w-12 h-12 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin"></div>
                  <Monitor size={20} className="text-indigo-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
                </div>
                <div className="text-center mt-4">
                  <p className="text-white/70 text-sm font-medium">Caricamento {session.deviceIp}...</p>
                  <p className="text-white/30 text-[10px] mt-2 font-mono">via 86NocConnector</p>
                </div>
              </div>
            )}
            {session.iframeSrc && (
              <iframe
                ref={(el) => setIframeRef(session.id, el)}
                src={session.iframeSrc}
                onLoad={() => onIframeLoad(session.id)}
                className="w-full h-full border-0 bg-white"
                title={`Web Console ${session.deviceIp}`}
                sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-downloads allow-modals"
                data-testid="web-console-iframe"
              />
            )}
          </>
        )}
      </div>

      {/* Status Bar */}
      <div className="flex items-center justify-between px-3 py-1 border-t border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-[9px] text-white/30 font-mono">{session.deviceIp}:{session.port}</span>
          {session.path && session.path !== "/" && (
            <span className="text-[9px] text-white/20 truncate max-w-[220px] font-mono">{session.path}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full ${session.loading ? "bg-amber-400 animate-pulse" : session.error ? "bg-red-400" : "bg-emerald-400"}`}></span>
          <span className="text-[9px] text-white/30">
            {session.loading ? "Caricamento..." : session.error ? "Errore" : "Connesso"}
          </span>
        </div>
      </div>
    </div>
  );
}
