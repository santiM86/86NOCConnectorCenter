import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArrowLeft, ShieldCheck, Trash, Plug, Sparkle, ArrowsClockwise } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function DattoRmmSettingsPage() {
  const navigate = useNavigate();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [config, setConfig] = useState(null);
  const [form, setForm] = useState({ api_key: "", user_id: "", base_url: "" });
  const [sites, setSites] = useState([]);
  const [links, setLinks] = useState([]);
  const [clients, setClients] = useState([]);
  const [schedStatus, setSchedStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [c, s, cl, sched] = await Promise.all([
        axios.get(`${API}/api/admin/datto/config`, { headers }),
        axios.get(`${API}/api/datto/sites`, { headers }).catch(() => ({ data: { items: [] } })),
        axios.get(`${API}/api/clients`, { headers }).catch(() => ({ data: [] })),
        axios.get(`${API}/api/datto/scheduler-status`, { headers }).catch(() => ({ data: null })),
      ]);
      setConfig(c.data);
      setSites(s.data.items || []);
      setSchedStatus(sched.data);
      const cls = Array.isArray(cl.data) ? cl.data : (cl.data.clients || []);
      setClients(cls);
      // Carica link per ogni client (parallelo)
      const linkResults = await Promise.all(cls.map((cli) =>
        axios.get(`${API}/api/clients/${cli.id}/datto/link`, { headers }).then((r) => ({ ...r.data, _client: cli })).catch(() => null),
      ));
      setLinks(linkResults.filter(Boolean));
      if (c.data.configured) {
        setForm({ api_key: "", user_id: c.data.user_id || "", base_url: c.data.base_url || "" });
      }
    } catch (e) {
      toast.error("Errore caricamento config Datto");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const save = async () => {
    if (!form.api_key || form.api_key.length < 8) {
      toast.error("API key obbligatoria (min 8 caratteri)");
      return;
    }
    if (!form.user_id) {
      toast.error("User ID obbligatorio");
      return;
    }
    setSaving(true);
    try {
      await axios.put(`${API}/api/admin/datto/config`, {
        api_key: form.api_key, user_id: form.user_id,
        base_url: form.base_url || undefined,
      }, { headers });
      toast.success("Configurazione Datto salvata (API key cifrata)");
      setForm({ ...form, api_key: "" });
      await reload();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const r = await axios.post(`${API}/api/admin/datto/test`, {}, { headers });
      toast.success(`Connessione OK: ${r.data.sites_found} site Datto, ${r.data.sites.reduce((a, s) => a + s.device_count, 0)} device totali`);
      await reload();
    } catch (e) {
      toast.error(`Test fallito: ${e.response?.data?.detail || e.message}`);
    } finally {
      setTesting(false);
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await axios.post(`${API}/api/datto/sync-now`, {}, { headers });
      toast.success(`Sync OK: ${r.data.sites} site, ${r.data.linked_clients} client linkati, ${r.data.matched_endpoints} endpoint matchati`);
      await reload();
    } catch (e) {
      toast.error(`Sync fallito: ${e.response?.data?.detail || e.message}`);
    } finally {
      setSyncing(false);
    }
  };

  const removeConfig = async () => {
    if (!window.confirm("Rimuovere la configurazione Datto RMM? Tutti i link client e i device sincronizzati saranno rimossi.")) return;
    try {
      await axios.delete(`${API}/api/admin/datto/config`, { headers });
      toast.success("Configurazione Datto rimossa");
      setForm({ api_key: "", user_id: "", base_url: "" });
      await reload();
    } catch (e) {
      toast.error("Errore rimozione");
    }
  };

  const linkClient = async (clientId, siteId) => {
    if (!siteId) {
      // Unlink
      try {
        await axios.delete(`${API}/api/clients/${clientId}/datto/link`, { headers });
        toast.success("Link rimosso");
        await reload();
      } catch (e) { toast.error("Errore unlink"); }
      return;
    }
    try {
      const r = await axios.put(`${API}/api/clients/${clientId}/datto/link`, { site_id: siteId }, { headers });
      toast.success(`Cliente linkato: ${r.data.device_count} device, sync immediato avviato`);
      await reload();
    } catch (e) {
      toast.error(`Errore link: ${e.response?.data?.detail || e.message}`);
    }
  };

  if (loading) {
    return <div className="p-6 text-[var(--text-secondary)]">Caricamento…</div>;
  }

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4" data-testid="datto-settings-page">
      <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="mb-2 text-xs">
        <ArrowLeft size={14} className="mr-1" /> Indietro
      </Button>

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5">
        <div className="flex items-center gap-2 mb-3">
          <Plug size={18} className="text-cyan-400" />
          <h2 className="text-base font-bold">Datto RMM API</h2>
          {config?.configured && (
            <span className="ml-2 px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-[10px] font-bold">
              CONFIGURATA · {config.api_key_preview}
            </span>
          )}
        </div>
        <p className="text-[11px] text-[var(--text-secondary)] mb-3">
          Endpoint custom esposto da <span className="font-mono">portal.86bit.it</span>. Riceveremo lista clienti +
          dispositivi (nome, MAC, IP, OS). I device verranno automaticamente matchati con le entry FDB degli switch
          per evitare "Dispositivo sconosciuto" sulle porte.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <Label className="text-[10px] uppercase tracking-wider">API Key</Label>
            <Input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              placeholder={config?.configured ? `(salvata: ${config.api_key_preview})` : "Es. f34ASDF2SADF2344..."}
              className="mt-1 h-9 text-xs font-mono"
              data-testid="datto-api-key-input"
            />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-wider">User ID</Label>
            <Input
              type="text"
              value={form.user_id}
              onChange={(e) => setForm({ ...form, user_id: e.target.value })}
              placeholder="Es. 5ec7affa4cdcd40b443d5c38"
              className="mt-1 h-9 text-xs font-mono"
              data-testid="datto-user-id-input"
            />
          </div>
          <div className="md:col-span-2">
            <Label className="text-[10px] uppercase tracking-wider">Base URL (opzionale)</Label>
            <Input
              type="text"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              placeholder="https://portal.86bit.it/api/v1/reports/datto/getDattoDevices"
              className="mt-1 h-9 text-xs font-mono"
              data-testid="datto-base-url-input"
            />
          </div>
        </div>
        <div className="flex items-center gap-2 pt-3 mt-3 border-t border-[var(--bg-border)]">
          <Button size="sm" onClick={save} disabled={saving} className="text-xs h-8" data-testid="datto-save-btn">
            <ShieldCheck size={14} className="mr-1" /> {saving ? "Salvataggio…" : "Salva (cifrata)"}
          </Button>
          {config?.configured && (
            <>
              <Button size="sm" variant="outline" onClick={test} disabled={testing} className="text-xs h-8" data-testid="datto-test-btn">
                <Sparkle size={14} className="mr-1" /> {testing ? "Test…" : "Test connessione"}
              </Button>
              <Button size="sm" variant="outline" onClick={sync} disabled={syncing} className="text-xs h-8" data-testid="datto-sync-btn">
                <ArrowsClockwise size={14} className="mr-1" /> {syncing ? "Sync…" : "Sync ora"}
              </Button>
              <Button size="sm" variant="outline" onClick={removeConfig} className="text-xs h-8 text-red-400 ml-auto" data-testid="datto-remove-btn">
                <Trash size={14} className="mr-1" /> Rimuovi
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Linking matrix */}
      {config?.configured && schedStatus && (
        <div className="rounded-xl border border-fuchsia-500/30 bg-fuchsia-500/5 p-3 flex items-center gap-3">
          <ArrowsClockwise size={18} className="text-fuchsia-300" />
          <div className="flex-1 text-[11px]">
            <div className="text-fuchsia-200 font-semibold">Auto-sync attivo (ogni 6h)</div>
            <div className="text-[var(--text-secondary)]">
              Ultimo refresh: {schedStatus.last_refresh_at ? new Date(schedStatus.last_refresh_at).toLocaleString("it-IT") : "mai"}
              {" · "}
              Prossimo: {schedStatus.next_scheduled_at ? new Date(schedStatus.next_scheduled_at).toLocaleString("it-IT") : "—"}
              {" · "}
              {schedStatus.sites_in_cache} site, {schedStatus.linked_clients} cliente linkato, {schedStatus.synced_devices} device sincronizzati
            </div>
          </div>
        </div>
      )}

      {config?.configured && (
        <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold">Mappatura Cliente Center ↔ Site Datto</h3>
            <span className="text-[10px] text-[var(--text-muted)]">
              {sites.length} site disponibili · {clients.length} client locali
            </span>
          </div>
          {clients.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)] italic">Nessun cliente nel Center.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-[10px] uppercase text-[var(--text-secondary)] border-b border-[var(--bg-border)]">
                  <tr>
                    <th className="text-left py-2 px-2">Cliente Center</th>
                    <th className="text-left py-2 px-2">Site Datto</th>
                    <th className="text-right py-2 px-2">Device sync</th>
                    <th className="text-right py-2 px-2">Matched</th>
                    <th className="text-right py-2 px-2">Ultimo sync</th>
                  </tr>
                </thead>
                <tbody>
                  {clients.map((cli) => {
                    const link = links.find((l) => l._client?.id === cli.id);
                    return (
                      <tr key={cli.id} className="border-b border-[var(--bg-border)]/50 hover:bg-[var(--bg-hover)]/30" data-testid={`datto-client-row-${cli.id}`}>
                        <td className="py-2 px-2 font-medium">{cli.name}</td>
                        <td className="py-2 px-2">
                          <select
                            value={link?.site_id || ""}
                            onChange={(e) => linkClient(cli.id, e.target.value)}
                            className="h-7 px-2 text-xs rounded border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
                            style={{ colorScheme: "dark" }}
                            data-testid={`datto-site-select-${cli.id}`}
                          >
                            <option value="" style={{ backgroundColor: "#0f1115", color: "#e5e7eb" }}>— Non linkato —</option>
                            {sites.map((s) => (
                              <option
                                key={s.site_id}
                                value={s.site_id}
                                style={{ backgroundColor: "#0f1115", color: "#e5e7eb" }}
                              >
                                {s.site_name} ({s.device_count})
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2 px-2 text-right font-mono">{link?.device_count ?? "—"}</td>
                        <td className="py-2 px-2 text-right">
                          {link?.matched_count != null && link.device_count ? (
                            <span className="text-emerald-300 font-mono">
                              {link.matched_count}/{link.device_count}
                            </span>
                          ) : "—"}
                        </td>
                        <td className="py-2 px-2 text-right text-[10px] text-[var(--text-muted)]">
                          {link?.last_sync_at ? new Date(link.last_sync_at).toLocaleString("it-IT") : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[10px] text-[var(--text-muted)] italic mt-3">
            💡 Quando linki un cliente, viene fatto immediatamente un sync. Ogni device Datto con MAC o IP che corrisponde
            ad un MAC visto nelle FDB degli switch verra' usato per nominare quel device sulle porte (badge violetto "DATTO" in Vista Cavo).
          </p>
        </div>
      )}
    </div>
  );
}
