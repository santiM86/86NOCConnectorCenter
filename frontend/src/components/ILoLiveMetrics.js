import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { API } from "@/App";

/**
 * iLOLiveMetrics — sparkline real-time (polls /api/redfish/metrics/{ip} ogni 15s).
 * Mostra: power_watts corrente + sparkline, max temperature + sparkline, health dot.
 * Props: deviceIp (string), deviceName (optional), compact (bool — se true, riduce le dimensioni).
 */
export default function ILoLiveMetrics({ deviceIp, deviceName, compact = false }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const res = await axios.get(`${API}/redfish/metrics/${deviceIp}?minutes=60`);
        if (!cancelled) {
          setData(res.data);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e.response?.status === 404 ? "Nessuna telemetria" : (e.message || "Errore"));
          setLoading(false);
        }
      }
    };
    fetchData();
    timerRef.current = setInterval(fetchData, 15000);
    return () => { cancelled = true; if (timerRef.current) clearInterval(timerRef.current); };
  }, [deviceIp]);

  if (loading) return <div className="text-[10px] text-white/30 font-mono">…</div>;
  if (error) return <div className="text-[10px] text-amber-400/70 font-mono">⚠ {error}</div>;
  if (!data?.latest) return <div className="text-[10px] text-white/30 font-mono">no data</div>;

  const latest = data.latest;
  const maxTemp = latest.temperatures?.length
    ? Math.max(...latest.temperatures.map(t => t.celsius || 0))
    : null;
  const avgTemp = latest.temperatures?.length
    ? Math.round(latest.temperatures.reduce((a, t) => a + (t.celsius || 0), 0) / latest.temperatures.length)
    : null;

  const powerSeries = data.series?.power_watts || [];
  const tempSeries = data.series?.max_temperature || [];

  const tempColor = maxTemp >= 75 ? "#ef4444" : maxTemp >= 65 ? "#f59e0b" : "#10b981";
  const healthColor = latest.health_status === "ok" ? "#10b981" : latest.health_status === "warning" ? "#f59e0b" : "#ef4444";

  // Age
  let ageText = "";
  try {
    const ts = new Date(latest.timestamp).getTime();
    const age = Math.floor((Date.now() - ts) / 1000);
    ageText = age < 60 ? `${age}s fa` : age < 3600 ? `${Math.floor(age / 60)}m fa` : `${Math.floor(age / 3600)}h fa`;
  } catch {}

  const size = compact ? { h: 28, w: 60, fontVal: "11px", fontLbl: "9px" } : { h: 36, w: 80, fontVal: "14px", fontLbl: "10px" };

  return (
    <div className="flex items-center gap-3" data-testid={`ilo-live-${deviceIp}`}>
      <span className="inline-flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: healthColor }} title={`Health: ${latest.health_status}`} />
        <span className="text-[9px] font-bold uppercase text-white/40 tracking-wider">LIVE</span>
      </span>

      {/* POWER */}
      <div className="flex items-center gap-1.5" title="Power consumption (Watt)">
        <Sparkline data={powerSeries} width={size.w} height={size.h} color="#a78bfa" />
        <div className="flex flex-col leading-tight">
          <span className="text-white font-mono font-bold" style={{ fontSize: size.fontVal }}>
            {latest.power_watts != null ? `${Math.round(latest.power_watts)}W` : "—"}
          </span>
          <span className="text-white/30 font-mono uppercase" style={{ fontSize: size.fontLbl }}>power</span>
        </div>
      </div>

      {/* TEMPERATURE */}
      <div className="flex items-center gap-1.5" title={`Max sensor ${maxTemp}°C · Avg ${avgTemp}°C`}>
        <Sparkline data={tempSeries} width={size.w} height={size.h} color={tempColor} />
        <div className="flex flex-col leading-tight">
          <span className="font-mono font-bold" style={{ fontSize: size.fontVal, color: tempColor }}>
            {maxTemp != null ? `${maxTemp}°C` : "—"}
          </span>
          <span className="text-white/30 font-mono uppercase" style={{ fontSize: size.fontLbl }}>max temp</span>
        </div>
      </div>

      <span className="text-[9px] text-white/30 font-mono ml-auto" title={`Source: ${latest.source}`}>{ageText}</span>
    </div>
  );
}

function Sparkline({ data, width = 80, height = 36, color = "#a78bfa" }) {
  if (!data || data.length === 0) {
    return <svg width={width} height={height}><line x1={0} y1={height / 2} x2={width} y2={height / 2} stroke="#2a2a3e" strokeWidth={1} strokeDasharray="2,2" /></svg>;
  }
  const values = data.map(d => d.v).filter(v => typeof v === "number");
  if (values.length === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = data.length > 1 ? width / (data.length - 1) : width;
  const points = data.map((d, i) => {
    const x = i * step;
    const y = height - ((d.v - min) / range) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = data[data.length - 1];
  const lastX = (data.length - 1) * step;
  const lastY = height - ((last.v - min) / range) * (height - 4) - 2;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline fill="none" stroke={color} strokeWidth={1.5} points={points} opacity={0.85} />
      <circle cx={lastX} cy={lastY} r={2} fill={color} />
      <circle cx={lastX} cy={lastY} r={4} fill={color} opacity={0.25}>
        <animate attributeName="r" values="3;6;3" dur="1.5s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.4;0.05;0.4" dur="1.5s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}
