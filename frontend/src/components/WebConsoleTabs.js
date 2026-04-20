import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Monitor, Globe, ArrowClockwise, X, ShieldCheck, Warning,
  ArrowSquareOut, House, CaretLeft,
} from "@phosphor-icons/react";

/**
 * WebConsoleTabs — ARCHITETTURA LIVE (enterprise-grade, v4).
 *
 * - POST /api/web-console/session → capability token (UUID) + iframe_url.
 * - <iframe src={iframe_url}> ha ORIGINE argus.86bit.it → cookie, XHR, JS funzionano.
 * - Backend /api/web-proxy/live/{sid}/{ip}/{port}/{path} proxa via connector, inietta
 *   <base href> → CSS/JS/IMG/XHR relativi vengono auto-proxati dal browser.
 * - Navigation/back/submit: nativi browser, nessun postMessage hack.
 * - Service Worker bypassa /api/web-proxy/live/ (sw.js v4).
 * - Multi-tab dock preservato. Refocus se stesso device+port gia' aperto.
 */

const WebConsoleContext = createContext(null);

export function useWebConsoleTabs() {
  const ctx = useContext(WebConsoleContext);
  if (!ctx) throw new Error("useWebConsoleTabs must be used within WebConsoleTabsProvider");
  return ctx;
}

function buildIframeUrl(iframeUrl) {
  // iframeUrl dal backend e' un path assoluto tipo /api/web-proxy/live/.../
  // Lo rendiamo assoluto con l'origine del frontend per evitare ambiguita' in iframe.
  try {
    return new URL(iframeUrl, window.location.origin).toString();
  } catch {
    return iframeUrl;
  }
}

export function WebConsoleTabsProvider({ children }) {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [minimized, setMinimized] = useState(false);
  const sessionsRef = useRef([]);

  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  const updateSession = useCallback((id, patch) => {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, ...patch } : s));
  }, []);

  const open = useCallback(async (clientId, deviceIp, port, path) => {
    const p = port || 80;
    // Dedup: stesso device+port -> refocus
    const existing = sessionsRef.current.find(s => s.deviceIp === deviceIp && s.port === p);
    if (existing) {
      setActiveId(existing.id);
      setMinimized(false);
      return existing.id;
    }

    // Pre-flight: se il Service Worker in pagina e' vecchio (senza bypass /api/web-proxy/live/)
    // potrebbe intercettare la request iframe e servire stale cache. Forziamo un update check.
    try {
      if ("serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.getRegistration();
        if (reg) {
          reg.update().catch(() => {});
        }
      }
    } catch (_) {}

    const id = `wc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const placeholder = {
      id, clientId, deviceIp, port: p, path: path || "/",
      title: `${deviceIp}:${p}`,
      loading: true, error: null, iframeUrl: null, sessionId: null,
      iframeKey: 0, loadTime: null, startedAt: performance.now(),
    };
    setSessions(prev => [...prev, placeholder]);
    setActiveId(id);
    setMinimized(false);

    try {
      const res = await axios.post(`${API}/web-console/session`, {
        device_ip: deviceIp, port: p,
      }, { timeout: 15000 });
      const sid = res.data?.session_id;
      const url = res.data?.iframe_url;
      if (!sid || !url) throw new Error("Backend senza session_id/iframe_url");
      const absUrl = buildIframeUrl(url);
      updateSession(id, {
        loading: false, sessionId: sid, iframeUrl: absUrl,
      });
    } catch (e) {
      const status = e.response?.status;
      const detail = e.response?.data?.detail || e.message;
      let msg = detail;
      if (status === 403) msg = "Dispositivo non autorizzato per questo utente/cliente.";
      else if (status === 401) msg = "Sessione ARGUS scaduta, rieffettua il login.";
      updateSession(id, { loading: false, error: msg });
    }
    return id;
  }, [updateSession]);

  const reload = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s) return;
    updateSession(id, { iframeKey: (s.iframeKey || 0) + 1, loadTime: null, startedAt: performance.now() });
  }, [updateSession]);

  const goHome = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s || !s.iframeUrl) return;
    // Risetta src alla base -> iframe torna alla home del device
    const baseUrl = s.iframeUrl;
    updateSession(id, { iframeUrl: null });
    setTimeout(() => updateSession(id, { iframeUrl: baseUrl, iframeKey: (s.iframeKey || 0) + 1 }), 10);
  }, [updateSession]);

  const close = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (s?.sessionId) {
      // Fire-and-forget: revoca token lato server (best-effort)
      axios.delete(`${API}/web-console/session/${s.sessionId}`).catch(() => {});
    }
    setSessions(prev => prev.filter(x => x.id !== id));
    setActiveId(prev => {
      if (prev !== id) return prev;
      const remaining = sessionsRef.current.filter(x => x.id !== id);
      return remaining.length ? remaining[remaining.length - 1].id : null;
    });
  }, []);

  const setActive = useCallback((id) => { setActiveId(id); setMinimized(false); }, []);
  const minimize = useCallback(() => setMinimized(true), []);
  const closeAll = useCallback(() => {
    sessionsRef.current.forEach(s => {
      if (s.sessionId) axios.delete(`${API}/web-console/session/${s.sessionId}`).catch(() => {});
    });
    setSessions([]);
    setActiveId(null);
  }, []);

  // Apri LIVE proxy in NUOVA tab del browser (bypass iframe completamente)
  const openExternal = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s?.iframeUrl) return;
    window.open(s.iframeUrl, "_blank", "noopener");
  }, []);

  // Diagnostica: apre tab con JSON debug (content-type originale, size, preview body)
  const openDebug = useCallback(async (id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s?.sessionId) {
      alert("Sessione non pronta");
      return;
    }
    try {
      const res = await axios.get(`${API}/web-console/debug/${s.sessionId}`);
      const pretty = JSON.stringify(res.data, null, 2);
      const win = window.open("", "_blank");
      if (win) {
        win.document.write(`<pre style="font:12px/1.4 monospace;padding:16px;background:#0f0f17;color:#d4d4d4;white-space:pre-wrap;word-break:break-all">${pretty.replace(/</g, "&lt;")}</pre>`);
        win.document.title = `Debug ${s.deviceIp}:${s.port}`;
      }
    } catch (e) {
      alert("Debug fallito: " + (e.response?.data?.detail || e.message));
    }
  }, []);

  // postMessage listener: iframe invia title del device -> propaga nel chrome
  useEffect(() => {
    const handler = (event) => {
      const d = event.data;
      if (!d || typeof d !== "object") return;
      if (d.type === "argus-title" && typeof d.title === "string") {
        setSessions(prev => prev.map(s => {
          // Applica il title alla sessione attiva (l'origine postMessage e' same-origin ma non possiamo filtrare meglio)
          if (s.id === activeId) return { ...s, title: d.title };
          return s;
        }));
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [activeId]);

  const value = {
    sessions, activeId, minimized,
    open, reload, close, setActive, minimize, closeAll, goHome, openExternal, openDebug,
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
  const { sessions, setActive, close, reload, goHome, minimize, openExternal, openDebug } = useWebConsoleTabs();
  const iframeRef = useRef(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [loadTime, setLoadTime] = useState(null);

  useEffect(() => {
    setIframeLoaded(false);
    setLoadTime(null);
  }, [session.iframeKey, session.iframeUrl]);

  const onIframeLoad = useCallback(() => {
    setIframeLoaded(true);
    if (session.startedAt) {
      setLoadTime(Math.round(performance.now() - session.startedAt));
    }
  }, [session.startedAt]);

  // Back: usa history.back dell'iframe (same-origin, funziona)
  const goBack = useCallback(() => {
    try {
      iframeRef.current?.contentWindow?.history.back();
    } catch {}
  }, []);

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
          {loadTime != null && iframeLoaded && (
            <span className="text-[9px] text-white/30 font-mono px-2">
              {loadTime < 1000 ? `${loadTime}ms` : `${(loadTime / 1000).toFixed(2)}s`}
            </span>
          )}
          <button onClick={goBack} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Indietro" data-testid="web-console-back">
            <CaretLeft size={14} />
          </button>
          <button onClick={() => goHome(session.id)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Home" data-testid="web-console-home">
            <House size={14} />
          </button>
          <button onClick={() => reload(session.id)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Ricarica" data-testid="web-console-reload">
            <ArrowClockwise size={14} />
          </button>
          <button onClick={() => openExternal(session.id)} className="p-1.5 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors" title="Apri in nuova tab" data-testid="web-console-open-external">
            <ArrowSquareOut size={14} />
          </button>
          <button onClick={() => openDebug(session.id)} className="px-1.5 py-1 rounded hover:bg-amber-500/10 text-amber-400 text-[9px] font-bold font-mono transition-colors" title="Debug response" data-testid="web-console-debug">
            DBG
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

      <div className="flex-1 bg-white overflow-hidden relative" style={{ backgroundColor: "#ffffff" }}>
        {session.loading ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0d0d12]/95 z-10 backdrop-blur-sm">
            <div className="relative">
              <div className="w-12 h-12 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin" />
              <Monitor size={20} className="text-indigo-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
            </div>
            <div className="text-center mt-4">
              <p className="text-white/70 text-sm font-medium">Apertura sessione {session.deviceIp}...</p>
              <p className="text-white/30 text-[10px] mt-2 font-mono">LIVE proxy · capability token</p>
            </div>
          </div>
        ) : session.error ? (
          <div className="flex items-center justify-center h-full bg-[#0d0d12] p-6">
            <div className="text-center max-w-md">
              <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                <Warning size={28} className="text-red-400" />
              </div>
              <p className="text-red-400 font-bold text-lg mb-2">Impossibile aprire la Web Console</p>
              <p className="text-white/60 text-sm leading-relaxed">{session.error}</p>
              <button onClick={() => reload(session.id)} className="mt-4 px-4 py-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-xs font-bold hover:bg-indigo-500/20">
                Riprova
              </button>
            </div>
          </div>
        ) : session.iframeUrl ? (
          <>
            {!iframeLoaded && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0d0d12]/95 z-10 backdrop-blur-sm pointer-events-none">
                <div className="w-10 h-10 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin" />
                <p className="text-white/50 text-xs mt-3 font-mono">Caricamento device...</p>
              </div>
            )}
            <iframe
              ref={iframeRef}
              key={`${session.id}-${session.iframeKey}`}
              src={session.iframeUrl}
              onLoad={onIframeLoad}
              className="w-full h-full border-0"
              style={{ backgroundColor: "#ffffff" }}
              title={`Web Console ${session.deviceIp}`}
              sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads allow-top-navigation-by-user-activation"
              data-testid="web-console-iframe"
            />
          </>
        ) : null}
      </div>

      <div className="flex items-center justify-between px-3 py-1 border-t border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-[9px] text-white/30 font-mono">{session.deviceIp}:{session.port}</span>
          {session.iframeUrl && (
            <span className="text-[9px] text-emerald-400/70 font-mono uppercase">LIVE proxy</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full ${session.loading ? "bg-amber-400 animate-pulse" : session.error ? "bg-red-400" : iframeLoaded ? "bg-emerald-400" : "bg-amber-400 animate-pulse"}`} />
          <span className="text-[9px] text-white/30">
            {session.loading ? "Apertura..." : session.error ? "Errore" : iframeLoaded ? "Connesso" : "Caricamento..."}
          </span>
        </div>
      </div>
    </div>
  );
}
