import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  Lock, Eye, EyeSlash, Plus, Trash, PencilSimple,
  ShieldCheck, Key, Copy, Check, DesktopTower, Globe,
  WifiHigh, LockKey, ArrowClockwise, MagnifyingGlass,
  Lightning, Plugs, Warning, PlayCircle
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const typeConfig = {
  ilo: { label: "HPE iLO", icon: DesktopTower, color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/20" },
  ssh: { label: "SSH", icon: LockKey, color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" },
  snmp: { label: "SNMP", icon: WifiHigh, color: "text-purple-400", bg: "bg-purple-500/10 border-purple-500/20" },
  web: { label: "Web Panel", icon: Globe, color: "text-cyan-400", bg: "bg-cyan-500/10 border-cyan-500/20" },
  vpn: { label: "VPN", icon: ShieldCheck, color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
  other: { label: "Altro", icon: Key, color: "text-[var(--text-muted)]", bg: "bg-[var(--bg-hover)] border-[var(--bg-border)]" },
};

function CredentialRow({ cred, onReveal, onEdit, onDelete, revealed, failoverInfo, onToggleDirectPoll, onToggleConnectorOnly, onTestConnection }) {
  const [copied, setCopied] = useState(null);
  const tc = typeConfig[cred.credential_type] || typeConfig.other;
  const Icon = tc.icon;
  const isILO = cred.credential_type === "ilo";
  const fi = failoverInfo || {};

  const pollingBadge = {
    direct: { label: "DIRETTO (ENTERPRISE)", color: "text-cyan-400", bg: "bg-cyan-500/10 border-cyan-500/30" },
    failover: { label: "FAILOVER (LAN)", color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
    connector: { label: "SOLO CONNECTOR", color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30" },
    offline: { label: "OFFLINE", color: "text-[var(--critical)]", bg: "bg-[var(--critical-bg)] border-[var(--critical-border)]" },
  };

  const copyToClipboard = async (text, field) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(field);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      toast.error("Impossibile copiare");
    }
  };

  return (
    <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] hover:border-[var(--bg-border-hover)] transition-colors" data-testid={`cred-row-${cred.id}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg border ${tc.bg}`}>
            <Icon size={16} className={tc.color} />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-[var(--text-primary)]">{cred.device_name || cred.device_ip || "N/D"}</span>
              <span className={`text-[9px] px-1.5 py-0.5 rounded border font-medium ${tc.bg} ${tc.color}`}>{tc.label}</span>
              {cred.client_name && (
                <span className="text-[9px] px-1.5 py-0.5 rounded border font-medium bg-indigo-500/10 border-indigo-500/20 text-indigo-400">
                  {cred.client_name}
                </span>
              )}
              {!cred.client_id && (
                <span className="text-[9px] px-1.5 py-0.5 rounded border font-medium bg-[var(--bg-hover)] border-[var(--bg-border)] text-[var(--text-muted)]">
                  Globale
                </span>
              )}
              {isILO && fi.polling_mode && pollingBadge[fi.polling_mode] && (
                <span className={`text-[8px] px-1.5 py-0.5 rounded border font-bold ${pollingBadge[fi.polling_mode].bg} ${pollingBadge[fi.polling_mode].color}`}>
                  {fi.polling_mode === "failover" && <Warning size={8} className="inline mr-0.5" />}
                  {fi.polling_mode === "direct" && <Lightning size={8} className="inline mr-0.5" />}
                  {pollingBadge[fi.polling_mode].label}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-0.5">
              {cred.device_ip && <span className="text-[10px] font-mono text-[var(--text-muted)]">{cred.device_ip}</span>}
              {cred.url && <span className="text-[10px] text-[var(--text-muted)]">{cred.url}</span>}
              {cred.port && <span className="text-[10px] text-[var(--text-muted)]">:{cred.port}</span>}
              {fi.external_url && <span className="text-[10px] text-teal-400 font-mono">{fi.external_url}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {isILO && onTestConnection && (
            <Button size="sm" variant="ghost" onClick={() => onTestConnection(cred)} className="h-7 text-[10px] gap-1 text-teal-400" data-testid={`test-conn-${cred.id}`}>
              <Plugs size={12} /> Test
            </Button>
          )}
          {isILO && fi.external_url && onToggleConnectorOnly && (
            <Button size="sm" variant="ghost" onClick={() => onToggleConnectorOnly(cred)}
              className={`h-7 text-[10px] gap-1 ${fi.connector_only ? "text-emerald-400" : "text-cyan-400"}`}
              title={fi.connector_only ? "Disabilita modalita' solo-connector (torna a diretto+ridondante)" : "Forza solo-connector (disabilita polling diretto dal cloud)"}
              data-testid={`toggle-connector-only-${cred.id}`}>
              <Lightning size={12} /> {fi.connector_only ? "Solo Connector" : "Diretto ATTIVO"}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => onReveal(cred.id)} className="h-7 text-[10px] gap-1" data-testid={`reveal-${cred.id}`}>
            {revealed ? <EyeSlash size={12} /> : <Eye size={12} />}
            {revealed ? "Nascondi" : "Mostra"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onEdit(cred)} className="h-7 text-[10px] gap-1" data-testid={`edit-${cred.id}`}>
            <PencilSimple size={12} /> Modifica
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onDelete(cred.id)} className="h-7 text-[10px] gap-1 text-[var(--critical)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)]" data-testid={`delete-${cred.id}`}>
            <Trash size={12} />
          </Button>
        </div>
      </div>

      {/* Credential details */}
      <div className="mt-2 grid grid-cols-2 gap-2">
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[var(--bg-hover)] text-[10px]">
          <span className="text-[var(--text-muted)] w-16">Username:</span>
          <span className="font-mono text-[var(--text-primary)] flex-1">{revealed?.username || cred.username}</span>
          {revealed && (
            <button onClick={() => copyToClipboard(revealed.username, "user")} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
              {copied === "user" ? <Check size={10} className="text-[var(--ok)]" /> : <Copy size={10} />}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[var(--bg-hover)] text-[10px]">
          <span className="text-[var(--text-muted)] w-16">Password:</span>
          <span className="font-mono text-[var(--text-primary)] flex-1">
            {revealed?.password || "••••••••••••"}
          </span>
          {revealed && (
            <button onClick={() => copyToClipboard(revealed.password, "pass")} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
              {copied === "pass" ? <Check size={10} className="text-[var(--ok)]" /> : <Copy size={10} />}
            </button>
          )}
        </div>
      </div>

      {/* Tags and notes */}
      {(cred.tags?.length > 0 || cred.notes) && (
        <div className="mt-1.5 flex items-center gap-2 flex-wrap">
          {cred.tags?.map((tag, i) => (
            <span key={i} className="text-[8px] px-1.5 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">{tag}</span>
          ))}
          {cred.notes && <span className="text-[9px] text-[var(--text-muted)] italic">{cred.notes}</span>}
        </div>
      )}

      <div className="mt-1 text-[8px] text-[var(--text-muted)]">
        Creata da {cred.created_by} il {cred.created_at ? new Date(cred.created_at).toLocaleDateString("it-IT") : "N/D"}
      </div>
    </div>
  );
}

export default function VaultPage({ scopedClientId = null, scopedClientName = "" }) {
  const [credentials, setCredentials] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editCred, setEditCred] = useState(null);
  const [revealed, setRevealed] = useState({});
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");
  const [filterClient, setFilterClient] = useState("all");
  const [failoverStatus, setFailoverStatus] = useState([]);
  const [testingConn, setTestingConn] = useState(null);

  const [form, setForm] = useState({
    device_ip: "", device_name: "", credential_type: "ilo",
    username: "", password: "", url: "", port: "", notes: "", tags: "",
    external_url: "", client_id: scopedClientId || "",
  });

  const fetchCreds = useCallback(async () => {
    try {
      const url = scopedClientId
        ? `${API}/vault/credentials?client_id=${scopedClientId}`
        : `${API}/vault/credentials`;
      const res = await axios.get(url);
      setCredentials(res.data);
    } catch (e) {
      if (e.response?.status === 403) toast.error("Accesso riservato agli admin");
    } finally {
      setLoading(false);
    }
  }, [scopedClientId]);

  const fetchClients = useCallback(async () => {
    if (scopedClientId) return; // skip if scoped
    try {
      const res = await axios.get(`${API}/clients`);
      setClients(res.data || []);
    } catch {}
  }, [scopedClientId]);

  const fetchFailover = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/redfish/failover-status`);
      setFailoverStatus(res.data);
    } catch {}
  }, []);

  useEffect(() => { fetchCreds(); fetchClients(); fetchFailover(); }, [fetchCreds, fetchClients, fetchFailover]);
  useEffect(() => {
    const interval = setInterval(fetchFailover, 30000);
    return () => clearInterval(interval);
  }, [fetchFailover]);

  const handleReveal = async (credId) => {
    if (revealed[credId]) {
      setRevealed(prev => { const n = { ...prev }; delete n[credId]; return n; });
      return;
    }
    try {
      const res = await axios.get(`${API}/vault/credentials/${credId}`);
      setRevealed(prev => ({ ...prev, [credId]: res.data }));
      setTimeout(() => {
        setRevealed(prev => { const n = { ...prev }; delete n[credId]; return n; });
      }, 30000);
    } catch {
      toast.error("Errore nella decifratura");
    }
  };

  const handleSave = async () => {
    if (!form.username || !form.password) return toast.error("Username e password obbligatori");
    try {
      const payload = {
        ...form,
        port: form.port ? parseInt(form.port) : null,
        tags: form.tags ? form.tags.split(",").map(s => s.trim()).filter(Boolean) : [],
        client_id: form.client_id || scopedClientId || null,
      };
      if (editCred) {
        await axios.put(`${API}/vault/credentials/${editCred.id}`, payload);
        toast.success("Credenziale aggiornata");
      } else {
        await axios.post(`${API}/vault/credentials`, payload);
        toast.success("Credenziale salvata e cifrata con AES-256-GCM");
      }
      // If iLO and has external_url, also update direct poll config
      if (payload.credential_type === "ilo" && payload.external_url) {
        const credId = editCred?.id;
        if (credId) {
          await axios.put(`${API}/vault/credentials/${credId}/direct-poll`, {
            external_url: payload.external_url,
          }).catch(() => {});
        }
      }
      setShowAdd(false);
      setEditCred(null);
      setForm({ device_ip: "", device_name: "", credential_type: "ilo", username: "", password: "", url: "", port: "", notes: "", tags: "", external_url: "", client_id: scopedClientId || "" });
      fetchCreds();
      fetchFailover();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nel salvataggio");
    }
  };

  const handleEdit = async (cred) => {
    try {
      const res = await axios.get(`${API}/vault/credentials/${cred.id}`);
      const d = res.data;
      const fi = failoverStatus.find(f => f.device_ip === d.device_ip) || {};
      setForm({
        device_ip: d.device_ip || "",
        device_name: d.device_name || "",
        credential_type: d.credential_type || "ilo",
        username: d.username || "",
        password: d.password || "",
        url: d.url || "",
        port: d.port ? String(d.port) : "",
        notes: d.notes || "",
        tags: (d.tags || []).join(", "),
        external_url: fi.external_url || d.external_url || "",
        client_id: d.client_id || "",
      });
      setEditCred(d);
      setShowAdd(true);
    } catch {
      toast.error("Errore nel caricamento credenziale");
    }
  };

  const handleDelete = async (credId) => {
    if (!window.confirm("Sei sicuro di voler eliminare questa credenziale?")) return;
    try {
      await axios.delete(`${API}/vault/credentials/${credId}`);
      toast.success("Credenziale eliminata");
      fetchCreds();
      fetchFailover();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nell'eliminazione");
    }
  };

  const handleToggleConnectorOnly = async (cred) => {
    try {
      const fi = failoverStatus.find(f => f.device_ip === cred.device_ip);
      const newValue = !fi?.connector_only;
      await axios.put(`${API}/vault/credentials/${cred.id}`, {
        connector_only: newValue,
      });
      toast.success(newValue
        ? "Polling SOLO connector attivato (diretto disabilitato)"
        : "Polling diretto riattivato (enterprise ridondante)");
      fetchFailover();
    } catch (e) {
      toast.error("Errore nell'aggiornamento");
    }
  };

  const handleToggleDirectPoll = async (cred) => {
    const fi = failoverStatus.find(f => f.device_ip === cred.device_ip);
    if (!fi?.external_url) {
      toast.error("Configura prima l'URL Esterna iLO nelle impostazioni della credenziale");
      return;
    }
    try {
      await axios.put(`${API}/vault/credentials/${cred.id}/direct-poll`, {
        direct_poll: !fi.direct_poll,
      });
      toast.success(fi.direct_poll ? "Polling diretto disattivato" : "Polling diretto attivato");
      fetchFailover();
    } catch {
      toast.error("Errore nell'aggiornamento");
    }
  };

  const handleTestConnection = async (cred) => {
    const fi = failoverStatus.find(f => f.device_ip === cred.device_ip);
    const url = fi?.external_url || cred.url || `https://${cred.device_ip}`;
    setTestingConn(cred.id);
    try {
      const dec = await axios.get(`${API}/vault/credentials/${cred.id}`);
      const res = await axios.post(`${API}/redfish/test-connection`, {
        url: url.replace(/\/$/, ""),
        username: dec.data.username,
        password: dec.data.password,
      });
      if (res.data.success) {
        toast.success(`Connessione OK: ${res.data.model || res.data.product} | Health: ${res.data.health}`);
      } else {
        toast.error(`Connessione fallita: ${res.data.error}`);
      }
    } catch (e) {
      toast.error("Errore nel test connessione: " + (e.response?.data?.detail || e.message));
    } finally {
      setTestingConn(null);
    }
  };

  const handleTriggerPoll = async () => {
    try {
      await axios.post(`${API}/redfish/poll-now`);
      toast.success("Polling Redfish manuale avviato");
    } catch {
      toast.error("Errore nell'avvio del polling");
    }
  };

  const filtered = credentials.filter(c => {
    const matchSearch = !search || 
      (c.device_name || "").toLowerCase().includes(search.toLowerCase()) ||
      (c.device_ip || "").toLowerCase().includes(search.toLowerCase()) ||
      (c.username || "").toLowerCase().includes(search.toLowerCase()) ||
      (c.notes || "").toLowerCase().includes(search.toLowerCase()) ||
      (c.client_name || "").toLowerCase().includes(search.toLowerCase());
    const matchType = filterType === "all" || c.credential_type === filterType;
    const matchClient = filterClient === "all" ||
      (filterClient === "__none__" ? !c.client_id : c.client_id === filterClient);
    return matchSearch && matchType && matchClient;
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40">
        <ArrowClockwise size={20} className="animate-spin text-[var(--text-muted)]" />
      </div>
    );
  }

  return (
    <div className={scopedClientId ? "space-y-4" : "space-y-4 p-4 max-w-7xl mx-auto"} data-testid="vault-page">
      {/* Header (hide if scoped to client) */}
      {!scopedClientId && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <Lock size={20} className="text-amber-400" />
            </div>
            <div>
              <h1 className="text-base font-bold text-[var(--text-primary)]">Vault Credenziali</h1>
              <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1">
                <ShieldCheck size={10} className="text-[var(--ok)]" /> Cifrate con AES-256-GCM | Solo admin
              </p>
            </div>
          </div>
          <Button onClick={() => { setEditCred(null); setForm({ device_ip: "", device_name: "", credential_type: "ilo", username: "", password: "", url: "", port: "", notes: "", tags: "", external_url: "", client_id: scopedClientId || "" }); setShowAdd(true); }} className="bg-amber-600 hover:bg-amber-700 text-white h-8 text-xs gap-1" data-testid="add-credential-btn">
            <Plus size={14} /> Aggiungi Credenziale
          </Button>
        </div>
      )}
      {scopedClientId && (
        <div className="flex items-center justify-between">
          <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1">
            <ShieldCheck size={10} className="text-[var(--ok)]" /> Credenziali del cliente — cifrate AES-256-GCM, visibili solo al suo Connector
          </p>
          <Button onClick={() => { setEditCred(null); setForm({ device_ip: "", device_name: "", credential_type: "ilo", username: "", password: "", url: "", port: "", notes: "", tags: "", external_url: "", client_id: scopedClientId }); setShowAdd(true); }} className="bg-amber-600 hover:bg-amber-700 text-white h-8 text-xs gap-1" data-testid="add-credential-btn">
            <Plus size={14} /> Aggiungi Credenziale
          </Button>
        </div>
      )}

      {/* Failover Status Panel */}
      {failoverStatus.length > 0 && (
        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="failover-panel">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Lightning size={14} className="text-teal-400" />
              <span className="text-xs font-medium text-[var(--text-primary)]">Stato Polling iLO Diretto / Failover</span>
            </div>
            <Button size="sm" variant="ghost" onClick={handleTriggerPoll} className="h-6 text-[10px] gap-1 text-teal-400" data-testid="trigger-poll-btn">
              <PlayCircle size={12} /> Polling Manuale
            </Button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {failoverStatus.map((fi, i) => {
              const modeConfig = {
                direct: { label: "Polling Diretto", color: "text-teal-400", border: "border-teal-500/30", bg: "bg-teal-500/5" },
                failover: { label: "Failover Attivo", color: "text-amber-400", border: "border-amber-500/30", bg: "bg-amber-500/5" },
                connector: { label: "Via Connector", color: "text-[var(--ok)]", border: "border-[var(--low-border)]", bg: "bg-[var(--low-bg)]" },
                offline: { label: "Non Monitorato", color: "text-[var(--critical)]", border: "border-[var(--critical-border)]", bg: "bg-[var(--critical-bg)]" },
              };
              const mc = modeConfig[fi.polling_mode] || modeConfig.offline;
              return (
                <div key={i} className={`p-2 rounded-md border ${mc.border} ${mc.bg} flex items-center justify-between`}>
                  <div>
                    <div className="text-[10px] font-medium text-[var(--text-primary)]">{fi.device_name || fi.device_ip}</div>
                    <div className="text-[9px] text-[var(--text-muted)] font-mono">{fi.device_ip}</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-[9px] font-bold ${mc.color}`}>{mc.label}</div>
                    {fi.external_url && <div className="text-[8px] text-[var(--text-muted)]">{fi.external_url}</div>}
                    {fi.connector_offline && !fi.external_url && (
                      <div className="text-[8px] text-[var(--critical)]">Configura URL esterna!</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-2 text-[8px] text-[var(--text-muted)]">
            Il SOC interroga direttamente le iLO quando il connettore e' offline (failover) o quando il polling diretto e' attivo. Richiede NAT/VPN per raggiungere l'iLO dall'esterno.
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cerca per IP, nome, utente, cliente..." className="pl-8 h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="vault-search" />
        </div>
        <div className="flex gap-1 flex-wrap">
          {[{ key: "all", label: "Tutti" }, ...Object.entries(typeConfig).map(([k, v]) => ({ key: k, label: v.label }))].map(t => (
            <button key={t.key} onClick={() => setFilterType(t.key)}
              className={`text-[9px] px-2 py-1 rounded-md border transition-colors ${filterType === t.key ? "bg-amber-500/10 border-amber-500/20 text-amber-400" : "bg-[var(--bg-hover)] border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`}
              data-testid={`filter-${t.key}`}
            >{t.label}</button>
          ))}
        </div>
        {!scopedClientId && clients.length > 0 && (
          <Select value={filterClient} onValueChange={setFilterClient}>
            <SelectTrigger className="h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)] w-48" data-testid="filter-client-select">
              <SelectValue placeholder="Cliente" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tutti i clienti</SelectItem>
              <SelectItem value="__none__">Solo Globali (nessun cliente)</SelectItem>
              {clients.map(c => (
                <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <span className="text-[10px] text-[var(--text-muted)] ml-auto">{filtered.length} credenziali</span>
      </div>

      {/* Credentials List */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Lock size={40} className="text-[var(--text-muted)] mb-3 opacity-30" />
          <p className="text-sm text-[var(--text-muted)]">{credentials.length === 0 ? "Nessuna credenziale salvata" : "Nessun risultato"}</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">Aggiungi le credenziali ILO, SSH, SNMP dei tuoi dispositivi</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map(cred => (
            <CredentialRow
              key={cred.id}
              cred={cred}
              onReveal={handleReveal}
              onEdit={handleEdit}
              onDelete={handleDelete}
              revealed={revealed[cred.id]}
              failoverInfo={failoverStatus.find(f => f.device_ip === cred.device_ip)}
              onToggleDirectPoll={handleToggleDirectPoll}
              onToggleConnectorOnly={handleToggleConnectorOnly}
              onTestConnection={handleTestConnection}
            />
          ))}
        </div>
      )}

      {/* Add/Edit Dialog */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <Lock size={18} className="text-amber-400" />
              {editCred ? "Modifica Credenziale" : "Nuova Credenziale"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Tipo</Label>
                <Select value={form.credential_type} onValueChange={v => setForm({ ...form, credential_type: v })}>
                  <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="cred-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(typeConfig).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{v.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">IP Dispositivo</Label>
                <Input value={form.device_ip} onChange={e => setForm({ ...form, device_ip: e.target.value })} placeholder="192.168.1.10" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="cred-device-ip" />
              </div>
            </div>
            {!scopedClientId && (
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Cliente</Label>
                <Select value={form.client_id || "__none__"} onValueChange={v => setForm({ ...form, client_id: v === "__none__" ? "" : v })}>
                  <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="cred-client-select">
                    <SelectValue placeholder="Seleziona cliente (opzionale)" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Nessuno (credenziale globale)</SelectItem>
                    {clients.map(c => (
                      <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[8px] text-[var(--text-muted)] mt-0.5">Le credenziali assegnate a un cliente sono visibili solo dal suo Connector.</p>
              </div>
            )}
            {scopedClientId && (
              <div className="p-2 rounded-md bg-indigo-500/10 border border-indigo-500/20 text-[10px] text-indigo-400">
                <ShieldCheck size={10} className="inline mr-1" /> Credenziale associata al cliente <b>{scopedClientName}</b>
              </div>
            )}
            <div>
              <Label className="text-[var(--text-muted)] text-[10px]">Nome Dispositivo</Label>
              <Input value={form.device_name} onChange={e => setForm({ ...form, device_name: e.target.value })} placeholder="ILO - SRV-DC01" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Username</Label>
                <Input value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} placeholder="Administrator" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="cred-username" />
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Password</Label>
                <Input type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} placeholder="••••••••" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="cred-password" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">URL Interna (opzionale)</Label>
                <Input value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="https://192.168.1.10" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">Porta (opzionale)</Label>
                <Input type="number" value={form.port} onChange={e => setForm({ ...form, port: e.target.value })} placeholder="443" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
              </div>
            </div>
            {form.credential_type === "ilo" && (
              <div className="p-2 rounded-lg bg-teal-500/5 border border-teal-500/20">
                <Label className="text-teal-400 text-[10px] flex items-center gap-1 mb-1"><Lightning size={10} /> URL Esterna iLO (per polling diretto / failover)</Label>
                <Input value={form.external_url} onChange={e => setForm({ ...form, external_url: e.target.value })} placeholder="https://ilo.azienda.com:443 oppure https://IP_PUBBLICO:porta" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" data-testid="cred-external-url" />
                <p className="text-[8px] text-teal-400/60 mt-1">Se configurata, il SOC puo' interrogare l'iLO direttamente anche col server spento (richiede NAT/VPN)</p>
              </div>
            )}
            <div>
              <Label className="text-[var(--text-muted)] text-[10px]">Note (opzionale)</Label>
              <Input value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Server sala CED, rack 3" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[var(--text-muted)] text-[10px]">Tag (separati da virgola)</Label>
              <Input value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} placeholder="ilo, datacenter, produzione" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs" />
            </div>
            <div className="flex items-center gap-1 text-[9px] text-[var(--text-muted)]">
              <ShieldCheck size={10} className="text-[var(--ok)]" />
              Le credenziali vengono cifrate con AES-256-GCM prima del salvataggio
            </div>
            <Button onClick={handleSave} className="w-full bg-amber-600 hover:bg-amber-700 text-white" data-testid="save-credential-btn">
              <Lock size={14} className="mr-1" /> {editCred ? "Aggiorna" : "Salva e Cifra"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
