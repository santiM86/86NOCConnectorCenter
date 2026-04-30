import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Database, ShieldCheck, ArrowsClockwise, Trash, Plug } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useNavigate } from "react-router-dom";

export default function HornetsecuritySettingsPage() {
  const navigate = useNavigate();
  const [config, setConfig] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [viewMode, setViewMode] = useState("by-tenant"); // "by-tenant" | "by-client"
  const [form, setForm] = useState({ api_url: "", api_key: "", poll_interval_minutes: 30, enabled: true });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [cfgRes, tenRes, cliRes] = await Promise.all([
        axios.get(`${API}/admin/hornetsecurity/global-config`),
        axios.get(`${API}/admin/hornetsecurity/tenants`).catch(() => ({ data: { tenants: [], mappings: [] } })),
        axios.get(`${API}/clients`).catch(() => ({ data: [] })),
      ]);
      setConfig(cfgRes.data);
      setTenants(tenRes.data.tenants || []);
      setMappings(tenRes.data.mappings || []);
      setClients(cliRes.data || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const saveConfig = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/admin/hornetsecurity/global-config`, form);
      toast.success("Configurazione salvata. Il primo polling avverrà entro un minuto.");
      setShowEdit(false);
      setForm({ ...form, api_key: "" });
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const testNow = async () => {
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/admin/hornetsecurity/test`);
      if (data.ok) toast.success(`Connessione OK — ${data.workloads_detected} workload, ${data.tenants_detected} tenant`);
      else toast.error(`Test fallito (HTTP ${data.http_status}): ${(data.raw_response_excerpt || "").slice(0, 200)}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore test");
    } finally {
      setBusy(false);
    }
  };

  const pollNow = async () => {
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/admin/hornetsecurity/poll`);
      toast.success(
        `Poll OK — ${data.workloads_total} workload (${data.workloads_failed} falliti, ${data.tenants_seen} tenant)`,
      );
      await reload();
    } catch (e) {
      const status = e?.response?.status;
      const det = e?.response?.data?.detail || e.message;
      if (status === 429) toast.warning(det); else toast.error(`Errore poll: ${det}`);
    } finally {
      setBusy(false);
    }
  };

  const removeConfig = async () => {
    if (!window.confirm("Eliminare la configurazione globale Hornetsecurity? I dati storici vengono mantenuti.")) return;
    try {
      await axios.delete(`${API}/admin/hornetsecurity/global-config`);
      toast.success("Configurazione rimossa");
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore");
    }
  };

  const updateMapping = async (clientId, newTenants) => {
    try {
      await axios.put(`${API}/clients/${clientId}/backup/hornetsecurity/mapping`, { tenants: newTenants });
      toast.success("Mapping aggiornato");
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore mapping");
    }
  };

  if (loading) return <div className="p-6 text-[var(--text-muted)] text-sm">Caricamento…</div>;

  const isConfigured = config?.configured;
  const tenantNamesSet = new Set(tenants.map(t => t.tenant));
  const mappedTenants = new Set();
  mappings.forEach(m => (m.tenants || []).forEach(t => mappedTenants.add(t)));
  const unmappedTenants = tenants.filter(t => !mappedTenants.has(t.tenant));

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4" data-testid="hornetsecurity-settings-page">
      <div className="flex items-center gap-3 mb-2">
        <button onClick={() => navigate(-1)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm">←</button>
        <Database size={20} className="text-cyan-400" />
        <h1 className="text-xl font-bold text-[var(--text-primary)]">Hornetsecurity 365 Backup</h1>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        Configurazione a livello Center (una sola API key per tutti i tenant).
        I dati ingestiti vengono filtrati per cliente tramite mapping <code>cliente ↔ tenant</code> sotto.
      </p>

      {/* Config card */}
      <div className="noc-panel p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Plug size={16} className="text-cyan-400" />
            <span className="text-sm font-bold">Connessione API</span>
            {isConfigured && config.enabled && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">ATTIVA</span>
            )}
            {isConfigured && !config.enabled && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">DISABILITATA</span>
            )}
            {!isConfigured && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--bg-border)]">NON CONFIGURATA</span>
            )}
          </div>
          <div className="flex gap-1.5">
            {isConfigured && (
              <>
                <Button size="sm" onClick={pollNow} disabled={busy} className="bg-cyan-600 hover:bg-cyan-700 h-7 text-[11px] gap-1" data-testid="poll-now-btn">
                  <ArrowsClockwise size={12} /> {busy ? "..." : "Poll Ora"}
                </Button>
                <Button size="sm" onClick={testNow} disabled={busy} className="bg-indigo-600 hover:bg-indigo-700 h-7 text-[11px]" data-testid="test-now-btn">Test</Button>
              </>
            )}
            <Button size="sm" onClick={() => { setForm({ api_url: config?.api_url || "", api_key: "", poll_interval_minutes: config?.poll_interval_minutes || 30, enabled: config?.enabled ?? true }); setShowEdit(true); }} variant="outline" className="h-7 text-[11px]" data-testid="edit-cfg-btn">
              {isConfigured ? "Modifica" : "Configura"}
            </Button>
            {isConfigured && (
              <Button size="sm" onClick={removeConfig} variant="outline" className="h-7 text-[11px] text-red-400 border-red-400/30" data-testid="delete-cfg-btn"><Trash size={11} /></Button>
            )}
          </div>
        </div>
        {isConfigured && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
            <div>
              <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">API URL</p>
              <p className="font-mono truncate" title={config.api_url}>{config.api_url}</p>
            </div>
            <div>
              <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">X-API-KEY</p>
              <p className="font-mono">{config.api_key_preview}</p>
            </div>
            <div>
              <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">Polling</p>
              <p>Ogni {config.poll_interval_minutes} minuti</p>
            </div>
            <div>
              <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">Ultimo poll</p>
              <p className={config.last_poll_status === "failed" ? "text-red-400" : ""}>
                {config.last_polled_at ? new Date(config.last_polled_at).toLocaleString("it-IT") : "Mai eseguito"}
                {config.last_poll_status === "failed" && <span className="block text-[9px]">{(config.last_poll_error || "").slice(0, 100)}</span>}
              </p>
            </div>
            {config.last_poll_summary && (
              <div className="md:col-span-2 grid grid-cols-2 md:grid-cols-5 gap-2 mt-1">
                <SmallStat label="Tenant" value={config.last_poll_summary.tenants_seen} />
                <SmallStat label="Workload" value={config.last_poll_summary.workloads_total} />
                <SmallStat label="OK" value={config.last_poll_summary.workloads_success} color="#34C759" />
                <SmallStat label="Failed" value={config.last_poll_summary.workloads_failed} color="#FF3B30" />
                <SmallStat label="In progress" value={config.last_poll_summary.workloads_in_progress} color="#FFB400" />
              </div>
            )}
          </div>
        )}
        {!isConfigured && (
          <p className="text-[11px] text-[var(--text-muted)]">
            Genera la API key dal Control Panel Hornetsecurity → 365 Total Backup → <strong>Alerts → Monitoring &amp; Alerts</strong> → tab Monitoring → Generate API Link. Whitelist l'IP di argus.86bit.it.
          </p>
        )}
      </div>

      {/* Mapping clienti ↔ tenant */}
      {isConfigured && tenants.length > 0 && (
        <div className="noc-panel p-4 space-y-3" data-testid="mapping-section">
          <div className="flex items-center gap-2 flex-wrap">
            <ShieldCheck size={16} className="text-emerald-400" />
            <span className="text-sm font-bold">Mapping clienti ↔ tenant Hornetsecurity</span>
            <span className="text-[10px] text-[var(--text-muted)]">{tenants.length} tenant · {mappedTenants.size} mappati · {unmappedTenants.length} liberi</span>
            <div className="ml-auto flex items-center gap-1 text-[10px]">
              <span className="text-[var(--text-muted)]">Vista:</span>
              <button
                onClick={() => setViewMode("by-tenant")}
                className={`px-2 py-0.5 rounded border ${viewMode === "by-tenant" ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
                data-testid="view-by-tenant"
              >Per tenant Hornetsecurity</button>
              <button
                onClick={() => setViewMode("by-client")}
                className={`px-2 py-0.5 rounded border ${viewMode === "by-client" ? "bg-emerald-500/20 border-emerald-400 text-emerald-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
                data-testid="view-by-client"
              >Per cliente ARGUS</button>
            </div>
          </div>
          <p className="text-[10px] text-[var(--text-muted)]">
            {viewMode === "by-tenant"
              ? "Per ciascun tenant Hornetsecurity scegli a quale cliente ARGUS appartiene. Modalita` consigliata quando vuoi mappare velocemente molti tenant."
              : "Per ciascun cliente ARGUS scegli quali tenant Hornetsecurity gli appartengono. Un cliente puo` avere piu` tenant (multi-dominio)."}
          </p>
          {viewMode === "by-tenant" ? (
            <TenantMappingTable tenants={tenants} clients={clients} mappings={mappings} updateMapping={updateMapping} />
          ) : (
            <ClientMappingTable clients={clients} tenants={tenants} updateMapping={updateMapping} />
          )}
        </div>
      )}

      {/* Edit dialog */}
      {showEdit && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => setShowEdit(false)}>
          <div className="bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded-lg p-5 max-w-lg w-full space-y-3" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold flex items-center gap-2"><Database size={14} className="text-cyan-400" /> Configura Hornetsecurity</h3>
            <p className="text-[10px] text-[var(--text-muted)]">
              cp.hornetsecurity.com → 365 Total Backup → Alerts → Monitoring &amp; Alerts → tab Monitoring → Generate API Link. Whitelist IP del Center.
            </p>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">API URL</label>
              <Input value={form.api_url} onChange={e => setForm({ ...form, api_url: e.target.value })} placeholder="https://eu-public.backup.hornetsecurity.com/..." className="bg-[var(--bg-card)] h-8 text-xs font-mono" data-testid="cfg-url" />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">X-API-KEY {config?.api_key_preview && <span className="text-[9px] ml-1">(attuale: {config.api_key_preview} — lascia vuoto per non cambiarla)</span>}</label>
              <Input type="password" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder="A3DA-XXXX-XXXX" className="bg-[var(--bg-card)] h-8 text-xs font-mono" data-testid="cfg-key" />
            </div>
            <div className="flex gap-3 items-end">
              <div className="flex-1">
                <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Polling (min)</label>
                <Input type="number" min={5} max={720} value={form.poll_interval_minutes} onChange={e => setForm({ ...form, poll_interval_minutes: parseInt(e.target.value) || 30 })} className="bg-[var(--bg-card)] h-8 text-xs" data-testid="cfg-interval" />
              </div>
              <label className="flex items-center gap-1.5 text-[11px] cursor-pointer pb-1.5">
                <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} data-testid="cfg-enabled" />
                <span>Abilitato</span>
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowEdit(false)} disabled={saving}>Annulla</Button>
              <Button onClick={saveConfig} disabled={saving || !form.api_url || (!isConfigured && !form.api_key)} className="bg-cyan-600 hover:bg-cyan-700" data-testid="cfg-save">
                {saving ? "Salvataggio..." : "Salva"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TenantMappingTable({ tenants, clients, mappings, updateMapping }) {
  // Build reverse map: tenant -> client_id (assumendo 1 tenant a 1 cliente principale, ma supportiamo piu` clienti per tenant via lista)
  const tenantToClient = {};
  mappings.forEach(m => {
    (m.tenants || []).forEach(t => {
      if (!tenantToClient[t]) tenantToClient[t] = [];
      tenantToClient[t].push({ id: m.client_id, name: m.client_name });
    });
  });

  const [filter, setFilter] = useState("all"); // all | mapped | unmapped | failed
  const filteredTenants = tenants.filter(t => {
    if (filter === "mapped") return tenantToClient[t.tenant]?.length > 0;
    if (filter === "unmapped") return !tenantToClient[t.tenant]?.length;
    if (filter === "failed") return (t.workloads_failed || 0) > 0;
    return true;
  });

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-[10px]">
        <span className="text-[var(--text-muted)]">Filtra:</span>
        {[
          { id: "all", label: `Tutti (${tenants.length})` },
          { id: "unmapped", label: `Da mappare (${tenants.filter(t => !tenantToClient[t.tenant]?.length).length})` },
          { id: "mapped", label: `Mappati (${tenants.filter(t => tenantToClient[t.tenant]?.length).length})` },
          { id: "failed", label: `Con backup falliti (${tenants.filter(t => (t.workloads_failed || 0) > 0).length})` },
        ].map(f => (
          <button key={f.id} onClick={() => setFilter(f.id)}
            className={`px-2 py-0.5 rounded border ${filter === f.id ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
            data-testid={`filter-${f.id}`}>
            {f.label}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="noc-table w-full text-[11px]">
          <thead>
            <tr>
              <th>Tenant Hornetsecurity</th>
              <th>Workload</th>
              <th>Falliti</th>
              <th>Cliente ARGUS</th>
              <th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            {filteredTenants.map(t => (
              <TenantMappingRow key={t.tenant} tenant={t} clients={clients} currentClients={tenantToClient[t.tenant] || []} updateMapping={updateMapping} mappings={mappings} />
            ))}
          </tbody>
        </table>
        {filteredTenants.length === 0 && (
          <div className="text-center py-3 text-[var(--text-muted)] text-[11px]">Nessun tenant corrispondente al filtro</div>
        )}
      </div>
    </div>
  );
}

function TenantMappingRow({ tenant, clients, currentClients, updateMapping, mappings }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentClients[0]?.id || "");
  const [saving, setSaving] = useState(false);

  // suggerimento auto: cliente con nome simile al tenant
  const tn = tenant.tenant.toLowerCase().replace(/[^a-z0-9]/g, "");
  const tnLong = (tenant.tenant_long || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const suggested = clients.find(c => {
    const cn = (c.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    if (!cn) return false;
    return cn === tn || tn.includes(cn) || cn.includes(tn) ||
           (tnLong && (cn === tnLong || tnLong.includes(cn) || cn.includes(tnLong)));
  });

  const startEdit = () => {
    setDraft(currentClients[0]?.id || suggested?.id || "");
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      // Rimuovi questo tenant da TUTTI i clienti che ce l'avevano
      for (const c of currentClients) {
        if (c.id !== draft) {
          const cm = mappings.find(m => m.client_id === c.id);
          const newTenants = (cm?.tenants || []).filter(x => x !== tenant.tenant);
          await updateMapping(c.id, newTenants);
        }
      }
      // Aggiungi al nuovo cliente (se selezionato)
      if (draft) {
        const cm = mappings.find(m => m.client_id === draft);
        const existing = cm?.tenants || [];
        if (!existing.includes(tenant.tenant)) {
          await updateMapping(draft, [...existing, tenant.tenant]);
        }
      }
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    setSaving(true);
    try {
      for (const c of currentClients) {
        const cm = mappings.find(m => m.client_id === c.id);
        const newTenants = (cm?.tenants || []).filter(x => x !== tenant.tenant);
        await updateMapping(c.id, newTenants);
      }
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const failedCol = (tenant.workloads_failed || 0) > 0 ? "#FF3B30" : "var(--text-muted)";

  return (
    <tr data-testid={`tenant-row-${tenant.tenant}`}>
      <td>
        <div className="font-semibold">{tenant.tenant}</div>
        {tenant.tenant_long && tenant.tenant_long !== tenant.tenant && (
          <div className="text-[9px] text-[var(--text-muted)] font-mono">{tenant.tenant_long}</div>
        )}
      </td>
      <td className="text-[10px] font-mono">{tenant.workloads_total || 0}</td>
      <td className="text-[10px] font-mono font-bold" style={{ color: failedCol }}>{tenant.workloads_failed || 0}</td>
      <td>
        {editing ? (
          <select
            value={draft}
            onChange={e => setDraft(e.target.value)}
            className="text-[11px] bg-[var(--bg-card)] border border-[var(--bg-border)] rounded px-1 py-0.5 w-full"
            data-testid={`tenant-select-${tenant.tenant}`}
            autoFocus
          >
            <option value="">— Nessun cliente —</option>
            {clients
              .slice()
              .sort((a, b) => {
                if (suggested && a.id === suggested.id) return -1;
                if (suggested && b.id === suggested.id) return 1;
                return (a.name || "").localeCompare(b.name || "");
              })
              .map(c => (
                <option key={c.id} value={c.id}>
                  {suggested && c.id === suggested.id ? "★ " : ""}{c.name}
                </option>
              ))}
          </select>
        ) : currentClients.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {currentClients.map(c => (
              <span key={c.id} className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                {c.name}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-[10px] text-[var(--text-muted)] italic">
            — non mappato —{suggested && <span className="ml-1 text-amber-300">suggerimento: {suggested.name}</span>}
          </span>
        )}
      </td>
      <td>
        {editing ? (
          <div className="flex gap-1">
            <Button size="sm" onClick={save} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700 h-6 text-[10px]" data-testid={`save-tenant-${tenant.tenant}`}>
              {saving ? "..." : "Salva"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving} className="h-6 text-[10px]">Annulla</Button>
          </div>
        ) : (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={startEdit} data-testid={`edit-tenant-${tenant.tenant}`}>
              {currentClients.length > 0 ? "Modifica" : "Associa"}
            </Button>
            {currentClients.length > 0 && (
              <Button size="sm" variant="outline" onClick={remove} disabled={saving} className="h-6 text-[10px] text-red-400 border-red-400/30" data-testid={`remove-tenant-${tenant.tenant}`}>
                <Trash size={10} />
              </Button>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}

function ClientMappingTable({ clients, tenants, updateMapping }) {
  const tenantOptions = tenants.map(t => t.tenant).sort();
  return (
    <div className="overflow-x-auto">
      <table className="noc-table w-full text-[11px]">
        <thead>
          <tr><th>Cliente ARGUS</th><th>Tenant Hornetsecurity associati</th><th>Azioni</th></tr>
        </thead>
        <tbody>
          {clients.map(c => (
            <ClientMappingRow key={c.id} client={c} tenantOptions={tenantOptions} tenantStats={tenants} updateMapping={updateMapping} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClientMappingRow({ client, tenantOptions, tenantStats, updateMapping }) {
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState(null);
  const [draftSelection, setDraftSelection] = useState([]);

  const loadCurrent = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/clients/${client.id}/backup/hornetsecurity/mapping`);
      setSelected(r.data?.tenants || []);
    } catch { setSelected([]); }
  }, [client.id]);

  useEffect(() => { loadCurrent(); }, [loadCurrent]);

  const startEdit = () => { setDraftSelection([...(selected || [])]); setEditing(true); };
  const toggleTenant = (t) => setDraftSelection(s => s.includes(t) ? s.filter(x => x !== t) : [...s, t]);
  const save = async () => { await updateMapping(client.id, draftSelection); setSelected(draftSelection); setEditing(false); };

  // Auto-suggestion: tenant con nome simile al cliente
  const suggestions = tenantOptions.filter(t => {
    const ln = (client.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const tn = t.toLowerCase().replace(/[^a-z0-9]/g, "");
    return ln && tn && (ln.includes(tn) || tn.includes(ln));
  });

  if (selected === null) return <tr><td colSpan={3} className="text-[var(--text-muted)] text-[10px]">…</td></tr>;

  if (editing) {
    return (
      <tr>
        <td className="font-semibold">{client.name}</td>
        <td colSpan={2}>
          <div className="flex flex-wrap gap-1 mb-2">
            {tenantOptions.map(t => {
              const sel = draftSelection.includes(t);
              const stats = tenantStats.find(x => x.tenant === t) || {};
              const isSug = suggestions.includes(t);
              return (
                <button key={t} onClick={() => toggleTenant(t)}
                  className={`text-[10px] px-1.5 py-0.5 rounded border ${sel ? "bg-cyan-500/20 border-cyan-400 text-cyan-300" : isSug ? "border-amber-500/40 text-amber-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
                  data-testid={`tenant-toggle-${t}`} title={`${stats.workloads_total || 0} workload`}>
                  {t}{stats.workloads_failed ? ` ⚠${stats.workloads_failed}` : ""}
                </button>
              );
            })}
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" onClick={save} className="bg-emerald-600 hover:bg-emerald-700 h-6 text-[10px]" data-testid={`save-mapping-${client.id}`}>Salva</Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)} className="h-6 text-[10px]">Annulla</Button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td className="font-semibold">{client.name}</td>
      <td>
        {selected.length === 0 ? (
          <span className="text-[10px] text-[var(--text-muted)]">— nessun tenant — {suggestions.length > 0 && <span className="text-amber-300">suggerimento: {suggestions.slice(0, 2).join(", ")}</span>}</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {selected.map(t => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">{t}</span>
            ))}
          </div>
        )}
      </td>
      <td>
        <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={startEdit} data-testid={`edit-mapping-${client.id}`}>Modifica</Button>
      </td>
    </tr>
  );
}

function SmallStat({ label, value, color }) {
  return (
    <div className="rounded bg-[var(--bg-card)] border border-[var(--bg-border)] px-2 py-1.5">
      <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
      <p className="text-base font-bold font-mono leading-none mt-0.5" style={{ color: color || "var(--text-primary)" }}>{value}</p>
    </div>
  );
}
