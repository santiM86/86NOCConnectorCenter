import { useState, useRef, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";

const TYPE_STYLES = {
  internet: { color: "#06b6d4", icon: "M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2c2.7 0 4 4.5 4 10s-1.3 10-4 10-4-4.5-4-10S9.3 2 12 2z", label: "Internet" },
  firewall: { color: "#f59e0b", icon: "M12 2L3 7v6c0 5.25 3.83 10.16 9 11.38C17.17 23.16 21 18.25 21 13V7l-9-5z", label: "Firewall" },
  router:   { color: "#06b6d4", icon: "M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2a15 15 0 014 10 15 15 0 01-4 10 15 15 0 01-4-10A15 15 0 0112 2z", label: "Router" },
  switch:   { color: "#818cf8", icon: "M4 8h16M4 16h16M8 4v16M16 4v16", label: "Switch" },
  server:   { color: "#10b981", icon: "M2 6h20v4H2zM2 14h20v4H2zM6 8h.01M6 16h.01", label: "Server" },
  ilo:      { color: "#ef4444", icon: "M2 6h20v4H2zM2 14h20v4H2zM6 8h.01M6 16h.01M18 8h.01M18 16h.01", label: "iLO" },
  ap:       { color: "#a78bfa", icon: "M12 20h.01M8.5 16.4a5 5 0 017 0M5 12.8a9 9 0 0114 0M1.5 9.1a13 13 0 0121 0", label: "AP WiFi" },
  printer:  { color: "#78716c", icon: "M6 9V2h12v7M6 18H4a2 2 0 01-2-2v-5h20v5a2 2 0 01-2 2h-2M6 14h12v8H6z", label: "Stampante" },
  camera:   { color: "#ec4899", icon: "M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2zM12 17a5 5 0 100-10 5 5 0 000 10z", label: "Telecamera" },
  nas:      { color: "#14b8a6", icon: "M2 4h20v16H2zM2 12h20M7 8h.01M7 16h.01", label: "NAS" },
  generic:  { color: "#64748b", icon: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5", label: "Dispositivo" },
};

const EDGE_STYLES = {
  wan:    { color: "#06b6d4", dash: "none", width: 2.5 },
  trunk:  { color: "#818cf8", dash: "none", width: 2 },
  access: { color: "#64748b", dash: "none", width: 1.2 },
  server: { color: "#10b981", dash: "4 2", width: 1.2 },
  mgmt:   { color: "#f59e0b", dash: "6 3", width: 1 },
};

function HealthGauge({ score, x, y }) {
  const r = 22;
  const circumference = 2 * Math.PI * r;
  const pct = score / 100;
  const offset = circumference * (1 - pct);
  const color = score >= 80 ? "#10b981" : score >= 50 ? "#f59e0b" : "#ef4444";

  return (
    <g transform={`translate(${x}, ${y})`}>
      <circle r={r + 2} fill="var(--bg-panel, #111)" stroke="var(--bg-border, #333)" strokeWidth={0.5} />
      <circle r={r} fill="none" stroke="var(--bg-hover, #222)" strokeWidth={4} />
      <circle r={r} fill="none" stroke={color} strokeWidth={4}
        strokeDasharray={circumference} strokeDashoffset={offset}
        strokeLinecap="round" transform="rotate(-90)" />
      <text x={0} y={2} textAnchor="middle" fontSize={14} fontWeight={800} fill={color} fontFamily="monospace">{score}</text>
      <text x={0} y={12} textAnchor="middle" fontSize={6} fill="var(--text-muted, #888)">HEALTH</text>
    </g>
  );
}

function TopoNode({ x, y, node, selected, onSelect, onHover, onLeave }) {
  const style = TYPE_STYLES[node.type] || TYPE_STYLES.generic;
  const isVirtual = node.virtual;
  const isReachable = node.reachable;
  const nr = isVirtual ? 22 : 26;

  return (
    <g transform={`translate(${x}, ${y})`}
      onClick={() => !isVirtual && onSelect(node)}
      onMouseEnter={() => !isVirtual && onHover(node, x, y)}
      onMouseLeave={onLeave}
      style={{ cursor: isVirtual ? "default" : "pointer" }}
      data-testid={`topo-node-${node.id}`}
    >
      {!isVirtual && (
        <circle r={nr + 5} fill={isReachable ? "rgba(16,185,129,0.06)" : "rgba(239,68,68,0.06)"} />
      )}
      {!isVirtual && (
        <circle r={nr + 1.5} fill="none"
          stroke={isReachable ? "#10b981" : "#ef4444"}
          strokeWidth={selected ? 2.5 : 1}
          strokeDasharray={isReachable ? "none" : "4 2"}
          opacity={0.5} />
      )}
      <circle r={nr} fill="var(--bg-card, #1a1a2e)" stroke={isVirtual ? "rgba(6,182,212,0.3)" : "var(--bg-border, #2a2a4a)"} strokeWidth={isVirtual ? 1.5 : 1} />
      <svg x={-9} y={-9} width={18} height={18} viewBox="0 0 24 24">
        <path d={style.icon} fill="none" stroke={style.color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {!isVirtual && (
        <circle cx={nr - 3} cy={-nr + 3} r={4} fill={isReachable ? "#10b981" : "#ef4444"} stroke="var(--bg-card, #1a1a2e)" strokeWidth={1.5} />
      )}
      <text x={0} y={nr + 16} textAnchor="middle" fontSize={9} fontWeight={600} fill="var(--text-primary, #eee)" style={{ userSelect: "none" }}>
        {(node.name || node.id).length > 18 ? (node.name || node.id).substring(0, 16) + "..." : (node.name || node.id)}
      </text>
      {!isVirtual && (
        <text x={0} y={nr + 27} textAnchor="middle" fontSize={7.5} fontFamily="monospace" fill="var(--text-muted, #888)" style={{ userSelect: "none" }}>
          {node.ip || node.id}
        </text>
      )}
      {!isVirtual && node.role && (
        <g>
          <rect x={-18} y={-nr - 12} width={36} height={11} rx={5.5} fill={`${style.color}15`} stroke={`${style.color}30`} strokeWidth={0.5} />
          <text x={0} y={-nr - 4} textAnchor="middle" fontSize={6.5} fontWeight={600} fill={style.color} fontFamily="monospace">
            {style.label}
          </text>
        </g>
      )}
    </g>
  );
}

function TopoEdge({ x1, y1, x2, y2, edge }) {
  const style = EDGE_STYLES[edge.type] || EDGE_STYLES.access;
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;

  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={style.color} strokeWidth={style.width}
        strokeDasharray={style.dash} opacity={0.5} />
      {edge.type !== "access" && (
        <circle r={2} fill={style.color} opacity={0.7}>
          <animateMotion dur={edge.type === "wan" ? "2s" : "3s"} repeatCount="indefinite"
            path={`M${x1},${y1} L${x2},${y2}`} />
        </circle>
      )}
      {edge.label && (
        <g transform={`translate(${midX}, ${midY})`}>
          <rect x={-20} y={-6} width={40} height={12} rx={6} fill="var(--bg-panel, #111)" stroke="var(--bg-border, #333)" strokeWidth={0.4} opacity={0.9} />
          <text x={0} y={3} textAnchor="middle" fontSize={6.5} fontFamily="monospace" fill={style.color}>
            {edge.label}
          </text>
        </g>
      )}
    </g>
  );
}

function TopoTooltip({ node, x, y }) {
  if (!node) return null;
  const style = TYPE_STYLES[node.type] || TYPE_STYLES.generic;
  const isPing = node.monitor_type === "ping";
  const ports = node.ports || [];
  const upPorts = ports.filter(p => p.status === "up").length;

  return (
    <g transform={`translate(${Math.min(x + 45, 700)}, ${Math.max(y - 50, 10)})`}>
      <rect x={0} y={0} width={210} height={82} rx={8} fill="var(--bg-panel, #111)" stroke={`${style.color}50`} strokeWidth={1} filter="url(#topoShadow)" />
      <rect x={0} y={0} width={4} height={82} rx={2} fill={style.color} />
      <text x={14} y={17} fontSize={11} fontWeight={700} fill="var(--text-primary, #eee)">{node.name || node.ip}</text>
      <text x={14} y={31} fontSize={9} fontFamily="monospace" fill="var(--text-muted, #888)">{node.ip} ({style.label})</text>
      <text x={14} y={45} fontSize={9} fill={node.reachable ? "#10b981" : "#ef4444"}>
        {node.reachable ? "RAGGIUNGIBILE" : "NON RAGGIUNGIBILE"}
        {node.ping_ms != null && ` (${node.ping_ms}ms)`}
      </text>
      <text x={14} y={59} fontSize={8.5} fill="var(--text-secondary, #aaa)">
        Monitor: {isPing ? "Ping+HTTP" : "SNMP"} | Ruolo: {node.role || "?"}
      </text>
      {ports.length > 0 && (
        <text x={14} y={73} fontSize={8.5} fill="var(--text-secondary, #aaa)">
          Porte: {upPorts}/{ports.length} attive
        </text>
      )}
    </g>
  );
}

export default function NetworkMap({ clientGroups, onDeviceSelect }) {
  const [topologies, setTopologies] = useState({});
  const [selectedNode, setSelectedNode] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });
  const [loading, setLoading] = useState(true);
  const containerRef = useRef(null);
  const [width, setWidth] = useState(900);

  useEffect(() => {
    const updateWidth = () => {
      if (containerRef.current) setWidth(Math.max(containerRef.current.getBoundingClientRect().width, 600));
    };
    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  useEffect(() => {
    const fetchTopologies = async () => {
      setLoading(true);
      const results = {};
      for (const group of clientGroups) {
        try {
          const res = await axios.get(`${API}/network/topology/${group.clientId}`);
          results[group.clientId] = res.data;
        } catch (err) {
          console.error("Topology fetch error:", err);
        }
      }
      setTopologies(results);
      setLoading(false);
    };
    if (clientGroups.length > 0) fetchTopologies();
  }, [clientGroups]);

  const layoutNodes = useCallback((topo) => {
    if (!topo?.nodes?.length) return { positions: {}, h: 200 };
    const layers = topo.layers || [];
    const nodeMap = {};
    topo.nodes.forEach(n => { nodeMap[n.id] = n; });

    const layerSpacing = 110;
    const positions = {};
    let maxY = 0;

    layers.forEach((layer, li) => {
      const nodesInLayer = layer.nodes;
      const count = nodesInLayer.length;
      const totalW = count * 130;
      const startX = (width - totalW) / 2 + 65;
      const y = 60 + li * layerSpacing;

      nodesInLayer.forEach((nodeId, ni) => {
        positions[nodeId] = {
          x: count === 1 ? width / 2 : startX + ni * (totalW / count),
          y: y,
        };
      });
      maxY = Math.max(maxY, y);
    });

    return { positions, h: maxY + 120 };
  }, [width]);

  if (loading) {
    return (
      <div className="noc-panel p-8 text-center" data-testid="network-map-loading">
        <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-[var(--text-muted)] text-sm">Analisi topologia di rete...</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="space-y-4" data-testid="network-map">
      {clientGroups.map((group) => {
        const topo = topologies[group.clientId];
        if (!topo || !topo.nodes?.length) return null;
        const { positions, h } = layoutNodes(topo);
        const health = topo.health || {};
        const svgH = Math.max(h, 300);

        return (
          <div key={group.clientId} className="noc-panel overflow-hidden" data-testid={`topo-client-${group.clientId}`}>
            {/* Header */}
            <div className="p-3 border-b border-[var(--bg-border)] flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full ${health.score >= 80 ? "bg-emerald-500" : health.score >= 50 ? "bg-amber-500" : "bg-red-500"}`} />
                <span className="font-heading font-bold text-sm text-[var(--text-primary)]">{topo.client_name}</span>
                <span className="text-[10px] text-[var(--text-muted)] font-mono">
                  {health.devices_online}/{health.devices_total} online
                </span>
                {health.avg_ping_ms && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded border text-[var(--text-muted)] border-[var(--bg-border)] font-mono">
                    avg {health.avg_ping_ms}ms
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {health.ports_total > 0 && (
                  <span className="text-[10px] text-[var(--text-muted)]">
                    Porte: {health.ports_up}/{health.ports_total}
                  </span>
                )}
                <div className="flex items-center gap-1.5">
                  <span className={`font-heading text-lg font-black ${health.score >= 80 ? "text-emerald-400" : health.score >= 50 ? "text-amber-400" : "text-red-400"}`} data-testid={`health-score-${group.clientId}`}>
                    {health.score}%
                  </span>
                  <span className="text-[9px] text-[var(--text-muted)] uppercase">health</span>
                </div>
              </div>
            </div>

            {/* SVG Topology */}
            <svg width={width} height={svgH} viewBox={`0 0 ${width} ${svgH}`} className="bg-[var(--bg-app)]" style={{ display: "block" }}>
              <defs>
                <filter id="topoShadow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="4" stdDeviation="8" floodOpacity="0.4" />
                </filter>
                <radialGradient id="topoGrad" cx="50%" cy="30%" r="60%">
                  <stop offset="0%" stopColor="rgba(99,102,241,0.03)" />
                  <stop offset="100%" stopColor="rgba(0,0,0,0)" />
                </radialGradient>
              </defs>

              <rect width={width} height={svgH} fill="url(#topoGrad)" />

              {/* Grid */}
              {Array.from({ length: Math.ceil(width / 50) }).map((_, i) => (
                <line key={`vg${i}`} x1={i * 50} y1={0} x2={i * 50} y2={svgH} stroke="var(--bg-border,#222)" strokeWidth={0.2} opacity={0.3} />
              ))}
              {Array.from({ length: Math.ceil(svgH / 50) }).map((_, i) => (
                <line key={`hg${i}`} x1={0} y1={i * 50} x2={width} y2={i * 50} stroke="var(--bg-border,#222)" strokeWidth={0.2} opacity={0.3} />
              ))}

              {/* Layer labels */}
              {(topo.layers || []).map((layer, li) => {
                const firstNodeId = layer.nodes[0];
                const pos = positions[firstNodeId];
                if (!pos) return null;
                return (
                  <g key={`layer-${li}`}>
                    <line x1={10} y1={pos.y} x2={width - 10} y2={pos.y} stroke="var(--bg-border, #222)" strokeWidth={0.5} strokeDasharray="8 4" opacity={0.3} />
                    <text x={12} y={pos.y - 8} fontSize={8} fill="var(--text-muted, #555)" fontWeight={600} style={{ textTransform: "uppercase" }} letterSpacing="0.08em">
                      {layer.name}
                    </text>
                  </g>
                );
              })}

              {/* Edges */}
              {(topo.edges || []).map((edge, i) => {
                const from = positions[edge.from];
                const to = positions[edge.to];
                if (!from || !to) return null;
                return <TopoEdge key={`e${i}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} edge={edge} />;
              })}

              {/* Nodes */}
              {(topo.nodes || []).map((node) => {
                const pos = positions[node.id];
                if (!pos) return null;
                return (
                  <TopoNode
                    key={node.id} x={pos.x} y={pos.y} node={node}
                    selected={selectedNode?.id === node.id}
                    onSelect={(n) => { setSelectedNode(prev => prev?.id === n.id ? null : n); if (onDeviceSelect && !n.virtual) onDeviceSelect(n); }}
                    onHover={(n, nx, ny) => { setHoveredNode(n); setHoverPos({ x: nx, y: ny }); }}
                    onLeave={() => setHoveredNode(null)}
                  />
                );
              })}

              {/* Tooltip */}
              {hoveredNode && !hoveredNode.virtual && (
                <TopoTooltip node={hoveredNode} x={hoverPos.x} y={hoverPos.y} />
              )}

              {/* Health gauge */}
              <HealthGauge score={health.score} x={width - 50} y={svgH - 40} />

              {/* Legend */}
              <g transform={`translate(12, ${svgH - 80})`}>
                <rect x={0} y={0} width={150} height={72} rx={6} fill="var(--bg-panel, #111)" stroke="var(--bg-border, #333)" strokeWidth={0.5} opacity={0.9} />
                <text x={10} y={14} fontSize={7.5} fontWeight={700} fill="var(--text-muted, #888)" style={{ textTransform: "uppercase" }} letterSpacing="0.08em">Tipo collegamento</text>
                {[
                  { label: "WAN", ...EDGE_STYLES.wan },
                  { label: "Trunk", ...EDGE_STYLES.trunk },
                  { label: "Accesso", ...EDGE_STYLES.access },
                  { label: "Management", ...EDGE_STYLES.mgmt },
                ].map((item, i) => (
                  <g key={i} transform={`translate(10, ${24 + i * 12})`}>
                    <line x1={0} y1={0} x2={20} y2={0} stroke={item.color} strokeWidth={item.width} strokeDasharray={item.dash} />
                    <text x={26} y={3} fontSize={8} fill="var(--text-secondary, #aaa)">{item.label}</text>
                  </g>
                ))}
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
