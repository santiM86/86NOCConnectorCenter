import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Plug, Plus, Trash, Play, Globe, CheckCircle, XCircle,
  Clock, Lightning, ArrowRight
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

export default function PortMonitorPage() {
  const [clients, setClients] = useState([]);
  const [clientId, setClientId] = useState("");
  const [services, setServices] = useState([]);
  const [commonPorts, setCommonPorts] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [checking, setChecking] = useState(false);
  const [devices, setDevices] = useState([]);
  const [form, setForm] = useState({ device_ip: "", port: "80", service_name: "HTTP" });

  useEffect(() => {
    axios.get(`${API}/clients`).then(r => {
      const c = r.data?.clients || r.data || [];
      setClients(c);
      if (c.length > 0) setClientId(c[0].id);
    }).catch(() => {});
    axios.get(`${API}/port-monitor/common-ports`).then(r => setCommonPorts(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!clientId) return;
    fetchServices();
    axios.get(`${API}/inventory/${clientId}`).then(r => setDevices(r.data?.devices || [])).catch(() => {});
  }, [clientId]);

  const fetchServices = () => {
    axios.get(`${API}/port-monitor/services/${clientId}`).then(r => setServices(r.data)).catch(() => {});
  };

  const addService = async () => {
    if (!form.device_ip || !form.port) { toast.error("Compila tutti i campi"); return; }
    const deviceName = devices.find(d => d.device_ip === form.device_ip)?.device_name || form.device_ip;
    try {
      await axios.post(`${API}/port-monitor/services`, {
        client_id: clientId,
        device_ip: form.device_ip,
        device_name: deviceName,
        port: parseInt(form.port),
        service_name: form.service_name,
      });
      toast.success("Servizio aggiunto");
      setShowAdd(false);
      setForm({ device_ip: "", port: "80", service_name: "HTTP" });
      fetchServices();
    } catch { toast.error("Errore"); }
  };

  const removeService = async (id) => {
    try {
      await axios.delete(`${API}/port-monitor/services/${id}`);
      fetchServices();
      toast.success("Rimosso");
    } catch { toast.error("Errore"); }
  };

  const checkAll = async () => {
    setChecking(true);
    try {
      const res = await axios.post(`${API}/port-monitor/check/${clientId}`);
      toast.success(`Controllati ${res.data.checked} servizi`);
      fetchServices();
    } catch { toast.error("Errore nel controllo"); }
    finally { setChecking(false); }
  };

  const handlePortSelect = (portStr) => {
    const port = parseInt(portStr);
    const found = commonPorts.find(p => p.port === port);
    setForm(f => ({ ...f, port: portStr, service_name: found?.name || "Custom" }));
  };

  const openCount = services.filter(s => s.is_open === true).length;
  const closedCount = services.filter(s => s.is_open === false).length;
  const unknownCount = services.filter(s => s.is_open === null).length;

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="port-monitor-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)]">Monitor Servizi</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Controlla lo stato delle porte TCP e dei servizi</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={checkAll} disabled={checking || !clientId}
            className="h-8 bg-emerald-600 hover:bg-emerald-700 text-white text-xs gap-1" data-testid="check-all-btn">
            <Play size={14} /> {checking ? "Controllo..." : "Controlla Tutto"}
          </Button>
          <Dialog open={showAdd} onOpenChange={setShowAdd}>
            <DialogTrigger asChild>
              <Button className="h-8 bg-indigo-600 hover:bg-indigo-700 text-white text-xs gap-1" data-testid="add-service-btn">
                <Plus size={14} /> Aggiungi
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)] max-w-sm">
              <DialogHeader><DialogTitle className="text-[var(--text-primary)]">Aggiungi Servizio</DialogTitle></DialogHeader>
              <div className="space-y-3 pt-2">
                <Select value={form.device_ip} onValueChange={v => setForm(f => ({...f, device_ip: v}))}>
                  <SelectTrigger className="h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs" data-testid="port-device-select">
                    <SelectValue placeholder="Seleziona dispositivo..." />
                  </SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                    {devices.map(d => (
                      <SelectItem key={d.device_ip} value={d.device_ip} className="text-xs text-[var(--text-primary)]">
                        {d.device_name || d.device_ip} ({d.device_ip})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="grid grid-cols-2 gap-2">
                  <Select value={form.port} onValueChange={handlePortSelect}>
                    <SelectTrigger className="h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs" data-testid="port-select">
                      <SelectValue placeholder="Porta" />
                    </SelectTrigger>
                    <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)] max-h-[200px]">
                      {commonPorts.map(p => (
                        <SelectItem key={p.port} value={String(p.port)} className="text-xs text-[var(--text-primary)]">
                          {p.port} - {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input value={form.service_name} onChange={e => setForm(f => ({...f, service_name: e.target.value}))}
                    placeholder="Nome servizio"
                    className="h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs text-[var(--text-primary)]"
                    data-testid="port-service-name" />
                </div>
                <Button onClick={addService} className="w-full h-8 bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="submit-service-btn">Aggiungi</Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="noc-panel p-3">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Aperti</p>
          <p className="font-heading text-2xl font-bold text-emerald-400">{openCount}</p>
        </div>
        <div className="noc-panel p-3">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Chiusi</p>
          <p className="font-heading text-2xl font-bold text-red-400">{closedCount}</p>
        </div>
        <div className="noc-panel p-3">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Non Controllati</p>
          <p className="font-heading text-2xl font-bold text-zinc-400">{unknownCount}</p>
        </div>
      </div>

      {/* Table */}
      <div className="noc-panel overflow-x-auto">
        <table className="alert-table w-full min-w-[760px]" data-testid="port-monitor-table">
          <thead>
            <tr>
              <th>Stato</th>
              <th>Dispositivo</th>
              <th>IP</th>
              <th>Porta</th>
              <th>Servizio</th>
              <th>Risposta</th>
              <th>Ultimo Check</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {services.length === 0 ? (
              <tr><td colSpan={8} className="text-center text-[var(--text-muted)] py-8 text-xs">
                Nessun servizio monitorato. Aggiungi una porta per iniziare.
              </td></tr>
            ) : services.map(s => (
              <tr key={s.id} data-testid={`port-row-${s.id}`}>
                <td>
                  {s.is_open === null ? (
                    <span className="text-[10px] text-zinc-400">-</span>
                  ) : s.is_open ? (
                    <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                      <CheckCircle size={10} weight="fill" /> Aperto
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-400">
                      <XCircle size={10} weight="fill" /> Chiuso
                    </span>
                  )}
                </td>
                <td className="text-[var(--text-primary)] text-xs">{s.device_name || "-"}</td>
                <td className="font-mono text-[var(--text-muted)] text-xs">{s.device_ip}</td>
                <td className="font-mono text-[var(--text-primary)]">{s.port}</td>
                <td className="text-[var(--text-secondary)] text-xs">{s.service_name}</td>
                <td className="font-mono text-xs">
                  {s.response_time_ms != null ? (
                    <span className={s.response_time_ms < 50 ? "text-emerald-400" : s.response_time_ms < 200 ? "text-amber-400" : "text-red-400"}>
                      {s.response_time_ms}ms
                    </span>
                  ) : s.error ? (
                    <span className="text-red-400 text-[10px]">{s.error}</span>
                  ) : "-"}
                </td>
                <td className="text-[10px] text-[var(--text-muted)]">
                  {s.last_check ? new Date(s.last_check).toLocaleTimeString("it-IT", {hour:"2-digit",minute:"2-digit"}) : "-"}
                </td>
                <td>
                  <Button variant="ghost" size="icon" className="h-6 w-6 text-red-400 hover:text-red-300"
                    onClick={() => removeService(s.id)} data-testid={`remove-port-${s.id}`}>
                    <Trash size={12} />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
