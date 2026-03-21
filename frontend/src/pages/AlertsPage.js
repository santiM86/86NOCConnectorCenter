import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { 
  FunnelSimple, 
  MagnifyingGlass,
  CaretDown,
  Check
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";

export default function AlertsPage() {
  const [alerts, setAlerts] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    status: "",
    severity: "",
    client_id: "",
    device_type: "",
    search: ""
  });
  const navigate = useNavigate();

  useEffect(() => {
    fetchAlerts();
    fetchClients();
  }, [filters.status, filters.severity, filters.client_id, filters.device_type]);

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
    } catch (error) {
      toast.error("Errore nel caricamento alert");
    } finally {
      setLoading(false);
    }
  };

  const fetchClients = async () => {
    try {
      const response = await axios.get(`${API}/clients`);
      setClients(response.data);
    } catch (error) {
      console.error("Error fetching clients:", error);
    }
  };

  const handleAcknowledge = async (alertId, e) => {
    e.stopPropagation();
    try {
      await axios.patch(`${API}/alerts/${alertId}`, { status: "acknowledged" });
      fetchAlerts();
      toast.success("Alert confermato");
    } catch (error) {
      toast.error("Errore");
    }
  };

  const handleResolve = async (alertId, e) => {
    e.stopPropagation();
    try {
      await axios.patch(`${API}/alerts/${alertId}`, { status: "resolved" });
      fetchAlerts();
      toast.success("Alert risolto");
    } catch (error) {
      toast.error("Errore");
    }
  };

  const filteredAlerts = alerts.filter(alert => {
    if (filters.search) {
      const search = filters.search.toLowerCase();
      return (
        alert.title.toLowerCase().includes(search) ||
        alert.message.toLowerCase().includes(search) ||
        alert.device_name?.toLowerCase().includes(search) ||
        alert.client_name?.toLowerCase().includes(search) ||
        alert.ip_address?.toLowerCase().includes(search)
      );
    }
    return true;
  });

  const severityOptions = [
    { value: "", label: "Tutte" },
    { value: "critical", label: "Critico" },
    { value: "high", label: "Alto" },
    { value: "medium", label: "Medio" },
    { value: "low", label: "Basso" }
  ];

  const statusOptions = [
    { value: "", label: "Tutti" },
    { value: "active", label: "Attivo" },
    { value: "acknowledged", label: "Confermato" },
    { value: "resolved", label: "Risolto" }
  ];

  const deviceTypeOptions = [
    { value: "", label: "Tutti" },
    { value: "backup", label: "Backup" },
    { value: "firewall", label: "Firewall" },
    { value: "switch", label: "Switch" },
    { value: "ilo", label: "ILO/iDRAC" }
  ];

  return (
    <div className="p-4 md:p-6" data-testid="alerts-page">
      {/* Header */}
      <div className="mb-6">
        <h1 className="font-heading text-2xl font-bold text-zinc-100 tracking-tight">
          Alert
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          Gestione e monitoraggio di tutti gli alert
        </p>
      </div>

      {/* Filter Bar */}
      <div className="filter-bar mb-4 flex-wrap">
        <div className="flex items-center gap-2 text-zinc-400">
          <FunnelSimple size={18} />
          <span className="text-xs uppercase tracking-wider">Filtri:</span>
        </div>

        {/* Search */}
        <div className="relative flex-1 min-w-[200px]">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <Input
            placeholder="Cerca..."
            value={filters.search}
            onChange={(e) => setFilters(f => ({ ...f, search: e.target.value }))}
            className="pl-9 bg-zinc-900 border-zinc-800 text-zinc-100 rounded-sm h-9 text-sm"
            data-testid="search-input"
          />
        </div>

        {/* Severity Filter */}
        <FilterDropdown
          label="Severità"
          value={filters.severity}
          options={severityOptions}
          onChange={(v) => setFilters(f => ({ ...f, severity: v }))}
          testId="filter-severity"
        />

        {/* Status Filter */}
        <FilterDropdown
          label="Stato"
          value={filters.status}
          options={statusOptions}
          onChange={(v) => setFilters(f => ({ ...f, status: v }))}
          testId="filter-status"
        />

        {/* Device Type Filter */}
        <FilterDropdown
          label="Tipo"
          value={filters.device_type}
          options={deviceTypeOptions}
          onChange={(v) => setFilters(f => ({ ...f, device_type: v }))}
          testId="filter-device-type"
        />

        {/* Client Filter */}
        <FilterDropdown
          label="Cliente"
          value={filters.client_id}
          options={[
            { value: "", label: "Tutti" },
            ...clients.map(c => ({ value: c.id, label: c.name }))
          ]}
          onChange={(v) => setFilters(f => ({ ...f, client_id: v }))}
          testId="filter-client"
        />
      </div>

      {/* Alert Count */}
      <div className="mb-4 text-zinc-500 text-sm">
        {filteredAlerts.length} alert trovati
      </div>

      {/* Alerts Table */}
      <div className="noc-panel overflow-hidden">
        <ScrollArea className="h-[calc(100vh-320px)]">
          <table className="alert-table" data-testid="alerts-table">
            <thead>
              <tr>
                <th className="w-24">Severità</th>
                <th className="w-24">Stato</th>
                <th>Titolo</th>
                <th>Dispositivo</th>
                <th>Cliente</th>
                <th className="w-28">IP</th>
                <th className="w-20">Fonte</th>
                <th className="w-36">Data/Ora</th>
                <th className="w-32">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="text-center text-zinc-500 py-8">
                    Caricamento...
                  </td>
                </tr>
              ) : filteredAlerts.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center text-zinc-500 py-8">
                    Nessun alert trovato
                  </td>
                </tr>
              ) : (
                filteredAlerts.map((alert) => (
                  <tr 
                    key={alert.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/alerts/${alert.id}`)}
                    data-testid={`alert-row-${alert.id}`}
                  >
                    <td>
                      <span className={`severity-badge severity-${alert.severity}`}>
                        {alert.severity}
                      </span>
                    </td>
                    <td>
                      <span className={`text-xs uppercase tracking-wider status-${alert.status}`}>
                        {alert.status}
                      </span>
                    </td>
                    <td className="text-zinc-200 hover:text-white transition-fast">
                      {alert.title}
                    </td>
                    <td className="font-mono text-zinc-400 text-sm">
                      {alert.device_name}
                    </td>
                    <td className="text-zinc-300">{alert.client_name}</td>
                    <td className="font-mono text-blue-400 text-sm">{alert.ip_address}</td>
                    <td className="text-xs uppercase text-zinc-500">{alert.source_type}</td>
                    <td className="font-mono text-zinc-500 text-xs">
                      {new Date(alert.created_at).toLocaleString("it-IT", {
                        day: "2-digit",
                        month: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit"
                      })}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div className="flex gap-1">
                        {alert.status === "active" && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={(e) => handleAcknowledge(alert.id, e)}
                            className="rounded-sm text-xs h-7 border-zinc-700 hover:bg-zinc-800"
                            data-testid={`ack-btn-${alert.id}`}
                          >
                            ACK
                          </Button>
                        )}
                        {alert.status !== "resolved" && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={(e) => handleResolve(alert.id, e)}
                            className="rounded-sm text-xs h-7 border-zinc-700 hover:bg-green-900/50 hover:text-green-400 hover:border-green-800"
                            data-testid={`resolve-btn-${alert.id}`}
                          >
                            <Check size={14} />
                          </Button>
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

const FilterDropdown = ({ label, value, options, onChange, testId }) => {
  const selectedLabel = options.find(o => o.value === value)?.label || label;
  
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button 
          variant="outline" 
          size="sm"
          className="rounded-sm h-9 border-zinc-800 bg-zinc-900 hover:bg-zinc-800 text-zinc-300 gap-2"
          data-testid={testId}
        >
          <span className="text-zinc-500 text-xs">{label}:</span>
          <span>{selectedLabel}</span>
          <CaretDown size={14} className="text-zinc-500" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent 
        align="start"
        className="bg-zinc-900 border-zinc-800 rounded-sm min-w-[150px]"
      >
        {options.map((opt) => (
          <DropdownMenuItem
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`rounded-sm text-sm ${value === opt.value ? "bg-zinc-800 text-white" : "text-zinc-300"}`}
          >
            {opt.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
