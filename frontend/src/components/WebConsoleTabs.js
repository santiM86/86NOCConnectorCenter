import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Monitor, Globe, ArrowClockwise, X, CircleNotch, ShieldCheck, Warning,
  Minus, CaretLeft, CaretRight,
} from "@phosphor-icons/react";

/**
 * WebConsoleTabs — Multi-session manager per la Web Console.
 * Ogni tab è una sessione indipendente (long-poll separato), persistente
 * tra cambi di pagina. Dock flottante in basso + modal attiva.
 */

const WebConsoleContext = createContext(null);

export function useWebConsoleTabs() {
  const ctx = useContext(WebConsoleContext);
  if (!ctx) throw new Error("useWebConsoleTabs must be used within WebConsoleTabsProvider");
  return ctx;
}

function uuidv4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === "x" ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

export function WebConsoleTabsProvider({ children }) {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [minimized, setMinimized] = useState(false);
  const abortsRef = useRef({});
  const sessionsRef = useRef([]);

  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  const updateSession = useCallback((id, patch) => {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, ...patch } : s));
  }, []);

  const _runSession = useCallback(async (id, clientId, deviceIp, port, path, controller) => {
    const t0 = performance.now();
    try {
      const reqRes = await axios.post(
        `${API}/connector/web-proxy/request`,
        { client_id: clientId, device_ip: deviceIp, port: port || 80, path: path || "/", method: "GET" },
        { signal: controller.signal }
      );
      const requestId = reqRes.data?.request_id;
      if (!requestId) {
        throw new Error("Backend non ha restituito un request_id valido");
      }
      updateSession(id, { progress: 30, requestId });

      const resp = await axios.get(
        `${API}/connector/web-proxy/response/${requestId}?wait=25`,
        { signal: controller.signal, timeout: 30000 }
      );
      const loadTime = performance.now() - t0;

      if (resp.data.status !== "completed" || !resp.data.response) {
        // Long-poll scaduto: connector non ha risposto. Controllo lo stato del connector
        // per dare un messaggio piu' preciso all'utente.
        let hint = "Verifica che il servizio <b>86NocConnector</b> sia attivo sulla rete del cliente e il dispositivo raggiungibile.";
        let errorLabel = "Connettore non risponde";
        try {
          const st = await axios.get(`${API}/connector/status`);
          const row = Array.isArray(st.data) ? st.data.find(r => r.client_id === clientId) : null;
          if (row) {
            const v = row.connector_version || "?";
            const isOld = /^(1\.|2\.|3\.0\.[0-2]$)/.test(v);
            if (row.is_offline) {
              errorLabel = `Connettore OFFLINE (ultimo contatto: ${row.last_seen ? new Date(row.last_seen).toLocaleString("it-IT") : "sconosciuto"})`;
              hint = `Il connector <b>${row.hostname || ""}</b> (v${v}) risulta offline. Avvia il servizio <b>86NocConnector</b> sulla macchina del cliente.`;
            } else if (isOld) {
              errorLabel = `Connettore v${v} troppo vecchio`;
              hint = `Per usare la Web Console serve il connector <b>v3.0.3 o superiore</b>. Aggiorna tramite l'icona tray → Aggiorna Connector, oppure reinstalla con il wizard.`;
            }
          }
        } catch (_) { /* ignore status check errors */ }
        updateSession(id, {
          loading: false, progress: 100,
          html: `<div style="padding:40px;text-align:center;font-family:system-ui"><h2 style="color:#FF3B30;margin-bottom:12px">${errorLabel}</h2><p style="color:#888;line-height:1.6">${hint}</p></div>`,
          error: errorLabel,
          loadTime,
        });
        return;
      }

      updateSession(id, {
        loading: false, progress: 100,
        html: resp.data.response.body,
        title: resp.data.response.title || `${deviceIp}:${port}${path}`,
        error: resp.data.response.error,
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
        html = `<div style="padding:40px;text-align:center;font-family:system-ui;max-width:480px;margin:0 auto">
          <h2 style="color:#FF3B30;margin-bottom:12px">Dispositivo non censito</h2>
          <p style="color:#aaa;line-height:1.6">Il dispositivo <b style="color:#fff">${deviceIp}:${port}</b> non risulta registrato per questo cliente.</p>
          <p style="color:#888;line-height:1.6;margin-top:12px">Aggiungilo dalla pagina <b>Cliente → Dispositivi → + Aggiungi Dispositivo</b>, oppure attendi che il connector lo scopra via SNMP discovery.</p>
        </div>`;
      } else if (status === 401) {
        errLabel = "Sessione scaduta";
      } else if (status === 404) {
        errLabel = "Richiesta scaduta o non trovata";
      }

      updateSession(id, {
        loading: false, progress: 100,
        html, error: errLabel, loadTime,
      });
    } finally {
      delete abortsRef.current[id];
    }
  }, [updateSession]);

  const open = useCallback((clientId, deviceIp, port = 80, path = "/") => {
    // Refocus esistente se già aperta la stessa combinazione
    const existing = sessionsRef.current.find(
      s => s.clientId === clientId && s.deviceIp === deviceIp && s.port === (port || 80)
    );
    if (existing) {
      setActiveId(existing.id);
      setMinimized(false);
      return existing.id;
    }

    const id = uuidv4();
    const controller = new AbortController();
    abortsRef.current[id] = controller;

    const newSession = {
      id, clientId, deviceIp, port: port || 80, path: path || "/",
      loading: true, progress: 10, html: null, title: `${deviceIp}:${port}`,
      error: null, loadTime: null, requestId: null,
    };
    setSessions(prev => [...prev, newSession]);
    setActiveId(id);
    setMinimized(false);
    _runSession(id, clientId, deviceIp, port || 80, path || "/", controller);
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

  const navigate = useCallback((id, newPath) => {
    const s = sessionsRef.current.find(x => x.id === id);
    if (!s) return;
    if (abortsRef.current[id]) { try { abortsRef.current[id].abort(); } catch {} }
    const controller = new AbortController();
    abortsRef.current[id] = controller;
    updateSession(id, { loading: true, progress: 10, html: null, error: null, loadTime: null, path: newPath });
    _runSession(id, s.clientId, s.deviceIp, s.port, newPath, controller);
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

  const setActive = useCallback((id) => {
    setActiveId(id);
    setMinimized(false);
  }, []);

  const minimize = useCallback(() => setMinimized(true), []);
  const closeAll = useCallback(() => {
    Object.values(abortsRef.current).forEach(c => { try { c.abort(); } catch {} });
    abortsRef.current = {};
    setSessions([]);
    setActiveId(null);
  }, []);

  // Listen for proxy-navigate from iframe (click interno al device)
  useEffect(() => {
    const handler = (event) => {
      if (event.data?.type === "proxy-navigate" && activeId) {
        let p = event.data.path;
        if (event.data.baseUrl && p.startsWith(event.data.baseUrl)) p = p.replace(event.data.baseUrl, "");
        if (!p.startsWith("/")) p = "/" + p;
        navigate(activeId, p);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [activeId, navigate]);

  // Progress visual pulse per sessioni in caricamento
  useEffect(() => {
    const anyLoading = sessions.some(s => s.loading && s.progress < 95);
    if (!anyLoading) return;
    const iv = setInterval(() => {
      setSessions(prev => prev.map(s => s.loading && s.progress < 95 ? { ...s, progress: Math.min(95, s.progress + 3) } : s));
    }, 200);
    return () => clearInterval(iv);
  }, [sessions]);

  const value = {
    sessions, activeId, minimized,
    open, close, reload, navigate, setActive, minimize, closeAll,
  };

  const activeSession = sessions.find(s => s.id === activeId);

  return (
    <WebConsoleContext.Provider value={value}>
      {children}
      {/* Dock: sempre visibile quando ci sono sessioni aperte */}
      {sessions.length > 0 && (
        <WebConsoleDock
          sessions={sessions} activeId={activeId}
          minimized={minimized || !activeId}
          onSelect={setActive} onClose={close} onCloseAll={closeAll}
        />
      )}
      {/* Modal: visibile solo se c'è una sessione attiva E non è minimizzata */}
      {activeSession && !minimized && (
        <WebConsoleModal
          session={activeSession}
          onClose={() => minimize()}
          onDestroy={() => close(activeSession.id)}
          onReload={() => reload(activeSession.id)}
          sessionsCount={sessions.length}
          onPrev={() => {
            const idx = sessions.findIndex(s => s.id === activeId);
            if (idx > 0) setActive(sessions[idx - 1].id);
          }}
          onNext={() => {
            const idx = sessions.findIndex(s => s.id === activeId);
            if (idx < sessions.length - 1) setActive(sessions[idx + 1].id);
          }}
          activeIndex={sessions.findIndex(s => s.id === activeId) + 1}
        />
      )}
    </WebConsoleContext.Provider>
  );
}

/* ========== Dock flottante in basso a destra ========== */
function WebConsoleDock({ sessions, activeId, minimized, onSelect, onClose, onCloseAll }) {
  return (
    <div className="fixed bottom-3 right-3 z-40 flex items-center gap-1.5 p-1.5 rounded-xl bg-[#0f0f17]/95 backdrop-blur-md border border-[#1e1e2e] shadow-2xl shadow-black/50 max-w-[calc(100vw-24px)] overflow-x-auto"
      data-testid="web-console-dock">
      <div className="flex items-center gap-1 px-2 text-white/40">
        <Monitor size={12} />
        <span className="text-[9px] font-bold uppercase tracking-wider">Consoles ({sessions.length})</span>
      </div>
      <div className="h-5 w-px bg-white/10" />
      {sessions.map(s => {
        const isActive = s.id === activeId && !minimized;
        const statusDot = s.loading ? "bg-amber-400 animate-pulse"
          : s.error ? "bg-red-400"
          : "bg-emerald-400";
        return (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`group flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors text-[10px] font-mono whitespace-nowrap ${
              isActive
                ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                : "bg-white/5 text-white/60 border border-transparent hover:bg-white/10 hover:text-white"
            }`}
            title={`${s.deviceIp}:${s.port}${s.path}`}
            data-testid={`console-tab-${s.deviceIp}`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
            <span className="max-w-[120px] truncate">{s.deviceIp}:{s.port}</span>
            <span
              onClick={(e) => { e.stopPropagation(); onClose(s.id); }}
              className="w-4 h-4 rounded-sm flex items-center justify-center text-white/30 hover:text-white hover:bg-red-500/30 transition-colors"
              data-testid={`console-tab-close-${s.deviceIp}`}
              role="button"
            >
              <X size={9} weight="bold" />
            </span>
          </button>
        );
      })}
      {sessions.length > 1 && (
        <>
          <div className="h-5 w-px bg-white/10" />
          <button
            onClick={onCloseAll}
            className="px-2 py-1 rounded-md text-[9px] text-white/40 hover:text-red-400 hover:bg-red-500/10 transition-colors font-bold uppercase tracking-wider"
            data-testid="console-close-all"
          >
            Chiudi tutte
          </button>
        </>
      )}
    </div>
  );
}

/* ========== Modal con Prev/Next fra le tabs ========== */
function WebConsoleModal({ session, onClose, onDestroy, onReload, onPrev, onNext, activeIndex, sessionsCount }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 md:p-3" data-testid="web-console-modal">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-md" onClick={onClose}></div>
      <div className="relative w-full max-w-7xl h-[95vh] md:h-[90vh] bg-[#0d0d12] rounded-xl border border-[#1e1e2e] shadow-2xl shadow-black/50 flex flex-col overflow-hidden">

        {/* Title Bar */}
        <div className="flex items-center justify-between px-3 md:px-4 py-2 border-b border-[#1e1e2e] bg-[#12121a] flex-shrink-0">
          <div className="flex items-center gap-2 md:gap-3">
            <div className="flex gap-1.5">
              <div className="w-3 h-3 rounded-full bg-red-500/80 cursor-pointer hover:bg-red-500" onClick={onDestroy} title="Chiudi sessione"></div>
              <div className="w-3 h-3 rounded-full bg-yellow-500/80 cursor-pointer hover:bg-yellow-500" onClick={onClose} title="Minimizza"></div>
              <div className="w-3 h-3 rounded-full bg-green-500/80"></div>
            </div>
            <Monitor size={15} className="text-indigo-400 ml-1 md:ml-2" />
            <span className="text-[11px] font-bold text-white/90">Web Console</span>
            {sessionsCount > 1 && (
              <span className="text-[9px] text-white/30 font-mono">({activeIndex}/{sessionsCount})</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {sessionsCount > 1 && (
              <>
                <button onClick={onPrev} disabled={activeIndex <= 1}
                  className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-30 disabled:hover:bg-transparent"
                  title="Sessione precedente" data-testid="console-prev">
                  <CaretLeft size={12} />
                </button>
                <button onClick={onNext} disabled={activeIndex >= sessionsCount}
                  className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-30 disabled:hover:bg-transparent"
                  title="Sessione successiva" data-testid="console-next">
                  <CaretRight size={12} />
                </button>
              </>
            )}
            {!session.loading && session.loadTime && (
              <span className="text-[9px] text-white/30 font-mono px-1">{(session.loadTime / 1000).toFixed(2)}s</span>
            )}
            <button onClick={onClose} className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors"
              title="Minimizza (resta nel dock)" data-testid="web-console-minimize">
              <Minus size={14} />
            </button>
            <button onClick={onDestroy} className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-red-400 hover:bg-red-500/10 transition-colors"
              title="Chiudi e termina sessione" data-testid="web-console-close">
              <X size={14} />
            </button>
          </div>
        </div>

        {/* URL Bar */}
        <div className="flex items-center gap-2 px-2 md:px-3 py-1.5 border-b border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
          <button onClick={onReload}
            className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors" title="Ricarica">
            <ArrowClockwise size={13} />
          </button>
          <div className="flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#1a1a26] border border-[#2a2a3e] min-w-0">
            <Globe size={12} className="text-white/30 flex-shrink-0" />
            <span className="text-[11px] text-white/60 font-mono truncate">
              {session.port === 443 ? "https" : "http"}://{session.deviceIp}:{session.port}{session.path}
            </span>
            {session.loading && <CircleNotch size={12} className="text-indigo-400 animate-spin ml-auto flex-shrink-0" />}
            {!session.loading && !session.error && <ShieldCheck size={12} className="text-emerald-400 ml-auto flex-shrink-0" />}
          </div>
          <span className="text-[9px] px-2 py-1 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold whitespace-nowrap hidden sm:inline-block">
            via Connector
          </span>
        </div>

        {/* Progress Bar */}
        {session.loading && (
          <div className="h-0.5 bg-[#1e1e2e] flex-shrink-0">
            <div className="h-full bg-indigo-500 transition-all duration-300 ease-out" style={{ width: `${session.progress || 0}%` }}></div>
          </div>
        )}

        {/* Content Area */}
        <div className="flex-1 bg-white overflow-auto">
          {session.loading ? (
            <div className="flex flex-col items-center justify-center h-full gap-4 bg-[#0d0d12]">
              <div className="relative">
                <div className="w-12 h-12 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin"></div>
                <Monitor size={20} className="text-indigo-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
              </div>
              <div className="text-center">
                <p className="text-white/70 text-sm font-medium">Connessione in corso...</p>
                <p className="text-white/30 text-xs mt-1">{session.deviceIp}:{session.port}{session.path}</p>
                <p className="text-white/20 text-[10px] mt-2 font-mono">Long-poll via 86NocConnector</p>
              </div>
            </div>
          ) : session.error ? (
            <div className="flex items-center justify-center h-full bg-[#0d0d12] p-6 md:p-8">
              <div className="text-center max-w-md">
                <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                  <Warning size={28} className="text-red-400" />
                </div>
                <p className="text-red-400 font-bold text-lg mb-2">Connessione Fallita</p>
                <p className="text-white/40 text-sm">{session.error}</p>
                <button onClick={onReload}
                  className="mt-4 px-4 py-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-xs font-bold hover:bg-indigo-500/20 transition-colors">
                  Riprova
                </button>
              </div>
            </div>
          ) : (
            <iframe srcDoc={session.html} className="w-full h-full border-0" title="Web Console" sandbox="allow-same-origin" />
          )}
        </div>

        {/* Status Bar */}
        <div className="flex items-center justify-between px-3 py-1 border-t border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-[9px] text-white/30 font-mono">{session.deviceIp}</span>
            {session.title && session.title !== `${session.deviceIp}:${session.port}` && (
              <span className="text-[9px] text-white/20 truncate max-w-[180px]">{session.title}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full ${session.loading ? "bg-amber-400 animate-pulse" : session.error ? "bg-red-400" : "bg-emerald-400"}`}></span>
            <span className="text-[9px] text-white/30">{session.loading ? "Caricamento..." : session.error ? "Errore" : "Connesso"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
