import { useEffect, useRef, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { X, ArrowsOutSimple, Cursor, ArrowClockwise, Keyboard } from "@phosphor-icons/react";

/**
 * RemoteBrowserModal — HTTP/SSE version (no WebSocket).
 *
 * Opens EventSource to /api/console-rmt/stream/{token} for incoming frames + status,
 * and POSTs input events to /api/console-rmt/input/{token}.
 *
 * Funziona su qualunque ingress HTTP standard, senza necessità di abilitare WS upgrade
 * sul dominio custom.
 */
export function RemoteBrowserModal({ session, onClose }) {
  const canvasRef = useRef(null);
  const esRef = useRef(null);
  const tokenRef = useRef(null);
  const [state, setState] = useState("connecting"); // connecting|upgrade|error|ready|streaming|closed
  const [message, setMessage] = useState("Apertura sessione Remote Browser...");
  const [fullscreen, setFullscreen] = useState(false);
  const [kbOpen, setKbOpen] = useState(false);
  const [frameCount, setFrameCount] = useState(0);
  const [lastFrameTs, setLastFrameTs] = useState(null);

  // Establish session + SSE stream
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        // 1. Create session
        const res = await axios.post(`${API}/console-rmt/session`, {
          device_ip: session.deviceIp,
          port: session.port,
        });
        if (cancelled) return;
        const { token, connector_supported, connector_offline, connector_version, required_version } = res.data;
        tokenRef.current = token;

        if (connector_offline) {
          setState("error");
          setMessage("Il connector è offline. Accendi il PC del cliente e riprova.");
          return;
        }
        if (!connector_supported) {
          setState("upgrade");
          setMessage(
            `Remote Browser richiede connector v${required_version}+ (installato: v${connector_version || "sconosciuta"}). ` +
            `Aggiorna dal menu "Connettori" del Center.`
          );
          return;
        }

        // 2. Open SSE stream
        const url = `${API}/console-rmt/stream/${token}`;
        const es = new EventSource(url, { withCredentials: false });
        esRef.current = es;

        es.onopen = () => setMessage("Connesso al backend, in attesa del connector...");
        es.onerror = () => {
          if (cancelled) return;
          // EventSource auto-reconnects; mark error only if nothing ever arrived
          if (state === "connecting") {
            setState("error");
            setMessage("Errore di connessione SSE. Verifica che il dominio supporti Server-Sent Events.");
          }
        };
        es.onmessage = (ev) => {
          if (cancelled) return;
          try {
            const m = JSON.parse(ev.data);
            handleMessage(m);
          } catch {
            // ignore non-JSON (pings)
          }
        };
      } catch (e) {
        if (cancelled) return;
        setState("error");
        setMessage(e?.response?.data?.detail || e.message || "Errore sessione");
      }
    };
    run();
    return () => {
      cancelled = true;
      if (esRef.current) {
        try { esRef.current.close(); } catch {}
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.deviceIp, session.port]);

  const handleMessage = useCallback((m) => {
    if (m.type === "ready") {
      setState("ready");
      setMessage(m.msg || "Session pronta, in attesa del primo frame...");
      return;
    }
    if (m.type === "upgrade_required") {
      setState("upgrade");
      setMessage(m.msg);
      return;
    }
    if (m.type === "error") {
      setState("error");
      setMessage(m.msg);
      return;
    }
    if (m.type === "closed") {
      setState("closed");
      setMessage(m.msg || "Sessione chiusa");
      return;
    }
    if (m.type === "frame" && m.data) {
      setState("streaming");
      drawFrame(m.data);
      setFrameCount((c) => c + 1);
      setLastFrameTs(Date.now());
    }
  }, []);

  const drawFrame = useCallback((b64) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const img = new Image();
    img.onload = () => {
      if (canvas.width !== img.width) canvas.width = img.width;
      if (canvas.height !== img.height) canvas.height = img.height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0);
    };
    img.src = `data:image/jpeg;base64,${b64}`;
  }, []);

  const sendEvent = useCallback((evt) => {
    const token = tokenRef.current;
    if (!token) return;
    // Fire-and-forget POST
    axios.post(`${API}/console-rmt/input/${token}`, evt).catch(() => {});
  }, []);

  const onCanvasMouseMove = useCallback((e) => {
    if (state !== "streaming") return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.round(((e.clientX - r.left) / r.width) * (canvasRef.current?.width || 1600));
    const y = Math.round(((e.clientY - r.top) / r.height) * (canvasRef.current?.height || 900));
    sendEvent({ type: "mouse", event: "move", x, y });
  }, [state, sendEvent]);

  const onCanvasMouseDown = useCallback((e) => {
    if (state !== "streaming") return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.round(((e.clientX - r.left) / r.width) * (canvasRef.current?.width || 1600));
    const y = Math.round(((e.clientY - r.top) / r.height) * (canvasRef.current?.height || 900));
    const btnMap = { 0: "left", 1: "middle", 2: "right" };
    sendEvent({ type: "mouse", event: "down", x, y, button: btnMap[e.button] || "left" });
  }, [state, sendEvent]);

  const onCanvasMouseUp = useCallback((e) => {
    if (state !== "streaming") return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.round(((e.clientX - r.left) / r.width) * (canvasRef.current?.width || 1600));
    const y = Math.round(((e.clientY - r.top) / r.height) * (canvasRef.current?.height || 900));
    const btnMap = { 0: "left", 1: "middle", 2: "right" };
    sendEvent({ type: "mouse", event: "up", x, y, button: btnMap[e.button] || "left" });
  }, [state, sendEvent]);

  const onCanvasWheel = useCallback((e) => {
    if (state !== "streaming") return;
    sendEvent({ type: "scroll", dx: e.deltaX, dy: e.deltaY });
  }, [state, sendEvent]);

  useEffect(() => {
    if (state !== "streaming") return;
    const onKey = (e) => {
      if (e.key === "Escape") { onClose(); return; }
      e.preventDefault();
      sendEvent({
        type: "key",
        event: e.type === "keydown" ? "down" : "up",
        key: e.key,
        code: e.code,
        mods: { ctrl: e.ctrlKey, shift: e.shiftKey, alt: e.altKey, meta: e.metaKey },
      });
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
    };
  }, [state, sendEvent, onClose]);

  const containerCls = fullscreen
    ? "fixed inset-0 z-[80] flex flex-col bg-black overflow-hidden"
    : "fixed inset-0 md:inset-4 z-[80] flex flex-col bg-[#0d0d12] md:rounded-2xl overflow-hidden border border-fuchsia-500/40 shadow-2xl shadow-fuchsia-900/30";

  return (
    <div className={containerCls} data-testid="rmt-modal">
      <div className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-[#1a0d1f] to-[#12121a] border-b border-fuchsia-500/30 flex-shrink-0">
        <div className="flex items-center gap-1.5 mr-2">
          <button onClick={onClose} className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400" title="Chiudi" data-testid="rmt-close" />
          <button onClick={() => setFullscreen((f) => !f)} className="w-3 h-3 rounded-full bg-emerald-500 hover:bg-emerald-400" title="Fullscreen" />
        </div>
        <span className="text-fuchsia-400 text-[10px] font-bold font-mono bg-fuchsia-500/10 border border-fuchsia-500/30 px-2 py-0.5 rounded">RMT</span>
        <span className="text-white/80 text-xs font-mono">{session.deviceIp}:{session.port}</span>
        <span className="text-white/30 text-[10px]">Remote Browser · SSE/HTTP</span>
        <div className="flex-1" />
        {state === "streaming" && (
          <>
            <span className="text-[9px] font-mono text-emerald-400/80">● {frameCount} frames</span>
            <button
              onClick={() => setKbOpen((o) => !o)}
              className={`p-1.5 rounded ${kbOpen ? "bg-fuchsia-500/20 text-fuchsia-300" : "hover:bg-white/5 text-white/40 hover:text-white/80"}`}
              title="Tastiera on-screen"
              data-testid="rmt-kb-toggle"
            >
              <Keyboard size={14} />
            </button>
          </>
        )}
        <button onClick={() => setFullscreen((f) => !f)} className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/80" title="Fullscreen">
          <ArrowsOutSimple size={14} />
        </button>
      </div>

      <div className="flex-1 flex items-center justify-center bg-black overflow-hidden relative">
        {state !== "streaming" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-10 bg-black/90 backdrop-blur-sm">
            {state === "connecting" || state === "ready" ? (
              <>
                <div className="relative mb-4">
                  <div className="w-14 h-14 rounded-full border-2 border-fuchsia-500/20 border-t-fuchsia-500 animate-spin" />
                  <Cursor size={22} className="text-fuchsia-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
                </div>
                <p className="text-fuchsia-200/80 text-sm max-w-md text-center px-6">{message}</p>
              </>
            ) : state === "upgrade" ? (
              <div className="text-center max-w-xl px-8">
                <div className="w-16 h-16 rounded-full bg-amber-500/10 border border-amber-500/30 flex items-center justify-center mx-auto mb-4">
                  <ArrowClockwise size={28} className="text-amber-400" />
                </div>
                <h2 className="text-amber-300 text-lg font-bold mb-3">Aggiornamento connector richiesto</h2>
                <p className="text-white/70 text-xs leading-relaxed">{message}</p>
                <button
                  onClick={() => { window.location.href = "/connectors"; }}
                  className="mt-5 px-4 py-2 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-medium rounded"
                  data-testid="rmt-goto-connectors"
                >
                  Vai a Connettori →
                </button>
              </div>
            ) : state === "error" ? (
              <div className="text-center max-w-xl px-8">
                <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center mx-auto mb-4">
                  <X size={28} className="text-red-400" />
                </div>
                <h2 className="text-red-300 text-lg font-bold mb-3">Errore</h2>
                <p className="text-white/70 text-xs leading-relaxed">{message}</p>
              </div>
            ) : (
              <p className="text-white/50 text-sm">{message}</p>
            )}
          </div>
        )}
        <canvas
          ref={canvasRef}
          className="max-w-full max-h-full object-contain cursor-crosshair"
          onMouseMove={onCanvasMouseMove}
          onMouseDown={onCanvasMouseDown}
          onMouseUp={onCanvasMouseUp}
          onWheel={onCanvasWheel}
          onContextMenu={(e) => e.preventDefault()}
          data-testid="rmt-canvas"
        />
      </div>

      <div className="flex items-center justify-between px-3 py-1 border-t border-fuchsia-500/20 bg-[#0f0a10] flex-shrink-0 text-[9px] font-mono">
        <div className="flex items-center gap-3 text-white/40">
          <span>Session: {session.deviceIp}:{session.port}</span>
          <span className="text-fuchsia-400/70">CDP screencast via HTTP</span>
          {lastFrameTs && <span>last: {Math.round((Date.now() - lastFrameTs) / 100) / 10}s ago</span>}
        </div>
        <span className={`${state === "streaming" ? "text-emerald-400/80" : state === "error" ? "text-red-400/80" : "text-white/30"}`}>
          {state.toUpperCase()}
        </span>
      </div>
    </div>
  );
}

export default RemoteBrowserModal;
