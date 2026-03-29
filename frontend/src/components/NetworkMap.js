import { useState, useRef, useEffect, useCallback } from "react";

const DEVICE_ICONS = {
  switch: { path: "M4 8h16M4 16h16M8 4v16M16 4v16", color: "#818cf8" },
  firewall: { path: "M12 2L3 7v6c0 5.25 3.83 10.16 9 11.38C17.17 23.16 21 18.25 21 13V7l-9-5z", color: "#f59e0b" },
  server: { path: "M2 6h20v4H2zM2 14h20v4H2zM6 8h.01M6 16h.01", color: "#10b981" },
  ilo: { path: "M2 6h20v4H2zM2 14h20v4H2zM6 8h.01M6 16h.01M18 8h.01M18 16h.01", color: "#ef4444" },
  router: { path: "M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z", color: "#06b6d4" },
  generic: { path: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5", color: "#8b5cf6" },
};

function getDeviceType(dev) {
  const name = (dev.device_name || "").toLowerCase();
  const descr = (dev.sys_descr || "").toLowerCase();
  const combined = name + " " + descr;
  if (combined.includes("ilo") || combined.includes("redfish")) return "ilo";
  if (combined.includes("firewall") || combined.includes("usg") || combined.includes("zyxel")) return "firewall";
  if (combined.includes("switch") || combined.includes("hpe") || combined.includes("netgear") || combined.includes("officeconnect")) return "switch";
  if (combined.includes("server") || combined.includes("srv")) return "server";
  if (combined.includes("router") || combined.includes("gateway")) return "router";
  return "generic";
}

function DeviceNode({ x, y, dev, selected, onSelect, onHover, onLeave }) {
  const type = getDeviceType(dev);
  const icon = DEVICE_ICONS[type] || DEVICE_ICONS.generic;
  const isReachable = dev.reachable;
  const isPing = dev.monitor_type === "ping" || dev.monitor_type === "http";
  const nodeRadius = 28;

  return (
    <g
      transform={`translate(${x}, ${y})`}
      onClick={() => onSelect(dev)}
      onMouseEnter={() => onHover(dev, x, y)}
      onMouseLeave={onLeave}
      style={{ cursor: "pointer" }}
      data-testid={`map-node-${dev.device_ip}`}
    >
      {/* Glow effect */}
      <circle
        r={nodeRadius + 6}
        fill={isReachable ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)"}
        stroke="none"
      />
      {/* Status ring */}
      <circle
        r={nodeRadius + 2}
        fill="none"
        stroke={isReachable ? "#10b981" : "#ef4444"}
        strokeWidth={selected ? 3 : 1.5}
        strokeDasharray={isReachable ? "none" : "4 2"}
        opacity={0.6}
      />
      {/* Main circle */}
      <circle
        r={nodeRadius}
        fill="var(--bg-card, #1a1a2e)"
        stroke="var(--bg-border, #2a2a4a)"
        strokeWidth={1}
      />
      {/* Icon */}
      <svg x={-10} y={-10} width={20} height={20} viewBox="0 0 24 24">
        <path d={icon.path} fill="none" stroke={icon.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {/* Status dot */}
      <circle
        cx={nodeRadius - 4}
        cy={-nodeRadius + 4}
        r={5}
        fill={isReachable ? "#10b981" : "#ef4444"}
        stroke="var(--bg-card, #1a1a2e)"
        strokeWidth={2}
      />
      {/* Monitor type badge */}
      <rect
        x={-12} y={nodeRadius - 2}
        width={24} height={12}
        rx={6} fill={isPing ? "rgba(99, 102, 241, 0.2)" : "rgba(59, 130, 246, 0.2)"}
        stroke={isPing ? "rgba(99, 102, 241, 0.3)" : "rgba(59, 130, 246, 0.3)"}
        strokeWidth={0.5}
      />
      <text
        x={0} y={nodeRadius + 8}
        textAnchor="middle" fontSize={7} fontWeight={600}
        fill={isPing ? "#818cf8" : "#60a5fa"}
        fontFamily="monospace"
      >
        {isPing ? "PING" : "SNMP"}
      </text>
      {/* Label below */}
      <text
        x={0} y={nodeRadius + 22}
        textAnchor="middle" fontSize={9} fontWeight={600}
        fill="var(--text-primary, #e0e0f0)"
        style={{ userSelect: "none" }}
      >
        {(dev.device_name || dev.device_ip).length > 16
          ? (dev.device_name || dev.device_ip).substring(0, 14) + "..."
          : (dev.device_name || dev.device_ip)
        }
      </text>
      <text
        x={0} y={nodeRadius + 34}
        textAnchor="middle" fontSize={8}
        fill="var(--text-muted, #888)"
        fontFamily="monospace"
        style={{ userSelect: "none" }}
      >
        {dev.device_ip}
      </text>
    </g>
  );
}

function ConnectionLine({ x1, y1, x2, y2, reachable, pingMs }) {
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;

  return (
    <g>
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={reachable ? "rgba(16, 185, 129, 0.25)" : "rgba(239, 68, 68, 0.25)"}
        strokeWidth={reachable ? 1.5 : 1}
        strokeDasharray={reachable ? "none" : "6 4"}
      />
      {/* Animated pulse on active connections */}
      {reachable && (
        <circle r={2.5} fill="#10b981" opacity={0.6}>
          <animateMotion
            dur="3s" repeatCount="indefinite"
            path={`M${x1},${y1} L${x2},${y2}`}
          />
        </circle>
      )}
      {/* Latency label */}
      {pingMs != null && (
        <g transform={`translate(${midX}, ${midY})`}>
          <rect x={-14} y={-7} width={28} height={14} rx={7} fill="var(--bg-panel, #111)" stroke="var(--bg-border, #333)" strokeWidth={0.5} />
          <text x={0} y={3} textAnchor="middle" fontSize={7} fontFamily="monospace" fill={pingMs > 100 ? "#f59e0b" : "#10b981"}>
            {pingMs}ms
          </text>
        </g>
      )}
    </g>
  );
}

function Tooltip({ dev, x, y }) {
  if (!dev) return null;
  const type = getDeviceType(dev);
  const isPing = dev.monitor_type === "ping" || dev.monitor_type === "http";
  const portStats = (dev.ports || []);
  const upPorts = portStats.filter(p => p.status === "up").length;
  const downPorts = portStats.filter(p => p.status === "down").length;

  return (
    <g transform={`translate(${x + 40}, ${y - 60})`}>
      <rect x={0} y={0} width={200} height={90} rx={8} fill="var(--bg-panel, #111)" stroke="var(--bg-border, #333)" strokeWidth={1} filter="url(#shadow)" />
      <text x={10} y={18} fontSize={11} fontWeight={700} fill="var(--text-primary, #eee)">{dev.device_name || dev.device_ip}</text>
      <text x={10} y={32} fontSize={9} fontFamily="monospace" fill="var(--text-muted, #888)">{dev.device_ip}</text>
      <text x={10} y={46} fontSize={9} fill="var(--text-secondary, #aaa)">
        Tipo: {type.toUpperCase()} ({isPing ? "Ping+HTTP" : "SNMP"})
      </text>
      <text x={10} y={60} fontSize={9} fill={dev.reachable ? "#10b981" : "#ef4444"}>
        Stato: {dev.reachable ? "RAGGIUNGIBILE" : "NON RAGGIUNGIBILE"}
      </text>
      {!isPing && portStats.length > 0 && (
        <text x={10} y={74} fontSize={9} fill="var(--text-secondary, #aaa)">
          Porte: {upPorts} UP / {downPorts} DOWN
        </text>
      )}
      {isPing && dev.ping_ms != null && (
        <text x={10} y={74} fontSize={9} fill="var(--text-secondary, #aaa)">
          Ping: {dev.ping_ms}ms {dev.http_status ? `| HTTP ${dev.http_status}` : ""}
        </text>
      )}
      {dev.sys_descr && (
        <text x={10} y={86} fontSize={8} fill="var(--text-muted, #666)">
          {dev.sys_descr.substring(0, 35)}{dev.sys_descr.length > 35 ? "..." : ""}
        </text>
      )}
    </g>
  );
}

export default function NetworkMap({ clientGroups, onDeviceSelect }) {
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [hoveredDevice, setHoveredDevice] = useState(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 900, height: 500 });

  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({ width: Math.max(rect.width, 600), height: Math.max(400, Math.min(600, rect.width * 0.55)) });
      }
    };
    updateDimensions();
    window.addEventListener("resize", updateDimensions);
    return () => window.removeEventListener("resize", updateDimensions);
  }, []);

  const handleSelect = useCallback((dev) => {
    setSelectedDevice(prev => prev?.device_ip === dev.device_ip ? null : dev);
    if (onDeviceSelect) onDeviceSelect(dev);
  }, [onDeviceSelect]);

  const handleHover = useCallback((dev, x, y) => {
    setHoveredDevice(dev);
    setHoverPos({ x, y });
  }, []);

  const handleLeave = useCallback(() => {
    setHoveredDevice(null);
  }, []);

  return (
    <div ref={containerRef} className="space-y-4" data-testid="network-map">
      {clientGroups.map((group) => {
        const devices = group.devices;
        const count = devices.length;
        if (count === 0) return null;

        const w = dimensions.width;
        const h = dimensions.height;
        const centerX = w / 2;
        const centerY = h / 2;
        const radius = Math.min(w, h) * 0.32;
        const reachableCount = devices.filter(d => d.reachable).length;

        return (
          <div key={group.clientId} className="noc-panel overflow-hidden" data-testid={`map-client-${group.clientId}`}>
            <div className="p-3 border-b border-[var(--bg-border)] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full" style={{ background: reachableCount === count ? "#10b981" : reachableCount === 0 ? "#ef4444" : "#f59e0b" }} />
                <span className="font-heading font-bold text-sm text-[var(--text-primary)]">{group.clientName}</span>
                <span className="text-[10px] text-[var(--text-muted)] font-mono">
                  {reachableCount}/{count} raggiungibili
                </span>
              </div>
              {group.connectorOnline && (
                <span className="text-[10px] px-2 py-0.5 rounded border text-[var(--ok)] bg-[var(--low-bg)] border-[var(--low-border)]">
                  Connettore Online
                </span>
              )}
            </div>

            <svg
              width={w} height={h}
              viewBox={`0 0 ${w} ${h}`}
              className="bg-[var(--bg-app)]"
              style={{ display: "block" }}
            >
              <defs>
                <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="4" stdDeviation="8" floodOpacity="0.3" />
                </filter>
                <radialGradient id="gridGradient" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="rgba(99, 102, 241, 0.04)" />
                  <stop offset="100%" stopColor="rgba(0, 0, 0, 0)" />
                </radialGradient>
              </defs>

              {/* Background grid */}
              <rect width={w} height={h} fill="url(#gridGradient)" />
              {Array.from({ length: Math.ceil(w / 40) }).map((_, i) => (
                <line key={`vg${i}`} x1={i * 40} y1={0} x2={i * 40} y2={h} stroke="var(--bg-border, #222)" strokeWidth={0.3} opacity={0.3} />
              ))}
              {Array.from({ length: Math.ceil(h / 40) }).map((_, i) => (
                <line key={`hg${i}`} x1={0} y1={i * 40} x2={w} y2={i * 40} stroke="var(--bg-border, #222)" strokeWidth={0.3} opacity={0.3} />
              ))}

              {/* Connection lines */}
              {devices.map((dev, i) => {
                const angle = (2 * Math.PI * i) / count - Math.PI / 2;
                const dx = centerX + radius * Math.cos(angle);
                const dy = centerY + radius * Math.sin(angle);
                return (
                  <ConnectionLine
                    key={`line-${dev.device_ip}`}
                    x1={centerX} y1={centerY}
                    x2={dx} y2={dy}
                    reachable={dev.reachable}
                    pingMs={dev.ping_ms}
                  />
                );
              })}

              {/* Center node (Client/Gateway) */}
              <g transform={`translate(${centerX}, ${centerY})`}>
                <circle r={38} fill="var(--bg-card, #1a1a2e)" stroke="rgba(99, 102, 241, 0.4)" strokeWidth={2} />
                <circle r={34} fill="rgba(99, 102, 241, 0.08)" stroke="none" />
                <svg x={-14} y={-14} width={28} height={28} viewBox="0 0 24 24">
                  <path d="M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z" fill="none" stroke="#818cf8" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <text x={0} y={52} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--text-primary, #eee)">
                  {group.clientName.length > 18 ? group.clientName.substring(0, 16) + "..." : group.clientName}
                </text>
                <text x={0} y={64} textAnchor="middle" fontSize={8} fill="var(--text-muted, #888)">
                  {count} dispositivi
                </text>
              </g>

              {/* Device nodes */}
              {devices.map((dev, i) => {
                const angle = (2 * Math.PI * i) / count - Math.PI / 2;
                const dx = centerX + radius * Math.cos(angle);
                const dy = centerY + radius * Math.sin(angle);
                return (
                  <DeviceNode
                    key={dev.device_ip}
                    x={dx} y={dy}
                    dev={dev}
                    selected={selectedDevice?.device_ip === dev.device_ip}
                    onSelect={handleSelect}
                    onHover={handleHover}
                    onLeave={handleLeave}
                  />
                );
              })}

              {/* Tooltip */}
              {hoveredDevice && (
                <Tooltip dev={hoveredDevice} x={hoverPos.x} y={hoverPos.y} />
              )}

              {/* Legend */}
              <g transform={`translate(${w - 150}, 15)`}>
                <rect x={0} y={0} width={140} height={70} rx={6} fill="var(--bg-panel, #111)" stroke="var(--bg-border, #333)" strokeWidth={0.5} opacity={0.9} />
                <text x={10} y={16} fontSize={8} fontWeight={700} fill="var(--text-muted, #888)" style={{ textTransform: "uppercase" }} letterSpacing="0.05em">Legenda</text>
                <circle cx={18} cy={30} r={4} fill="#10b981" />
                <text x={28} y={33} fontSize={8} fill="var(--text-secondary, #aaa)">Raggiungibile</text>
                <circle cx={18} cy={46} r={4} fill="#ef4444" />
                <text x={28} y={49} fontSize={8} fill="var(--text-secondary, #aaa)">Non raggiungibile</text>
                <line x1={10} y1={60} x2={26} y2={60} stroke="rgba(16, 185, 129, 0.4)" strokeWidth={1.5} />
                <text x={28} y={63} fontSize={8} fill="var(--text-secondary, #aaa)">Connessione attiva</text>
              </g>
            </svg>
          </div>
        );
      })}

      {clientGroups.length === 0 && (
        <div className="noc-panel p-8 text-center" data-testid="no-map-data">
          <p className="text-[var(--text-muted)] text-sm">Nessun dispositivo da visualizzare</p>
        </div>
      )}
    </div>
  );
}
