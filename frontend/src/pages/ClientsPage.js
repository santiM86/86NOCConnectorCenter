import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Plus, Trash, Buildings, EnvelopeSimple } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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

export default function ClientsPage() {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newClient, setNewClient] = useState({
    name: "",
    description: "",
    contact_email: ""
  });

  useEffect(() => {
    fetchClients();
  }, []);

  const fetchClients = async () => {
    try {
      const response = await axios.get(`${API}/clients`);
      setClients(response.data);
    } catch (error) {
      toast.error("Errore nel caricamento clienti");
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/clients`, newClient);
      toast.success("Cliente creato");
      setDialogOpen(false);
      setNewClient({ name: "", description: "", contact_email: "" });
      fetchClients();
    } catch (error) {
      toast.error("Errore nella creazione");
    }
  };

  const handleDelete = async (clientId) => {
    try {
      await axios.delete(`${API}/clients/${clientId}`);
      toast.success("Cliente eliminato");
      fetchClients();
    } catch (error) {
      toast.error("Errore nell'eliminazione");
    }
  };

  return (
    <div className="p-4 md:p-6" data-testid="clients-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-heading text-2xl font-bold text-zinc-100 tracking-tight">
            Clienti
          </h1>
          <p className="text-zinc-500 text-sm mt-1">
            Gestione clienti e relativi dispositivi
          </p>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button 
              className="rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white gap-2"
              data-testid="add-client-btn"
            >
              <Plus size={16} />
              Nuovo Cliente
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-zinc-900 border-zinc-800 rounded-sm">
            <DialogHeader>
              <DialogTitle className="font-heading text-zinc-100">
                Nuovo Cliente
              </DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Nome *
                </Label>
                <Input
                  value={newClient.name}
                  onChange={(e) => setNewClient(c => ({ ...c, name: e.target.value }))}
                  placeholder="Acme Corporation"
                  required
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
                  data-testid="client-name-input"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Descrizione
                </Label>
                <Input
                  value={newClient.description}
                  onChange={(e) => setNewClient(c => ({ ...c, description: e.target.value }))}
                  placeholder="Cliente enterprise con infrastruttura complessa"
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
                  data-testid="client-description-input"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Email Contatto
                </Label>
                <Input
                  type="email"
                  value={newClient.contact_email}
                  onChange={(e) => setNewClient(c => ({ ...c, contact_email: e.target.value }))}
                  placeholder="it@acme.com"
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
                  data-testid="client-email-input"
                />
              </div>
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
                  data-testid="save-client-btn"
                >
                  Salva
                </Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Clients Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          <p className="text-zinc-500 col-span-full text-center py-8">
            Caricamento...
          </p>
        ) : clients.length === 0 ? (
          <div className="col-span-full noc-panel p-8 text-center">
            <Buildings size={48} className="mx-auto text-zinc-600 mb-4" />
            <p className="text-zinc-400 mb-2">Nessun cliente configurato</p>
            <p className="text-zinc-600 text-sm">
              Aggiungi il primo cliente per iniziare a monitorare i dispositivi
            </p>
          </div>
        ) : (
          clients.map((client) => (
            <div 
              key={client.id} 
              className="noc-panel p-5 hover:border-zinc-700 transition-fast"
              data-testid={`client-card-${client.id}`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-sm bg-zinc-800 flex items-center justify-center">
                    <Buildings size={20} className="text-zinc-400" />
                  </div>
                  <div>
                    <h3 className="font-heading font-semibold text-zinc-100">
                      {client.name}
                    </h3>
                    <p className="text-zinc-500 text-xs font-mono">
                      ID: {client.id.substring(0, 8)}
                    </p>
                  </div>
                </div>

                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-zinc-500 hover:text-red-400 hover:bg-red-900/20 rounded-sm"
                      data-testid={`delete-client-${client.id}`}
                    >
                      <Trash size={16} />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent className="bg-zinc-900 border-zinc-800 rounded-sm">
                    <AlertDialogHeader>
                      <AlertDialogTitle className="text-zinc-100">
                        Eliminare {client.name}?
                      </AlertDialogTitle>
                      <AlertDialogDescription className="text-zinc-400">
                        Questa azione non può essere annullata. Tutti i dispositivi e gli alert associati saranno mantenuti.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel className="rounded-sm bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700">
                        Annulla
                      </AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => handleDelete(client.id)}
                        className="rounded-sm bg-red-900 text-red-100 hover:bg-red-800"
                      >
                        Elimina
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>

              {client.description && (
                <p className="text-zinc-400 text-sm mb-3 line-clamp-2">
                  {client.description}
                </p>
              )}

              {client.contact_email && (
                <div className="flex items-center gap-2 text-zinc-500 text-sm">
                  <EnvelopeSimple size={14} />
                  <span className="font-mono">{client.contact_email}</span>
                </div>
              )}

              <div className="mt-4 pt-4 border-t border-zinc-800">
                <p className="text-zinc-600 text-xs">
                  Creato: {new Date(client.created_at).toLocaleDateString("it-IT")}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
