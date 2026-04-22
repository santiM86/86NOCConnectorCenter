import { useEffect, useRef, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { X, ArrowsOutSimple, Cursor, ArrowClockwise, Keyboard } from "@phosphor-icons/react";

/**
 * RemoteBrowserModal — POLLING version (no SSE, no WebSocket).
 *
 * Frame polling: GET /api/console-rmt/latest-frame/{token}?since=<seq> every 250ms
 * Status polling: GET /api/console-rmt/poll-status/{token} every 1500ms (until streaming)
 * Input: POST /api/console-rmt/input/{token} on events
 *
 * Funziona su qualunque ingress / CDN / dominio custom. Zero streaming deps.
 */
export function RemoteBrowserModal({ session, onClose }) {
  const canvasRef = useRef(null);
  const tokenRef = useRef(null);
  const stopRef = useRef(false);
  const seqRef = useRef(0);
  const [state, setState] = useState("connecting");
  const [message, setMessage] = useState("Apertura sessione Remote Browser...");
  const [fullscreen, setFullscreen] = useState(false);
  const [kbOpen, setKbOpen] = useState(false);
  const [frameCount, setFrameCount] = useState(0);
  const [lastFrameTs, setLastFrameTs] = useState(null);

  useEffect(() => {
    stopRef.current = false;
    seqRef.current = 0;

    const run = async () => {
      try {
        // 1. Create session
        const res = await axios.post(`${API}/console-rmt/session`, {
          device_ip: session.deviceIp,
          port: session.port,
        });
        if (stopRef.current) return;
        const { token, connector_offline, connector_supported, connector_version, required_version } = res.data;
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

        setMessage("Connessione al connector...");
        // 2. Start status poller (slow: 1.5s)
        statusPollLoop(token);
        // 3. Start frame poller (fast: 250ms)
        framePollLoop(token);
      } catch (e) {
        if (stopRef.current) return;
        setState("error");
        setMessage(e?.response?.data?.detail || e.message || "Errore sessione");
      }
    };

    const statusPollLoop = async (token) => {
      while (!stopRef.current) {
        try {
          const r = await axios.get(`${API}/console-rmt/poll-status`, {
            headers: { "X-RMT-Token": token },
            timeout: 10000,
          });
          const m = r.data;
          if (stopRef.current) return;
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
          // "ready" or other - keep waiting
        } catch {
          // network blip, retry
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
    };

    const framePollLoop = async (token) => {
      while (!stopRef.current) {
        try {
          const r = await axios.get(`${API}/console-rmt/latest-frame`, {
            params: { since: seqRef.current },
            headers: { "X-RMT-Token": token },
            timeout: 10000,
            validateStatus: (s) => s === 200 || s === 204,
          });
          if (stopRef.current) return;
          if (r.status === 200 && r.data && r.data.data) {
            seqRef.current = r.data.seq || seqRef.current + 1;
            setState("streaming");
            drawFrame(r.data.data);
            setFrameCount((c) => c + 1);
            setLastFrameTs(Date.now());
          }
        } catch {
          // retry
        }
        await new Promise((r) => setTimeout(r, 250));
      }
    };

    run();

    return () => {
      stopRef.current = true;
      // Best-effort notify backend
      const t = tokenRef.current;
      if (t) {
        axios.post(`${API}/console-rmt/input`, { type: "close" }, { headers: { "X-RMT-Token": t } }).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.deviceIp, session.port]);

  const drawFrame = useCallback((b64) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const img = new Image();
    img.onload = () => {
      if (canvas.width !== img.width) canvas.width = img.width;
      if (canvas.height !== img.height) canvas.height = img.height;
      canvas.getContext("2d").drawImage(img, 0, 0);
    };
    img.src = `data:image/jpeg;base64,${b64}`;
  }, []);

  const sendEvent = useCallback((evt) => {
    const token = tokenRef.current;
    if (!token) return;
    axios.post(`${API}/console-rmt/input`, evt, { headers: { "X-RMT-Token": token } }).catch(() => {});
  }, []);

  const getNormXY = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const cw = canvasRef.current?.width || 1600;
    const ch = canvasRef.current?.height || 900;
    return {
      x: Math.round(((e.clientX - r.left) / r.width) * cw),
      y: Math.round(((e.clientY - r.top) / r.height) * ch),
    };
  };

  const onCanvasMouseMove = useCallback((e) => {
    if (state !== "streaming") return;
    const { x, y } = getNormXY(e);
    sendEvent({ type: "mouse", event: "move", x, y });
  }, [state, sendEvent]);

  const onCanvasMouseDown = useCallback((e) => {
    if (state !== "streaming") return;
    const { x, y } = getNormXY(e);
    const btnMap = { 0: "left", 1: "middle", 2: "right" };
    sendEvent({ type: "mouse", event: "down", x, y, button: btnMap[e.button] || "left" });
  }, [state, sendEvent]);

  const onCanvasMouseUp = useCallback((e) => {
    if (state !== "streaming") return;
    const { x, y } = getNormXY(e);
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
        <span className="text-white/30 text-[10px]">Remote Browser · HTTP polling</span>
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
          <span className="text-fuchsia-400/70">CDP screencast via HTTP polling</span>
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
