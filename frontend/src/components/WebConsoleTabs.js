import { RemoteBrowserModal } from "./RemoteBrowserModal";
import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Monitor, Globe, ArrowClockwise, X, ShieldCheck, Warning,
  ArrowSquareOut, House, CaretLeft, Star, ArrowsOutSimple, Record,
  Share, Copy, Eye, Clock, Users,
} from "@phosphor-icons/react";

/**
 * WebConsoleTabs — ENTERPRISE LIVE (v5).
 * Feature enterprise: Fullscreen, Shortcuts, Latency, Quick Access (recent+favorites+live),
 * Session Recording opt-in, Session Share link read-only.
 */

const WebConsoleContext = createContext(null);

export function useWebConsoleTabs() {
  const ctx = useContext(WebConsoleContext);
  if (!ctx) throw new Error("useWebConsoleTabs must be used within WebConsoleTabsProvider");
  return ctx;
}

function buildIframeUrl(iframeUrl) {
  try { return new URL(iframeUrl, window.location.origin).toString(); } catch { return iframeUrl; }
}

export function WebConsoleTabsProvider({ children }) {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [minimized, setMinimized] = useState(false);
  const [quickAccessOpen, setQuickAccessOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const sessionsRef = useRef([]);

  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  const updateSession = useCallback((id, patch) => {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, ...patch } : s));
  }, []);

  const open = useCallback(async (clientId, deviceIp, port, path, opts = {}) => {
    const p = port || 80;
    const existing = sessionsRef.current.find(s => s.deviceIp === deviceIp && s.port === p);
    if (existing) {
      setActiveId(existing.id); setMinimized(false); return existing.id;
    }

    try {
      if ("serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.getRegistration();
        if (reg) reg.update().catch(() => {});
      }
    } catch (_) {}

    const id = `wc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const placeholder = {
      id, clientId, deviceIp, port: p, path: path || "/",
      title: `${deviceIp}:${p}`,
      loading: true, error: null, iframeUrl: null, sessionId: null,
      iframeKey: 0, loadTime: null, startedAt: performance.now(),
      recording: !!opts.record,
    };
    setSessions(prev => [...prev, placeholder]);
    setActiveId(id); setMinimized(false); setQuickAccessOpen(false);

    try {
      const res = await axios.post(`${API}/web-console/session`, {
        device_ip: deviceIp, port: p, record: !!opts.record,
      }, { timeout: 15000 });
      const sid = res.data?.session_id;
      const url = res.data?.iframe_url;
      if (!sid || !url) throw new Error("Backend senza session_id/iframe_url");
      const sep = url.includes("?") ? "&" : "?";
      const absUrl = buildIframeUrl(`${url}${sep}_t=${Date.now()}`);
      updateSession(id, {
        loading: false, sessionId: sid, iframeUrl: absUrl,
        recording: !!res.data?.recording,
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
    const baseUrl = s.iframeUrl;
    updateSession(id, { iframeUrl: null });
    setTimeout(() => updateSession(id, { iframeUrl: baseUrl, iframeKey: (s.iframeKey || 0) + 1 }), 10);
  }, [updateSession]);

  const openPopup = useCallback(async (deviceIp, opts = {}) => {
    // V4 popup mode: window.open() in new tab, no iframe. Enterprise cloud proxy.
    if (!deviceIp) return null;
    try {
      const res = await axios.post(`${API}/console-v4/request-session`, {
        device_ip: deviceIp,
      }, { timeout: 10000 });
      const path = res.data?.url;
      if (!path) throw new Error("Backend senza URL sessione");
      // Backend returns a relative path; prefix with current origin so the
      // browser targets the public (ingress) URL, not the internal host.
      const absUrl = path.startsWith("http")
        ? path
        : `${window.location.origin}${path}`;
      // Open in new tab. Browser pop-up blockers require user gesture (questo e' chiamato da click)
      const win = window.open(absUrl, "_blank", "noopener,noreferrer");
      if (!win) {
        alert("⚠ Pop-up bloccato dal browser. Consenti pop-up da " + window.location.hostname + " e riprova.");
        return null;
      }
      return { ...res.data, absolute_url: absUrl };
    } catch (e) {
      const detail = e.response?.data?.detail || e.message;
      alert(`Errore apertura console: ${detail}`);
      return null;
    }
  }, []);

  const close = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (s?.sessionId) axios.delete(`${API}/web-console/session/${s.sessionId}`).catch(() => {});
    setSessions(prev => prev.filter(x => x.id !== id));
    setActiveId(prev => {
      if (prev !== id) return prev;
      const remaining = sessionsRef.current.filter(x => x.id !== id);
      return remaining.length ? remaining[remaining.length - 1].id : null;
    });
    if (sessionsRef.current.length <= 1) setFullscreen(false);
  }, []);

  const setActive = useCallback((id) => { setActiveId(id); setMinimized(false); }, []);
  const minimize = useCallback(() => { setMinimized(true); setFullscreen(false); }, []);
  const closeAll = useCallback(() => {
    sessionsRef.current.forEach(s => {
      if (s.sessionId) axios.delete(`${API}/web-console/session/${s.sessionId}`).catch(() => {});
    });
    setSessions([]); setActiveId(null); setFullscreen(false);
  }, []);

  const openExternal = useCallback((id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s?.iframeUrl) return;
    window.open(s.iframeUrl, "_blank", "noopener");
  }, []);

  const openDebug = useCallback(async (id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s?.sessionId) { alert("Sessione non pronta"); return; }
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

  const toggleRecording = useCallback(async (id) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s?.sessionId) return;
    try {
      const res = await axios.post(`${API}/web-console/recording/${s.sessionId}/toggle`, {
        enabled: !s.recording,
      });
      updateSession(id, { recording: !!res.data?.recording });
    } catch (e) { alert("Recording toggle fallito: " + (e.response?.data?.detail || e.message)); }
  }, [updateSession]);

  const toggleFullscreen = useCallback(() => setFullscreen(f => !f), []);
  const toggleQuickAccess = useCallback(() => setQuickAccessOpen(o => !o), []);

  const value = {
    sessions, activeId, minimized, fullscreen, quickAccessOpen,
    open, openPopup, reload, close, setActive, minimize, closeAll, goHome, openExternal, openDebug,
    toggleRecording, toggleFullscreen, toggleQuickAccess,
  };

  // Keyboard shortcuts globali quando una console e' attiva
  useEffect(() => {
    const onKey = (e) => {
      const active = sessionsRef.current.find(s => s.id === activeId);
      if (!active || minimized) return;
      // Non intercettare se focus e' in input/textarea della UI ARGUS
      const tag = e.target?.tagName?.toLowerCase();
      const isInput = tag === "input" || tag === "textarea" || e.target?.isContentEditable;
      if (isInput) return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "r") {
        e.preventDefault(); reload(active.id);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "h") {
        e.preventDefault(); goHome(active.id);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") {
        e.preventDefault(); openDebug(active.id);
      } else if (e.key === "F11") {
        e.preventDefault(); toggleFullscreen();
      } else if (e.key === "Escape" && fullscreen) {
        e.preventDefault(); setFullscreen(false);
      } else if (e.altKey && e.key === "ArrowLeft") {
        e.preventDefault();
        try {
          const iframe = document.querySelector('iframe[data-testid="web-console-iframe"]');
          iframe?.contentWindow?.history.back();
        } catch {}
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeId, minimized, fullscreen, reload, goHome, openDebug, toggleFullscreen]);

  useEffect(() => {
    const handler = (event) => {
      const d = event.data;
      if (!d || typeof d !== "object") return;
      if (d.type === "argus-title" && typeof d.title === "string") {
        setSessions(prev => prev.map(s => s.id === activeId ? { ...s, title: d.title } : s));
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [activeId]);

  return (
    <WebConsoleContext.Provider value={value}>
      {children}
      <WebConsoleDock />
      {quickAccessOpen && <QuickAccessDrawer />}
    </WebConsoleContext.Provider>
  );
}

/* ==================== DOCK ==================== */

function WebConsoleDock() {
  const { sessions, activeId, minimized } = useWebConsoleTabs();
  if (sessions.length === 0) return null;
  const active = sessions.find(s => s.id === activeId);
  if (minimized || !active) return <MinimizedDock />;
  return <ActiveConsole session={active} />;
}

function MinimizedDock() {
  const { sessions, setActive, close, closeAll, toggleQuickAccess } = useWebConsoleTabs();
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 items-end" data-testid="web-console-dock-minimized">
      <div className="bg-[#0f0f17]/95 backdrop-blur-xl border border-[#2a2a3e] rounded-xl shadow-2xl p-2 flex flex-col gap-1 max-w-[280px]">
        <div className="flex items-center justify-between px-2 pt-1 pb-2 border-b border-[#1e1e2e]">
          <div className="flex items-center gap-2">
            <Globe size={14} className="text-indigo-400" />
            <span className="text-[10px] font-bold text-white/60 uppercase">Web Console</span>
            <span className="text-[9px] text-white/30 font-mono">({sessions.length})</span>
          </div>
          <div className="flex gap-1">
            <button onClick={toggleQuickAccess} className="p-1 rounded hover:bg-indigo-500/10 text-indigo-400/80 hover:text-indigo-300" title="Quick Access" data-testid="quick-access-toggle">
              <Star size={12} />
            </button>
            <button onClick={closeAll} className="p-1 rounded hover:bg-red-500/10 text-white/30 hover:text-red-400" title="Chiudi tutte" data-testid="web-console-close-all">
              <X size={12} />
            </button>
          </div>
        </div>
        {sessions.map(s => (
          <div key={s.id} className="flex items-center gap-1 group">
            <button onClick={() => setActive(s.id)} className="flex-1 text-left px-2 py-1.5 rounded-lg hover:bg-indigo-500/10" data-testid={`web-console-tab-${s.deviceIp}`}>
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.loading ? "bg-amber-400 animate-pulse" : s.error ? "bg-red-400" : "bg-emerald-400"}`} />
                <span className="text-[11px] text-white/80 font-mono truncate">{s.deviceIp}:{s.port}</span>
                {s.recording && <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" title="Recording" />}
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

/* ==================== ACTIVE CONSOLE ==================== */

function ActiveConsole({ session }) {
  const {
    sessions, setActive, close, reload, goHome, minimize, openExternal, openDebug, openPopup,
    toggleRecording, toggleFullscreen, fullscreen, toggleQuickAccess,
  } = useWebConsoleTabs();
  const iframeRef = useRef(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [loadTime, setLoadTime] = useState(null);
  const [showShare, setShowShare] = useState(false);
  const [showRmt, setShowRmt] = useState(false);
  const [probeOpen, setProbeOpen] = useState(false);
  const [probeRunning, setProbeRunning] = useState(false);
  const [probeData, setProbeData] = useState(null);
  const [probeError, setProbeError] = useState(null);

  const runProbe = useCallback(async () => {
    setProbeRunning(true); setProbeError(null); setProbeData(null);
    try {
      const res = await axios.post(`${API}/diag/web-console-probe`, {
        device_ip: session.deviceIp, port: session.port,
      }, { timeout: 45000 });
      setProbeData(res.data);
    } catch (e) {
      setProbeError(e?.response?.data?.detail || e.message || "Probe fallita");
    } finally {
      setProbeRunning(false);
    }
  }, [session.deviceIp, session.port]);

  const applyProbePath = useCallback(async (path) => {
    try {
      await axios.post(`${API}/diag/apply-web-console-path`, {
        device_ip: session.deviceIp, path,
      });
      setProbeOpen(false);
      reload(session.id);
    } catch (e) {
      setProbeError(e?.response?.data?.detail || e.message || "Apply fallito");
    }
  }, [session.deviceIp, session.id, reload]);

  useEffect(() => {
    setIframeLoaded(false); setLoadTime(null);
  }, [session.iframeKey, session.iframeUrl]);

  const onIframeLoad = useCallback(() => {
    setIframeLoaded(true);
    if (session.startedAt) setLoadTime(Math.round(performance.now() - session.startedAt));
  }, [session.startedAt]);

  const goBack = useCallback(() => {
    try { iframeRef.current?.contentWindow?.history.back(); } catch {}
  }, []);

  const containerCls = fullscreen
    ? "fixed inset-0 z-[60] flex flex-col bg-[#0d0d12] overflow-hidden"
    : "fixed inset-0 md:inset-4 z-50 flex flex-col bg-[#0d0d12] md:rounded-2xl overflow-hidden border border-[#2a2a3e] shadow-2xl shadow-black/50";

  return (
    <div className={containerCls} data-testid="web-console-active">
      <div className="flex items-center gap-2 px-3 py-2 bg-[#12121a] border-b border-[#1e1e2e] flex-shrink-0">
        <div className="flex items-center gap-1.5 mr-2">
          <button onClick={() => close(session.id)} className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400" title="Chiudi" data-testid="web-console-close" />
          <button onClick={minimize} className="w-3 h-3 rounded-full bg-amber-500 hover:bg-amber-400" title="Minimizza" data-testid="web-console-minimize" />
          <button onClick={toggleFullscreen} className="w-3 h-3 rounded-full bg-emerald-500 hover:bg-emerald-400" title="Fullscreen (F11)" data-testid="web-console-fullscreen" />
        </div>
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <ShieldCheck size={14} className="text-emerald-400 flex-shrink-0" />
          <div className="flex flex-col min-w-0">
            <span className="text-[11px] text-white/80 font-mono truncate">{session.deviceIp}:{session.port}</span>
            {session.title && session.title !== `${session.deviceIp}:${session.port}` && (
              <span className="text-[9px] text-white/40 truncate">{session.title}</span>
            )}
          </div>
          {session.recording && (
            <span className="flex items-center gap-1 px-2 py-0.5 bg-red-500/10 border border-red-500/30 rounded text-[9px] font-bold text-red-400 font-mono ml-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />REC
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {loadTime != null && iframeLoaded && (
            <span className="text-[9px] text-white/30 font-mono px-2" title="Tempo caricamento primo frame">
              {loadTime < 1000 ? `${loadTime}ms` : `${(loadTime / 1000).toFixed(2)}s`}
            </span>
          )}
          <button onClick={toggleQuickAccess} className="p-1.5 rounded hover:bg-indigo-500/10 text-indigo-400/70 hover:text-indigo-300" title="Quick Access (preferiti + recenti)" data-testid="web-console-quick-access">
            <Star size={14} />
          </button>
          <button onClick={goBack} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Indietro (Alt+←)" data-testid="web-console-back">
            <CaretLeft size={14} />
          </button>
          <button onClick={() => goHome(session.id)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Home (Ctrl+H)" data-testid="web-console-home">
            <House size={14} />
          </button>
          <button onClick={() => reload(session.id)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Ricarica (Ctrl+R)" data-testid="web-console-reload">
            <ArrowClockwise size={14} />
          </button>
          <button onClick={() => toggleRecording(session.id)}
            className={`p-1.5 rounded transition-colors ${session.recording ? "bg-red-500/20 text-red-400 hover:bg-red-500/30" : "hover:bg-white/5 text-white/40 hover:text-white/80"}`}
            title={session.recording ? "Ferma registrazione" : "Registra sessione"}
            data-testid="web-console-recording-toggle">
            <Record size={14} />
          </button>
          <button onClick={() => setShowShare(true)} className="p-1.5 rounded hover:bg-purple-500/10 text-purple-400/80 hover:text-purple-300" title="Condividi sessione" data-testid="web-console-share-open">
            <Share size={14} />
          </button>
          <button onClick={toggleFullscreen} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title={fullscreen ? "Esci Fullscreen (Esc)" : "Fullscreen (F11)"} data-testid="web-console-fullscreen-btn">
            <ArrowsOutSimple size={14} />
          </button>
          <button onClick={() => openExternal(session.id)} className="p-1.5 rounded hover:bg-indigo-500/10 text-indigo-400 transition-colors" title="Apri in nuova tab" data-testid="web-console-open-external">
            <ArrowSquareOut size={14} />
          </button>
          <button
            onClick={() => openPopup(session.deviceIp)}
            className="px-2 py-1 rounded hover:bg-indigo-500/20 bg-indigo-500/10 text-indigo-300 text-[9px] font-bold border border-indigo-500/30 transition-colors"
            title="Popup V4 — apre in nuova tab bypassando blocchi iframe (CSP/JS)"
            data-testid="web-console-popup-v4"
          >
            V4
          </button>
          <button onClick={() => openDebug(session.id)} className="px-1.5 py-1 rounded hover:bg-amber-500/10 text-amber-400 text-[9px] font-bold font-mono transition-colors" title="Debug response (Ctrl+D)" data-testid="web-console-debug">
            DBG
          </button>
          <button
            onClick={() => { setProbeOpen(true); runProbe(); }}
            className="px-1.5 py-1 rounded hover:bg-cyan-500/10 text-cyan-400 text-[9px] font-bold font-mono transition-colors"
            title="Probe path — scansiona URL comuni del device (login.html, webui, frame...)"
            data-testid="web-console-probe"
          >
            PRB
          </button>
          <button
            onClick={() => setShowRmt(true)}
            className="px-1.5 py-1 rounded hover:bg-fuchsia-500/20 bg-fuchsia-500/10 text-fuchsia-300 text-[9px] font-bold font-mono border border-fuchsia-500/30 transition-colors"
            title="Remote Browser (RMT) — Edge headless via connector, nessun parsing HTML. Richiede connector v3.4+"
            data-testid="web-console-rmt"
          >
            RMT
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
              {s.recording && <span className="w-1 h-1 rounded-full bg-red-500 animate-pulse" />}
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
          {session.iframeUrl && <span className="text-[9px] text-emerald-400/70 font-mono uppercase">LIVE proxy</span>}
          {session.recording && <span className="text-[9px] text-red-400/80 font-mono uppercase">● REC</span>}
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full ${session.loading ? "bg-amber-400 animate-pulse" : session.error ? "bg-red-400" : iframeLoaded ? "bg-emerald-400" : "bg-amber-400 animate-pulse"}`} />
          <span className="text-[9px] text-white/30">
            {session.loading ? "Apertura..." : session.error ? "Errore" : iframeLoaded ? "Connesso" : "Caricamento..."}
          </span>
        </div>
      </div>

      {showShare && <ShareSessionModal session={session} onClose={() => setShowShare(false)} />}
      {showRmt && <RemoteBrowserModal session={session} onClose={() => setShowRmt(false)} />}
      {probeOpen && (
        <ProbePathsModal
          session={session}
          running={probeRunning}
          data={probeData}
          error={probeError}
          onRetry={runProbe}
          onApply={applyProbePath}
          onClose={() => setProbeOpen(false)}
        />
      )}
    </div>
  );
}

function ProbePathsModal({ session, running, data, error, onRetry, onApply, onClose }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        className="bg-[#0f0f17] border border-[#2a2a3e] rounded-xl shadow-2xl max-w-2xl w-full max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
        data-testid="web-console-probe-modal"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e1e2e]">
          <div className="flex items-center gap-2">
            <span className="text-cyan-400 text-[10px] font-bold font-mono">PRB</span>
            <span className="text-white/80 text-sm font-medium">Scansione path web — {session.deviceIp}:{session.port}</span>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/5 text-white/40 hover:text-white" data-testid="web-console-probe-close">
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4 text-[11px] font-mono text-white/70">
          {running && (
            <div className="flex items-center gap-3 py-8 justify-center">
              <div className="w-5 h-5 rounded-full border-2 border-cyan-500/20 border-t-cyan-500 animate-spin" />
              <span className="text-white/50 text-xs">Sondaggio in corso via connector (max ~20s)...</span>
            </div>
          )}
          {error && !running && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-red-300 text-xs">{error}</div>
          )}
          {data && !running && (
            <>
              <div className="flex items-center gap-3 pb-3 text-[10px] text-white/40">
                <span>{data.total_paths} path testati</span>
                <span className="text-emerald-400">{data.ok_count} OK</span>
                {data.best_path && <span className="text-cyan-400">Best: {data.best_path}</span>}
              </div>
              <table className="w-full text-[10px]">
                <thead className="text-white/30 border-b border-[#1e1e2e]">
                  <tr>
                    <th className="text-left py-1 font-normal">Path</th>
                    <th className="text-right py-1 font-normal w-14">Status</th>
                    <th className="text-right py-1 font-normal w-16">Size</th>
                    <th className="text-left py-1 font-normal">Title</th>
                    <th className="w-20"></th>
                  </tr>
                </thead>
                <tbody>
                  {(data.results || []).map((r) => (
                    <tr key={r.path} className="border-b border-[#141420] hover:bg-white/[0.02]">
                      <td className="py-1.5 text-white/80">{r.path}</td>
                      <td className={`py-1.5 text-right ${r.ok ? "text-emerald-400" : r.status_code >= 400 ? "text-amber-400" : "text-red-400"}`}>
                        {r.status_code || "—"}
                      </td>
                      <td className="py-1.5 text-right text-white/50">{r.body_size}</td>
                      <td className="py-1.5 text-white/60 truncate max-w-[200px]" title={r.title || r.error || ""}>
                        {r.title || <span className="text-white/25">{r.error || "—"}</span>}
                      </td>
                      <td className="py-1.5 text-right">
                        {r.ok && (
                          <button
                            onClick={() => onApply(r.path)}
                            className="px-2 py-0.5 rounded bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 text-[9px] font-bold border border-cyan-500/30"
                            data-testid={`web-console-probe-apply-${r.path}`}
                            title="Salva questo path nel profilo device"
                          >
                            USA
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
        <div className="flex items-center justify-between px-4 py-2 border-t border-[#1e1e2e] text-[10px]">
          <span className="text-white/30">Scan parallelo · 12 path standard · timeout 8s/path</span>
          <button onClick={onRetry} disabled={running} className="px-2 py-1 rounded bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 text-[10px] font-bold border border-cyan-500/30 disabled:opacity-40" data-testid="web-console-probe-retry">
            Riscansiona
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==================== QUICK ACCESS ==================== */

function QuickAccessDrawer() {
  const { open, openPopup, toggleQuickAccess } = useWebConsoleTabs();
  const [tab, setTab] = useState("recent");
  const [recent, setRecent] = useState([]);
  const [favorites, setFavorites] = useState([]);
  const [live, setLive] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2, r3] = await Promise.allSettled([
        axios.get(`${API}/web-console/recent?limit=15`),
        axios.get(`${API}/web-console/favorites`),
        axios.get(`${API}/web-console/live-sessions`),
      ]);
      if (r1.status === "fulfilled") setRecent(r1.value.data?.items || []);
      if (r2.status === "fulfilled") setFavorites(r2.value.data?.items || []);
      if (r3.status === "fulfilled") setLive(r3.value.data?.items || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const toggleFav = async (deviceIp) => {
    try {
      await axios.post(`${API}/web-console/favorites/toggle`, { device_ip: deviceIp });
      refresh();
    } catch (e) { alert("Toggle preferito fallito: " + (e.response?.data?.detail || e.message)); }
  };

  const isFavorite = (ip) => favorites.some(f => f.device_ip === ip);

  const list = tab === "recent" ? recent : tab === "fav" ? favorites : live;

  return (
    <div className="fixed inset-0 z-[55] flex justify-end" onClick={toggleQuickAccess}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div className="relative w-full max-w-md h-full bg-[#0d0d12] border-l border-[#2a2a3e] shadow-2xl flex flex-col" onClick={e => e.stopPropagation()} data-testid="quick-access-drawer">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e1e2e]">
          <div className="flex items-center gap-2">
            <Star size={16} className="text-indigo-400" weight="fill" />
            <h3 className="text-sm font-bold text-white">Quick Access</h3>
          </div>
          <button onClick={toggleQuickAccess} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white">
            <X size={16} />
          </button>
        </div>
        <div className="flex border-b border-[#1e1e2e]">
          {[
            { id: "recent", label: "Recenti", icon: Clock, count: recent.length },
            { id: "fav", label: "Preferiti", icon: Star, count: favorites.length },
            { id: "live", label: "Live", icon: Users, count: live.length },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-[11px] font-bold transition-colors ${
                tab === t.id ? "bg-indigo-500/10 text-indigo-400 border-b-2 border-indigo-500" : "text-white/40 hover:text-white/70 hover:bg-white/5"
              }`}
              data-testid={`quick-access-tab-${t.id}`}>
              <t.icon size={12} />
              {t.label}
              <span className="text-[9px] opacity-60">({t.count})</span>
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading ? (
            <div className="text-center py-8"><div className="w-6 h-6 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin mx-auto" /></div>
          ) : list.length === 0 ? (
            <div className="text-center py-12 text-white/40">
              <Globe size={32} className="mx-auto mb-3 opacity-30" />
              <p className="text-xs">
                {tab === "recent" ? "Nessuna console recente" : tab === "fav" ? "Nessun preferito. Clicca ⭐ per aggiungere." : "Nessuna sessione live"}
              </p>
            </div>
          ) : list.map((item, i) => (
            <QuickAccessItem key={`${item.device_ip}-${i}`} item={item} tab={tab}
              isFavorite={isFavorite(item.device_ip)}
              onOpen={() => { open(item.client_id, item.device_ip, item.port); }}
              onOpenPopup={() => { openPopup(item.device_ip); }}
              onToggleFav={() => toggleFav(item.device_ip)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function QuickAccessItem({ item, tab, isFavorite, onOpen, onOpenPopup, onToggleFav }) {
  return (
    <div className="group bg-[#12121a] border border-[#1e1e2e] hover:border-indigo-500/30 rounded-lg p-3 flex items-start gap-2 transition-all">
      <button onClick={onToggleFav} className={`p-1 rounded ${isFavorite ? "text-amber-400" : "text-white/20 hover:text-amber-400 opacity-0 group-hover:opacity-100 transition-opacity"}`} title={isFavorite ? "Rimuovi preferito" : "Aggiungi preferito"} data-testid={`fav-toggle-${item.device_ip}`}>
        <Star size={14} weight={isFavorite ? "fill" : "regular"} />
      </button>
      <div className="flex-1 min-w-0 cursor-pointer" onClick={onOpen} data-testid={`quick-open-${item.device_ip}`}>
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-bold text-white font-mono truncate">{item.device_ip}:{item.port || 443}</span>
          {item.device_type && <span className="text-[9px] uppercase text-indigo-400/80 font-mono">{item.device_type}</span>}
        </div>
        {item.device_name && <p className="text-[11px] text-white/60 truncate mt-0.5">{item.device_name}</p>}
        <div className="flex items-center gap-3 mt-1 text-[9px] text-white/30 font-mono">
          {item.client_name && <span>🏢 {item.client_name}</span>}
          {tab === "recent" && item.started_at && <span>🕐 {formatRelative(item.started_at)}</span>}
          {tab === "live" && item.user_email && <span><Eye size={9} className="inline" /> {item.user_email}</span>}
          {tab === "recent" && item.recorded && <span className="text-red-400">● REC</span>}
        </div>
      </div>
      {onOpenPopup && (
        <button
          onClick={(e) => { e.stopPropagation(); onOpenPopup(); }}
          className="flex-shrink-0 px-2 py-1 rounded bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 text-[10px] font-bold border border-indigo-500/20 transition-colors"
          title="Apri in nuova tab (Popup V4 — bypassa iframe blocks)"
          data-testid={`quick-popup-${item.device_ip}`}
        >
          <ArrowSquareOut size={12} className="inline mr-1" />V4
        </button>
      )}
    </div>
  );
}

function formatRelative(iso) {
  try {
    const then = new Date(iso).getTime();
    const delta = Math.floor((Date.now() - then) / 1000);
    if (delta < 60) return `${delta}s fa`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m fa`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h fa`;
    return `${Math.floor(delta / 86400)}g fa`;
  } catch { return iso; }
}

/* ==================== SHARE MODAL ==================== */

function ShareSessionModal({ session, onClose }) {
  const [ttl, setTtl] = useState(15);
  const [password, setPassword] = useState("");
  const [shareLink, setShareLink] = useState(null);
  const [shareToken, setShareToken] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  const create = async () => {
    setLoading(true); setError(null);
    try {
      const res = await axios.post(`${API}/web-console/share/${session.sessionId}`, {
        ttl_minutes: ttl, password: password || null,
      });
      const token = res.data?.share_token;
      setShareToken(token);
      setShareLink(`${window.location.origin}/shared-console/${token}`);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };

  const revoke = async () => {
    if (!shareToken) return;
    try {
      await axios.delete(`${API}/web-console/share/${shareToken}`);
      setShareLink(null); setShareToken(null);
    } catch (e) { setError(e.response?.data?.detail || e.message); }
  };

  const copy = () => {
    if (!shareLink) return;
    navigator.clipboard.writeText(shareLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[#12121a] border border-[#2a2a3e] rounded-xl w-full max-w-md p-5 shadow-2xl" onClick={e => e.stopPropagation()} data-testid="share-session-modal">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Share size={18} className="text-purple-400" />
            <h3 className="text-sm font-bold text-white">Condividi sessione</h3>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/5 text-white/40"><X size={14} /></button>
        </div>

        {!shareLink ? (
          <>
            <p className="text-[11px] text-white/50 mb-4 leading-relaxed">
              Genera un link temporaneo read-only della console <b className="text-white/80 font-mono">{session.deviceIp}:{session.port}</b>.
              Chi riceve il link può vedere l'iframe live SENZA login ARGUS.
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-bold text-white/60 uppercase mb-1 block">Scadenza</label>
                <select value={ttl} onChange={e => setTtl(Number(e.target.value))}
                  className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded-lg px-3 py-2 text-[12px] text-white focus:border-indigo-500 outline-none"
                  data-testid="share-ttl-select">
                  <option value={5}>5 minuti</option>
                  <option value={15}>15 minuti</option>
                  <option value={30}>30 minuti</option>
                  <option value={60}>60 minuti</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] font-bold text-white/60 uppercase mb-1 block">Password (opzionale)</label>
                <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                  placeholder="Lascia vuoto per link aperto"
                  className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded-lg px-3 py-2 text-[12px] text-white placeholder-white/20 focus:border-indigo-500 outline-none"
                  data-testid="share-password-input" />
              </div>
            </div>
            {error && <p className="text-[11px] text-red-400 mt-3">{error}</p>}
            <div className="flex gap-2 mt-4">
              <button onClick={onClose} className="flex-1 px-3 py-2 rounded-lg bg-white/5 text-white/60 hover:bg-white/10 text-[12px] font-bold">Annulla</button>
              <button onClick={create} disabled={loading}
                className="flex-1 px-3 py-2 rounded-lg bg-purple-500/20 text-purple-400 border border-purple-500/30 hover:bg-purple-500/30 text-[12px] font-bold disabled:opacity-50"
                data-testid="share-create-btn">
                {loading ? "Generazione..." : "Genera link"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3 mb-3">
              <p className="text-[11px] text-emerald-400 font-bold mb-2">✓ Link generato (valido {ttl} min)</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 bg-[#0d0d12] text-[10px] text-white/80 font-mono break-all p-2 rounded border border-[#1e1e2e]">{shareLink}</code>
                <button onClick={copy} className={`p-2 rounded ${copied ? "bg-emerald-500/20 text-emerald-400" : "bg-white/5 text-white/40 hover:text-white hover:bg-white/10"}`} title="Copia" data-testid="share-copy-btn">
                  <Copy size={14} />
                </button>
              </div>
              {password && <p className="text-[10px] text-amber-400 mt-2">🔒 Richiede password per accedere</p>}
            </div>
            <div className="flex gap-2">
              <button onClick={revoke} className="flex-1 px-3 py-2 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 text-[12px] font-bold" data-testid="share-revoke-btn">
                Revoca
              </button>
              <button onClick={onClose} className="flex-1 px-3 py-2 rounded-lg bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/30 text-[12px] font-bold">
                Fatto
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
