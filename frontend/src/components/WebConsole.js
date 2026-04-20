import { useState, useRef, useCallback, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Monitor, Globe, ArrowClockwise, X, CircleNotch, ShieldCheck, Warning,
} from "@phosphor-icons/react";

/**
 * useWebConsole — hook centralizzato per aprire la Web Console di un device
 * tramite il connettore PowerShell.
 *
 * Strategia velocità:
 *  - 1 POST `/web-proxy/request` → ottiene request_id
 *  - 1 GET `/web-proxy/response/{id}?wait=25` (long-poll) → ritorna entro 50ms dal completamento
 *  - Nessun setInterval: hot-trigger server-side + HTTP long-poll = latenza minima.
 */
export function useWebConsole() {
  const [state, setState] = useState(null);
  const abortRef = useRef(null);

  const close = useCallback(() => {
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch {}
      abortRef.current = null;
    }
    setState(null);
  }, []);

  const open = useCallback(async (clientId, deviceIp, port = 80, path = "/") => {
    // Abort previous pending request (if any)
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch {}
    }
    const controller = new AbortController();
    abortRef.current = controller;

    const t0 = performance.now();
    setState({
      clientId, deviceIp, port: port || 80, path: path || "/",
      loading: true, html: null,
      title: `${deviceIp}:${port}`,
      progress: 10,
    });

    try {
      const reqRes = await axios.post(
        `${API}/connector/web-proxy/request`,
        { client_id: clientId, device_ip: deviceIp, port: port || 80, path: path || "/", method: "GET" },
        { signal: controller.signal }
      );
      const requestId = reqRes.data?.request_id;
      if (!requestId) throw new Error("Backend non ha restituito un request_id valido");
      setState(prev => prev ? { ...prev, progress: 30 } : null);

      // Single long-poll GET — server risponde appena il connector pubblica la response
      const resp = await axios.get(
        `${API}/connector/web-proxy/response/${requestId}?wait=25`,
        { signal: controller.signal, timeout: 30000 }
      );
      const loadTime = performance.now() - t0;

      if (resp.data.status !== "completed" || !resp.data.response) {
        let hint = "Verifica che il servizio <b>86NocConnector</b> sia attivo sulla rete del cliente.";
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
              hint = `Per usare la Web Console serve il connector <b>v3.0.3 o superiore</b>. Aggiorna tramite icona tray oppure reinstalla con il wizard.`;
            }
          }
        } catch (_) { /* ignore */ }
        setState(prev => prev ? {
          ...prev,
          loading: false, progress: 100,
          html: `<div style="padding:40px;text-align:center;font-family:system-ui"><h2 style="color:#FF3B30;margin-bottom:12px">${errorLabel}</h2><p style="color:#888;line-height:1.6">${hint}</p></div>`,
          error: errorLabel,
          loadTime,
        } : null);
        return;
      }

      setState(prev => prev ? {
        ...prev,
        loading: false, progress: 100,
        html: resp.data.response.body,
        title: resp.data.response.title || `${deviceIp}:${port}${path}`,
        error: resp.data.response.error,
        loadTime,
      } : null);
    } catch (e) {
      if (axios.isCancel(e) || e.name === "CanceledError" || e.name === "AbortError") return;
      const loadTime = performance.now() - t0;
      const status = e.response?.status;
      const detail = e.response?.data?.detail;
      let errLabel = detail || e.message || "Errore sconosciuto";
      let html = `<div style="padding:40px;text-align:center;font-family:system-ui"><h2 style="color:#FF3B30;margin-bottom:12px">Errore</h2><p style="color:#888;line-height:1.6">${errLabel}</p></div>`;
      if (status === 403 && /not authorized/i.test(detail || "")) {
        errLabel = "Dispositivo non censito";
        html = `<div style="padding:40px;text-align:center;font-family:system-ui;max-width:480px;margin:0 auto"><h2 style="color:#FF3B30;margin-bottom:12px">Dispositivo non censito</h2><p style="color:#aaa;line-height:1.6">Il dispositivo <b style="color:#fff">${deviceIp}:${port}</b> non risulta registrato per questo cliente.</p><p style="color:#888;line-height:1.6;margin-top:12px">Aggiungilo da <b>Cliente → Dispositivi → + Aggiungi</b>, o attendi la discovery SNMP del connector.</p></div>`;
      } else if (status === 401) {
        errLabel = "Sessione scaduta";
      } else if (status === 404) {
        errLabel = "Richiesta scaduta o non trovata";
      }
      setState(prev => prev ? {
        ...prev,
        loading: false, progress: 100,
        html, error: errLabel, loadTime,
      } : null);
    }
  }, []);

  // Progress pulse mentre caricamento è in corso (semplice visual feedback)
  useEffect(() => {
    if (!state?.loading) return;
    const iv = setInterval(() => {
      setState(prev => (prev && prev.loading && prev.progress < 95)
        ? { ...prev, progress: Math.min(95, prev.progress + 3) } : prev);
    }, 200);
    return () => clearInterval(iv);
  }, [state?.loading]);

  // Listen for proxy-navigate messages from iframe content (click su link interni)
  useEffect(() => {
    const handler = (event) => {
      if (event.data?.type === "proxy-navigate" && state) {
        let path = event.data.path;
        if (event.data.baseUrl && path.startsWith(event.data.baseUrl)) {
          path = path.replace(event.data.baseUrl, "");
        }
        if (!path.startsWith("/")) path = "/" + path;
        open(state.clientId, state.deviceIp, state.port, path);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [state, open]);

  return { state, open, close };
}

/**
 * Componente modale Web Console (UI only, usa lo stato del hook).
 */
export function WebConsoleModal({ state, onClose, onReload }) {
  if (!state) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 md:p-3" data-testid="web-console-modal">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-md" onClick={onClose}></div>
      <div className="relative w-full max-w-7xl h-[95vh] md:h-[90vh] bg-[#0d0d12] rounded-xl border border-[#1e1e2e] shadow-2xl shadow-black/50 flex flex-col overflow-hidden">

        {/* Title Bar */}
        <div className="flex items-center justify-between px-3 md:px-4 py-2 border-b border-[#1e1e2e] bg-[#12121a] flex-shrink-0">
          <div className="flex items-center gap-2 md:gap-3">
            <div className="flex gap-1.5">
              <div className="w-3 h-3 rounded-full bg-red-500/80 cursor-pointer hover:bg-red-500" onClick={onClose}></div>
              <div className="w-3 h-3 rounded-full bg-yellow-500/80"></div>
              <div className="w-3 h-3 rounded-full bg-green-500/80"></div>
            </div>
            <Monitor size={15} className="text-indigo-400 ml-1 md:ml-2" />
            <span className="text-[11px] font-bold text-white/90">Web Console</span>
          </div>
          <div className="flex items-center gap-2">
            {!state.loading && state.loadTime && (
              <span className="text-[9px] text-white/30 font-mono">{(state.loadTime / 1000).toFixed(2)}s</span>
            )}
            <button onClick={onClose} className="w-7 h-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors" data-testid="web-console-close">
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
              {state.port === 443 ? "https" : "http"}://{state.deviceIp}:{state.port}{state.path}
            </span>
            {state.loading && <CircleNotch size={12} className="text-indigo-400 animate-spin ml-auto flex-shrink-0" />}
            {!state.loading && !state.error && <ShieldCheck size={12} className="text-emerald-400 ml-auto flex-shrink-0" />}
          </div>
          <span className="text-[9px] px-2 py-1 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold whitespace-nowrap hidden sm:inline-block">
            via Connector
          </span>
        </div>

        {/* Progress Bar */}
        {state.loading && (
          <div className="h-0.5 bg-[#1e1e2e] flex-shrink-0">
            <div className="h-full bg-indigo-500 transition-all duration-300 ease-out" style={{ width: `${state.progress || 0}%` }}></div>
          </div>
        )}

        {/* Content Area */}
        <div className="flex-1 bg-white overflow-auto">
          {state.loading ? (
            <div className="flex flex-col items-center justify-center h-full gap-4 bg-[#0d0d12]">
              <div className="relative">
                <div className="w-12 h-12 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin"></div>
                <Monitor size={20} className="text-indigo-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
              </div>
              <div className="text-center">
                <p className="text-white/70 text-sm font-medium">Connessione in corso...</p>
                <p className="text-white/30 text-xs mt-1">{state.deviceIp}:{state.port}{state.path}</p>
                <p className="text-white/20 text-[10px] mt-2 font-mono">Long-poll via 86NocConnector</p>
              </div>
            </div>
          ) : state.error ? (
            <div className="flex items-center justify-center h-full bg-[#0d0d12] p-6 md:p-8">
              <div className="text-center max-w-md">
                <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                  <Warning size={28} className="text-red-400" />
                </div>
                <p className="text-red-400 font-bold text-lg mb-2">Connessione Fallita</p>
                <p className="text-white/40 text-sm">{state.error}</p>
                <button onClick={onReload}
                  className="mt-4 px-4 py-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-xs font-bold hover:bg-indigo-500/20 transition-colors">
                  Riprova
                </button>
              </div>
            </div>
          ) : (
            <iframe srcDoc={state.html} className="w-full h-full border-0" title="Web Console" sandbox="allow-same-origin" />
          )}
        </div>

        {/* Status Bar */}
        <div className="flex items-center justify-between px-3 py-1 border-t border-[#1e1e2e] bg-[#0f0f17] flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-[9px] text-white/30 font-mono">{state.deviceIp}</span>
            {state.title && state.title !== `${state.deviceIp}:${state.port}` && (
              <span className="text-[9px] text-white/20 truncate max-w-[180px]">{state.title}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full ${state.loading ? "bg-amber-400 animate-pulse" : state.error ? "bg-red-400" : "bg-emerald-400"}`}></span>
            <span className="text-[9px] text-white/30">{state.loading ? "Caricamento..." : state.error ? "Errore" : "Connesso"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Determina se un device può essere aperto via Web Console.
 * Regole: device online/active + tipi tipicamente dotati di interfaccia web.
 */
export function canOpenWebConsole(device) {
  if (!device) return false;
  const status = (device.status || "").toLowerCase();
  if (status !== "online" && status !== "active") return false;
  const type = (device.device_type || "").toLowerCase();
  const webTypes = ["firewall", "switch", "router", "access-point", "access_point", "ap", "printer", "ilo", "server", "nas", "ups"];
  return webTypes.includes(type) || (device.monitor_type || "").toLowerCase() === "http";
}

/**
 * Porta web di default per tipo di dispositivo.
 * Priority: web_console_port (rilevato dal tray) > http_port (manuale) > device_type default
 */
export function defaultWebPort(device) {
  if (device?.web_console_port) return device.web_console_port;
  if (device?.http_port) return device.http_port;
  const type = (device?.device_type || "").toLowerCase();
  // HTTPS default: iLO, firewall, switch (HP/Aruba/Cisco/Zyxel usano 443), access-point, UPS moderni
  if (["ilo", "firewall", "switch", "router", "access-point", "ups"].includes(type)) return 443;
  return 80;
}

/**
 * Schema web di default (http / https)
 */
export function defaultWebScheme(device) {
  if (device?.web_console_scheme) return device.web_console_scheme;
  const port = defaultWebPort(device);
  return [443, 8443, 4443].includes(port) ? "https" : "http";
}
