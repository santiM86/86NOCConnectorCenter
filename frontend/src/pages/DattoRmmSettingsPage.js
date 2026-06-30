import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArrowLeft, ShieldCheck, Trash, Plug, Sparkle, ArrowsClockwise, Stethoscope, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import DattoBrowser from "@/components/DattoBrowser";
import ErrorBoundary from "@/components/ErrorBoundary";

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
  const [diag, setDiag] = useState(null);
  const [loadingDiag, setLoadingDiag] = useState(false);

  const runDiagnostics = useCallback(async () => {
    setLoadingDiag(true);
    try {
      const r = await axios.get(`${API}/api/datto/diagnostics`, { headers });
      setDiag(r.data);
    } catch (e) {
      toast.error(`Diagnostica fallita: ${e.response?.data?.detail || e.message}`);
    } finally {
      setLoadingDiag(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // v2026-06-02: tool per risolvere il caso "Galvan/Zitac 0 device sync".
  // Pulizia link orfani + force re-sync per singolo client + diagnosi.
  const cleanupOrphans = async () => {
    if (!window.confirm("Eliminare i link Datto a clienti non più esistenti (mostrati come '(eliminato?)')?")) return;
    try {
      const r = await axios.post(`${API}/api/admin/datto/cleanup-orphan-links`, {}, { headers });
      toast.success(`✅ ${r.data.removed_links} link orfani eliminati, ${r.data.removed_devices} datto_devices puliti`);
      await runDiagnostics();
    } catch (e) {
      toast.error(`Cleanup fallito: ${e.response?.data?.detail || e.message}`);
    }
  };

  const debugClient = async (clientId, clientName) => {
    try {
      const r = await axios.get(`${API}/api/admin/datto/client-debug/${clientId}`, { headers });
      const d = r.data;
      const msg = `${clientName}: ${d.diagnosis}\n\n` +
        `Link site: ${d.link?.site_name || "—"} (${d.link?.site_id?.slice(0, 8)}...)\n` +
        `In DB: ${d.datto_devices_in_db} dev (${d.matched_in_db} matched)\n` +
        `Live Datto: ${d.live_devices_for_linked_site} dev` +
        (d.sites_with_same_name_but_different_id?.length
          ? `\n\n⚠️ ${d.sites_with_same_name_but_different_id.length} altri site Datto con stesso nome ma site_id diverso — RILINKA via dropdown!` : "");
      window.alert(msg);
    } catch (e) {
      toast.error(`Debug fallito: ${e.response?.data?.detail || e.message}`);
    }
  };

  const forceSyncClient = async (clientId, clientName) => {
    if (!window.confirm(`Forzare re-sync Datto per ${clientName}?\n(Esegue un refresh globale, può richiedere ~15s)`)) return;
    const tId = toast.loading(`Re-sync ${clientName} in corso…`);
    try {
      const r = await axios.post(`${API}/api/admin/datto/sync-client/${clientId}`, {}, { headers });
      toast.success(`✅ ${clientName}: ${r.data.devices_count} device, ${r.data.matched_count} match`, { id: tId, duration: 6000 });
      await runDiagnostics();
    } catch (e) {
      toast.error(`Re-sync fallito: ${e.response?.data?.detail || e.message}`, { id: tId });
    }
  };

  // v2026-06-29: Match Debug — diagnostica specifica per il caso
  // "N device persisted ma 0 match con discovered_endpoints".
  // Chiama /api/admin/datto/match-debug/{client_id} e mostra in alert
  // la causa esatta (A/B/C/D/E) con sample MAC/IP per debug visivo.
  const matchDebugClient = async (clientId, clientName) => {
    try {
      const r = await axios.get(`${API}/api/admin/datto/match-debug/${clientId}`, { headers });
      const d = r.data;
      const sampleDatto = (d.sample_datto_with_mac || []).map(x =>
        `  • ${x.name}  MAC=${x.mac || "(no MAC)"} IP=${x.ip || "—"}`
      ).join("\n");
      const sampleEps = (d.sample_eps_with_mac || []).map(x =>
        `  • MAC=${x.mac} IP=${x.ip || "—"} sw=${x.switch_ip || "?"}:${x.port || "?"}`
      ).join("\n");
      const sampleNoMac = (d.sample_datto_no_mac || []).slice(0, 5).join(", ");

      const msg =
        `🔎 Match Debug — ${clientName}\n\n` +
        `${d.diagnosis}\n\n` +
        `📊 Numeri:\n` +
        `  Datto persisted    : ${d.datto_devices_persisted}\n` +
        `  Datto con MAC      : ${d.datto_devices_with_mac}\n` +
        `  Datto senza MAC    : ${d.datto_devices_without_mac}\n` +
        `  Datto con IP       : ${d.datto_devices_with_ip}\n` +
        `  Discovered eps     : ${d.discovered_endpoints_total}\n` +
        `  Eps con MAC        : ${d.discovered_endpoints_with_mac}\n` +
        `  Eps con IP         : ${d.discovered_endpoints_with_ip}\n` +
        `  Intersezione MAC   : ${d.intersection_mac}\n` +
        `  Intersezione IP    : ${d.intersection_ip}\n` +
        (sampleDatto ? `\n📦 Sample Datto:\n${sampleDatto}\n` : "") +
        (sampleEps ? `\n🔌 Sample Endpoints:\n${sampleEps}\n` : "") +
        (sampleNoMac ? `\n⚠️ Datto senza MAC (audit endpoint vuoto): ${sampleNoMac}\n` : "");
      window.alert(msg);
    } catch (e) {
      toast.error(`Match Debug fallito: ${e.response?.data?.detail || e.message}`);
    }
  };

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
      // v2026-06-02: endpoint resiliente — non lancia piu' 500, ritorna
      // {ok:true, ...} o {ok:false, stage_failed, error_type, error, hint}
      if (r.data.ok === false) {
        const stage = r.data.stage_failed || "?";
        const errType = r.data.error_type || "Error";
        const hint = r.data.hint || "";
        toast.error(
          `Test fallito @ ${stage} [${errType}]: ${hint}\nDettaglio: ${r.data.error?.slice(0, 200)}`,
          { duration: 12000 }
        );
        return;
      }
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
            <p className="text-[10px] text-[var(--text-muted)] mt-1 leading-tight">
              ObjectId Mongo del portal (24 hex). <span className="text-red-400">NON</span> l&apos;email.
            </p>
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
            <p className="text-[10px] text-[var(--text-muted)] mt-1 leading-tight">
              Solo l&apos;endpoint, <span className="text-red-400">SENZA</span> <code className="text-amber-400">?api_key=...&amp;userId=...</code> — i parametri li aggiunge il backend automaticamente.
              Endpoint corretto: <code className="text-cyan-400">/api/v1/reports/datto/getDattoDevices</code> (lista devices), non <code>getDattoSites</code>.
            </p>
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
              <Button size="sm" variant="outline" onClick={runDiagnostics} disabled={loadingDiag} className="text-xs h-8 border-cyan-500/40 hover:bg-cyan-500/10 text-cyan-300" data-testid="datto-diag-btn">
                <Stethoscope size={14} className="mr-1" /> {loadingDiag ? "Analisi…" : "Diagnostica"}
              </Button>
              <Button size="sm" variant="outline" onClick={removeConfig} className="text-xs h-8 text-red-400 ml-auto" data-testid="datto-remove-btn">
                <Trash size={14} className="mr-1" /> Rimuovi
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Diagnostica risultati */}
      {diag && (
        <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-3" data-testid="datto-diag-card">
          <div className="flex items-center gap-2">
            <Stethoscope size={16} className="text-cyan-300" weight="bold" />
            <h3 className="text-sm font-bold text-cyan-200">Diagnostica integrazione Datto RMM</h3>
            <span className={`ml-auto text-[10px] px-2 py-0.5 rounded-full font-bold ${diag.healthy ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-300"}`} data-testid="datto-diag-health">
              {diag.healthy ? "HEALTHY" : "ATTENZIONE"}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {diag.checks.map((c, i) => (
              <div key={i} className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-2.5">
                <div className="flex items-center gap-2">
                  {c.ok ? <CheckCircle size={14} className="text-emerald-400" weight="bold" /> : <WarningCircle size={14} className="text-amber-400" weight="bold" />}
                  <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{c.step.replace(/^\d+_/, "").replace(/_/g, " ")}</span>
                </div>
                <p className="text-[11px] text-[var(--text-primary)] mt-1">{c.detail}</p>
                {c.sites_in_cache !== undefined && <div className="text-[10px] mt-1 font-mono text-cyan-300">{c.sites_in_cache} site</div>}
                {c.linked_clients !== undefined && <div className="text-[10px] mt-1 font-mono text-cyan-300">{c.linked_clients} client linkati</div>}
                {c.total_in_db !== undefined && <div className="text-[10px] mt-1 font-mono text-cyan-300">{c.total_in_db} device</div>}
              </div>
            ))}
          </div>
          {diag.links_summary && diag.links_summary.length > 0 && (
            <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-2.5">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Stato per cliente</div>
                {diag.links_summary.some(l => (l.client_name || "").toLowerCase().includes("eliminato")) && (
                  <Button
                    data-testid="datto-cleanup-orphans-btn"
                    size="sm"
                    variant="outline"
                    onClick={cleanupOrphans}
                    className="h-6 text-[10px] border-red-500/40 text-red-300 hover:bg-red-500/10"
                  >
                    <Trash size={10} className="mr-1" />
                    Pulisci link orfani
                  </Button>
                )}
              </div>
              <div className="space-y-1">
                {diag.links_summary.map((l, i) => {
                  const isOrphan = (l.client_name || "").toLowerCase().includes("eliminato");
                  const noSyncOrZeroMatch = l.persisted_in_db === 0 || l.matched_count === 0;
                  return (
                    <div key={i} className="flex items-center justify-between text-[11px] py-1 border-b border-[var(--bg-border)]/40 last:border-0" data-testid={`datto-diag-link-${i}`}>
                      <span className={`font-bold ${isOrphan ? "text-red-300 italic" : "text-[var(--text-primary)]"}`}>{l.client_name}</span>
                      <div className="flex items-center gap-2 font-mono text-[10px]">
                        <span className="text-emerald-300">{l.persisted_in_db} dev</span>
                        <span className={l.matched_count > 0 ? "text-emerald-300" : "text-amber-300"}>{l.matched_count} match</span>
                        <span className="text-[var(--text-muted)]">{l.last_sync_at ? new Date(l.last_sync_at).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "mai"}</span>
                        {!isOrphan && noSyncOrZeroMatch && l.client_id && (
                          <>
                            <button
                              data-testid={`datto-debug-client-${i}`}
                              onClick={() => debugClient(l.client_id, l.client_name)}
                              className="px-1.5 py-0.5 rounded border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 text-[9px]"
                              title="Diagnosi: perché 0 device?"
                            >
                              Debug
                            </button>
                            <button
                              data-testid={`datto-force-sync-client-${i}`}
                              onClick={() => forceSyncClient(l.client_id, l.client_name)}
                              className="px-1.5 py-0.5 rounded border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10 text-[9px]"
                              title="Forza re-sync per questo cliente"
                            >
                              Re-sync
                            </button>
                            <button
                              data-testid={`datto-match-debug-client-${i}`}
                              onClick={() => matchDebugClient(l.client_id, l.client_name)}
                              className="px-1.5 py-0.5 rounded border border-fuchsia-500/40 text-fuchsia-300 hover:bg-fuchsia-500/10 text-[9px]"
                              title="Analisi: perché 0 match con discovered_endpoints?"
                            >
                              Match
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {diag.actions_suggested && diag.actions_suggested.length > 0 && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5">
              <div className="text-[10px] uppercase tracking-wider text-amber-300 mb-2">📋 Azioni suggerite</div>
              <ul className="text-[11px] text-[var(--text-primary)] space-y-1">
                {diag.actions_suggested.map((a, i) => (
                  <li key={i} className="flex gap-2"><span className="text-amber-400">•</span>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

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
                                {`${s.site_name || "—"} (${Number.isFinite(s.device_count) ? s.device_count : 0})`}
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

      {/* Datto Browser: Siti/Device paginati */}
      {config?.configured && (
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 space-y-3" data-testid="datto-browser-section">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)]">Esplora Datto RMM</h3>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                Vista paginata di tutti i siti e dispositivi sincronizzati dal portale. Solo nome/MAC/IP visibili — dati sensibili cifrati.
              </p>
            </div>
          </div>
          <ErrorBoundary label="Esplora Datto">
            <DattoBrowser />
          </ErrorBoundary>
        </div>
      )}
    </div>
  );
}
