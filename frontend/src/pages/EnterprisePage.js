import { useState, useEffect } from "react";
import axios from "axios";
import { API, useAuth } from "@/App";
import { toast } from "sonner";
import {
  ShieldCheck, Users, Clock, Wrench, FileText,
  Plus, Trash, Download, CaretDown, Check,
  Timer, Warning, Lightning, Eye, Lock, 
  ArrowClockwise, XCircle, UserCircle, Globe
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { SecurityAuditTab } from "@/components/SecurityAuditTab";

export default function EnterprisePage() {
  const { user } = useAuth();

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="enterprise-page">
      <div className="mb-5">
        <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">
          Enterprise
        </h1>
        <p className="text-[var(--text-muted)] text-xs mt-0.5">
          RBAC, SLA, Manutenzione e Report
        </p>
      </div>

      <Tabs defaultValue="sla" className="space-y-4">
        <TabsList className="bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded-lg p-1 h-auto flex-wrap">
          <TabsTrigger value="sla" className="rounded-md data-[state=active]:bg-indigo-600/20 data-[state=active]:text-indigo-300 text-xs gap-1.5 h-8">
            <Timer size={14} /> SLA
          </TabsTrigger>
          <TabsTrigger value="rbac" className="rounded-md data-[state=active]:bg-indigo-600/20 data-[state=active]:text-indigo-300 text-xs gap-1.5 h-8">
            <ShieldCheck size={14} /> RBAC
          </TabsTrigger>
          <TabsTrigger value="maintenance" className="rounded-md data-[state=active]:bg-indigo-600/20 data-[state=active]:text-indigo-300 text-xs gap-1.5 h-8">
            <Wrench size={14} /> Manutenzione
          </TabsTrigger>
          <TabsTrigger value="reports" className="rounded-md data-[state=active]:bg-indigo-600/20 data-[state=active]:text-indigo-300 text-xs gap-1.5 h-8">
            <FileText size={14} /> Report
          </TabsTrigger>
          <TabsTrigger value="security" className="rounded-md data-[state=active]:bg-red-600/20 data-[state=active]:text-red-300 text-xs gap-1.5 h-8">
            <Eye size={14} /> Security Audit
          </TabsTrigger>
        </TabsList>

        <TabsContent value="sla"><SLATab /></TabsContent>
        <TabsContent value="rbac"><RBACTab /></TabsContent>
        <TabsContent value="maintenance"><MaintenanceTab /></TabsContent>
        <TabsContent value="reports"><ReportsTab /></TabsContent>
        <TabsContent value="security"><SecurityAuditTab /></TabsContent>
      </Tabs>
    </div>
  );
}

/* ==================== SLA TAB ==================== */
function SLATab() {
  const [stats, setStats] = useState(null);
  const [configs, setConfigs] = useState({});
  const [breaches, setBreaches] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    try {
      const [statsRes, configsRes, breachesRes] = await Promise.all([
        axios.get(`${API}/sla/stats`),
        axios.get(`${API}/sla/configs`),
        axios.get(`${API}/sla/breaches?days=30&limit=20`)
      ]);
      setStats(statsRes.data);
      setConfigs(configsRes.data);
      setBreaches(breachesRes.data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  if (loading) return <LoadingState />;

  return (
    <div className="space-y-4" data-testid="sla-tab">
      {/* SLA Overview */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <MetricBox label="Alert Totali" value={stats.total_alerts} sub={`Ultimi ${stats.period_days} giorni`} />
          <MetricBox label="Tasso Risoluzione" value={`${stats.resolution_rate.toFixed(1)}%`}
            color={stats.resolution_rate > 90 ? "var(--ok)" : stats.resolution_rate > 70 ? "var(--high)" : "var(--critical)"} />
          <MetricBox label="Compliance SLA Risposta" value={`${stats.response_sla_compliance.toFixed(1)}%`}
            color={stats.response_sla_compliance > 95 ? "var(--ok)" : "var(--high)"} />
          <MetricBox label="Compliance SLA Risoluzione" value={`${stats.resolution_sla_compliance.toFixed(1)}%`}
            color={stats.resolution_sla_compliance > 95 ? "var(--ok)" : "var(--high)"} />
        </div>
      )}

      {/* Response Times */}
      {stats && (
        <div className="grid grid-cols-2 gap-3">
          <div className="noc-panel p-4">
            <p className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest mb-1">Tempo Medio Risposta</p>
            <p className="font-heading text-2xl font-bold text-[var(--text-primary)]">
              {stats.avg_response_time_minutes.toFixed(1)} <span className="text-sm text-[var(--text-muted)]">min</span>
            </p>
          </div>
          <div className="noc-panel p-4">
            <p className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest mb-1">Tempo Medio Risoluzione</p>
            <p className="font-heading text-2xl font-bold text-[var(--text-primary)]">
              {stats.avg_resolution_time_minutes.toFixed(1)} <span className="text-sm text-[var(--text-muted)]">min</span>
            </p>
          </div>
        </div>
      )}

      {/* SLA Configs */}
      <div className="noc-panel p-4">
        <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">Configurazione SLA</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {Object.entries(configs).map(([severity, config]) => (
            <div key={severity} className={`p-3 rounded-lg border severity-${severity}`}>
              <p className="font-heading font-bold text-sm uppercase mb-2">{severity}</p>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between">
                  <span className="opacity-70">Risposta:</span>
                  <span className="font-mono">{config.response_time_minutes} min</span>
                </div>
                <div className="flex justify-between">
                  <span className="opacity-70">Risoluzione:</span>
                  <span className="font-mono">{config.resolution_time_minutes} min</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Breaches */}
      <div className="noc-panel p-4">
        <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">
          Violazioni SLA Recenti
        </h3>
        {breaches.length === 0 ? (
          <p className="text-[var(--text-muted)] text-xs py-4 text-center">Nessuna violazione</p>
        ) : (
          <div className="space-y-2">
            {breaches.map((b, i) => (
              <div key={i} className="flex items-center gap-3 p-2 rounded-md bg-[var(--bg-card)]">
                <Warning size={14} className="text-[var(--high)] flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-[var(--text-secondary)] truncate">
                    <span className={`severity-badge severity-${b.severity} mr-2`}>{b.severity}</span>
                    {b.breach_type} - {b.elapsed_minutes?.toFixed(0)} min
                  </p>
                </div>
                <span className="text-[10px] text-[var(--text-muted)] font-mono flex-shrink-0">
                  {b.timestamp?.substring(0, 16).replace("T", " ")}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ==================== RBAC TAB ==================== */
function RBACTab() {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editUser, setEditUser] = useState(null);
  const [newRole, setNewRole] = useState("");

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    try {
      const [usersRes, rolesRes] = await Promise.all([
        axios.get(`${API}/users`),
        axios.get(`${API}/rbac/roles`)
      ]);
      setUsers(usersRes.data);
      setRoles(rolesRes.data);
    } catch (e) {
      if (e.response?.status === 403) {
        toast.error("Accesso admin richiesto");
      }
    } finally { setLoading(false); }
  };

  const handleRoleUpdate = async () => {
    if (!editUser || !newRole) return;
    try {
      await axios.patch(`${API}/users/${editUser.id}/role`, { role: newRole });
      toast.success("Ruolo aggiornato");
      setEditUser(null);
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  if (loading) return <LoadingState />;

  return (
    <div className="space-y-4" data-testid="rbac-tab">
      {/* Roles Overview */}
      <div className="noc-panel p-4">
        <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">Ruoli Disponibili</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {roles.map(r => (
            <div key={r.name} className="p-3 rounded-lg bg-[var(--bg-card)] border border-[var(--bg-border)]">
              <p className="font-heading font-bold text-xs text-[var(--text-primary)] uppercase">{r.name.replace("_", " ")}</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-1">{r.permissions?.length || 0} permessi</p>
            </div>
          ))}
        </div>
      </div>

      {/* Users List */}
      <div className="noc-panel">
        <div className="p-3 border-b border-[var(--bg-border)]">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest">Utenti</h3>
        </div>
        <ScrollArea className="max-h-[400px]">
          <div className="overflow-x-auto">
          <table className="alert-table min-w-[640px]">
            <thead>
              <tr>
                <th>Nome</th>
                <th>Email</th>
                <th>Ruolo</th>
                <th>2FA</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td className="text-[var(--text-primary)] text-xs font-medium">{u.name}</td>
                  <td className="font-mono text-[var(--text-muted)] text-xs">{u.email}</td>
                  <td>
                    <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md bg-indigo-600/10 text-indigo-300 border border-indigo-600/20">
                      {u.role}
                    </span>
                  </td>
                  <td>
                    <span className={`text-[10px] ${u.two_factor_enabled ? "text-[var(--ok)]" : "text-[var(--text-muted)]"}`}>
                      {u.two_factor_enabled ? "Attivo" : "Off"}
                    </span>
                  </td>
                  <td>
                    <Button size="sm" variant="ghost" 
                      onClick={() => { setEditUser(u); setNewRole(u.role); }}
                      className="text-[10px] h-6 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                      data-testid={`edit-role-${u.id}`}>
                      Modifica
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </ScrollArea>
      </div>

      {/* Edit Role Dialog */}
      <Dialog open={!!editUser} onOpenChange={() => setEditUser(null)}>
        <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-heading text-[var(--text-primary)] text-sm">
              Modifica Ruolo - {editUser?.name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-3">
            <div className="space-y-1.5">
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Ruolo</Label>
              <Select value={newRole} onValueChange={setNewRole}>
                <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                  {roles.map(r => (
                    <SelectItem key={r.name} value={r.name} className="text-xs">{r.name.replace("_"," ")}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setEditUser(null)} className="rounded-md text-xs">Annulla</Button>
              <Button size="sm" onClick={handleRoleUpdate} className="rounded-md bg-indigo-600 hover:bg-indigo-700 text-white text-xs">Salva</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ==================== MAINTENANCE TAB ==================== */
function MaintenanceTab() {
  const [windows, setWindows] = useState([]);
  const [activeWindows, setActiveWindows] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({
    name: "", description: "", client_id: "", start_time: "", end_time: "",
    suppress_alerts: true, suppress_severities: ["low", "medium"]
  });

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    try {
      const [wRes, aRes, cRes] = await Promise.all([
        axios.get(`${API}/maintenance/windows`),
        axios.get(`${API}/maintenance/active`),
        axios.get(`${API}/clients`)
      ]);
      setWindows(wRes.data);
      setActiveWindows(aRes.data);
      setClients(cRes.data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        ...form,
        client_id: form.client_id || null,
        start_time: new Date(form.start_time).toISOString(),
        end_time: new Date(form.end_time).toISOString()
      };
      await axios.post(`${API}/maintenance/windows`, payload);
      toast.success("Finestra di manutenzione creata");
      setDialogOpen(false);
      setForm({ name: "", description: "", client_id: "", start_time: "", end_time: "", suppress_alerts: true, suppress_severities: ["low","medium"] });
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const handleDelete = async (id) => {
    try {
      await axios.delete(`${API}/maintenance/windows/${id}`);
      toast.success("Eliminata");
      fetchAll();
    } catch { toast.error("Errore"); }
  };

  if (loading) return <LoadingState />;

  return (
    <div className="space-y-4" data-testid="maintenance-tab">
      {/* Active banner */}
      {activeWindows.length > 0 && (
        <div className="p-3 rounded-lg border border-[var(--high-border)] bg-[var(--high-bg)]">
          <div className="flex items-center gap-2">
            <Wrench size={16} className="text-[var(--high)]" />
            <p className="text-[var(--high)] text-xs font-medium">
              {activeWindows.length} finestre di manutenzione attive
            </p>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest">
          Finestre Manutenzione
        </h3>
        <Button size="sm" onClick={() => setDialogOpen(true)}
          className="rounded-md bg-indigo-600 hover:bg-indigo-700 text-white text-xs h-7 gap-1"
          data-testid="add-maintenance-btn">
          <Plus size={12} /> Nuova
        </Button>
      </div>

      {/* Windows List */}
      {windows.length === 0 ? (
        <div className="noc-panel p-6 text-center">
          <Wrench size={32} className="mx-auto text-[var(--text-muted)] mb-2" />
          <p className="text-[var(--text-muted)] text-xs">Nessuna finestra programmata</p>
        </div>
      ) : (
        <div className="space-y-2">
          {windows.map(w => (
            <div key={w.id} className="noc-panel p-3 flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full ${w.status === "active" ? "bg-[var(--high)]" : w.status === "scheduled" ? "bg-[var(--medium)]" : "bg-[var(--text-muted)]"}`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-[var(--text-primary)]">{w.name}</p>
                <p className="text-[10px] text-[var(--text-muted)] font-mono">
                  {w.start_time?.substring(0,16).replace("T"," ")} - {w.end_time?.substring(0,16).replace("T"," ")}
                </p>
              </div>
              <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md ${
                w.status === "active" ? "bg-[var(--high-bg)] text-[var(--high)] border border-[var(--high-border)]" :
                w.status === "scheduled" ? "bg-[var(--medium-bg)] text-[var(--medium)] border border-[var(--medium-border)]" :
                "bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--bg-border)]"
              }`}>{w.status === "active" ? "Attiva" : w.status === "scheduled" ? "Programmata" : "Completata"}</span>
              <Button size="sm" variant="ghost" onClick={() => handleDelete(w.id)}
                className="h-7 w-7 text-[var(--text-muted)] hover:text-[var(--critical)] p-0">
                <Trash size={14} />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading text-[var(--text-primary)] text-sm">Nuova Manutenzione</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-3 mt-3">
            <div className="space-y-1.5">
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Nome *</Label>
              <Input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} required
                placeholder="Aggiornamento firmware" className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="maint-name-input" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Cliente</Label>
              <Select value={form.client_id} onValueChange={v => setForm(f => ({...f, client_id: v}))}>
                <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8">
                  <SelectValue placeholder="Tutti" />
                </SelectTrigger>
                <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                  <SelectItem value="all" className="text-xs">Tutti</SelectItem>
                  {clients.map(c => <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Inizio *</Label>
                <Input type="datetime-local" value={form.start_time} required
                  onChange={e => setForm(f => ({...f, start_time: e.target.value}))}
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Fine *</Label>
                <Input type="datetime-local" value={form.end_time} required
                  onChange={e => setForm(f => ({...f, end_time: e.target.value}))}
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setDialogOpen(false)} className="rounded-md text-xs">Annulla</Button>
              <Button type="submit" size="sm" className="rounded-md bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="save-maintenance-btn">Crea</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ==================== REPORTS TAB ==================== */
function ReportsTab() {
  const [downloading, setDownloading] = useState(null);

  const downloadReport = async (type) => {
    setDownloading(type);
    try {
      const endpoints = {
        "sla-pdf": { url: `${API}/reports/sla/pdf`, filename: "sla_report.pdf", type: "application/pdf" },
        "alerts-csv": { url: `${API}/reports/alerts/csv`, filename: "alerts_export.csv", type: "text/csv" },
        "devices-csv": { url: `${API}/reports/devices/csv`, filename: "devices_export.csv", type: "text/csv" }
      };
      const ep = endpoints[type];
      const response = await axios.get(ep.url, { responseType: "blob" });
      const blob = new Blob([response.data], { type: ep.type });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = ep.filename;
      a.click();
      window.URL.revokeObjectURL(url);
      toast.success("Report scaricato");
    } catch (e) { toast.error("Errore download"); }
    finally { setDownloading(null); }
  };

  return (
    <div className="space-y-4" data-testid="reports-tab">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <ReportCard
          title="Report SLA"
          description="Compliance SLA, tempi risposta, violazioni"
          format="PDF"
          onDownload={() => downloadReport("sla-pdf")}
          loading={downloading === "sla-pdf"}
          testId="download-sla-pdf"
        />
        <ReportCard
          title="Export Alert"
          description="Tutti gli alert con dettagli completi"
          format="CSV"
          onDownload={() => downloadReport("alerts-csv")}
          loading={downloading === "alerts-csv"}
          testId="download-alerts-csv"
        />
        <ReportCard
          title="Export Dispositivi"
          description="Lista completa dispositivi monitorati"
          format="CSV"
          onDownload={() => downloadReport("devices-csv")}
          loading={downloading === "devices-csv"}
          testId="download-devices-csv"
        />
      </div>
    </div>
  );
}

function ReportCard({ title, description, format, onDownload, loading, testId }) {
  return (
    <div className="noc-panel p-4 flex flex-col">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-8 h-8 rounded-lg bg-indigo-600/10 flex items-center justify-center flex-shrink-0">
          <FileText size={16} className="text-indigo-400" />
        </div>
        <div>
          <p className="text-xs font-medium text-[var(--text-primary)]">{title}</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{description}</p>
        </div>
      </div>
      <div className="mt-auto pt-3 flex items-center justify-between">
        <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase">{format}</span>
        <Button size="sm" variant="outline" onClick={onDownload} disabled={loading}
          className="rounded-md text-xs h-7 gap-1 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
          data-testid={testId}>
          <Download size={12} />
          {loading ? "..." : "Scarica"}
        </Button>
      </div>
    </div>
  );
}

/* ==================== SHARED COMPONENTS ==================== */
function MetricBox({ label, value, sub, color }) {
  return (
    <div className="noc-panel p-3">
      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-1">{label}</p>
      <p className="font-heading text-xl font-bold" style={{ color: color || "var(--text-primary)" }}>{value}</p>
      {sub && <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{sub}</p>}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-12">
      <p className="text-[var(--text-muted)] text-xs">Caricamento...</p>
    </div>
  );
}
