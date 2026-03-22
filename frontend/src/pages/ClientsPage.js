import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Plus, Trash, Buildings, EnvelopeSimple, Key, Copy, ArrowsClockwise } from "@phosphor-icons/react";
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
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newClient, setNewClient] = useState({ name: "", description: "", contact_email: "" });

  useEffect(() => { fetchClients(); }, []);

  const fetchClients = async () => {
    try { const r = await axios.get(`${API}/clients`); setClients(r.data); }
    catch { toast.error("Errore nel caricamento clienti"); }
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

  const handleDelete = async (clientId) => {
    try { await axios.delete(`${API}/clients/${clientId}`); toast.success("Cliente eliminato"); fetchClients(); }
    catch { toast.error("Errore nell'eliminazione"); }
  };

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="clients-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Clienti</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Gestione clienti e dispositivi</p>
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

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {loading ? (
          <p className="text-[var(--text-muted)] col-span-full text-center py-8 text-xs">Caricamento...</p>
        ) : clients.length === 0 ? (
          <div className="col-span-full noc-panel p-8 text-center">
            <Buildings size={36} className="mx-auto text-[var(--text-muted)] mb-2" />
            <p className="text-[var(--text-secondary)] text-xs mb-1">Nessun cliente</p>
            <p className="text-[var(--text-muted)] text-[10px]">Aggiungi il primo cliente</p>
          </div>
        ) : (
          clients.map(client => (
            <div key={client.id} className="noc-panel p-4 hover:border-[var(--bg-hover)] transition-colors" data-testid={`client-card-${client.id}`}>
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-indigo-600/10 flex items-center justify-center">
                    <Buildings size={16} className="text-indigo-400" />
                  </div>
                  <div>
                    <h3 className="font-heading font-semibold text-xs text-[var(--text-primary)]">{client.name}</h3>
                    <p className="text-[var(--text-muted)] text-[10px] font-mono">ID: {client.id.substring(0, 8)}</p>
                  </div>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] rounded-md" data-testid={`delete-client-${client.id}`}>
                      <Trash size={14} />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                    <AlertDialogHeader>
                      <AlertDialogTitle className="text-[var(--text-primary)] text-sm">Eliminare {client.name}?</AlertDialogTitle>
                      <AlertDialogDescription className="text-[var(--text-muted)] text-xs">Azione irreversibile.</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel className="rounded-md bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] text-xs">Annulla</AlertDialogCancel>
                      <AlertDialogAction onClick={() => handleDelete(client.id)} className="rounded-md bg-red-900 text-red-100 hover:bg-red-800 text-xs">Elimina</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
              {client.description && <p className="text-[var(--text-secondary)] text-[11px] mb-2 line-clamp-2">{client.description}</p>}
              {client.contact_email && (
                <div className="flex items-center gap-1.5 text-[var(--text-muted)] text-[11px]">
                  <EnvelopeSimple size={12} /><span className="font-mono">{client.contact_email}</span>
                </div>
              )}
              {client.api_key && (
                <div className="mt-2 p-2 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)]">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest flex items-center gap-1"><Key size={10} /> API Key</span>
                    <div className="flex items-center gap-1">
                      <button onClick={() => { navigator.clipboard.writeText(client.api_key); toast.success("API Key copiata"); }}
                        className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-0.5" title="Copia"
                        data-testid={`copy-key-${client.id}`}>
                        <Copy size={12} />
                      </button>
                      <button onClick={async () => { 
                        try { const r = await axios.post(`${API}/clients/${client.id}/regenerate-key`); toast.success("Nuova API Key generata"); fetchClients(); }
                        catch { toast.error("Errore"); }
                      }}
                        className="text-[var(--text-muted)] hover:text-[var(--high)] transition-colors p-0.5" title="Rigenera"
                        data-testid={`regen-key-${client.id}`}>
                        <ArrowsClockwise size={12} />
                      </button>
                    </div>
                  </div>
                  <p className="font-mono text-[10px] text-[var(--text-secondary)] break-all select-all">{client.api_key}</p>
                </div>
              )}
              <div className="mt-3 pt-3 border-t border-[var(--bg-border)]">
                <p className="text-[var(--text-muted)] text-[10px]">Creato: {new Date(client.created_at).toLocaleDateString("it-IT")}</p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
