import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { 
  Plus, 
  Trash, 
  HardDrives, 
  Shield, 
  Database, 
  Cpu,
  ArrowsClockwise,
  Key,
  CheckCircle,
  Warning,
  Plugs
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

const deviceTypeIcons = {
  backup: Database,
  firewall: Shield,
  switch: ArrowsClockwise,
  ilo: Cpu
};

const deviceTypeLabels = {
  backup: "Backup",
  firewall: "Firewall",
  switch: "Switch",
  ilo: "ILO/iDRAC"
};

export default function DevicesPage() {
  const [devices, setDevices] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [credDialogOpen, setCredDialogOpen] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [filterClient, setFilterClient] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [testingConnection, setTestingConnection] = useState(false);
  
  const [newDevice, setNewDevice] = useState({
    client_id: "",
    name: "",
    device_type: "",
    ip_address: "",
    hostname: "",
    location: "",
    redfish_enabled: false
  });
  
  const [credentials, setCredentials] = useState({
    username: "",
    password: ""
  });

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [devicesRes, clientsRes] = await Promise.all([
        axios.get(`${API}/devices`),
        axios.get(`${API}/clients`)
      ]);
      setDevices(devicesRes.data);
      setClients(clientsRes.data);
    } catch (error) {
      toast.error("Errore nel caricamento");
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/devices`, newDevice);
      toast.success("Dispositivo creato");
      setDialogOpen(false);
      setNewDevice({
        client_id: "",
        name: "",
        device_type: "",
        ip_address: "",
        hostname: "",
        location: "",
        redfish_enabled: false
      });
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Errore nella creazione");
    }
  };

  const handleDelete = async (deviceId) => {
    try {
      await axios.delete(`${API}/devices/${deviceId}`);
      toast.success("Dispositivo eliminato");
      fetchData();
    } catch (error) {
      toast.error("Errore nell'eliminazione");
    }
  };

  const handleSaveCredentials = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/devices/${selectedDevice.id}/credentials`, credentials);
      toast.success("Credenziali salvate con crittografia AES-256");
      setCredDialogOpen(false);
      setCredentials({ username: "", password: "" });
      fetchData();
    } catch (error) {
      toast.error("Errore nel salvataggio credenziali");
    }
  };

  const handleTestRedfish = async (deviceId) => {
    setTestingConnection(deviceId);
    try {
      const response = await axios.post(`${API}/devices/${deviceId}/test-redfish`);
      if (response.data.success) {
        toast.success(`Connesso! ${response.data.product} - Redfish v${response.data.version}`);
      } else {
        toast.error(`Errore: ${response.data.error}`);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Test connessione fallito");
    } finally {
      setTestingConnection(false);
    }
  };

  const handleDeleteCredentials = async (deviceId) => {
    try {
      await axios.delete(`${API}/devices/${deviceId}/credentials`);
      toast.success("Credenziali eliminate");
      fetchData();
    } catch (error) {
      toast.error("Errore");
    }
  };

  const filteredDevices = devices.filter(d => {
    if (filterClient && filterClient !== "all" && d.client_id !== filterClient) return false;
    if (filterType && filterType !== "all" && d.device_type !== filterType) return false;
    return true;
  });

  return (
    <div className="p-4 md:p-6" data-testid="devices-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-heading text-2xl font-bold text-zinc-100 tracking-tight">
            Dispositivi
          </h1>
          <p className="text-zinc-500 text-sm mt-1">
            Gestione dispositivi monitorati con supporto Redfish/iLO
          </p>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button 
              className="rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white gap-2"
              data-testid="add-device-btn"
            >
              <Plus size={16} />
              Nuovo Dispositivo
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-zinc-900 border-zinc-800 rounded-sm max-w-md">
            <DialogHeader>
              <DialogTitle className="font-heading text-zinc-100">
                Nuovo Dispositivo
              </DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Cliente *
                </Label>
                <Select
                  value={newDevice.client_id}
                  onValueChange={(v) => setNewDevice(d => ({ ...d, client_id: v }))}
                >
                  <SelectTrigger 
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
                    data-testid="device-client-select"
                  >
                    <SelectValue placeholder="Seleziona cliente" />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-800 border-zinc-700 rounded-sm">
                    {clients.map(c => (
                      <SelectItem key={c.id} value={c.id} className="text-zinc-200">
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Nome *
                </Label>
                <Input
                  value={newDevice.name}
                  onChange={(e) => setNewDevice(d => ({ ...d, name: e.target.value }))}
                  placeholder="HP-5130-CORE-SW01"
                  required
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono"
                  data-testid="device-name-input"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Tipo *
                </Label>
                <Select
                  value={newDevice.device_type}
                  onValueChange={(v) => setNewDevice(d => ({ ...d, device_type: v }))}
                >
                  <SelectTrigger 
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
                    data-testid="device-type-select"
                  >
                    <SelectValue placeholder="Seleziona tipo" />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-800 border-zinc-700 rounded-sm">
                    <SelectItem value="backup" className="text-zinc-200">Backup</SelectItem>
                    <SelectItem value="firewall" className="text-zinc-200">Firewall</SelectItem>
                    <SelectItem value="switch" className="text-zinc-200">Switch</SelectItem>
                    <SelectItem value="ilo" className="text-zinc-200">ILO/iDRAC</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Indirizzo IP *
                </Label>
                <Input
                  value={newDevice.ip_address}
                  onChange={(e) => setNewDevice(d => ({ ...d, ip_address: e.target.value }))}
                  placeholder="192.168.1.100"
                  required
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono"
                  data-testid="device-ip-input"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Hostname
                </Label>
                <Input
                  value={newDevice.hostname}
                  onChange={(e) => setNewDevice(d => ({ ...d, hostname: e.target.value }))}
                  placeholder="sw01.cliente.local"
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono"
                  data-testid="device-hostname-input"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Location
                </Label>
                <Input
                  value={newDevice.location}
                  onChange={(e) => setNewDevice(d => ({ ...d, location: e.target.value }))}
                  placeholder="Rack A1 - Sala Server"
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
                  data-testid="device-location-input"
                />
              </div>

              {newDevice.device_type === "ilo" && (
                <div className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-sm border border-zinc-700">
                  <div>
                    <Label className="text-zinc-300">Abilita Redfish Polling</Label>
                    <p className="text-zinc-500 text-xs mt-1">Interroga automaticamente iLO per stato hardware</p>
                  </div>
                  <Switch
                    checked={newDevice.redfish_enabled}
                    onCheckedChange={(checked) => setNewDevice(d => ({ ...d, redfish_enabled: checked }))}
                  />
                </div>
              )}

              <div className="flex justify-end gap-2 pt-4">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setDialogOpen(false)}
                  className="rounded-sm text-zinc-400"
                >
                  Annulla
                </Button>
                <Button
                  type="submit"
                  className="rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white"
                  data-testid="save-device-btn"
                >
                  Salva
                </Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Credentials Dialog */}
      <Dialog open={credDialogOpen} onOpenChange={setCredDialogOpen}>
        <DialogContent className="bg-zinc-900 border-zinc-800 rounded-sm max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading text-zinc-100 flex items-center gap-2">
              <Key size={20} />
              Credenziali {selectedDevice?.name}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSaveCredentials} className="space-y-4 mt-4">
            <div className="p-3 bg-green-900/20 border border-green-800/50 rounded-sm">
              <p className="text-green-400 text-xs flex items-center gap-2">
                <Shield size={14} />
                Le credenziali saranno crittografate con AES-256-GCM
              </p>
            </div>
            
            <div className="space-y-2">
              <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                Username iLO/iDRAC *
              </Label>
              <Input
                value={credentials.username}
                onChange={(e) => setCredentials(c => ({ ...c, username: e.target.value }))}
                placeholder="Administrator"
                required
                className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                Password *
              </Label>
              <Input
                type="password"
                value={credentials.password}
                onChange={(e) => setCredentials(c => ({ ...c, password: e.target.value }))}
                placeholder="••••••••"
                required
                className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
              />
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setCredDialogOpen(false)}
                className="rounded-sm text-zinc-400"
              >
                Annulla
              </Button>
              <Button
                type="submit"
                className="rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white"
              >
                Salva Crittografate
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Filters */}
      <div className="filter-bar mb-4">
        <Select value={filterClient} onValueChange={setFilterClient}>
          <SelectTrigger className="w-[180px] bg-zinc-900 border-zinc-800 text-zinc-100 rounded-sm">
            <SelectValue placeholder="Tutti i clienti" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-800 border-zinc-700 rounded-sm">
            <SelectItem value="all" className="text-zinc-200">Tutti i clienti</SelectItem>
            {clients.map(c => (
              <SelectItem key={c.id} value={c.id} className="text-zinc-200">
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-[180px] bg-zinc-900 border-zinc-800 text-zinc-100 rounded-sm">
            <SelectValue placeholder="Tutti i tipi" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-800 border-zinc-700 rounded-sm">
            <SelectItem value="all" className="text-zinc-200">Tutti i tipi</SelectItem>
            <SelectItem value="backup" className="text-zinc-200">Backup</SelectItem>
            <SelectItem value="firewall" className="text-zinc-200">Firewall</SelectItem>
            <SelectItem value="switch" className="text-zinc-200">Switch</SelectItem>
            <SelectItem value="ilo" className="text-zinc-200">ILO/iDRAC</SelectItem>
          </SelectContent>
        </Select>

        <span className="text-zinc-500 text-sm ml-auto">
          {filteredDevices.length} dispositivi
        </span>
      </div>

      {/* Devices Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {loading ? (
          <p className="text-zinc-500 col-span-full text-center py-8">
            Caricamento...
          </p>
        ) : filteredDevices.length === 0 ? (
          <div className="col-span-full noc-panel p-8 text-center">
            <HardDrives size={48} className="mx-auto text-zinc-600 mb-4" />
            <p className="text-zinc-400 mb-2">Nessun dispositivo trovato</p>
            <p className="text-zinc-600 text-sm">
              Aggiungi dispositivi per iniziare il monitoraggio
            </p>
          </div>
        ) : (
          filteredDevices.map((device) => {
            const Icon = deviceTypeIcons[device.device_type] || HardDrives;
            return (
              <div 
                key={device.id} 
                className="noc-panel p-4 hover:border-zinc-700 transition-fast"
                data-testid={`device-card-${device.id}`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-sm bg-zinc-800 flex items-center justify-center">
                      <Icon size={20} className="text-zinc-400" />
                    </div>
                    <div>
                      <h3 className="font-mono font-medium text-zinc-100 text-sm">
                        {device.name}
                      </h3>
                      <p className="text-zinc-500 text-xs uppercase tracking-wider">
                        {deviceTypeLabels[device.device_type] || device.device_type}
                      </p>
                    </div>
                  </div>

                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-zinc-500 hover:text-red-400 hover:bg-red-900/20 rounded-sm"
                        data-testid={`delete-device-${device.id}`}
                      >
                        <Trash size={16} />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent className="bg-zinc-900 border-zinc-800 rounded-sm">
                      <AlertDialogHeader>
                        <AlertDialogTitle className="text-zinc-100">
                          Eliminare {device.name}?
                        </AlertDialogTitle>
                        <AlertDialogDescription className="text-zinc-400">
                          Questa azione eliminerà anche le credenziali associate.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel className="rounded-sm bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700">
                          Annulla
                        </AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => handleDelete(device.id)}
                          className="rounded-sm bg-red-900 text-red-100 hover:bg-red-800"
                        >
                          Elimina
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>

                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-zinc-500">IP:</span>
                    <span className="font-mono text-blue-400">{device.ip_address}</span>
                  </div>
                  {device.hostname && (
                    <div className="flex justify-between">
                      <span className="text-zinc-500">Host:</span>
                      <span className="font-mono text-zinc-300">{device.hostname}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Cliente:</span>
                    <span className="text-zinc-300">{device.client_name}</span>
                  </div>
                  {device.health_status && (
                    <div className="flex justify-between">
                      <span className="text-zinc-500">Health:</span>
                      <span className={`text-xs uppercase ${device.health_status === "OK" ? "text-green-400" : "text-red-400"}`}>
                        {device.health_status}
                      </span>
                    </div>
                  )}
                </div>

                {/* Device Actions */}
                <div className="mt-3 pt-3 border-t border-zinc-800 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className={`text-xs uppercase tracking-wider ${device.status === "active" ? "text-green-400" : "text-zinc-500"}`}>
                      {device.status}
                    </span>
                    {device.redfish_enabled && (
                      <span className="text-xs text-blue-400 flex items-center gap-1">
                        <Plugs size={12} />
                        Redfish
                      </span>
                    )}
                  </div>
                  
                  {device.device_type === "ilo" && (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setSelectedDevice(device);
                          setCredDialogOpen(true);
                        }}
                        className="flex-1 rounded-sm text-xs h-8 border-zinc-700 hover:bg-zinc-800 gap-1"
                      >
                        <Key size={12} />
                        {device.has_credentials ? "Aggiorna" : "Credenziali"}
                      </Button>
                      {device.has_credentials && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleTestRedfish(device.id)}
                          disabled={testingConnection === device.id}
                          className="flex-1 rounded-sm text-xs h-8 border-zinc-700 hover:bg-zinc-800 gap-1"
                        >
                          {testingConnection === device.id ? (
                            "..."
                          ) : (
                            <>
                              <Plugs size={12} />
                              Test
                            </>
                          )}
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
