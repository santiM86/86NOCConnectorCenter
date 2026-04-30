import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Database, ShieldCheck, ArrowsClockwise, Trash, Plug, CaretDown, CaretRight, Users } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useNavigate } from "react-router-dom";

export default function HornetsecuritySettingsPage() {
  const navigate = useNavigate();
  const [provider, setProvider] = useState("m365"); // "m365" | "vm"
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

  // Helper centrale per modificare l'assegnazione di un singolo (tenant, sub_group):
  // - newClientId: cliente target (vuoto = rimuove l'assegnazione)
  // Mantiene intatti tutti gli altri mapping e i mapping "whole_tenant" altrui.
  const updateSubGroupMapping = async (tenantName, subGroup, newClientId) => {
    try {
      // 1) Rimuovi questo (tenant, sub_group) da TUTTI i clienti che lo avevano
      for (const m of mappings) {
        const filters = m.filters || [];
        const had = filters.some(f => f.tenant === tenantName && Array.isArray(f.sub_groups) && f.sub_groups.includes(subGroup));
        if (!had) continue;
        const newFilters = filters
          .map(f => {
            if (f.tenant !== tenantName) return f;
            if (!Array.isArray(f.sub_groups)) return f;
            const cleaned = f.sub_groups.filter(x => x !== subGroup);
            if (cleaned.length === 0) return null;
            return { tenant: f.tenant, sub_groups: cleaned };
          })
          .filter(Boolean);
        // ricostruisci payload (string per whole tenant, dict per sub-group)
        const payload = newFilters.map(f => (f.sub_groups ? { tenant: f.tenant, sub_groups: f.sub_groups } : f.tenant));
        await axios.put(`${API}/clients/${m.client_id}/backup/hornetsecurity/mapping`, { tenants: payload });
      }
      // 2) Aggiungi al nuovo cliente (se selezionato)
      if (newClientId) {
        const cm = mappings.find(m => m.client_id === newClientId);
        const filters = (cm && cm.filters) || [];
        // Se il cliente ha gia` tutto il tenant come whole, non serve aggiungere il sub_group
        const hasWhole = filters.some(f => f.tenant === tenantName && !f.sub_groups);
        if (!hasWhole) {
          let found = false;
          const newFilters = filters.map(f => {
            if (f.tenant === tenantName && Array.isArray(f.sub_groups)) {
              found = true;
              return { tenant: f.tenant, sub_groups: Array.from(new Set([...(f.sub_groups || []), subGroup])) };
            }
            return f;
          });
          if (!found) newFilters.push({ tenant: tenantName, sub_groups: [subGroup] });
          const payload = newFilters.map(f => (f.sub_groups ? { tenant: f.tenant, sub_groups: f.sub_groups } : f.tenant));
          await axios.put(`${API}/clients/${newClientId}/backup/hornetsecurity/mapping`, { tenants: payload });
        }
      }
      toast.success(`Sotto-gruppo "${subGroup}" aggiornato`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore mapping sub-group");
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
        <h1 className="text-xl font-bold text-[var(--text-primary)]">Hornetsecurity Backup</h1>
      </div>

      {/* Provider tabs */}
      <div className="flex items-center gap-1.5 flex-wrap text-[11px] border-b border-[var(--bg-border)] pb-2">
        <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Provider:</span>
        <button
          onClick={() => setProvider("m365")}
          className={`px-3 py-1 rounded-md border text-[11px] font-semibold transition ${
            provider === "m365"
              ? "bg-cyan-500/20 border-cyan-400 text-cyan-300"
              : "border-cyan-500/30 text-cyan-300/70 hover:bg-cyan-500/10"
          }`}
          data-testid="settings-provider-m365"
        >
          365 Total Backup
        </button>
        <button
          onClick={() => setProvider("vm")}
          className={`px-3 py-1 rounded-md border text-[11px] font-semibold transition ${
            provider === "vm"
              ? "bg-violet-500/20 border-violet-400 text-violet-300"
              : "border-violet-500/30 text-violet-300/70 hover:bg-violet-500/10"
          }`}
          data-testid="settings-provider-vm"
        >
          VM Backup (Altaro)
        </button>
      </div>

      {provider === "vm" ? (
        <VMBackupSettingsSection clients={clients} />
      ) : (
      <>
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
            <TenantMappingTable tenants={tenants} clients={clients} mappings={mappings} updateMapping={updateMapping} updateSubGroupMapping={updateSubGroupMapping} />
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
      </>
      )}
    </div>
  );
}

/* ==================== VM BACKUP SETTINGS SECTION ==================== */
function VMBackupSettingsSection({ clients }) {
  const [config, setConfig] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [filter, setFilter] = useState("all"); // all | unmapped | mapped | problems
  const [form, setForm] = useState({
    api_url: "https://portal.86bit.it/api/v1/reports/altaro/getHornetSecurityReport",
    api_key: "", user_id: "", polling_interval_minutes: 10, enabled: true,
  });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [cfgR, custR] = await Promise.all([
        axios.get(`${API}/admin/hornetsecurity-vm/config`),
        axios.get(`${API}/admin/hornetsecurity-vm/customers`).catch(() => ({ data: { customers: [], mappings: [] } })),
      ]);
      setConfig(cfgR.data);
      setCustomers(custR.data?.customers || []);
      setMappings(custR.data?.mappings || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento VM Backup config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const saveConfig = async () => {
    setSaving(true);
    try {
      const payload = { ...form };
      if (!payload.api_key && config?.configured) {
        toast.error("Inserisci la chiave API (non mostrata per sicurezza)");
        setSaving(false);
        return;
      }
      await axios.put(`${API}/admin/hornetsecurity-vm/config`, payload);
      toast.success("Configurazione salvata. Primo polling entro un minuto.");
      setShowEdit(false);
      setForm(f => ({ ...f, api_key: "" }));
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const pollNow = async () => {
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/admin/hornetsecurity-vm/poll-now`);
      if (data?.error) {
        toast.error(`Poll fallito: ${data.error}`);
      } else {
        toast.success(
          `Poll OK — ${data.vms || 0} VM (${data.failed || 0} failed, ${data.warning || 0} warn, ${data.stale || 0} stale) su ${data.customers || 0} customer`,
        );
      }
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore poll");
    } finally {
      setBusy(false);
    }
  };

  const syncAll = async () => {
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/admin/hornetsecurity-vm/sync-all-alerts`);
      toast.success(`Sync alert completato: ${data.alerts_synced || 0} alert su ${data.clients_touched || 0} clienti`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore sync");
    } finally {
      setBusy(false);
    }
  };

  const removeConfig = async () => {
    if (!window.confirm("Rimuovere la configurazione VM Backup? I dati gia` ingestiti restano nel DB.")) return;
    try {
      await axios.delete(`${API}/admin/hornetsecurity-vm/config`);
      toast.success("Configurazione rimossa");
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore");
    }
  };

  const updateCustomerMapping = async (clientId, newCustomers) => {
    try {
      const r = await axios.put(`${API}/clients/${clientId}/backup/vmbackup/mapping`, { customers: newCustomers });
      toast.success(`Mapping aggiornato (${r.data?.alerts_synced ?? 0} alert sincronizzati)`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore mapping");
    }
  };

  // Helper: modifica l'assegnazione di un singolo (customer, host) mantenendo
  // intatti gli altri mapping. Se `newClientId` e` vuoto: rimuove l'assegnazione.
  const updateHostMapping = async (customerName, hostName, newClientId) => {
    try {
      // 1) Rimuovi questo (customer, host) da TUTTI i clienti che lo avevano
      for (const m of mappings) {
        const filters = m.filters || [];
        const had = filters.some(f => f.customer === customerName && Array.isArray(f.hosts) && f.hosts.includes(hostName));
        if (!had) continue;
        const newFilters = filters
          .map(f => {
            if (f.customer !== customerName) return f;
            if (!Array.isArray(f.hosts)) return f;
            const cleaned = f.hosts.filter(h => h !== hostName);
            if (cleaned.length === 0) return null;
            return { customer: f.customer, hosts: cleaned };
          })
          .filter(Boolean);
        const payload = newFilters.map(f => (f.hosts ? { customer: f.customer, hosts: f.hosts } : f.customer));
        await axios.put(`${API}/clients/${m.client_id}/backup/vmbackup/mapping`, { customers: payload });
      }
      // 2) Aggiungi al nuovo cliente
      if (newClientId) {
        const cm = mappings.find(m => m.client_id === newClientId);
        const filters = (cm && cm.filters) || [];
        const hasWhole = filters.some(f => f.customer === customerName && !f.hosts);
        if (!hasWhole) {
          let found = false;
          const newFilters = filters.map(f => {
            if (f.customer === customerName && Array.isArray(f.hosts)) {
              found = true;
              return { customer: f.customer, hosts: Array.from(new Set([...(f.hosts || []), hostName])) };
            }
            return f;
          });
          if (!found) newFilters.push({ customer: customerName, hosts: [hostName] });
          const payload = newFilters.map(f => (f.hosts ? { customer: f.customer, hosts: f.hosts } : f.customer));
          await axios.put(`${API}/clients/${newClientId}/backup/vmbackup/mapping`, { customers: payload });
        }
      }
      toast.success(`Host "${hostName}" aggiornato`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore mapping host");
    }
  };

  if (loading) return <div className="p-4 text-[var(--text-muted)] text-sm">Caricamento…</div>;

  const isConfigured = !!config?.configured;

  // Reverse map: customer → clients
  const customerToClients = {};
  mappings.forEach(m => {
    (m.customers || []).forEach(c => {
      if (!customerToClients[c]) customerToClients[c] = [];
      customerToClients[c].push({ id: m.client_id, name: m.client_name });
    });
  });

  const filteredCustomers = customers.filter(c => {
    if (filter === "unmapped") return !(customerToClients[c.customer_name]?.length);
    if (filter === "mapped") return (customerToClients[c.customer_name]?.length || 0) > 0;
    if (filter === "problems") return (c.vms_failed || 0) > 0 || (c.vms_warning || 0) > 0 || (c.vms_stale || 0) > 0;
    return true;
  });

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-[var(--text-muted)]">
        Integrazione <strong>Altaro VM Backup</strong> (Hyper-V / VMware). Config a livello Center: una sola chiamata API copre
        tutti i customer. I dati ingestiti sono filtrati per cliente tramite il mapping <code>cliente ↔ customerName</code>.
      </p>

      {/* Config card */}
      <div className="noc-panel p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Plug size={16} className="text-violet-400" />
            <span className="text-sm font-bold">Connessione API portal MSP</span>
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
                <Button size="sm" onClick={pollNow} disabled={busy} className="bg-violet-600 hover:bg-violet-700 h-7 text-[11px] gap-1" data-testid="vm-poll-now-btn">
                  <ArrowsClockwise size={12} /> {busy ? "..." : "Poll Ora"}
                </Button>
                <Button size="sm" onClick={syncAll} disabled={busy} variant="outline" className="h-7 text-[11px]" data-testid="vm-sync-all-btn">Sync Alert</Button>
              </>
            )}
            <Button size="sm" onClick={() => {
              setForm({
                api_url: config?.api_url || "https://portal.86bit.it/api/v1/reports/altaro/getHornetSecurityReport",
                api_key: "", user_id: config?.user_id || "",
                polling_interval_minutes: config?.polling_interval_minutes || 10,
                enabled: config?.enabled ?? true,
              });
              setShowEdit(true);
            }} variant="outline" className="h-7 text-[11px]" data-testid="vm-edit-cfg-btn">
              {isConfigured ? "Modifica" : "Configura"}
            </Button>
            {isConfigured && (
              <Button size="sm" onClick={removeConfig} variant="outline" className="h-7 text-[11px] text-red-400 border-red-400/30" data-testid="vm-delete-cfg-btn"><Trash size={11} /></Button>
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
              <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">User ID</p>
              <p className="font-mono">{config.user_id}</p>
            </div>
            <div>
              <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">API Key</p>
              <p className="font-mono">{config.api_key_masked}</p>
            </div>
            <div>
              <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">Intervallo polling</p>
              <p className="font-mono">{config.polling_interval_minutes} min</p>
            </div>
            {config.last_polled_at && (
              <div className="md:col-span-2">
                <p className="text-[9px] uppercase text-[var(--text-muted)] tracking-wide">Ultimo polling</p>
                <p className="font-mono">
                  {new Date(config.last_polled_at).toLocaleString("it-IT")}
                  {config.last_poll_status === "success" && <span className="ml-2 text-emerald-400">✓ success</span>}
                  {config.last_poll_status === "failed" && <span className="ml-2 text-red-400">✗ {config.last_poll_error}</span>}
                </p>
                {config.last_poll_summary && (
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    {config.last_poll_summary.customers || 0} customer · {config.last_poll_summary.vms || 0} VM ·{" "}
                    <span className="text-red-400">{config.last_poll_summary.failed || 0} failed</span> ·{" "}
                    <span className="text-amber-400">{config.last_poll_summary.warning || 0} warn</span> ·{" "}
                    <span className="text-orange-300">{config.last_poll_summary.stale || 0} stale</span>
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {showEdit && (
        <div className="noc-panel p-4 space-y-3 border border-violet-400/40">
          <p className="text-[11px] font-bold text-violet-300">
            {isConfigured ? "Modifica configurazione VM Backup" : "Nuova configurazione VM Backup"}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] block mb-1">API URL</label>
              <Input value={form.api_url} onChange={e => setForm({ ...form, api_url: e.target.value })} placeholder="https://portal.../getHornetSecurityReport" className="font-mono text-[11px]" data-testid="vm-cfg-url" />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] block mb-1">User ID</label>
              <Input value={form.user_id} onChange={e => setForm({ ...form, user_id: e.target.value })} placeholder="5ec7affa..." className="font-mono text-[11px]" data-testid="vm-cfg-userid" />
            </div>
            <div className="md:col-span-2">
              <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] block mb-1">
                API Key {isConfigured && <span className="text-[9px] text-[var(--text-muted)]">(lascia vuoto per non cambiarla, oppure inserisci la nuova)</span>}
              </label>
              <Input type="password" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder={isConfigured ? "••••••••••••" : "la tua chiave API"} className="font-mono text-[11px]" data-testid="vm-cfg-key" />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] block mb-1">Intervallo polling (min)</label>
              <Input type="number" min={5} max={120} value={form.polling_interval_minutes} onChange={e => setForm({ ...form, polling_interval_minutes: parseInt(e.target.value) || 10 })} className="font-mono text-[11px]" data-testid="vm-cfg-interval" />
            </div>
            <label className="flex items-center gap-1.5 text-[11px] cursor-pointer pb-1.5">
              <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} data-testid="vm-cfg-enabled" />
              <span>Abilitato</span>
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowEdit(false)} disabled={saving}>Annulla</Button>
            <Button onClick={saveConfig} disabled={saving || !form.api_url || !form.user_id || (!isConfigured && !form.api_key)} className="bg-violet-600 hover:bg-violet-700" data-testid="vm-cfg-save">
              {saving ? "Salvataggio..." : "Salva"}
            </Button>
          </div>
        </div>
      )}

      {/* Customers mapping table */}
      {isConfigured && customers.length === 0 ? (
        <div className="noc-panel p-5 text-center text-[11px] text-[var(--text-muted)]">
          Nessun customer ancora ingerito. Clicca "Poll Ora" per scaricare i dati dal portal MSP.
        </div>
      ) : isConfigured && (
        <div className="noc-panel p-3 space-y-2">
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="text-[var(--text-muted)]">Filtra:</span>
            {[
              { id: "all", label: `Tutti (${customers.length})` },
              { id: "unmapped", label: `Da mappare (${customers.filter(c => !customerToClients[c.customer_name]?.length).length})` },
              { id: "mapped", label: `Mappati (${customers.filter(c => customerToClients[c.customer_name]?.length).length})` },
              { id: "problems", label: `Con problemi (${customers.filter(c => (c.vms_failed || 0) > 0 || (c.vms_warning || 0) > 0 || (c.vms_stale || 0) > 0).length})` },
            ].map(f => (
              <button key={f.id} onClick={() => setFilter(f.id)}
                className={`px-2 py-0.5 rounded border ${filter === f.id ? "bg-violet-500/20 border-violet-400 text-violet-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
                data-testid={`vm-filter-${f.id}`}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="noc-table w-full text-[11px]">
              <thead>
                <tr>
                  <th style={{ width: 24 }}></th>
                  <th>Customer Hornetsecurity VM</th>
                  <th>VM</th>
                  <th>Hosts</th>
                  <th>Failed</th>
                  <th>Stale</th>
                  <th>Cliente ARGUS</th>
                  <th>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {filteredCustomers.map(c => (
                  <VMCustomerRow
                    key={c.customer_name}
                    customer={c}
                    clients={clients}
                    mappings={mappings}
                    currentClients={customerToClients[c.customer_name] || []}
                    updateMapping={updateCustomerMapping}
                    updateHostMapping={updateHostMapping}
                  />
                ))}
              </tbody>
            </table>
            {filteredCustomers.length === 0 && (
              <div className="text-center py-3 text-[var(--text-muted)] text-[11px]">Nessun customer corrispondente al filtro</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function VMCustomerRow({ customer, clients, mappings, currentClients, updateMapping, updateHostMapping }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentClients[0]?.id || "");
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [hosts, setHosts] = useState(null);
  const [loadingHosts, setLoadingHosts] = useState(false);

  // Auto-suggestion: cliente con nome simile al customer
  const cn = customer.customer_name.toLowerCase().replace(/\.(it|com|net|eu|onmicrosoft\.com)$/, "").replace(/[^a-z0-9]/g, "");
  const suggested = cn ? clients.find(cl => {
    const nn = (cl.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    return nn && (nn === cn || nn.includes(cn) || cn.includes(nn));
  }) : null;

  const loadHosts = useCallback(async () => {
    setLoadingHosts(true);
    try {
      const r = await axios.get(`${API}/admin/hornetsecurity-vm/customers/${encodeURIComponent(customer.customer_name)}/hosts`);
      setHosts(r.data?.hosts || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento host");
      setHosts([]);
    } finally {
      setLoadingHosts(false);
    }
  }, [customer.customer_name]);

  const toggleExpand = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && hosts === null) await loadHosts();
  };

  const onHostChanged = async (hostName, newClientId) => {
    await updateHostMapping(customer.customer_name, hostName, newClientId);
    await loadHosts();
  };

  const start = () => {
    setDraft(currentClients[0]?.id || suggested?.id || "");
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      for (const m of mappings) {
        if ((m.customers || []).includes(customer.customer_name) && m.client_id !== draft) {
          const newList = (m.customers || []).filter(x => x !== customer.customer_name);
          await axios.put(`${API}/clients/${m.client_id}/backup/vmbackup/mapping`, { customers: newList });
        }
      }
      if (draft) {
        const targetMapping = mappings.find(m => m.client_id === draft);
        const existing = new Set(targetMapping?.customers || []);
        existing.add(customer.customer_name);
        await updateMapping(draft, Array.from(existing));
      } else {
        toast.success("Customer rimosso dal mapping");
      }
      setEditing(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!currentClients[0]) return;
    setSaving(true);
    try {
      const m = mappings.find(x => x.client_id === currentClients[0].id);
      const newList = (m?.customers || []).filter(x => x !== customer.customer_name);
      await updateMapping(currentClients[0].id, newList);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const failedCol = (customer.vms_failed || 0) > 0 ? "#FF3B30" : "var(--text-muted)";
  const staleCol = (customer.vms_stale || 0) > 0 ? "#FF9500" : "var(--text-muted)";
  const hostsCount = customer.hosts_count || 0;

  return (
    <>
    <tr data-testid={`vm-customer-row-${customer.customer_name}`}>
      <td className="text-center">
        <button onClick={toggleExpand} className="text-[var(--text-muted)] hover:text-cyan-300 p-0.5" data-testid={`expand-vm-customer-${customer.customer_name}`} title="Espandi host del customer">
          {expanded ? <CaretDown size={12} /> : <CaretRight size={12} />}
        </button>
      </td>
      <td>
        <div className="font-semibold">{customer.customer_name}</div>
        <div className="text-[9px] text-[var(--text-muted)]">
          {customer.installations_count} install · {customer.hosts_count} host
        </div>
      </td>
      <td className="text-[10px] font-mono">{customer.vms_total || 0}</td>
      <td className="text-[10px] font-mono">
        {hostsCount > 1 ? (
          <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30" title="Customer con piu` host: mappabili singolarmente">
            {hostsCount} <Users size={9} className="inline" />
          </span>
        ) : (
          <span className="text-[var(--text-muted)]">{hostsCount}</span>
        )}
      </td>
      <td className="text-[10px] font-mono font-bold" style={{ color: failedCol }}>{customer.vms_failed || 0}</td>
      <td className="text-[10px] font-mono font-bold" style={{ color: staleCol }}>{customer.vms_stale || 0}</td>
      <td>
        {currentClients.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {currentClients.map(c => (
              <span key={c.id} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">{c.name}</span>
            ))}
          </div>
        ) : (
          <span className="text-[10px] text-[var(--text-muted)] italic">
            — non mappato —
            {suggested && <span className="ml-1 text-amber-300">★ {suggested.name}</span>}
          </span>
        )}
      </td>
      <td>
        {editing ? (
          <div className="flex items-center gap-1">
            <select
              value={draft}
              onChange={e => setDraft(e.target.value)}
              className="text-[10px] bg-[var(--bg-card)] border border-[var(--bg-border)] rounded px-1 py-0.5 max-w-[160px]"
              data-testid={`vm-select-${customer.customer_name}`}
              autoFocus
            >
              <option value="">— Nessuno —</option>
              {clients.slice().sort((a, b) => {
                if (suggested && a.id === suggested.id) return -1;
                if (suggested && b.id === suggested.id) return 1;
                return (a.name || "").localeCompare(b.name || "");
              }).map(c => (
                <option key={c.id} value={c.id}>
                  {suggested && c.id === suggested.id ? "★ " : ""}{c.name}
                </option>
              ))}
            </select>
            <Button size="sm" onClick={save} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700 h-6 text-[10px] px-2" data-testid={`vm-save-${customer.customer_name}`}>
              {saving ? "..." : "OK"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving} className="h-6 text-[10px] px-1.5">X</Button>
          </div>
        ) : (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={start} data-testid={`vm-edit-${customer.customer_name}`}>
              {currentClients.length > 0 ? "Cambia" : "Assegna"}
            </Button>
            {currentClients.length > 0 && (
              <Button size="sm" variant="outline" onClick={remove} disabled={saving} className="h-6 text-[10px] text-red-400 border-red-400/30" data-testid={`vm-remove-${customer.customer_name}`}>
                <Trash size={10} />
              </Button>
            )}
          </div>
        )}
      </td>
    </tr>
    {expanded && (
      <tr data-testid={`vm-hosts-row-${customer.customer_name}`}>
        <td></td>
        <td colSpan={7} className="bg-[var(--bg-card)]/40 px-2 py-2">
          <HostsPanel
            customerName={customer.customer_name}
            hosts={hosts}
            loading={loadingHosts}
            clients={clients}
            wholeCustomerClients={currentClients}
            onChange={onHostChanged}
          />
        </td>
      </tr>
    )}
    </>
  );
}

function HostsPanel({ customerName, hosts, loading, clients, wholeCustomerClients, onChange }) {
  if (loading || hosts === null) {
    return <div className="text-[10px] text-[var(--text-muted)] py-1">Caricamento host…</div>;
  }
  if (!hosts || hosts.length === 0) {
    return <div className="text-[10px] text-[var(--text-muted)] py-1">Nessun host rilevato</div>;
  }
  const whole = wholeCustomerClients[0];
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
        <Users size={11} className="text-amber-300" />
        <span>
          <strong className="text-[var(--text-primary)]">Host fisici (Hyper-V/VMware)</strong> di <em>{customerName}</em>.
          {whole && (
            <span className="ml-1 text-amber-300">
              Customer intero gia` mappato a <strong>{whole.name}</strong> — gli host sono ereditati ma puoi sovrascriverli.
            </span>
          )}
        </span>
      </div>
      <table className="noc-table w-full text-[10.5px]">
        <thead>
          <tr>
            <th>Host</th>
            <th>Hypervisor</th>
            <th>VM</th>
            <th>Failed</th>
            <th>Stale</th>
            <th>Cliente assegnato</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {hosts.map(h => (
            <HostRow key={h.host_name} customerName={customerName} host={h} clients={clients} onChange={onChange} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HostRow({ customerName, host, clients, onChange }) {
  const explicitMapped = (host.mapped_clients || []).filter(c => c.via !== "whole_customer");
  const inheritedMapped = (host.mapped_clients || []).filter(c => c.via === "whole_customer");
  const currentClientId = explicitMapped[0]?.client_id || "";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentClientId);
  const [saving, setSaving] = useState(false);

  // Auto-suggestion: match per nome host (es. GALVANSRV → cliente "Galvan")
  const hn = (host.host_name || "").toLowerCase().replace(/srv\d*$|server$|host\d*$/i, "").replace(/[^a-z0-9]/g, "");
  const suggested = hn ? clients.find(cl => {
    const nn = (cl.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    return nn && (nn === hn || nn.includes(hn) || hn.includes(nn));
  }) : null;

  const start = () => {
    setDraft(currentClientId || suggested?.id || "");
    setEditing(true);
  };
  const save = async () => {
    setSaving(true);
    try {
      await onChange(host.host_name, draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    setSaving(true);
    try {
      await onChange(host.host_name, "");
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr data-testid={`vm-host-row-${customerName}-${host.host_name}`}>
      <td className="font-mono text-[10px] font-semibold">{host.host_name}</td>
      <td className="text-[9.5px] text-[var(--text-muted)]">{host.host_type}</td>
      <td className="font-mono text-[10px]">{host.vms_total}</td>
      <td className="font-mono text-[10px]" style={{ color: host.vms_failed > 0 ? "#FF3B30" : "var(--text-muted)" }}>{host.vms_failed}</td>
      <td className="font-mono text-[10px]" style={{ color: host.vms_stale > 0 ? "#FF9500" : "var(--text-muted)" }}>{host.vms_stale}</td>
      <td>
        {editing ? (
          <select
            value={draft}
            onChange={e => setDraft(e.target.value)}
            className="text-[10px] bg-[var(--bg-card)] border border-[var(--bg-border)] rounded px-1 py-0.5 w-full"
            data-testid={`vm-host-select-${customerName}-${host.host_name}`}
            autoFocus
          >
            <option value="">— Nessuno —</option>
            {clients.slice().sort((a, b) => {
              if (suggested && a.id === suggested.id) return -1;
              if (suggested && b.id === suggested.id) return 1;
              return (a.name || "").localeCompare(b.name || "");
            }).map(c => (
              <option key={c.id} value={c.id}>
                {suggested && c.id === suggested.id ? "★ " : ""}{c.name}
              </option>
            ))}
          </select>
        ) : explicitMapped.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {explicitMapped.map(c => (
              <span key={c.client_id} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                {c.client_name}
              </span>
            ))}
          </div>
        ) : inheritedMapped.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {inheritedMapped.map(c => (
              <span key={c.client_id} className="text-[9.5px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-200 border border-cyan-500/20" title="Ereditato dal mapping intero del customer">
                {c.client_name} <span className="text-[8px]">(ereditato)</span>
              </span>
            ))}
          </div>
        ) : (
          <span className="text-[10px] text-[var(--text-muted)] italic">
            — non mappato —{suggested && <span className="ml-1 text-amber-300">★ {suggested.name}</span>}
          </span>
        )}
      </td>
      <td>
        {editing ? (
          <div className="flex gap-1">
            <Button size="sm" onClick={save} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700 h-5 text-[9px] px-1.5" data-testid={`vm-host-save-${customerName}-${host.host_name}`}>
              {saving ? "..." : "OK"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving} className="h-5 text-[9px] px-1.5">X</Button>
          </div>
        ) : (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" className="h-5 text-[9px] px-1.5" onClick={start} data-testid={`vm-host-edit-${customerName}-${host.host_name}`}>
              {explicitMapped.length > 0 ? "Cambia" : "Assegna"}
            </Button>
            {explicitMapped.length > 0 && (
              <Button size="sm" variant="outline" onClick={remove} disabled={saving} className="h-5 text-[9px] px-1.5 text-red-400 border-red-400/30" data-testid={`vm-host-remove-${customerName}-${host.host_name}`}>
                <Trash size={9} />
              </Button>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}

function TenantMappingTable({ tenants, clients, mappings, updateMapping, updateSubGroupMapping }) {
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
              <th style={{ width: 24 }}></th>
              <th>Tenant Hornetsecurity</th>
              <th>Workload</th>
              <th>Sotto-gruppi</th>
              <th>Falliti</th>
              <th>Cliente ARGUS</th>
              <th>Azioni</th>
            </tr>
          </thead>
          <tbody>
            {filteredTenants.map(t => (
              <TenantMappingRow key={t.tenant} tenant={t} clients={clients} currentClients={tenantToClient[t.tenant] || []} updateMapping={updateMapping} updateSubGroupMapping={updateSubGroupMapping} mappings={mappings} />
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

function TenantMappingRow({ tenant, clients, currentClients, updateMapping, updateSubGroupMapping, mappings }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentClients[0]?.id || "");
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [subGroups, setSubGroups] = useState(null);
  const [loadingSg, setLoadingSg] = useState(false);

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

  const loadSubGroups = useCallback(async () => {
    setLoadingSg(true);
    try {
      const r = await axios.get(`${API}/admin/hornetsecurity/tenants/${encodeURIComponent(tenant.tenant)}/sub-groups`);
      setSubGroups(r.data?.sub_groups || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento sotto-gruppi");
      setSubGroups([]);
    } finally {
      setLoadingSg(false);
    }
  }, [tenant.tenant]);

  const toggleExpand = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && subGroups === null) await loadSubGroups();
  };

  const onSubGroupChanged = async (subGroup, newClientId) => {
    await updateSubGroupMapping(tenant.tenant, subGroup, newClientId);
    await loadSubGroups();
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
  const sgCount = tenant.sub_groups_count ?? 0;

  return (
    <>
    <tr data-testid={`tenant-row-${tenant.tenant}`}>
      <td className="text-center">
        <button onClick={toggleExpand} className="text-[var(--text-muted)] hover:text-cyan-300 p-0.5" data-testid={`expand-tenant-${tenant.tenant}`} title="Espandi sotto-gruppi (domini)">
          {expanded ? <CaretDown size={12} /> : <CaretRight size={12} />}
        </button>
      </td>
      <td>
        <div className="font-semibold">{tenant.tenant}</div>
        {tenant.tenant_long && tenant.tenant_long !== tenant.tenant && (
          <div className="text-[9px] text-[var(--text-muted)] font-mono">{tenant.tenant_long}</div>
        )}
      </td>
      <td className="text-[10px] font-mono">{tenant.workloads_total || 0}</td>
      <td className="text-[10px] font-mono">
        {sgCount > 1 ? (
          <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30" title="Tenant con piu` sotto-gruppi (domini): puoi mappare ciascun sotto-gruppo a un cliente diverso">
            {sgCount} <Users size={9} className="inline" />
          </span>
        ) : (
          <span className="text-[var(--text-muted)]">{sgCount}</span>
        )}
      </td>
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
    {expanded && (
      <tr data-testid={`subgroups-row-${tenant.tenant}`}>
        <td></td>
        <td colSpan={6} className="bg-[var(--bg-card)]/40 px-2 py-2">
          <SubGroupsPanel
            tenantName={tenant.tenant}
            subGroups={subGroups}
            loading={loadingSg}
            clients={clients}
            wholeTenantClients={currentClients}
            onChange={onSubGroupChanged}
          />
        </td>
      </tr>
    )}
    </>
  );
}

function SubGroupsPanel({ tenantName, subGroups, loading, clients, wholeTenantClients, onChange }) {
  if (loading || subGroups === null) {
    return <div className="text-[10px] text-[var(--text-muted)] py-1">Caricamento sotto-gruppi…</div>;
  }
  if (!subGroups || subGroups.length === 0) {
    return <div className="text-[10px] text-[var(--text-muted)] py-1">Nessun sotto-gruppo rilevato</div>;
  }
  const wholeOwner = wholeTenantClients[0];
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
        <Users size={11} className="text-amber-300" />
        <span>
          <strong className="text-[var(--text-primary)]">Sotto-gruppi (domini email)</strong> di <em>{tenantName}</em>.
          {wholeOwner && (
            <span className="ml-1 text-amber-300">
              Tenant intero gia` mappato a <strong>{wholeOwner.name}</strong> — i sotto-gruppi sono ereditati ma puoi sovrascriverli.
            </span>
          )}
        </span>
      </div>
      <table className="noc-table w-full text-[10.5px]">
        <thead>
          <tr>
            <th>Sotto-gruppo</th>
            <th>Workload</th>
            <th>Falliti</th>
            <th>Tipi</th>
            <th>Cliente assegnato</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {subGroups.map(sg => (
            <SubGroupRow key={sg.sub_group} tenantName={tenantName} sg={sg} clients={clients} onChange={onChange} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SubGroupRow({ tenantName, sg, clients, onChange }) {
  const explicitMapped = (sg.mapped_clients || []).filter(c => c.via !== "whole_tenant");
  const inheritedMapped = (sg.mapped_clients || []).filter(c => c.via === "whole_tenant");
  const currentClientId = explicitMapped[0]?.client_id || "";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentClientId);
  const [saving, setSaving] = useState(false);

  // Auto-suggestion: cerca un cliente il cui nome matcha il dominio (es. "Galvan" ↔ "galvan.it")
  const dom = (sg.sub_group || "").toLowerCase();
  const domBase = dom.replace(/\.(it|com|net|org|onmicrosoft\.com|cloud)$/, "").replace(/[^a-z0-9]/g, "");
  const suggested = !sg.is_ungrouped && domBase ? clients.find(c => {
    const cn = (c.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    return cn && (cn === domBase || cn.includes(domBase) || domBase.includes(cn));
  }) : null;

  const start = () => {
    setDraft(currentClientId || suggested?.id || "");
    setEditing(true);
  };
  const save = async () => {
    setSaving(true);
    try {
      await onChange(sg.sub_group, draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    setSaving(true);
    try {
      await onChange(sg.sub_group, "");
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr data-testid={`subgroup-row-${tenantName}-${sg.sub_group}`}>
      <td className="font-mono text-[10px]">
        {sg.is_ungrouped ? <span className="italic text-[var(--text-muted)]">Senza dominio</span> : sg.sub_group}
      </td>
      <td className="font-mono text-[10px]">{sg.workloads_total}</td>
      <td className="font-mono text-[10px]" style={{ color: sg.workloads_failed > 0 ? "#FF3B30" : "var(--text-muted)" }}>{sg.workloads_failed}</td>
      <td className="text-[9.5px] text-[var(--text-muted)]">
        {(sg.types || []).slice(0, 4).join(", ")}{(sg.types || []).length > 4 ? "…" : ""}
      </td>
      <td>
        {editing ? (
          <select
            value={draft}
            onChange={e => setDraft(e.target.value)}
            className="text-[10px] bg-[var(--bg-card)] border border-[var(--bg-border)] rounded px-1 py-0.5 w-full"
            data-testid={`subgroup-select-${tenantName}-${sg.sub_group}`}
            autoFocus
          >
            <option value="">— Nessuno —</option>
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
        ) : explicitMapped.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {explicitMapped.map(c => (
              <span key={c.client_id} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                {c.client_name}
              </span>
            ))}
          </div>
        ) : inheritedMapped.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {inheritedMapped.map(c => (
              <span key={c.client_id} className="text-[9.5px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-200 border border-cyan-500/20" title="Ereditato dal mapping intero del tenant">
                {c.client_name} <span className="text-[8px]">(ereditato)</span>
              </span>
            ))}
          </div>
        ) : (
          <span className="text-[10px] text-[var(--text-muted)] italic">
            — non mappato —{suggested && <span className="ml-1 text-amber-300">★ {suggested.name}</span>}
          </span>
        )}
      </td>
      <td>
        {editing ? (
          <div className="flex gap-1">
            <Button size="sm" onClick={save} disabled={saving} className="bg-emerald-600 hover:bg-emerald-700 h-5 text-[9px] px-1.5" data-testid={`save-subgroup-${tenantName}-${sg.sub_group}`}>
              {saving ? "..." : "OK"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving} className="h-5 text-[9px] px-1.5">X</Button>
          </div>
        ) : (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" className="h-5 text-[9px] px-1.5" onClick={start} data-testid={`edit-subgroup-${tenantName}-${sg.sub_group}`}>
              {explicitMapped.length > 0 ? "Cambia" : "Assegna"}
            </Button>
            {explicitMapped.length > 0 && (
              <Button size="sm" variant="outline" onClick={remove} disabled={saving} className="h-5 text-[9px] px-1.5 text-red-400 border-red-400/30" data-testid={`remove-subgroup-${tenantName}-${sg.sub_group}`}>
                <Trash size={9} />
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
