import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function MaintenancePage() {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [windows, setWindows] = useState([]);
  const [devices, setDevices] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: "", description: "", start_time: "", end_time: "", device_ips: [], suppress_alerts: true });
  const [editingId, setEditingId] = useState(null);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    axios.get(`${API}/api/clients`, { headers }).then(r => {
      const cl = Array.isArray(r.data) ? r.data : r.data.clients || [];
      setClients(cl);
      if (cl.length > 0) setSelectedClient(cl[0].id);
    }).catch(() => {});
  }, []);

  const fetchData = useCallback(() => {
    if (!selectedClient) return;
    axios.get(`${API}/api/maintenance/${selectedClient}`, { headers })
      .then(r => setWindows(r.data)).catch(() => {});
    axios.get(`${API}/api/connector/device-poll-status`, { headers })
      .then(r => {
        const devs = (Array.isArray(r.data) ? r.data : []).filter(d => d.client_id === selectedClient);
        setDevices(devs);
      }).catch(() => {});
  }, [selectedClient]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSubmit = () => {
    if (!form.title || !form.start_time || !form.end_time) {
      toast.error("Compila titolo, data inizio e fine");
      return;
    }
    const payload = { ...form, start_time: new Date(form.start_time).toISOString(), end_time: new Date(form.end_time).toISOString() };

    const promise = editingId
      ? axios.put(`${API}/api/maintenance/${selectedClient}/${editingId}`, payload, { headers })
      : axios.post(`${API}/api/maintenance/${selectedClient}`, payload, { headers });

    promise
      .then(() => {
        toast.success(editingId ? "Finestra aggiornata" : "Finestra di manutenzione creata");
        setShowForm(false);
        setEditingId(null);
        setForm({ title: "", description: "", start_time: "", end_time: "", device_ips: [], suppress_alerts: true });
        fetchData();
      })
      .catch(() => toast.error("Errore"));
  };

  const deleteWindow = (id) => {
    if (!window.confirm("Eliminare questa finestra di manutenzione?")) return;
    axios.delete(`${API}/api/maintenance/${selectedClient}/${id}`, { headers })
      .then(() => { toast.success("Eliminata"); fetchData(); })
      .catch(() => toast.error("Errore eliminazione"));
  };

  const editWindow = (w) => {
    setForm({
      title: w.title,
      description: w.description || "",
      start_time: w.start_time ? w.start_time.slice(0, 16) : "",
      end_time: w.end_time ? w.end_time.slice(0, 16) : "",
      device_ips: w.device_ips || [],
      suppress_alerts: w.suppress_alerts !== false,
    });
    setEditingId(w.id);
    setShowForm(true);
  };

  const toggleDeviceIp = (ip) => {
    setForm(f => ({
      ...f,
      device_ips: f.device_ips.includes(ip) ? f.device_ips.filter(d => d !== ip) : [...f.device_ips, ip]
    }));
  };

  const isActive = (w) => {
    const now = new Date().toISOString();
    return w.start_time <= now && w.end_time >= now;
  };

  const isPast = (w) => new Date(w.end_time) < new Date();

  return (
    <div className="space-y-6" data-testid="maintenance-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Manutenzione Programmata</h1>
          <p className="text-sm text-[var(--text-secondary)]">Pianifica finestre di manutenzione per sopprimere gli alert</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={selectedClient} onChange={e => setSelectedClient(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="maint-client-select">
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={() => { setShowForm(!showForm); setEditingId(null); setForm({ title: "", description: "", start_time: "", end_time: "", device_ips: [], suppress_alerts: true }); }}
            className="h-8 px-4 text-xs font-semibold rounded-md bg-blue-600 text-white hover:bg-blue-700"
            data-testid="maint-new-btn">
            {showForm ? "Annulla" : "Nuova Finestra"}
          </button>
        </div>
      </div>

      {/* Creation/Edit Form */}
      {showForm && (
        <div className="rounded-xl border border-blue-500/30 bg-[var(--bg-card)] p-4 space-y-3" data-testid="maint-form">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">{editingId ? "Modifica" : "Nuova"} Finestra di Manutenzione</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-[var(--text-secondary)]">Titolo</label>
              <input type="text" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                className="w-full h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
                placeholder="Es. Aggiornamento firmware switch" data-testid="maint-title" />
            </div>
            <div>
              <label className="text-xs text-[var(--text-secondary)]">Descrizione</label>
              <input type="text" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                className="w-full h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
                placeholder="Dettagli opzionali" data-testid="maint-description" />
            </div>
            <div>
              <label className="text-xs text-[var(--text-secondary)]">Inizio</label>
              <input type="datetime-local" value={form.start_time} onChange={e => setForm(f => ({ ...f, start_time: e.target.value }))}
                className="w-full h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
                data-testid="maint-start" />
            </div>
            <div>
              <label className="text-xs text-[var(--text-secondary)]">Fine</label>
              <input type="datetime-local" value={form.end_time} onChange={e => setForm(f => ({ ...f, end_time: e.target.value }))}
                className="w-full h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
                data-testid="maint-end" />
            </div>
          </div>
          <div>
            <label className="text-xs text-[var(--text-secondary)] mb-1 block">Dispositivi coinvolti (clicca per selezionare)</label>
            <div className="flex flex-wrap gap-1.5">
              {devices.map(d => (
                <button key={d.device_ip} onClick={() => toggleDeviceIp(d.device_ip)}
                  className={`px-2 py-1 text-xs rounded-md border transition-colors ${form.device_ips.includes(d.device_ip) ? "bg-blue-600 text-white border-blue-600" : "border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}`}>
                  {d.device_name || d.device_ip}
                </button>
              ))}
              {devices.length === 0 && <span className="text-xs text-[var(--text-secondary)]">Nessun dispositivo. Vuoto = tutti i dispositivi.</span>}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-[var(--text-primary)]">
              <input type="checkbox" checked={form.suppress_alerts} onChange={e => setForm(f => ({ ...f, suppress_alerts: e.target.checked }))} />
              Sopprimi alert durante la manutenzione
            </label>
            <button onClick={handleSubmit}
              className="h-8 px-6 text-xs font-semibold rounded-md bg-emerald-600 text-white hover:bg-emerald-700"
              data-testid="maint-save-btn">
              {editingId ? "Aggiorna" : "Crea"} Finestra
            </button>
          </div>
        </div>
      )}

      {/* Windows list */}
      {windows.length > 0 ? (
        <div className="space-y-2">
          {windows.map(w => (
            <div key={w.id} className={`rounded-lg border p-3 flex items-center justify-between ${isActive(w) ? "border-amber-500/40 bg-amber-500/5" : isPast(w) ? "border-[var(--bg-border)] bg-[var(--bg-surface)] opacity-60" : "border-[var(--bg-border)] bg-[var(--bg-card)]"}`}
              data-testid={`maint-window-${w.id}`}>
              <div className="flex items-center gap-3">
                {isActive(w) ? (
                  <div className="w-2.5 h-2.5 rounded-full bg-amber-500 animate-pulse" title="In corso" />
                ) : isPast(w) ? (
                  <div className="w-2.5 h-2.5 rounded-full bg-gray-500" title="Completata" />
                ) : (
                  <div className="w-2.5 h-2.5 rounded-full bg-blue-500" title="Programmata" />
                )}
                <div>
                  <p className="text-sm font-semibold text-[var(--text-primary)]">
                    {w.title}
                    {isActive(w) && <span className="ml-2 px-1.5 py-0.5 text-[10px] font-bold rounded bg-amber-500/20 text-amber-400">IN CORSO</span>}
                    {isPast(w) && <span className="ml-2 px-1.5 py-0.5 text-[10px] rounded bg-gray-500/20 text-gray-400">COMPLETATA</span>}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)]">
                    {new Date(w.start_time).toLocaleString("it-IT")} — {new Date(w.end_time).toLocaleString("it-IT")}
                    {w.device_ips?.length > 0 && ` | ${w.device_ips.length} dispositivi`}
                    {w.suppress_alerts && " | Alert soppressi"}
                  </p>
                  {w.description && <p className="text-xs text-[var(--text-secondary)] mt-0.5">{w.description}</p>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {!isPast(w) && (
                  <button onClick={() => editWindow(w)}
                    className="h-7 px-3 text-xs rounded-md border border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]">
                    Modifica
                  </button>
                )}
                <button onClick={() => deleteWindow(w.id)}
                  className="h-7 px-3 text-xs rounded-md border border-red-500/30 text-red-400 hover:bg-red-500/10">
                  Elimina
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12">
          <p className="text-sm text-[var(--text-secondary)]">Nessuna finestra di manutenzione programmata.</p>
          <p className="text-xs text-[var(--text-secondary)] mt-1">Crea una finestra per sopprimere automaticamente gli alert durante gli interventi.</p>
        </div>
      )}
    </div>
  );
}
