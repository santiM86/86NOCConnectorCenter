/**
 * Port Flap History Sparkline
 * ============================
 * Micro-visualizzazione degli eventi flap UP/DOWN/ADMIN/SPEED di una porta
 * nelle ultime 24h (o N ore). SVG puro, zero dipendenze extra.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";

// Colori per tipo evento
const KIND_COLOR = {
  oper_change: "#f59e0b",    // amber = link flap
  admin_change: "#94a3b8",   // neutral = admin enable/disable
  speed_change: "#a78bfa",   // violet = speed autoneg change
};

export default function PortFlapHistory({ deviceIp, idx, hours = 24, width = 180, height = 26 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await axios.get(`${API}/devices/${encodeURIComponent(deviceIp)}/switch-ports/${idx}/flaps?hours=${hours}`);
        if (!cancelled) setData(r.data);
      } catch {
        if (!cancelled) setData({ events: [], total: 0, by_kind: {} });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [deviceIp, idx, hours]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
        <span className="inline-block w-3 h-3 border-2 border-cyan-500/50 border-t-transparent rounded-full animate-spin"></span>
        Caricamento flap history…
      </div>
    );
  }

  const events = data?.events || [];
  const total = data?.total || 0;
  const byKind = data?.by_kind || {};

  if (total === 0) {
    return (
      <div className="text-[10px] text-emerald-300/80 flex items-center gap-1.5" data-testid={`port-flap-${idx}-stable`}>
        <svg width="8" height="8" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3" fill="#10b981" /></svg>
        <span>Stabile ({hours}h)</span>
      </div>
    );
  }

  // Proietta eventi su asse tempo: x = position% nella finestra temporale
  const nowMs = Date.now();
  const startMs = nowMs - hours * 3600 * 1000;
  const rangeMs = hours * 3600 * 1000;

  const marks = events.map((e) => {
    const ts = Date.parse(e.ts);
    const x = Math.max(0, Math.min(1, (ts - startMs) / rangeMs)) * width;
    const color = KIND_COLOR[e.kind] || "#94a3b8";
    // "up-event" se nuovo oper/admin = 1, "down-event" se = 2
    const isDown = e.kind === "oper_change" && e.to === 2;
    const isUp = e.kind === "oper_change" && e.to === 1;
    return { x, color, kind: e.kind, isDown, isUp, ts: e.ts, from: e.from, to: e.to };
  });

  const severity =
    total >= 20 ? "critical" :
    total >= 6 ? "warning" :
    "info";
  const sevColor = severity === "critical" ? "#ef4444" : severity === "warning" ? "#f59e0b" : "#06b6d4";

  return (
    <div className="flex items-center gap-2" data-testid={`port-flap-${idx}`} title={`${total} eventi in ${hours}h`}>
      <svg width={width} height={height} style={{ overflow: "visible" }}>
        {/* Baseline timeline */}
        <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--bg-border)" strokeWidth="1" />
        {/* Marks per evento */}
        {marks.map((m, i) => (
          <g key={i}>
            {/* Linea verticale */}
            <line x1={m.x} x2={m.x} y1={m.isDown ? height / 2 : 4} y2={m.isDown ? height - 4 : height / 2} stroke={m.color} strokeWidth="1.5" />
            {/* Pallino */}
            <circle cx={m.x} cy={m.isDown ? height - 4 : m.isUp ? 4 : height / 2} r="2" fill={m.color} />
          </g>
        ))}
      </svg>
      <div className="flex items-center gap-1 text-[10px] font-mono" style={{ color: sevColor }}>
        <strong>{total}</strong>
        <span className="text-[9px] text-[var(--text-muted)]">in {hours}h</span>
      </div>
      {/* Tooltip breakdown */}
      <div className="flex items-center gap-1 text-[9px] text-[var(--text-muted)]">
        {byKind.oper_change > 0 && (
          <span title="Link up/down flaps" className="text-amber-300">↕{byKind.oper_change}</span>
        )}
        {byKind.admin_change > 0 && (
          <span title="Admin enable/disable" className="text-neutral-300">⚙{byKind.admin_change}</span>
        )}
        {byKind.speed_change > 0 && (
          <span title="Speed autoneg changes" className="text-violet-300">⇅{byKind.speed_change}</span>
        )}
      </div>
    </div>
  );
}
