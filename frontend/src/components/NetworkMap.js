import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  MarkerType,
  Handle,
  Position,
  Panel,
  useReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { FloppyDisk, ArrowsClockwise, Plugs, Trash, MagicWand, ArrowsOutSimple } from "@phosphor-icons/react";

/* ─── Device type styles ─── */
const TYPE_CONFIG = {
  internet:  { color: "#06b6d4", bg: "rgba(6,182,212,0.12)",  border: "rgba(6,182,212,0.35)",  label: "Internet",     icon: "M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2c2.7 0 4 4.5 4 10s-1.3 10-4 10-4-4.5-4-10S9.3 2 12 2z" },
  firewall:  { color: "#f59e0b", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.35)", label: "Firewall",     icon: "M12 2L3 7v6c0 5.25 3.83 10.16 9 11.38C17.17 23.16 21 18.25 21 13V7l-9-5z" },
  router:    { color: "#06b6d4", bg: "rgba(6,182,212,0.12)",  border: "rgba(6,182,212,0.35)",  label: "Router",       icon: "M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2a15 15 0 014 10 15 15 0 01-4 10 15 15 0 01-4-10A15 15 0 0112 2z" },
  switch:    { color: "#818cf8", bg: "rgba(129,140,248,0.12)", border: "rgba(129,140,248,0.35)", label: "Switch",      icon: "M4 8h16M4 16h16M8 4v16M16 4v16" },
  server:    { color: "#10b981", bg: "rgba(16,185,129,0.12)",  border: "rgba(16,185,129,0.35)", label: "Server",       icon: "M2 6h20v4H2zM2 14h20v4H2zM6 8h.01M6 16h.01" },
  ilo:       { color: "#ef4444", bg: "rgba(239,68,68,0.12)",   border: "rgba(239,68,68,0.35)",  label: "iLO",          icon: "M2 6h20v4H2zM2 14h20v4H2zM6 8h.01M6 16h.01M18 8h.01M18 16h.01" },
  ap:        { color: "#a78bfa", bg: "rgba(167,139,250,0.12)", border: "rgba(167,139,250,0.35)", label: "AP WiFi",     icon: "M12 20h.01M8.5 16.4a5 5 0 017 0M5 12.8a9 9 0 0114 0M1.5 9.1a13 13 0 0121 0" },
  printer:   { color: "#78716c", bg: "rgba(120,113,108,0.12)", border: "rgba(120,113,108,0.35)", label: "Stampante",   icon: "M6 9V2h12v7M6 18H4a2 2 0 01-2-2v-5h20v5a2 2 0 01-2 2h-2M6 14h12v8H6z" },
  camera:    { color: "#ec4899", bg: "rgba(236,72,153,0.12)",  border: "rgba(236,72,153,0.35)", label: "Telecamera",   icon: "M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2zM12 17a5 5 0 100-10 5 5 0 000 10z" },
  nas:       { color: "#14b8a6", bg: "rgba(20,184,166,0.12)",  border: "rgba(20,184,166,0.35)", label: "NAS",          icon: "M2 4h20v16H2zM2 12h20M7 8h.01M7 16h.01" },
  generic:   { color: "#64748b", bg: "rgba(100,116,139,0.12)", border: "rgba(100,116,139,0.35)", label: "Dispositivo", icon: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" },
};

/* ─── Custom Node Component ─── */
function DeviceNode({ data }) {
  const cfg = TYPE_CONFIG[data.deviceType] || TYPE_CONFIG.generic;
  const isVirtual = data.virtual;
  const isReachable = data.reachable !== false;

  return (
    <div
      className="relative group"
      data-testid={`flow-node-${data.nodeId}`}
      style={{ minWidth: 110 }}
    >
      {/* Handles for connections */}
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-indigo-500 !border-[var(--bg-panel)] !border-2 opacity-0 group-hover:opacity-100 transition-opacity" />
      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-indigo-500 !border-[var(--bg-panel)] !border-2 opacity-0 group-hover:opacity-100 transition-opacity" />
      <Handle type="target" position={Position.Left} id="left" className="!w-2 !h-2 !bg-indigo-500 !border-[var(--bg-panel)] !border-2 opacity-0 group-hover:opacity-100 transition-opacity" />
      <Handle type="source" position={Position.Right} id="right" className="!w-2 !h-2 !bg-indigo-500 !border-[var(--bg-panel)] !border-2 opacity-0 group-hover:opacity-100 transition-opacity" />

      {/* Node Card */}
      <div
        className="rounded-xl border-2 px-3 py-2.5 text-center cursor-grab active:cursor-grabbing transition-all duration-200 hover:scale-105"
        style={{
          background: `linear-gradient(135deg, var(--bg-card) 0%, ${cfg.bg} 100%)`,
          borderColor: data.selected ? "#818cf8" : cfg.border,
          boxShadow: data.selected ? `0 0 16px ${cfg.color}40` : `0 2px 8px rgba(0,0,0,0.3)`,
        }}
      >
        {/* Status indicator */}
        {!isVirtual && (
          <div
            className="absolute -top-1 -right-1 w-3 h-3 rounded-full border-2"
            style={{
              backgroundColor: isReachable ? "#22c55e" : "#ef4444",
              borderColor: "var(--bg-card)",
            }}
          />
        )}

        {/* Icon */}
        <div className="flex items-center justify-center mb-1.5">
          <svg width={22} height={22} viewBox="0 0 24 24">
            <path d={cfg.icon} fill="none" stroke={cfg.color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>

        {/* Type badge */}
        <div
          className="text-[8px] font-bold uppercase tracking-wider mb-1 px-1.5 py-0.5 rounded-full mx-auto inline-block"
          style={{ color: cfg.color, background: `${cfg.color}15`, border: `1px solid ${cfg.color}30` }}
        >
          {cfg.label}
        </div>

        {/* Name */}
        <div className="text-[10px] font-semibold text-[var(--text-primary)] truncate max-w-[100px]" title={data.label}>
          {data.label}
        </div>

        {/* IP */}
        {!isVirtual && data.ip && (
          <div className="text-[9px] font-mono text-[var(--text-muted)] mt-0.5">{data.ip}</div>
        )}

        {/* Ping */}
        {!isVirtual && data.ping_ms != null && (
          <div className={`text-[9px] font-mono mt-0.5 ${isReachable ? "text-emerald-400" : "text-red-400"}`}>
            {data.ping_ms}ms
          </div>
        )}
      </div>
    </div>
  );
}

const nodeTypes = { device: DeviceNode };

/* ─── Edge types color map ─── */
const EDGE_COLORS = {
  wan: "#06b6d4",
  trunk: "#818cf8",
  access: "#475569",
  server: "#10b981",
  mgmt: "#f59e0b",
  lldp: "#22d3ee",
  custom: "#8b5cf6",
};

/* ─── Convert backend topology to React Flow format ─── */
function topoToFlowNodes(topoNodes, hasCustomLayout) {
  return (topoNodes || []).map((n, i) => {
    const layer = n.layer ?? 0;
    return {
      id: n.id || n.ip || `node-${i}`,
      type: "device",
      position: n.position || { x: 200 + (i % 5) * 180, y: 80 + layer * 150 },
      data: {
        label: n.name || n.ip || n.id,
        nodeId: n.id || n.ip,
        ip: n.ip,
        deviceType: n.type || "generic",
        reachable: n.reachable,
        virtual: n.virtual,
        ping_ms: n.ping_ms,
        ports: n.ports,
        monitor_type: n.monitor_type,
        role: n.role,
      },
    };
  });
}

function topoToFlowEdges(topoEdges) {
  return (topoEdges || []).map((e, i) => ({
    id: e.id || `e-${e.from}-${e.to}-${i}`,
    source: e.from,
    target: e.to,
    type: "default",
    animated: e.type === "wan" || e.type === "trunk" || e.type === "lldp",
    label: e.label || "",
    style: {
      stroke: EDGE_COLORS[e.type] || EDGE_COLORS.custom,
      strokeWidth: e.type === "wan" ? 2.5 : e.type === "trunk" ? 2 : 1.5,
    },
    markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLORS[e.type] || EDGE_COLORS.custom, width: 14, height: 14 },
    data: { edgeType: e.type || "custom" },
    labelStyle: { fill: "var(--text-muted)", fontSize: 10, fontFamily: "monospace" },
    labelBgStyle: { fill: "var(--bg-panel)", fillOpacity: 0.85 },
    labelBgPadding: [6, 3],
    labelBgBorderRadius: 4,
  }));
}

/* ─── Auto-layout using layer-based positioning ─── */
function autoLayoutNodes(nodes, topoLayers, width) {
  if (!topoLayers?.length) return nodes;
  const layerSpacing = 160;
  const nodeSpacing = 180;
  const positioned = new Map();

  topoLayers.forEach((layer, li) => {
    const layerNodeIds = layer.nodes || [];
    const count = layerNodeIds.length;
    const totalW = count * nodeSpacing;
    const startX = (width - totalW) / 2 + nodeSpacing / 2;
    layerNodeIds.forEach((nid, ni) => {
      positioned.set(nid, {
        x: count === 1 ? width / 2 - 55 : startX + ni * nodeSpacing,
        y: 40 + li * layerSpacing,
      });
    });
  });

  return nodes.map((n) => {
    const pos = positioned.get(n.id);
    return pos ? { ...n, position: pos } : n;
  });
}

/* ─── Main Inner Component (needs ReactFlowProvider) ─── */
function NetworkMapInner({ clientGroups, onDeviceSelect }) {
  const [topologies, setTopologies] = useState({});
  const [loading, setLoading] = useState(true);
  const [activeClient, setActiveClient] = useState(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [hasChanges, setHasChanges] = useState(false);
  const [saving, setSaving] = useState(false);
  const [connectMode, setConnectMode] = useState(false);
  const containerRef = useRef(null);
  const { fitView } = useReactFlow();

  // Fetch topologies for all clients
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

      // Auto-select first client with data
      const firstKey = Object.keys(results).find((k) => results[k]?.nodes?.length > 0);
      if (firstKey && !activeClient) setActiveClient(firstKey);
    };
    if (clientGroups.length > 0) fetchTopologies();
  }, [clientGroups]);

  // When active client changes, load its nodes/edges into React Flow
  useEffect(() => {
    if (!activeClient || !topologies[activeClient]) return;
    const topo = topologies[activeClient];
    const hasCustom = topo.has_custom_layout;
    let flowNodes = topoToFlowNodes(topo.nodes, hasCustom);
    const flowEdges = topoToFlowEdges(topo.edges);

    if (!hasCustom && topo.layers?.length) {
      const w = containerRef.current?.getBoundingClientRect().width || 900;
      flowNodes = autoLayoutNodes(flowNodes, topo.layers, w);
    }

    setNodes(flowNodes);
    setEdges(flowEdges);
    setHasChanges(false);
    setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 100);
  }, [activeClient, topologies]);

  // Track changes
  const onNodeDragStop = useCallback(() => {
    setHasChanges(true);
  }, []);

  const onConnect = useCallback(
    (params) => {
      const newEdge = {
        ...params,
        id: `e-${params.source}-${params.target}-${Date.now()}`,
        type: "default",
        animated: false,
        style: { stroke: EDGE_COLORS.custom, strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLORS.custom, width: 14, height: 14 },
        data: { edgeType: "custom" },
      };
      setEdges((eds) => addEdge(newEdge, eds));
      setHasChanges(true);
      toast.success("Collegamento aggiunto");
    },
    [setEdges]
  );

  const onEdgeClick = useCallback(
    (event, edge) => {
      if (!connectMode) return;
      if (window.confirm(`Rimuovere il collegamento?`)) {
        setEdges((eds) => eds.filter((e) => e.id !== edge.id));
        setHasChanges(true);
        toast.success("Collegamento rimosso");
      }
    },
    [connectMode, setEdges]
  );

  const onNodeClick = useCallback(
    (event, node) => {
      if (onDeviceSelect && !node.data.virtual) {
        onDeviceSelect(node.data);
      }
    },
    [onDeviceSelect]
  );

  // Save layout
  const saveLayout = async () => {
    if (!activeClient) return;
    setSaving(true);
    try {
      const saveNodes = nodes.map((n) => ({
        id: n.id,
        position: n.position,
        name: n.data.label,
        ip: n.data.ip,
        type: n.data.deviceType,
        reachable: n.data.reachable,
        virtual: n.data.virtual,
        ping_ms: n.data.ping_ms,
        ports: n.data.ports,
        monitor_type: n.data.monitor_type,
        role: n.data.role,
        layer: n.data.layer,
      }));
      const saveEdges = edges.map((e) => ({
        id: e.id,
        from: e.source,
        to: e.target,
        type: e.data?.edgeType || "custom",
        label: e.label || "",
      }));
      await axios.post(`${API}/network/topology/${activeClient}/layout`, {
        nodes: saveNodes,
        edges: saveEdges,
      });
      setHasChanges(false);
      toast.success("Layout salvato con successo!");
    } catch (err) {
      toast.error("Errore nel salvataggio: " + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  // Reset layout
  const resetLayout = async () => {
    if (!activeClient) return;
    if (!window.confirm("Tornare alla topologia auto-generata? Il layout personalizzato verra' cancellato.")) return;
    try {
      await axios.delete(`${API}/network/topology/${activeClient}/layout`);
      const res = await axios.get(`${API}/network/topology/${activeClient}`);
      setTopologies((prev) => ({ ...prev, [activeClient]: res.data }));
      toast.success("Layout resettato");
    } catch (err) {
      toast.error("Errore: " + (err.response?.data?.detail || err.message));
    }
  };

  // Auto-layout (re-apply layer-based positions)
  const autoLayout = () => {
    const topo = topologies[activeClient];
    if (!topo?.layers?.length) {
      toast.error("Nessun dato layer per l'auto-layout");
      return;
    }
    const w = containerRef.current?.getBoundingClientRect().width || 900;
    const repositioned = autoLayoutNodes(nodes, topo.layers, w);
    setNodes(repositioned);
    setHasChanges(true);
    setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 50);
    toast.success("Auto-layout applicato");
  };

  const activeTopo = activeClient ? topologies[activeClient] : null;
  const health = activeTopo?.health || {};

  if (loading) {
    return (
      <div className="noc-panel p-8 text-center" data-testid="network-map-loading">
        <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-[var(--text-muted)] text-sm">Caricamento mappa di rete...</p>
      </div>
    );
  }

  if (clientGroups.length === 0) {
    return (
      <div className="noc-panel p-8 text-center" data-testid="no-map-data">
        <p className="text-[var(--text-muted)] text-sm">Nessun dispositivo da visualizzare</p>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="network-map">
      {/* Client selector + Toolbar */}
      <div className="noc-panel p-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          {clientGroups.map((g) => {
            const t = topologies[g.clientId];
            const h = t?.health || {};
            return (
              <button
                key={g.clientId}
                onClick={() => setActiveClient(g.clientId)}
                className={`h-8 px-3 rounded-lg text-xs font-medium transition-all flex items-center gap-2 ${
                  activeClient === g.clientId
                    ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/40"
                    : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)] border border-transparent"
                }`}
                data-testid={`select-client-map-${g.clientId}`}
              >
                <div className={`w-2 h-2 rounded-full ${h.score >= 80 ? "bg-emerald-500" : h.score >= 50 ? "bg-amber-500" : "bg-red-500"}`} />
                {g.clientName}
                <span className="text-[9px] font-mono opacity-60">{t?.nodes?.length || 0}</span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setConnectMode(!connectMode)}
            className={`h-7 px-2.5 rounded-md text-[10px] font-medium flex items-center gap-1.5 transition-all ${
              connectMode
                ? "bg-purple-600/20 text-purple-400 border border-purple-500/40"
                : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)] border border-[var(--bg-border)]"
            }`}
            title={connectMode ? "Clicca su un collegamento per rimuoverlo" : "Attiva modalita' modifica collegamenti"}
            data-testid="toggle-connect-mode"
          >
            <Plugs size={13} /> {connectMode ? "Modifica ON" : "Modifica"}
          </button>
          <button
            onClick={autoLayout}
            className="h-7 px-2.5 rounded-md text-[10px] font-medium text-[var(--text-muted)] hover:bg-[var(--bg-hover)] border border-[var(--bg-border)] flex items-center gap-1.5 transition-all"
            title="Ricalcola layout automatico"
            data-testid="auto-layout-btn"
          >
            <MagicWand size={13} /> Auto
          </button>
          <button
            onClick={resetLayout}
            className="h-7 px-2.5 rounded-md text-[10px] font-medium text-[var(--text-muted)] hover:bg-[var(--bg-hover)] border border-[var(--bg-border)] flex items-center gap-1.5 transition-all"
            title="Resetta il layout personalizzato"
            data-testid="reset-layout-btn"
          >
            <ArrowsClockwise size={13} /> Reset
          </button>
          <button
            onClick={saveLayout}
            disabled={!hasChanges || saving}
            className={`h-7 px-3 rounded-md text-[10px] font-bold flex items-center gap-1.5 transition-all ${
              hasChanges
                ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                : "bg-[var(--bg-hover)] text-[var(--text-muted)] opacity-50 cursor-not-allowed"
            }`}
            title="Salva il layout personalizzato"
            data-testid="save-layout-btn"
          >
            <FloppyDisk size={13} /> {saving ? "Salvataggio..." : "Salva Layout"}
          </button>
        </div>
      </div>

      {/* Health Bar */}
      {activeTopo && (
        <div className="noc-panel px-3 py-2 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="text-xs font-bold text-[var(--text-primary)]">{activeTopo.client_name}</span>
            <span className="text-[10px] text-[var(--text-muted)] font-mono">
              {health.devices_online}/{health.devices_total} online
            </span>
            {health.avg_ping_ms && (
              <span className="text-[10px] px-1.5 py-0.5 rounded border text-[var(--text-muted)] border-[var(--bg-border)] font-mono">
                avg {health.avg_ping_ms}ms
              </span>
            )}
            {health.ports_total > 0 && (
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                Porte: {health.ports_up}/{health.ports_total}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {activeTopo.has_custom_layout && (
              <span className="text-[9px] px-2 py-0.5 rounded-full bg-purple-600/15 text-purple-400 border border-purple-500/30 font-medium">
                Layout personalizzato
              </span>
            )}
            {activeTopo.lldp_count > 0 && (
              <span className="text-[9px] px-2 py-0.5 rounded-full bg-cyan-600/15 text-cyan-400 border border-cyan-500/30 font-medium" data-testid="lldp-badge">
                LLDP: {activeTopo.lldp_count}
              </span>
            )}
            {activeTopo.mac_connections_count > 0 && (
              <span className="text-[9px] px-2 py-0.5 rounded-full bg-emerald-600/15 text-emerald-400 border border-emerald-500/30 font-medium" data-testid="mac-badge">
                MAC: {activeTopo.mac_connections_count}
              </span>
            )}
            <span
              className={`font-heading text-lg font-black ${
                health.score >= 80 ? "text-emerald-400" : health.score >= 50 ? "text-amber-400" : "text-red-400"
              }`}
              data-testid="health-score"
            >
              {health.score}%
            </span>
          </div>
        </div>
      )}

      {/* React Flow Canvas */}
      <div
        ref={containerRef}
        className="noc-panel overflow-hidden"
        style={{ height: "calc(100vh - 340px)", minHeight: 420 }}
        data-testid="network-map-canvas"
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDragStop={onNodeDragStop}
          onEdgeClick={onEdgeClick}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          connectionLineStyle={{ stroke: "#8b5cf6", strokeWidth: 2 }}
          defaultEdgeOptions={{
            style: { strokeWidth: 1.5 },
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
          }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.2}
          maxZoom={3}
          snapToGrid
          snapGrid={[15, 15]}
          style={{ background: "var(--bg-app)" }}
        >
          <Background color="var(--bg-border)" gap={30} size={1} />
          <Controls
            showInteractive={false}
            className="!bg-[var(--bg-panel)] !border-[var(--bg-border)] !rounded-lg !shadow-lg [&>button]:!bg-[var(--bg-card)] [&>button]:!border-[var(--bg-border)] [&>button]:!fill-[var(--text-muted)] [&>button:hover]:!bg-[var(--bg-hover)]"
          />
          <MiniMap
            nodeColor={(n) => {
              const cfg = TYPE_CONFIG[n.data?.deviceType] || TYPE_CONFIG.generic;
              return cfg.color;
            }}
            maskColor="rgba(10,10,15,0.85)"
            className="!bg-[var(--bg-panel)] !border-[var(--bg-border)] !rounded-lg"
          />
          {/* Legend overlay */}
          <Panel position="bottom-left" className="!m-2">
            <div className="bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded-lg p-2.5 space-y-1">
              <p className="text-[8px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Collegamento</p>
              {[
                { label: "WAN", color: EDGE_COLORS.wan },
                { label: "Trunk", color: EDGE_COLORS.trunk },
                { label: "Accesso", color: EDGE_COLORS.access },
                { label: "Server", color: EDGE_COLORS.server },
                { label: "MGMT", color: EDGE_COLORS.mgmt },
                { label: "LLDP", color: EDGE_COLORS.lldp },
                { label: "Manuale", color: EDGE_COLORS.custom },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-2">
                  <div className="w-4 h-0.5 rounded" style={{ backgroundColor: item.color }} />
                  <span className="text-[9px] text-[var(--text-secondary)]">{item.label}</span>
                </div>
              ))}
            </div>
          </Panel>
          {/* Connect mode indicator */}
          {connectMode && (
            <Panel position="top-center" className="!m-2">
              <div className="bg-purple-600/20 border border-purple-500/40 rounded-lg px-4 py-1.5 text-[11px] text-purple-300 font-medium flex items-center gap-2">
                <Plugs size={14} /> Trascina da un nodo all'altro per collegare. Clicca su un collegamento per rimuoverlo.
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>
    </div>
  );
}

/* ─── Wrapper with Provider ─── */
export default function NetworkMap({ clientGroups, onDeviceSelect }) {
  return (
    <ReactFlowProvider>
      <NetworkMapInner clientGroups={clientGroups} onDeviceSelect={onDeviceSelect} />
    </ReactFlowProvider>
  );
}
