import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/App";
import { toast } from "sonner";
import {
  Ticket, Plus, Clock, CheckCircle, Spinner as SpinnerIcon, Warning,
  ArrowRight, ChatDots, UserCircle, Trash, CaretDown, FunnelSimple
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";

const STATUS_MAP = {
  open: { label: "Aperto", cls: "bg-red-500/15 text-red-400", icon: <Warning size={12} /> },
  in_progress: { label: "In Corso", cls: "bg-amber-500/15 text-amber-400", icon: <SpinnerIcon size={12} /> },
  resolved: { label: "Risolto", cls: "bg-emerald-500/15 text-emerald-400", icon: <CheckCircle size={12} /> },
  closed: { label: "Chiuso", cls: "bg-zinc-500/15 text-zinc-400", icon: <CheckCircle size={12} /> },
};

const PRIORITY_MAP = {
  critical: { label: "Critico", cls: "bg-red-500/15 text-red-400 border-red-500/30" },
  high: { label: "Alto", cls: "bg-orange-500/15 text-orange-400 border-orange-500/30" },
  medium: { label: "Medio", cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
  low: { label: "Basso", cls: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
};

export default function IncidentsPage() {
  const { user } = useAuth();
  const [incidents, setIncidents] = useState([]);
  const [stats, setStats] = useState(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newNote, setNewNote] = useState("");
  const [clients, setClients] = useState([]);

  const [form, setForm] = useState({ title: "", description: "", client_id: "", priority: "medium" });

  useEffect(() => {
    fetchIncidents();
    fetchStats();
    axios.get(`${API}/clients`).then(r => setClients(r.data?.clients || r.data || [])).catch(() => {});
  }, [statusFilter]);

  const fetchIncidents = () => {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    axios.get(`${API}/incidents?${params}`).then(r => setIncidents(r.data)).catch(() => {});
  };

  const fetchStats = () => {
    axios.get(`${API}/incidents/stats/summary`).then(r => setStats(r.data)).catch(() => {});
  };

  const createIncident = async () => {
    if (!form.title.trim()) { toast.error("Inserisci un titolo"); return; }
    const clientName = clients.find(c => c.id === form.client_id)?.name || "";
    try {
      const res = await axios.post(`${API}/incidents`, { ...form, client_name: clientName });
      toast.success("Incidente creato");
      setShowCreate(false);
      setForm({ title: "", description: "", client_id: "", priority: "medium" });
      fetchIncidents();
      fetchStats();
    } catch { toast.error("Errore"); }
  };

  const updateIncident = async (id, updates) => {
    try {
      const res = await axios.patch(`${API}/incidents/${id}`, updates);
      setSelected(res.data);
      fetchIncidents();
      fetchStats();
      toast.success("Aggiornato");
    } catch { toast.error("Errore"); }
  };

  const addNote = async () => {
    if (!newNote.trim() || !selected) return;
    await updateIncident(selected.id, { note: newNote });
    setNewNote("");
  };

  const deleteIncident = async (id) => {
    try {
      await axios.delete(`${API}/incidents/${id}`);
      setSelected(null);
      fetchIncidents();
      fetchStats();
      toast.success("Eliminato");
    } catch { toast.error("Errore"); }
  };

  const fmtDate = (iso) => {
    if (!iso) return "-";
    return new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
  };

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="incidents-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)]">Gestione Incidenti</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Traccia e gestisci gli interventi operativi</p>
        </div>
        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogTrigger asChild>
            <Button className="h-8 bg-indigo-600 hover:bg-indigo-700 text-white text-xs gap-1" data-testid="create-incident-btn">
              <Plus size={14} /> Nuovo Incidente
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)] max-w-md">
            <DialogHeader><DialogTitle className="text-[var(--text-primary)]">Nuovo Incidente</DialogTitle></DialogHeader>
            <div className="space-y-3 pt-2">
              <Input value={form.title} onChange={e => setForm(f => ({...f, title: e.target.value}))} placeholder="Titolo incidente" className="bg-[var(--bg-deep)] border-[var(--border-subtle)] text-[var(--text-primary)] text-xs h-9" data-testid="incident-title-input" />
              <textarea value={form.description} onChange={e => setForm(f => ({...f, description: e.target.value}))} placeholder="Descrizione..." className="w-full h-20 rounded-md bg-[var(--bg-deep)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-xs p-2 resize-none" data-testid="incident-desc-input" />
              <div className="grid grid-cols-2 gap-2">
                <Select value={form.client_id} onValueChange={v => setForm(f => ({...f, client_id: v}))}>
                  <SelectTrigger className="h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs"><SelectValue placeholder="Cliente" /></SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                    {clients.map(c => <SelectItem key={c.id} value={c.id} className="text-xs text-[var(--text-primary)]">{c.name}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Select value={form.priority} onValueChange={v => setForm(f => ({...f, priority: v}))}>
                  <SelectTrigger className="h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                    {Object.entries(PRIORITY_MAP).map(([k, v]) => <SelectItem key={k} value={k} className="text-xs text-[var(--text-primary)]">{v.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={createIncident} className="w-full h-8 bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="submit-incident-btn">Crea Incidente</Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MiniStat label="Aperti" value={stats.open} color="red" />
          <MiniStat label="In Corso" value={stats.in_progress} color="amber" />
          <MiniStat label="Risolti" value={stats.resolved} color="emerald" />
          <MiniStat label="Totale" value={stats.total} color="indigo" />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
        {/* List */}
        <div className="lg:col-span-2 noc-panel">
          <div className="p-3 border-b border-[var(--bg-border)] flex items-center gap-2">
            <FunnelSimple size={14} className="text-[var(--text-muted)]" />
            <Select value={statusFilter} onValueChange={v => setStatusFilter(v === "all" ? "" : v)}>
              <SelectTrigger className="h-7 w-[120px] bg-[var(--bg-deep)] border-[var(--border-subtle)] text-[10px]" data-testid="incident-status-filter">
                <SelectValue placeholder="Tutti" />
              </SelectTrigger>
              <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                <SelectItem value="all" className="text-xs text-[var(--text-primary)]">Tutti</SelectItem>
                {Object.entries(STATUS_MAP).map(([k, v]) => <SelectItem key={k} value={k} className="text-xs text-[var(--text-primary)]">{v.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <ScrollArea className="h-[500px]">
            <div className="p-2 space-y-1">
              {incidents.length === 0 ? (
                <p className="text-xs text-[var(--text-muted)] text-center py-8">Nessun incidente</p>
              ) : incidents.map(inc => {
                const st = STATUS_MAP[inc.status] || STATUS_MAP.open;
                const pr = PRIORITY_MAP[inc.priority] || PRIORITY_MAP.medium;
                return (
                  <div key={inc.id}
                    className={`p-2.5 rounded-md border cursor-pointer transition-all ${selected?.id === inc.id ? "border-indigo-500/50 bg-indigo-500/5" : "border-[var(--bg-border)] hover:border-[var(--border-subtle)]"}`}
                    onClick={() => setSelected(inc)}
                    data-testid={`incident-item-${inc.id}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-[var(--text-primary)] truncate">{inc.title}</p>
                        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{inc.client_name || "-"} | {fmtDate(inc.created_at)}</p>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className={`text-[9px] px-1.5 py-0.5 rounded border font-medium ${pr.cls}`}>{pr.label}</span>
                        <span className={`inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded font-medium ${st.cls}`}>{st.icon} {st.label}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        {/* Detail */}
        <div className="lg:col-span-3 noc-panel p-4" data-testid="incident-detail-panel">
          {!selected ? (
            <div className="flex flex-col items-center justify-center h-[500px] text-[var(--text-muted)]">
              <Ticket size={40} className="mb-3 opacity-30" />
              <p className="text-xs">Seleziona un incidente</p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-sm font-bold text-[var(--text-primary)]">{selected.title}</h2>
                  <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                    Creato da {selected.created_by} | {fmtDate(selected.created_at)}
                  </p>
                </div>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-red-400 hover:text-red-300 hover:bg-red-900/20"
                  onClick={() => deleteIncident(selected.id)} data-testid="delete-incident-btn">
                  <Trash size={14} />
                </Button>
              </div>

              {selected.description && (
                <p className="text-xs text-[var(--text-secondary)] bg-[var(--bg-deep)] rounded p-2.5">{selected.description}</p>
              )}

              <div className="flex gap-2 flex-wrap">
                <Select value={selected.status} onValueChange={v => updateIncident(selected.id, { status: v })}>
                  <SelectTrigger className="h-7 w-[120px] bg-[var(--bg-deep)] border-[var(--border-subtle)] text-[10px]" data-testid="incident-status-update"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                    {Object.entries(STATUS_MAP).map(([k, v]) => <SelectItem key={k} value={k} className="text-xs text-[var(--text-primary)]">{v.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Select value={selected.priority} onValueChange={v => updateIncident(selected.id, { priority: v })}>
                  <SelectTrigger className="h-7 w-[120px] bg-[var(--bg-deep)] border-[var(--border-subtle)] text-[10px]" data-testid="incident-priority-update"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                    {Object.entries(PRIORITY_MAP).map(([k, v]) => <SelectItem key={k} value={k} className="text-xs text-[var(--text-primary)]">{v.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>

              {/* Timeline */}
              <div>
                <h3 className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium mb-2">Timeline</h3>
                <ScrollArea className="h-[200px]">
                  <div className="space-y-2">
                    {(selected.timeline || []).map((t, i) => (
                      <div key={i} className="flex gap-2 text-xs">
                        <div className="w-1 rounded-full bg-indigo-500/30 flex-shrink-0" />
                        <div>
                          <p className="text-[var(--text-primary)]">{t.note}</p>
                          <p className="text-[10px] text-[var(--text-muted)]">{t.user} - {fmtDate(t.timestamp)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>

              {/* Add Note */}
              <div className="flex gap-2">
                <Input value={newNote} onChange={e => setNewNote(e.target.value)}
                  placeholder="Aggiungi nota operativa..."
                  className="flex-1 h-8 bg-[var(--bg-deep)] border-[var(--border-subtle)] text-xs text-[var(--text-primary)]"
                  data-testid="incident-note-input"
                  onKeyDown={e => e.key === "Enter" && addNote()}
                />
                <Button onClick={addNote} className="h-8 bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-3" data-testid="add-note-btn">
                  <ChatDots size={14} />
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value, color }) {
  const cls = {
    red: "text-red-400", amber: "text-amber-400", emerald: "text-emerald-400", indigo: "text-indigo-400"
  };
  return (
    <div className="noc-panel p-3" data-testid={`incident-stat-${label.toLowerCase()}`}>
      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
      <p className={`font-heading text-2xl font-bold ${cls[color]}`}>{value}</p>
    </div>
  );
}
