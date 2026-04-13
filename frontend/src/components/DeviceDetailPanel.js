import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { X, Warning, WifiHigh, WifiSlash, CircleNotch, Globe, PlusCircle, ArrowSquareOut } from "@phosphor-icons/react";
import { toast } from "sonner";
import { SnmpConfigPanel } from "@/components/SnmpConfigPanel";

const SEVERITY_COLORS = {
  critical: { bg: "bg-red-500/20", text: "text-red-400", border: "border-red-500/30" },
  high: { bg: "bg-orange-500/20", text: "text-orange-400", border: "border-orange-500/30" },
  medium: { bg: "bg-yellow-500/20", text: "text-yellow-400", border: "border-yellow-500/30" },
  low: { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
};

export function DeviceDetailPanel({ clientId, deviceIp, deviceData, onClose, onDeviceAdded, openWebConsole }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [monitorType, setMonitorType] = useState("ping");
  const [community, setCommunity] = useState("public");
  const [proxyLoading, setProxyLoading] = useState(false);

  useEffect(() => {
    if (!clientId || !deviceIp) return;
    setLoading(true);
    axios.get(`${API}/network/device-detail/${clientId}/${deviceIp}`)
      .then(res => setDetail(res.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [clientId, deviceIp]);

  if (!deviceIp) return null;

  const isEndpoint = deviceData?.role === "discovered_endpoint";
  const hasIp = deviceIp && !deviceIp.startsWith("mac-");

  const openWebPage = async () => {
    const ip = deviceData?.ip || deviceIp;
    if (!ip || ip.startsWith("mac-")) return;

    if (openWebConsole) {
      openWebConsole(clientId, ip, 80);
      return;
    }

    setProxyLoading(true);
    try {
      const res = await axios.post(`${API}/connector/web-proxy/request`, {
        client_id: clientId, device_ip: ip, port: 80, path: "/", method: "GET"
      });
      const requestId = res.data.request_id;
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        if (attempts > 30) {
          clearInterval(poll);
          setProxyLoading(false);
          toast.error("Timeout: il connettore non ha risposto entro 60s");
          return;
        }
        try {
          const resp = await axios.get(`${API}/connector/web-proxy/response/${requestId}`);
          if (resp.data.status === "completed" && resp.data.response) {
            clearInterval(poll);
            setProxyLoading(false);
            const html = resp.data.response.body;
            const win = window.open("", "_blank");
            if (win) {
              win.document.write(html);
              win.document.title = resp.data.response.title || `${ip} - Web Console`;
            }
          }
        } catch {}
      }, 2000);
    } catch (e) {
      setProxyLoading(false);
      toast.error("Errore nella richiesta proxy: " + (e.response?.data?.detail || e.message));
    }
  };

  const addToMonitoring = async () => {
    setAdding(true);
    try {
      const res = await axios.post(`${API}/network/add-to-monitoring`, {
        client_id: clientId,
        ip: deviceData?.ip || deviceIp,
        name: deviceData?.hostname || deviceData?.label || deviceIp,
        mac: deviceData?.mac || "",
        monitor_type: monitorType,
        community: monitorType === "snmp" ? community : "",
      });
      toast.success(res.data.message || "Dispositivo aggiunto!");
      if (onDeviceAdded) onDeviceAdded();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message;
      toast.error("Errore: " + msg);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div
      data-testid="device-detail-panel"
      className="absolute right-0 top-0 bottom-0 w-[380px] bg-[var(--bg-panel)] border-l border-[var(--border-subtle)] shadow-2xl z-50 flex flex-col overflow-hidden animate-in slide-in-from-right duration-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border-subtle)]">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] truncate" data-testid="detail-device-name">
            {deviceData?.label || deviceIp}
          </h3>
          <div className="flex items-center gap-2 mt-0.5">
            {hasIp && <span className="text-xs font-mono text-[var(--text-muted)]">{deviceData?.ip || deviceIp}</span>}
            {deviceData?.mac && (
              <span className="text-[10px] font-mono text-[var(--text-muted)] bg-[var(--bg-deep)] px-1.5 py-0.5 rounded">{deviceData.mac}</span>
            )}
          </div>
        </div>
        <button onClick={onClose} className="p-1.5 rounded hover:bg-white/10 transition-colors" data-testid="detail-close-btn">
          <X size={18} className="text-[var(--text-muted)]" />
        </button>
      </div>

      {/* Action Buttons */}
      <div className="p-3 border-b border-[var(--border-subtle)] flex gap-2">
        {hasIp && (
          <button
            onClick={openWebPage}
            disabled={proxyLoading}
            className="flex-1 h-8 rounded-lg bg-indigo-600/15 text-indigo-400 border border-indigo-500/30 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-indigo-600/25 transition-all disabled:opacity-50"
            data-testid="open-web-btn"
          >
            <Globe size={14} /> {proxyLoading ? "Caricamento via Connettore..." : "Apri Pagina Web"}
          </button>
        )}
        {isEndpoint && hasIp && (
          <button
            onClick={addToMonitoring}
            disabled={adding}
            className="flex-1 h-8 rounded-lg bg-emerald-600/15 text-emerald-400 border border-emerald-500/30 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-emerald-600/25 transition-all disabled:opacity-50"
            data-testid="add-to-monitoring-btn"
          >
            <PlusCircle size={14} /> {adding ? "Aggiunta..." : "Aggiungi al Monitoraggio"}
          </button>
        )}
      </div>

      {/* Monitor type selector (only for endpoints being added) */}
      {isEndpoint && hasIp && (
        <div className="px-3 py-2 border-b border-[var(--border-subtle)] flex items-center gap-2 text-[10px]">
          <span className="text-[var(--text-muted)]">Tipo:</span>
          {["ping", "snmp"].map(t => (
            <button
              key={t}
              onClick={() => setMonitorType(t)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-all ${
                monitorType === t
                  ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/40"
                  : "text-[var(--text-muted)] hover:bg-[var(--bg-hover)] border border-transparent"
              }`}
            >
              {t.toUpperCase()}
            </button>
          ))}
          {monitorType === "snmp" && (
            <input
              type="text"
              value={community}
              onChange={e => setCommunity(e.target.value)}
              placeholder="community"
              className="ml-1 h-5 px-1.5 w-20 rounded bg-[var(--bg-deep)] border border-[var(--border-subtle)] text-[10px] text-[var(--text-primary)] font-mono"
            />
          )}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {loading && !isEndpoint ? (
          <div className="flex items-center justify-center py-8">
            <CircleNotch size={24} className="animate-spin text-indigo-400" />
          </div>
        ) : isEndpoint ? (
          <EndpointInfo data={deviceData} />
        ) : detail ? (
          <>
            <DeviceInfo device={detail.device} />
            <AlertsSection alerts={detail.alerts} activeCount={detail.active_alerts} />
            <PortSpeedsSection speeds={detail.port_speeds} />
            <ConnectedEndpoints endpoints={detail.connected_endpoints} />
            <LldpSection neighbors={detail.lldp_neighbors} />
            <MacConnections connections={detail.mac_connections} />
            {/* SNMP Configuration for managed devices */}
            {clientId && detail.device?.device_ip && (
              <div className="border-t border-[var(--border-subtle)] pt-3">
                <SnmpConfigPanel
                  clientId={clientId}
                  deviceId={detail.device?.id || detail.device?.device_id}
                  device={detail.device}
                />
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-[var(--text-muted)] text-center py-8">Nessun dato disponibile</p>
        )}
      </div>
    </div>
  );
}

function SectionTitle({ children, count }) {
  return (
    <div className="flex items-center justify-between mb-2">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{children}</h4>
      {count !== undefined && (
        <span className="text-[10px] bg-indigo-500/20 text-indigo-300 px-1.5 py-0.5 rounded-full">{count}</span>
      )}
    </div>
  );
}

function DeviceInfo({ device }) {
  if (!device) return null;
  const reachable = device.reachable;
  return (
    <div className="space-y-2" data-testid="device-info-section">
      <SectionTitle>Informazioni Dispositivo</SectionTitle>
      <div className="bg-[var(--bg-deep)]/50 rounded-lg p-3 space-y-1.5 text-xs">
        <div className="flex justify-between">
          <span className="text-[var(--text-muted)]">Stato</span>
          <span className={`flex items-center gap-1 ${reachable ? "text-emerald-400" : "text-red-400"}`}>
            {reachable ? <WifiHigh size={12} /> : <WifiSlash size={12} />}
            {reachable ? "Online" : "Offline"}
          </span>
        </div>
        {device.device_name && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">Nome</span>
            <span className="text-[var(--text-primary)] text-right max-w-[200px] truncate">{device.device_name}</span>
          </div>
        )}
        {device.monitor_type && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">Tipo Monitor</span>
            <span className="text-[var(--text-primary)] uppercase">{device.monitor_type}</span>
          </div>
        )}
        {device.ping_ms !== undefined && device.ping_ms !== null && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">Latenza</span>
            <span className="text-[var(--text-primary)]">{device.ping_ms} ms</span>
          </div>
        )}
        {device.sys_descr && (
          <div className="mt-2 pt-2 border-t border-[var(--border-subtle)]">
            <span className="text-[var(--text-muted)] block mb-1">System Description</span>
            <span className="text-[var(--text-primary)] text-[10px] break-words">{device.sys_descr}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function AlertsSection({ alerts, activeCount }) {
  if (!alerts?.length) return (
    <div data-testid="alerts-section">
      <SectionTitle count={0}>Alert</SectionTitle>
      <p className="text-xs text-[var(--text-muted)] text-center py-2">Nessun alert</p>
    </div>
  );
  return (
    <div data-testid="alerts-section">
      <SectionTitle count={activeCount}>Alert Attivi</SectionTitle>
      <div className="space-y-1.5 max-h-40 overflow-y-auto">
        {alerts.slice(0, 10).map((a, i) => {
          const sev = SEVERITY_COLORS[a.severity] || SEVERITY_COLORS.low;
          return (
            <div key={i} className={`${sev.bg} ${sev.border} border rounded-md px-2.5 py-1.5 text-xs`}>
              <div className="flex items-center gap-1.5">
                <Warning size={12} className={sev.text} weight="fill" />
                <span className={`${sev.text} font-medium uppercase text-[10px]`}>{a.severity}</span>
                <span className="text-[var(--text-muted)] text-[10px] ml-auto">{formatTime(a.created_at)}</span>
              </div>
              <p className="text-[var(--text-primary)] mt-0.5 text-[11px]">{a.message}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PortSpeedsSection({ speeds }) {
  if (!speeds?.length) return null;
  return (
    <div data-testid="port-speeds-section">
      <SectionTitle count={speeds.length}>Porte High-Speed</SectionTitle>
      <div className="grid grid-cols-2 gap-1.5">
        {speeds.map((p, i) => (
          <div key={i} className="bg-orange-500/10 border border-orange-500/20 rounded px-2 py-1 text-xs">
            <span className="text-orange-400 font-mono">Port {p.port}</span>
            <span className="text-[var(--text-muted)] ml-1">{p.speed_mbps >= 10000 ? "10G" : `${p.speed_mbps / 1000}G`}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ConnectedEndpoints({ endpoints }) {
  if (!endpoints?.length) return null;
  return (
    <div data-testid="connected-endpoints-section">
      <SectionTitle count={endpoints.length}>Endpoint Connessi</SectionTitle>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {endpoints.map((ep, i) => (
          <div key={i} className="bg-[var(--bg-deep)]/50 rounded px-2.5 py-1.5 text-xs flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-[var(--text-primary)] truncate">{ep.hostname || ep.ip || ep.mac}</div>
              <div className="text-[10px] text-[var(--text-muted)] font-mono">{ep.mac} | Port {ep.port}</div>
            </div>
            {ep.ip && <span className="text-[10px] text-indigo-400 font-mono flex-shrink-0">{ep.ip}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function LldpSection({ neighbors }) {
  if (!neighbors?.length) return null;
  return (
    <div data-testid="lldp-section">
      <SectionTitle count={neighbors.length}>LLDP Neighbors</SectionTitle>
      <div className="space-y-1">
        {neighbors.map((n, i) => (
          <div key={i} className="bg-cyan-500/10 border border-cyan-500/20 rounded px-2.5 py-1.5 text-xs">
            <div className="text-cyan-300 font-medium">{n.remote_name || n.remote_ip}</div>
            <div className="text-[10px] text-[var(--text-muted)]">
              Port {n.local_port} &rarr; Port {n.remote_port}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MacConnections({ connections }) {
  if (!connections?.length) return null;
  return (
    <div data-testid="mac-connections-section">
      <SectionTitle count={connections.length}>Connessioni MAC</SectionTitle>
      <div className="space-y-1">
        {connections.map((c, i) => (
          <div key={i} className="bg-indigo-500/10 border border-indigo-500/20 rounded px-2.5 py-1.5 text-xs">
            <span className="text-indigo-300 font-mono">Port {c.from_port}</span>
            <span className="text-[var(--text-muted)] mx-1">&rarr;</span>
            <span className="text-[var(--text-primary)]">{c.to_ip}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EndpointInfo({ data }) {
  if (!data) return null;
  return (
    <div className="space-y-2" data-testid="endpoint-info-section">
      <SectionTitle>Endpoint Scoperto</SectionTitle>
      <div className="bg-[var(--bg-deep)]/50 rounded-lg p-3 space-y-1.5 text-xs">
        {data.hostname && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">Hostname</span>
            <span className="text-[var(--text-primary)]">{data.hostname}</span>
          </div>
        )}
        {data.ip && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">IP</span>
            <span className="text-[var(--text-primary)] font-mono">{data.ip}</span>
          </div>
        )}
        {data.mac && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">MAC Address</span>
            <span className="text-[var(--text-primary)] font-mono text-[10px]">{data.mac}</span>
          </div>
        )}
        {data.switch_port && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">Porta Switch</span>
            <span className="text-[var(--text-primary)]">Port {data.switch_port}</span>
          </div>
        )}
        {data.vlan && (
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">VLAN</span>
            <span className="text-[var(--text-primary)]">{data.vlan}</span>
          </div>
        )}
      </div>

      {/* SNMP Configuration Panel */}
      {detail?.managed && clientId && detail?.device_id && (
        <div className="mt-3 border-t border-[var(--bg-border)] pt-3">
          <SnmpConfigPanel
            clientId={clientId}
            deviceId={detail.device_id}
            device={detail}
          />
        </div>
      )}
    </div>
  );
}

function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}
