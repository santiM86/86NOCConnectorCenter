import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Plus, Trash, Buildings, EnvelopeSimple, Key, Copy, ArrowsClockwise,
  Globe, CaretRight, HardDrives, PlugsConnected, Bell, ShieldCheck,
  WifiHigh, WifiSlash,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export default function ClientsPage() {
  const [clients, setClients] = useState([]);
  const [overview, setOverview] = useState({ clients: [] });
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newClient, setNewClient] = useState({ name: "", description: "", contact_email: "" });
  const navigate = useNavigate();

  useEffect(() => { fetchClients(); }, []);

  const fetchClients = async () => {
    try {
      const [clientsRes, overviewRes] = await Promise.allSettled([
        axios.get(`${API}/clients`),
        axios.get(`${API}/overview/clients`),
      ]);
      if (clientsRes.status === "fulfilled") setClients(clientsRes.value.data);
      if (overviewRes.status === "fulfilled") setOverview(overviewRes.value.data);
    } catch { toast.error("Errore nel caricamento"); }
    finally { setLoading(false); }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/clients`, newClient);
      toast.success("Cliente creato");
      setDialogOpen(false);
      setNewClient({ name: "", description: "", contact_email: "" });
      fetchClients();
    } catch { toast.error("Errore nella creazione"); }
  };

  const handleDelete = async (clientId, e) => {
    e.stopPropagation();
    try { await axios.delete(`${API}/clients/${clientId}`); toast.success("Cliente eliminato"); fetchClients(); }
    catch { toast.error("Errore nell'eliminazione"); }
  };

  const handleRegenerateKey = async (clientId, clientName, e) => {
    e?.stopPropagation();
    try {
      const res = await axios.post(`${API}/clients/${clientId}/regenerate-key`);
      const newKey = res.data?.api_key;
      if (newKey) {
        // Auto-copy della nuova chiave negli appunti per facilitare l'aggiornamento del config.json del connector
        try { await navigator.clipboard.writeText(newKey); } catch {}
        toast.success(`API Key di "${clientName}" rigenerata e copiata`, {
          description: `${newKey.substring(0, 12)}…${newKey.substring(newKey.length - 4)} - aggiorna config.json del connector`,
          duration: 8000,
        });
        fetchClients();
      }
    } catch (err) {
      toast.error("Errore nella rigenerazione", { description: err?.response?.data?.detail || err.message });
    }
  };

  const nocUrl = window.location.origin;

  const copyToClipboard = (text, label, e) => {
    if (e) e.stopPropagation();
    try {
      navigator.clipboard.writeText(text)
        .then(() => toast.success(`${label} copiato`))
        .catch(() => { const t=document.createElement("textarea"); t.value=text; document.body.appendChild(t); t.select(); document.execCommand("copy"); document.body.removeChild(t); toast.success(`${label} copiato`); });
    } catch {
      const t=document.createElement("textarea"); t.value=text; document.body.appendChild(t); t.select(); document.execCommand("copy"); document.body.removeChild(t); toast.success(`${label} copiato`);
    }
  };

  // Build overview map by client id
  const overviewMap = {};
  (overview.clients || []).forEach(c => { overviewMap[c.id] = c; });

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="clients-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Clienti</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Clicca su un cliente per vedere tutti i suoi servizi</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button className="rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white gap-1.5 text-xs h-8" data-testid="add-client-btn">
              <Plus size={14} /> Nuovo Cliente
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
            <DialogHeader><DialogTitle className="font-heading text-[var(--text-primary)] text-sm">Nuovo Cliente</DialogTitle></DialogHeader>
            <form onSubmit={handleCreate} className="space-y-3 mt-3">
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Nome *</Label>
                <Input value={newClient.name} onChange={e => setNewClient(c => ({...c, name: e.target.value}))} placeholder="Acme Corp" required
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="client-name-input" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Descrizione</Label>
                <Input value={newClient.description} onChange={e => setNewClient(c => ({...c, description: e.target.value}))} placeholder="Cliente enterprise"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="client-description-input" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Email</Label>
                <Input type="email" value={newClient.contact_email} onChange={e => setNewClient(c => ({...c, contact_email: e.target.value}))} placeholder="it@acme.com"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="client-email-input" />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="ghost" size="sm" onClick={() => setDialogOpen(false)} className="rounded-md text-xs">Annulla</Button>
                <Button type="submit" size="sm" className="rounded-md bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="save-client-btn">Salva</Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Client List */}
      <div className="space-y-2">
        {loading ? (
          <p className="text-[var(--text-muted)] text-center py-8 text-xs">Caricamento...</p>
        ) : clients.length === 0 ? (
          <div className="noc-panel p-8 text-center">
            <Buildings size={36} className="mx-auto text-[var(--text-muted)] mb-2" />
            <p className="text-[var(--text-secondary)] text-xs mb-1">Nessun cliente</p>
            <p className="text-[var(--text-muted)] text-[10px]">Aggiungi il primo cliente</p>
          </div>
        ) : (
          clients.map(client => {
            const ov = overviewMap[client.id] || {};
            const health = ov.health || "ok";
            const hColor = health === "critical" ? "#FF3B30" : health === "warning" ? "#FF9500" : health === "attention" ? "#FFCC00" : "#34C759";

            return (
              <div key={client.id}
                className="noc-panel p-0 overflow-hidden hover:border-indigo-500/30 transition-all group select-none relative"
                data-testid={`client-row-${client.id}`}>

                {/* Absolute overlay Link — copre l'intera riga come tap target unico.
                    Risolve il bug touch su mobile dove altri elementi interferivano col target.
                    Gli elementi interattivi (bottoni) sotto hanno z-10 per stare sopra l'overlay. */}
                <Link
                  to={`/client/${client.id}`}
                  className="absolute inset-0 z-0"
                  aria-label={`Apri ${client.name}`}
                  data-testid={`client-link-${client.id}`}
                />

                {/* Main Row */}
                <div className="flex items-center gap-4 px-4 py-4 md:py-3 relative pointer-events-none">
                  {/* Health dot + Name */}
                  <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: hColor, boxShadow: `0 0 8px ${hColor}50` }}></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-bold text-[var(--text-primary)]">{client.name}</h3>
                      {client.description && <span className="text-[10px] text-[var(--text-muted)] truncate hidden md:inline">{client.description}</span>}
                    </div>
                    {/* Compact status pills on mobile */}
                    <div className="flex items-center gap-1.5 mt-1 md:hidden text-[10px]">
                      <span className="font-mono" style={{ color: ov.devices?.offline > 0 ? "#FF9500" : "#34C759" }}>
                        {ov.devices?.total > 0 ? `${ov.devices.online}/${ov.devices.total}` : "—"} disp.
                      </span>
                      <span className="text-[var(--text-muted)]">·</span>
                      <span style={{ color: ov.connector_online ? "#34C759" : ov.connector_online === false ? "#FF3B30" : "#888" }}>
                        {ov.connector_online ? "ON" : ov.connector_online === false ? "OFF" : "—"}
                      </span>
                      {ov.alerts?.total > 0 && (
                        <>
                          <span className="text-[var(--text-muted)]">·</span>
                          <span style={{ color: ov.alerts?.critical > 0 ? "#FF3B30" : "#FF9500" }}>{ov.alerts.total} alert</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Quick Status Pills (desktop only — cliccabili per dettagli future, ora pass-through) */}
                  <div className="flex items-center gap-2 flex-shrink-0 hidden md:flex">
                    {/* Devices */}
                    <StatusPill icon={HardDrives} value={ov.devices?.total > 0 ? `${ov.devices.online}/${ov.devices.total}` : "—"} color={ov.devices?.offline > 0 ? "#FF9500" : "#34C759"} label="Disp." />
                    {/* WAN */}
                    <StatusPill icon={Globe} value={ov.wan?.status === "ok" ? "OK" : ov.wan?.status === "not_configured" ? "N/C" : (ov.wan?.status || "—").toUpperCase()} color={ov.wan?.status === "ok" ? "#34C759" : ov.wan?.status === "not_configured" ? "#555" : "#FF3B30"} label="WAN" />
                    {/* Connector */}
                    <StatusPill icon={PlugsConnected} value={ov.connector_online === true ? "ON" : ov.connector_online === false ? "OFF" : "—"} color={ov.connector_online ? "#34C759" : ov.connector_online === false ? "#FF3B30" : "#555"} label="Conn." />
                    {/* Alerts */}
                    <StatusPill icon={Bell} value={ov.alerts?.total || 0} color={ov.alerts?.critical > 0 ? "#FF3B30" : ov.alerts?.total > 0 ? "#FF9500" : "#34C759"} label="Alert" />
                  </div>

                  {/* Connector Info — pointer-events-auto + z-10 per stare sopra il Link overlay */}
                  <div className="hidden md:flex items-center gap-2 flex-shrink-0 pointer-events-auto relative z-10" onClick={e => e.stopPropagation()}>
                    {client.api_key && (
                      <button onClick={(e) => copyToClipboard(client.api_key, "API Key", e)}
                        className="text-[9px] px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-indigo-400 hover:border-indigo-500/30 transition-colors flex items-center gap-1"
                        title={`API Key: ${client.api_key}`}>
                        <Key size={10} /> API Key
                      </button>
                    )}
                    {client.api_key && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <button onClick={(e) => e.stopPropagation()}
                            data-testid={`regenerate-api-key-${client.id}`}
                            className="text-[9px] px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-amber-400 hover:border-amber-500/30 transition-colors flex items-center gap-1"
                            title="Rigenera API Key (invalida la precedente)">
                            <ArrowsClockwise size={10} /> Rigenera
                          </button>
                        </AlertDialogTrigger>
                        <AlertDialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg" onClick={e => e.stopPropagation()}>
                          <AlertDialogHeader>
                            <AlertDialogTitle className="text-[var(--text-primary)] text-sm">Rigenera API Key per {client.name}?</AlertDialogTitle>
                            <AlertDialogDescription className="text-[var(--text-muted)] text-xs">
                              La chiave attuale verrà <strong className="text-amber-400">invalidata immediatamente</strong>. Il connector smetterà di funzionare finché non aggiorni <code className="text-[10px] bg-[var(--bg-card)] px-1 rounded">C:\ProgramData\86NocConnector\config.json</code> con la nuova chiave e riavvii il servizio.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-secondary)] text-xs">Annulla</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={(e) => handleRegenerateKey(client.id, client.name, e)}
                              className="bg-amber-600 hover:bg-amber-700 text-white text-xs">
                              Rigenera e copia
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                    <button onClick={(e) => copyToClipboard(nocUrl, "NOC URL", e)}
                      className="text-[9px] px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-indigo-400 hover:border-indigo-500/30 transition-colors flex items-center gap-1"
                      title={`URL: ${nocUrl}`}>
                      <Globe size={10} /> URL
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); }}
                      className="hidden">
                    </button>
                  </div>

                  {/* Delete + Arrow — pointer-events-auto + z-10 per stare sopra il Link overlay */}
                  <div className="flex items-center gap-1 flex-shrink-0 pointer-events-auto relative z-10" onClick={e => e.stopPropagation()}>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] rounded-md opacity-0 group-hover:opacity-100 transition-opacity" data-testid={`delete-client-${client.id}`}>
                          <Trash size={13} />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                        <AlertDialogHeader>
                          <AlertDialogTitle className="text-[var(--text-primary)] text-sm">Eliminare {client.name}?</AlertDialogTitle>
                          <AlertDialogDescription className="text-[var(--text-muted)] text-xs">Azione irreversibile. Verranno eliminati tutti i dispositivi e dati associati.</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel className="rounded-md bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] text-xs">Annulla</AlertDialogCancel>
                          <AlertDialogAction onClick={(e) => handleDelete(client.id, e)} className="rounded-md bg-red-900 text-red-100 hover:bg-red-800 text-xs">Elimina</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                  <CaretRight size={16} className="text-[var(--text-muted)] group-hover:text-indigo-400 transition-colors flex-shrink-0" />
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function StatusPill({ icon: Icon, value, color, label }) {
  return (
    <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] min-w-0">
      <Icon size={11} weight="bold" style={{ color }} />
      <span className="text-[9px] font-bold font-mono" style={{ color }}>{value}</span>
    </div>
  );
}
