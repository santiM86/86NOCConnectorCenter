import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  MagnifyingGlass, FunnelSimple, ArrowUp, ArrowDown, HardDrives,
  WifiHigh, WifiSlash, Desktop, ShieldCheckered, ArrowsDownUp,
  Database, Globe, CircleWavyCheck
} from "@phosphor-icons/react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { DeviceDetailPanel } from "@/components/DeviceDetailPanel";

const TYPE_ICONS = {
  switch: <Database size={14} className="text-cyan-400" />,
  firewall: <ShieldCheckered size={14} className="text-orange-400" />,
  server: <HardDrives size={14} className="text-indigo-400" />,
  ap: <WifiHigh size={14} className="text-green-400" />,
  unknown: <Desktop size={14} className="text-[var(--text-muted)]" />,
};

export default function InventoryPage() {
  const [data, setData] = useState(null);
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState("");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState("device_ip");
  const [sortDir, setSortDir] = useState("asc");
  const [selectedDevice, setSelectedDevice] = useState(null);

  useEffect(() => {
    axios.get(`${API}/clients`).then(r => {
      const c = r.data?.clients || r.data || [];
      setClients(c);
      if (c.length > 0) setClientId(c[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!clientId) return;
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (typeFilter) params.set("device_type", typeFilter);
    if (statusFilter) params.set("status", statusFilter);
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    axios.get(`${API}/inventory/${clientId}?${params}`).then(r => setData(r.data)).catch(() => {});
  }, [clientId, search, typeFilter, statusFilter, sortBy, sortDir]);

  const toggleSort = (field) => {
    if (sortBy === field) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortBy(field); setSortDir("asc"); }
  };

  const SortIcon = ({ field }) => {
    if (sortBy !== field) return <ArrowsDownUp size={10} className="text-[var(--text-muted)] opacity-40" />;
    return sortDir === "asc" ? <ArrowUp size={10} className="text-indigo-400" /> : <ArrowDown size={10} className="text-indigo-400" />;
  };

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="inventory-page">
      <div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Inventario Dispositivi</h1>
            <p className="text-[var(--text-muted)] text-xs mt-0.5">Vista completa di tutti i dispositivi in rete — <span className="text-indigo-400">clicca per dettagli</span></p>
          </div>
        </div>
      </div>

      {/* Stats */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatBox label="Totale" value={data.total} icon={<HardDrives size={16} />} color="indigo" />
          <StatBox label="Online" value={data.online} icon={<WifiHigh size={16} />} color="emerald" />
          <StatBox label="Offline" value={data.offline} icon={<WifiSlash size={16} />} color="red" />
          <StatBox label="Tipi" value={Object.keys(data.types || {}).length} icon={<FunnelSimple size={16} />} color="amber" />
        </div>
      )}

      {/* Filters */}
      <div className="noc-panel p-3 flex flex-wrap items-center gap-2">
        {clients.length > 1 && (
          <Select value={clientId} onValueChange={setClientId}>
            <SelectTrigger className="w-[180px] h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs" data-testid="inv-client-select">
              <SelectValue placeholder="Cliente" />
            </SelectTrigger>
            <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
              {clients.map(c => (
                <SelectItem key={c.id} value={c.id} className="text-xs text-[var(--text-primary)]">{c.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <div className="relative flex-1 min-w-[200px]">
          <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <Input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Cerca per IP, nome, MAC..."
            className="pl-8 h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs text-[var(--text-primary)]"
            data-testid="inv-search"
          />
        </div>

        <Select value={typeFilter} onValueChange={v => setTypeFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[130px] h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs" data-testid="inv-type-filter">
            <SelectValue placeholder="Tipo" />
          </SelectTrigger>
          <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
            <SelectItem value="all" className="text-xs text-[var(--text-primary)]">Tutti i tipi</SelectItem>
            <SelectItem value="switch" className="text-xs text-[var(--text-primary)]">Switch</SelectItem>
            <SelectItem value="firewall" className="text-xs text-[var(--text-primary)]">Firewall</SelectItem>
            <SelectItem value="server" className="text-xs text-[var(--text-primary)]">Server</SelectItem>
            <SelectItem value="ap" className="text-xs text-[var(--text-primary)]">Access Point</SelectItem>
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={v => setStatusFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[120px] h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs" data-testid="inv-status-filter">
            <SelectValue placeholder="Stato" />
          </SelectTrigger>
          <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
            <SelectItem value="all" className="text-xs text-[var(--text-primary)]">Tutti</SelectItem>
            <SelectItem value="online" className="text-xs text-[var(--text-primary)]">Online</SelectItem>
            <SelectItem value="offline" className="text-xs text-[var(--text-primary)]">Offline</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="relative min-h-[600px]">
        <div className={`noc-panel overflow-x-auto transition-all ${selectedDevice ? "md:mr-[390px]" : ""}`}>
          <table className="alert-table w-full min-w-[900px]" data-testid="inventory-table">
          <thead>
            <tr>
              {[
                { key: "reachable", label: "Stato", w: "60px" },
                { key: "device_name", label: "Nome" },
                { key: "device_ip", label: "IP" },
                { key: "device_type", label: "Tipo" },
                { key: "monitor_type", label: "Monitor" },
                { key: "mac", label: "MAC" },
                { key: "ping_ms", label: "Ping" },
                { key: "ports_up", label: "Porte" },
                { key: "last_seen", label: "Ultimo Contatto" },
                { key: "_actions", label: "", w: "40px" },
              ].map(col => (
                <th key={col.key} className={col.key !== "_actions" ? "cursor-pointer select-none" : ""} style={col.w ? {width: col.w} : {}}
                  onClick={() => col.key !== "_actions" && toggleSort(col.key)}>
                  <div className="flex items-center gap-1">
                    {col.label} <SortIcon field={col.key} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!data ? (
              <tr><td colSpan={10} className="text-center text-[var(--text-muted)] py-8 text-xs">Caricamento...</td></tr>
            ) : data.devices.length === 0 ? (
              <tr><td colSpan={10} className="text-center text-[var(--text-muted)] py-8 text-xs">Nessun dispositivo trovato</td></tr>
            ) : (
              data.devices.map((d, i) => (
                <tr key={d.device_ip + i} data-testid={`inv-row-${d.device_ip}`}
                  className={`cursor-pointer transition-colors hover:bg-indigo-500/5 ${selectedDevice?.device_ip === d.device_ip ? "!bg-indigo-500/10" : ""}`}
                  onClick={() => setSelectedDevice(d)}
                >
                  <td>
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      d.reachable ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${d.reachable ? "bg-emerald-400" : "bg-red-400"}`} />
                      {d.reachable ? "ON" : "OFF"}
                    </span>
                  </td>
                  <td className="font-medium text-[var(--text-primary)]">
                    <div className="flex items-center gap-1.5">
                      {TYPE_ICONS[d.device_type] || TYPE_ICONS.unknown}
                      <span className="truncate max-w-[180px]">{d.device_name || "-"}</span>
                    </div>
                  </td>
                  <td className="font-mono text-[var(--text-muted)]">{d.device_ip}</td>
                  <td className="capitalize text-[var(--text-secondary)]">{d.device_type || "-"}</td>
                  <td><span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-deep)] text-[var(--text-muted)]">{d.monitor_type}</span></td>
                  <td className="font-mono text-[10px] text-[var(--text-muted)]">{d.mac || "-"}</td>
                  <td className="font-mono">
                    {d.ping_ms != null ? (
                      <span className={d.ping_ms < 10 ? "text-emerald-400" : d.ping_ms < 50 ? "text-amber-400" : "text-red-400"}>
                        {d.ping_ms}ms
                      </span>
                    ) : "-"}
                  </td>
                  <td className="text-[var(--text-secondary)]">{d.ports_total > 0 ? `${d.ports_up}/${d.ports_total}` : "-"}</td>
                  <td className="text-[10px] text-[var(--text-muted)]">{d.uptime_display || "-"}</td>
                  <td>
                    <button
                      className="w-7 h-7 rounded-md flex items-center justify-center text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 transition-colors"
                      onClick={(e) => { e.stopPropagation(); setSelectedDevice(d); }}
                      data-testid={`inv-detail-btn-${d.device_ip}`}
                    >
                      <MagnifyingGlass size={14} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

        {/* Detail Panel */}
        {selectedDevice && (
          <DeviceDetailPanel
            clientId={clientId}
            deviceIp={selectedDevice.device_ip}
            deviceData={{
              label: selectedDevice.device_name || selectedDevice.device_ip,
              ip: selectedDevice.device_ip,
              mac: selectedDevice.mac,
              role: selectedDevice.device_type,
            }}
            onClose={() => setSelectedDevice(null)}
            onDeviceAdded={() => {}}
          />
        )}
      </div>
    </div>
  );
}

function StatBox({ label, value, icon, color }) {
  const colors = {
    indigo: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
    emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    red: "text-red-400 bg-red-500/10 border-red-500/20",
    amber: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  };
  return (
    <div className={`rounded-lg p-3 border ${colors[color]}`} data-testid={`inv-stat-${label.toLowerCase()}`}>
      <div className="flex items-center gap-2 mb-1">{icon}</div>
      <p className="font-heading text-2xl font-bold leading-none">{value}</p>
      <p className="text-[10px] uppercase tracking-widest mt-1 opacity-70">{label}</p>
    </div>
  );
}
