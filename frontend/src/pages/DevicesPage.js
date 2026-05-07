import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Plus, Trash, HardDrives, WifiHigh, WifiSlash, MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { DeviceDetailPanel } from "@/components/DeviceDetailPanel";
import { useSortableTable, SortableTh } from "@/utils/tableSort";

export default function DevicesPage() {
  const [devices, setDevices] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", ip_address: "", client_id: "", type: "switch", description: "" });
  const [selectedDevice, setSelectedDevice] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    try {
      const [devRes, cliRes] = await Promise.all([
        axios.get(`${API}/devices`),
        axios.get(`${API}/clients`)
      ]);
      setDevices(devRes.data);
      setClients(cliRes.data);
    } catch { toast.error("Errore nel caricamento"); }
    finally { setLoading(false); }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/devices`, form);
      toast.success("Dispositivo aggiunto");
      setDialogOpen(false);
      setForm({ name: "", ip_address: "", client_id: "", device_type: "switch", description: "" });
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const handleDelete = async (id) => {
    try { await axios.delete(`${API}/devices/${id}`); toast.success("Eliminato"); fetchAll(); }
    catch { toast.error("Errore"); }
  };

  const typeIcons = {
    firewall: { label: "Firewall", color: "var(--critical)" },
    switch: { label: "Switch", color: "#6366F1" },
    ilo: { label: "iLO/iDRAC", color: "var(--high)" },
    backup: { label: "Backup", color: "var(--low)" },
    server: { label: "Server", color: "#06B6D4" },
    printer: { label: "Stampante", color: "#FF9500" },
    generic: { label: "Generico", color: "var(--text-muted)" },
    "zyxel-usg": { label: "Firewall", color: "var(--critical)" },
    nas: { label: "NAS", color: "#10B981" },
    ups: { label: "UPS", color: "#F59E0B" },
    "access-point": { label: "WiFi AP", color: "#8B5CF6" },
    router: { label: "Router", color: "#06B6D4" },
    tvcc: { label: "TVCC", color: "#EC4899" },
  };

  // v3.8.31: ordinamento devices globale
  const STATUS_RANK = { online: 3, active: 2, offline: 1 };
  const { sorted: sortedDevices, sortKey, sortDir, requestSort } = useSortableTable(
    devices, "name", "asc",
    {
      persistKey: "devices-page-global",
      accessors: {
        name: (d) => (d?.name || "").toLowerCase(),
        device_type: (d) => (d?.device_type || d?.type || "").toLowerCase(),
        ip_address: (d) => {
          const ip = d?.ip_address || "";
          const p = ip.split(".").map(n => parseInt(n, 10));
          if (p.length === 4 && p.every(n => !isNaN(n))) return p[0]*16777216+p[1]*65536+p[2]*256+p[3];
          return ip.toLowerCase();
        },
        client_name: (d) => (d?.client_name || "").toLowerCase(),
        status: (d) => STATUS_RANK[d?.status] || 0,
      },
    }
  );

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="devices-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Dispositivi</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Monitoraggio dispositivi di rete — <span className="text-indigo-400">clicca per dettagli</span></p>
        </div>
        <Button onClick={() => setDialogOpen(true)} className="rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white gap-1.5 text-xs h-8" data-testid="add-device-btn">
          <Plus size={14} /> Nuovo
        </Button>
      </div>

      <div className="relative min-h-[600px]">
        <div className={`noc-panel overflow-x-auto transition-all ${selectedDevice ? "md:mr-[390px]" : ""}`}>
          <table className="alert-table min-w-[640px]" data-testid="devices-table">
            <thead>
              <tr>
                <SortableTh field="name" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Nome</SortableTh>
                <SortableTh field="device_type" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Tipo</SortableTh>
                <SortableTh field="ip_address" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>IP</SortableTh>
                <SortableTh field="client_name" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Cliente</SortableTh>
                <SortableTh field="status" sortKey={sortKey} sortDir={sortDir} onSort={requestSort}>Stato</SortableTh>
                <th>Azioni</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="text-center text-[var(--text-muted)] py-8 text-xs">Caricamento...</td></tr>
              ) : sortedDevices.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-8">
                  <HardDrives size={32} className="mx-auto text-[var(--text-muted)] mb-2" />
                  <p className="text-[var(--text-muted)] text-xs">Nessun dispositivo</p>
                </td></tr>
              ) : (
                sortedDevices.map(device => {
                  const typeInfo = typeIcons[device.device_type || device.type] || { label: device.device_type || device.type || "?", color: "var(--text-muted)" };
                  const isSelected = selectedDevice?.ip_address === device.ip_address;
                  return (
                    <tr key={device.id}
                      data-testid={`device-row-${device.id}`}
                      className={`cursor-pointer transition-colors hover:bg-indigo-500/5 ${isSelected ? "!bg-indigo-500/10" : ""}`}
                      onClick={() => setSelectedDevice(device)}
                    >
                      <td className="text-[var(--text-primary)] text-xs font-medium">{device.name}</td>
                    <td>
                      <span className="inline-flex items-center gap-1.5 text-[10px] px-2 py-0.5 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)]" style={{ color: typeInfo.color }}>
                        {typeInfo.label}
                      </span>
                    </td>
                    <td className="font-mono text-[var(--medium)] text-xs">{device.ip_address}</td>
                    <td className="text-[var(--text-secondary)] text-xs">{device.client_name}</td>
                    <td>
                      {device.status === "online" ? (
                        <span className="inline-flex items-center gap-1 text-[10px] text-[var(--ok)]"><WifiHigh size={12} /> Online</span>
                      ) : device.status === "active" ? (
                        <span className="inline-flex items-center gap-1 text-[10px] text-[var(--medium)]"><WifiHigh size={12} /> Attivo</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[10px] text-[var(--critical)]"><WifiSlash size={12} /> Offline</span>
                      )}
                      {device.source === "connector" && (
                        <span className="ml-1.5 text-[8px] px-1 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold">CONNECTOR</span>
                      )}
                    </td>
                    <td>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon"
                          className="h-7 w-7 text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 rounded-md"
                          onClick={(e) => { e.stopPropagation(); setSelectedDevice(device); }}
                          data-testid={`detail-btn-${device.id}`}
                        >
                          <MagnifyingGlass size={14} />
                        </Button>
                        <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-[var(--text-muted)] hover:text-[var(--critical)] rounded-md" data-testid={`delete-device-${device.id}`}>
                            <Trash size={14} />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                          <AlertDialogHeader>
                            <AlertDialogTitle className="text-[var(--text-primary)] text-sm">Eliminare {device.name}?</AlertDialogTitle>
                            <AlertDialogDescription className="text-[var(--text-muted)] text-xs">Azione irreversibile.</AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel className="rounded-md bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] text-xs">Annulla</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleDelete(device.id)} className="rounded-md bg-red-900 text-red-100 hover:bg-red-800 text-xs">Elimina</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

        {/* Detail Panel */}
        {selectedDevice && (
          <DeviceDetailPanel
            clientId={selectedDevice.client_id}
            deviceIp={selectedDevice.ip_address}
            deviceData={{
              label: selectedDevice.name,
              ip: selectedDevice.ip_address,
              role: selectedDevice.type,
            }}
            onClose={() => setSelectedDevice(null)}
            onDeviceAdded={fetchAll}
          />
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg max-w-md">
          <DialogHeader><DialogTitle className="font-heading text-[var(--text-primary)] text-sm">Nuovo Dispositivo</DialogTitle></DialogHeader>
          <form onSubmit={handleCreate} className="space-y-3 mt-3">
            <div className="space-y-1.5">
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Nome *</Label>
              <Input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} placeholder="FW-01" required
                className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="device-name-input" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">IP *</Label>
                <Input value={form.ip_address} onChange={e => setForm(f => ({...f, ip_address: e.target.value}))} placeholder="192.168.1.1" required
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="device-ip-input" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Tipo</Label>
                <Select value={form.device_type} onValueChange={v => setForm(f => ({...f, device_type: v}))}>
                  <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="device-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                    <SelectItem value="switch" className="text-xs">Switch</SelectItem>
                    <SelectItem value="firewall" className="text-xs">Firewall</SelectItem>
                    <SelectItem value="ilo" className="text-xs">ILO/iDRAC</SelectItem>
                    <SelectItem value="backup" className="text-xs">Backup</SelectItem>
                    <SelectItem value="server" className="text-xs">Server</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Cliente *</Label>
              <Select value={form.client_id} onValueChange={v => setForm(f => ({...f, client_id: v}))}>
                <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="device-client-select">
                  <SelectValue placeholder="Seleziona" />
                </SelectTrigger>
                <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                  {clients.map(c => <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setDialogOpen(false)} className="rounded-md text-xs">Annulla</Button>
              <Button type="submit" size="sm" className="rounded-md bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="save-device-btn">Salva</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
