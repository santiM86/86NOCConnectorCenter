import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { 
  FunnelSimple, MagnifyingGlass, CaretDown, Check
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";

export default function AlertsPage() {
  const [alerts, setAlerts] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState({
    status: searchParams.get("status") || "",
    severity: searchParams.get("severity") || "",
    client_id: searchParams.get("client_id") || "",
    device_type: searchParams.get("device_type") || "",
    search: "",
  });
  const navigate = useNavigate();

  // Sync filters -> URL so the state is shareable and the back button works as expected
  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.client_id) params.set("client_id", filters.client_id);
    if (filters.device_type) params.set("device_type", filters.device_type);
    setSearchParams(params, { replace: true });
  }, [filters.status, filters.severity, filters.client_id, filters.device_type, setSearchParams]);

  useEffect(() => { fetchAlerts(); fetchClients(); }, [filters.status, filters.severity, filters.client_id, filters.device_type]);

  const fetchAlerts = async () => {
    try {
      const params = new URLSearchParams();
      if (filters.status) params.append("status", filters.status);
      if (filters.severity) params.append("severity", filters.severity);
      if (filters.client_id) params.append("client_id", filters.client_id);
      if (filters.device_type) params.append("device_type", filters.device_type);
      params.append("limit", "500");
      const response = await axios.get(`${API}/alerts?${params.toString()}`);
      setAlerts(response.data);
    } catch { toast.error("Errore nel caricamento alert"); }
    finally { setLoading(false); }
  };

  const fetchClients = async () => {
    try { const r = await axios.get(`${API}/clients`); setClients(r.data); } catch {}
  };

  const handleAcknowledge = async (alertId, e) => {
    e.stopPropagation();
    try { await axios.patch(`${API}/alerts/${alertId}`, { status: "acknowledged" }); fetchAlerts(); toast.success("Alert confermato"); }
    catch { toast.error("Errore"); }
  };

  const handleResolve = async (alertId, e) => {
    e.stopPropagation();
    try { await axios.patch(`${API}/alerts/${alertId}`, { status: "resolved" }); fetchAlerts(); toast.success("Alert risolto"); }
    catch { toast.error("Errore"); }
  };

  const filteredAlerts = alerts.filter(alert => {
    if (!filters.search) return true;
    const s = filters.search.toLowerCase();
    return alert.title?.toLowerCase().includes(s) || alert.message?.toLowerCase().includes(s) ||
      alert.device_name?.toLowerCase().includes(s) || alert.client_name?.toLowerCase().includes(s) ||
      alert.ip_address?.toLowerCase().includes(s);
  });

  const sevOpts = [{ value: "", label: "Tutte" }, { value: "critical", label: "Critico" }, { value: "high", label: "Alto" }, { value: "medium", label: "Medio" }, { value: "low", label: "Basso" }];
  const statusOpts = [{ value: "", label: "Tutti" }, { value: "active", label: "Attivo" }, { value: "acknowledged", label: "Confermato" }, { value: "resolved", label: "Risolto" }];
  const typeOpts = [{ value: "", label: "Tutti" }, { value: "backup", label: "Backup" }, { value: "firewall", label: "Firewall" }, { value: "switch", label: "Switch" }, { value: "ilo", label: "ILO/iDRAC" }];

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="alerts-page">
      <div className="mb-4">
        <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Alert</h1>
        <p className="text-[var(--text-muted)] text-xs mt-0.5">Gestione e monitoraggio alert</p>
      </div>

      <div className="filter-bar mb-3">
        <div className="flex items-center gap-1.5 text-[var(--text-muted)]">
          <FunnelSimple size={14} />
          <span className="text-[10px] uppercase tracking-widest">Filtri:</span>
        </div>
        <div className="relative flex-1 min-w-[180px]">
          <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <Input placeholder="Cerca..." value={filters.search}
            onChange={(e) => setFilters(f => ({ ...f, search: e.target.value }))}
            className="pl-8 bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md h-8 text-xs"
            data-testid="search-input" />
        </div>
        <FilterDropdown label="Sev." value={filters.severity} options={sevOpts} onChange={v => setFilters(f => ({...f, severity: v}))} testId="filter-severity" />
        <FilterDropdown label="Stato" value={filters.status} options={statusOpts} onChange={v => setFilters(f => ({...f, status: v}))} testId="filter-status" />
        <FilterDropdown label="Tipo" value={filters.device_type} options={typeOpts} onChange={v => setFilters(f => ({...f, device_type: v}))} testId="filter-device-type" />
        <FilterDropdown label="Cliente" value={filters.client_id}
          options={[{ value: "", label: "Tutti" }, ...clients.map(c => ({ value: c.id, label: c.name }))]}
          onChange={v => setFilters(f => ({...f, client_id: v}))} testId="filter-client" />
      </div>

      <p className="text-[var(--text-muted)] text-[10px] mb-2">{filteredAlerts.length} alert</p>

      <div className="noc-panel overflow-hidden">
        <ScrollArea className="h-[calc(100vh-280px)]">
          <table className="alert-table" data-testid="alerts-table">
            <thead>
              <tr>
                <th className="w-20">Sev.</th>
                <th className="w-20">Stato</th>
                <th>Titolo</th>
                <th>Dispositivo</th>
                <th>Cliente</th>
                <th className="w-24">IP</th>
                <th className="w-16">Fonte</th>
                <th className="w-28">Data</th>
                <th className="w-24"></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="text-center text-[var(--text-muted)] py-6 text-xs">Caricamento...</td></tr>
              ) : filteredAlerts.length === 0 ? (
                <tr><td colSpan={9} className="text-center text-[var(--text-muted)] py-6 text-xs">Nessun alert</td></tr>
              ) : (
                filteredAlerts.map(alert => (
                  <tr key={alert.id} className="cursor-pointer" onClick={() => navigate(`/alerts/${alert.id}`)} data-testid={`alert-row-${alert.id}`}>
                    <td><span className={`severity-badge severity-${alert.severity}`}>{alert.severity}</span></td>
                    <td><span className={`text-[10px] uppercase tracking-wider status-${alert.status}`}>{alert.status}</span></td>
                    <td className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">{alert.title}</td>
                    <td className="font-mono text-[var(--text-muted)] text-xs">{alert.device_name}</td>
                    <td className="text-[var(--text-secondary)] text-xs">{alert.client_name}</td>
                    <td className="font-mono text-[var(--medium)] text-xs">{alert.ip_address}</td>
                    <td className="text-[10px] uppercase text-[var(--text-muted)]">{alert.source_type}</td>
                    <td className="font-mono text-[var(--text-muted)] text-[10px]">
                      {new Date(alert.created_at).toLocaleString("it-IT",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      <div className="flex gap-1">
                        {alert.status === "active" && (
                          <Button size="sm" variant="outline" onClick={e => handleAcknowledge(alert.id, e)}
                            className="rounded-md text-[10px] h-6 px-2 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                            data-testid={`ack-btn-${alert.id}`}>ACK</Button>
                        )}
                        {alert.status !== "resolved" && (
                          <Button size="sm" variant="outline" onClick={e => handleResolve(alert.id, e)}
                            className="rounded-md text-[10px] h-6 px-1.5 border-[var(--bg-border)] hover:bg-[var(--low-bg)] hover:text-[var(--low)] hover:border-[var(--low-border)]"
                            data-testid={`resolve-btn-${alert.id}`}><Check size={12} /></Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollArea>
      </div>
    </div>
  );
}

function FilterDropdown({ label, value, options, onChange, testId }) {
  const selectedLabel = options.find(o => o.value === value)?.label || label;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm"
          className="rounded-md h-8 border-[var(--bg-border)] bg-[var(--bg-card)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] gap-1 text-xs"
          data-testid={testId}>
          <span className="text-[var(--text-muted)] text-[10px]">{label}:</span>
          <span>{selectedLabel}</span>
          <CaretDown size={12} className="text-[var(--text-muted)]" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg min-w-[130px]">
        {options.map(opt => (
          <DropdownMenuItem key={opt.value} onClick={() => onChange(opt.value)}
            className={`rounded-md text-xs ${value === opt.value ? "bg-[var(--bg-hover)] text-[var(--text-primary)]" : "text-[var(--text-secondary)]"}`}>
            {opt.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
