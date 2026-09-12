import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft, Plug, RefreshCw, Link2, Unlink, Info } from "lucide-react";
import { API } from "@/App";

const TYPE_LBL = { firewall: "Gateway", switch: "Switch", access_point: "Access Point", other: "Altro" };

export default function OmadaSettingsPage() {
  const navigate = useNavigate();
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({ base_url: "https://euw1-omada-northbound.tplinkcloud.com", omadac_id: "", client_id: "", client_secret: "", enabled: true });
  const [sites, setSites] = useState([]);
  const [devices, setDevices] = useState([]);
  const [clients, setClients] = useState([]);
  const [busy, setBusy] = useState("");
  const [showGuide, setShowGuide] = useState(true);

  const load = useCallback(() => {
    axios.get(`${API}/omada/settings`).then(r => {
      setCfg(r.data);
      if (r.data.configured) { setForm(f => ({ ...f, base_url: r.data.base_url, omadac_id: r.data.omadac_id, client_id: r.data.client_id, enabled: r.data.enabled !== false })); setShowGuide(false); }
    }).catch(() => {});
    axios.get(`${API}/omada/sites`).then(r => setSites(r.data.sites || [])).catch(() => {});
    axios.get(`${API}/omada/devices`).then(r => setDevices(r.data.devices || [])).catch(() => {});
    axios.get(`${API}/clients`).then(r => setClients(r.data || [])).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const save = async () => {
    setBusy("save");
    try { await axios.put(`${API}/omada/settings`, form); toast.success("Credenziali Omada salvate (cifrate nel Vault)"); load(); }
    catch (e) { toast.error(e.response?.data?.detail?.[0]?.msg || e.response?.data?.detail || "Errore salvataggio"); }
    finally { setBusy(""); }
  };
  const test = async () => {
    setBusy("test");
    try { const r = await axios.post(`${API}/omada/test`); toast.success(`Connesso: ${r.data.sites.length} siti Omada trovati`); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Test fallito"); load(); }
    finally { setBusy(""); }
  };
  const sync = async () => {
    setBusy("sync");
    try { const r = await axios.post(`${API}/omada/sync`, null, { timeout: 180000 }); toast.success(r.data.error ? `Sync con errori: ${r.data.error}` : `Sync: ${r.data.sites} siti, ${r.data.devices} device, ${r.data.ports} porte`); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Sync fallito"); }
    finally { setBusy(""); }
  };
  const link = async (siteId, clientId) => {
    try {
      if (clientId) { await axios.put(`${API}/clients/${clientId}/omada/link`, { site_id: siteId }); toast.success("Sito collegato al cliente"); }
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore link"); }
  };
  const unlink = async (siteId, clientId) => {
    try { await axios.delete(`${API}/clients/${clientId}/omada/link/${siteId}`); toast.success("Sito scollegato"); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const inp = "h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]";
  return (
    <div className="space-y-4 p-3 md:p-5" data-testid="omada-settings-page">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="h-7 px-2" data-testid="omada-back"><ArrowLeft size={14} /></Button>
        <h1 className="text-base md:text-lg font-bold flex items-center gap-2"><Plug size={18} className="text-cyan-300" /> TP-Link Omada (Open API)</h1>
        {cfg?.configured && <span className={`text-[10px] px-2 py-0.5 rounded-full border ${cfg.last_error ? "border-red-500/40 text-red-300" : cfg.last_test_ok || cfg.last_sync_at ? "border-emerald-500/40 text-emerald-300" : "border-amber-500/40 text-amber-300"}`} data-testid="omada-status">
          {cfg.last_error ? "errore" : cfg.last_sync_at ? `sync ${new Date(cfg.last_sync_at).toLocaleTimeString("it-IT")}` : "configurato"}
        </span>}
        <button onClick={() => setShowGuide(g => !g)} className="ml-auto text-[11px] text-cyan-300 flex items-center gap-1 hover:underline" data-testid="omada-guide-toggle"><Info size={12} /> {showGuide ? "Nascondi guida" : "Dove trovo le credenziali?"}</button>
      </div>

      {showGuide && (
        <div className="noc-panel p-3 text-[11px] space-y-1.5 border-cyan-500/30" data-testid="omada-guide">
          <p className="font-semibold text-cyan-200">Come creare le credenziali Open API (5 minuti, serve controller ≥ 5.12)</p>
          <ol className="list-decimal ml-4 space-y-1 text-[var(--text-secondary)]">
            <li>Entra nella console Omada (cloud <code>omada.tplinkcloud.com</code> o il tuo controller) in <b>Global View</b> (menu in alto a sinistra, fuori dal singolo sito).</li>
            <li><b>Settings → Platform Integration → Open API</b> → <b>Add New App</b>.</li>
            <li>Mode: <b>Client Credentials</b> · Role: <b>Viewer</b> (sola lettura) · Site privileges: <b>All sites</b> (o i siti dei clienti da monitorare). Salva.</li>
            <li>Nella riga dell'app appena creata copia <b>Client ID</b> e <b>Client Secret</b> (il secret si vede una volta sola: se l'hai perso, rigeneralo).</li>
            <li>In alto nella stessa pagina Open API trovi <b>Omada ID</b> (omadacId, stringa lunga es. <code>7b5f…</code>) e <b>Interface Access Address</b>: incollalo così com'è nel campo URL (per il cloud europeo di solito è <code>https://euw1-omada-northbound.tplinkcloud.com</code>; l'indirizzo della console <code>…-omada-cloud…</code> NON è quello dell'API).</li>
            <li>Da quella pagina "Online API Document" ti mostra cosa espone il tuo controller.</li>
          </ol>
        </div>
      )}

      <div className="noc-panel p-3 space-y-2" data-testid="omada-form">
        <div className="grid sm:grid-cols-2 gap-2">
          <label className="text-[10px] text-[var(--text-muted)]">Interface Access Address (URL API)<Input className={inp} value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} placeholder="https://euw1-omada-northbound.tplinkcloud.com" data-testid="omada-base-url" /></label>
          <label className="text-[10px] text-[var(--text-muted)]">Omada ID (omadacId)<Input className={inp} value={form.omadac_id} onChange={e => setForm({ ...form, omadac_id: e.target.value })} data-testid="omada-omadac-id" /></label>
          <label className="text-[10px] text-[var(--text-muted)]">Client ID<Input className={inp} value={form.client_id} onChange={e => setForm({ ...form, client_id: e.target.value })} data-testid="omada-client-id" /></label>
          <label className="text-[10px] text-[var(--text-muted)]">Client Secret {cfg?.configured && <span className="text-emerald-300">(salvato: {cfg.client_secret_masked} — lascia vuoto per non cambiarlo)</span>}<Input type="password" className={inp} value={form.client_secret} onChange={e => setForm({ ...form, client_secret: e.target.value })} data-testid="omada-client-secret" /></label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-[11px] flex items-center gap-1.5"><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} className="accent-cyan-400" data-testid="omada-enabled" /> Sync automatico ogni 5 min</label>
          <div className="ml-auto flex gap-2">
            <Button size="sm" onClick={save} disabled={busy === "save" || !form.omadac_id || !form.client_id || (!cfg?.configured && !form.client_secret)} className="h-8 text-xs bg-cyan-600 hover:bg-cyan-700 text-white" data-testid="omada-save">Salva</Button>
            <Button size="sm" variant="outline" onClick={test} disabled={!cfg?.configured || busy === "test"} className="h-8 text-xs" data-testid="omada-test"><Plug size={13} className="mr-1" /> Test connessione</Button>
            <Button size="sm" variant="outline" onClick={sync} disabled={!cfg?.configured || busy === "sync"} className="h-8 text-xs" data-testid="omada-sync"><RefreshCw size={13} className={`mr-1 ${busy === "sync" ? "animate-spin" : ""}`} /> Sincronizza ora</Button>
          </div>
        </div>
        {cfg?.last_error && <p className="text-[10px] text-red-300" data-testid="omada-last-error">Ultimo errore: {cfg.last_error}</p>}
        {cfg?.last_sync_stats && <p className="text-[10px] text-[var(--text-muted)]">Ultimo sync: {cfg.last_sync_stats.sites} siti · {cfg.last_sync_stats.devices} device · {cfg.last_sync_stats.ports} porte switch · {cfg.last_sync_duration_s}s</p>}
      </div>

      <div className="noc-panel" data-testid="omada-sites">
        <div className="px-3 py-2 border-b border-[var(--bg-border)] text-[11px] font-semibold flex items-center gap-2"><Link2 size={13} /> Siti Omada → Clienti ({sites.length})</div>
        <table className="noc-table w-full text-[11px]">
          <thead><tr><th>Sito</th><th>Regione</th><th>Device</th><th>Cliente collegato</th><th /></tr></thead>
          <tbody>
            {sites.map(s => (
              <tr key={s.site_id} data-testid={`omada-site-${s.site_id}`}>
                <td className="font-semibold text-[var(--text-primary)]">{s.name}</td><td className="text-[var(--text-muted)]">{s.region || "—"}</td><td className="font-mono">{s.devices}</td>
                <td>
                  <select value={s.linked_client_id || ""} onChange={e => link(s.site_id, e.target.value)} className="h-7 px-2 text-[11px] rounded border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]" data-testid={`omada-site-link-${s.site_id}`}>
                    <option value="">— non collegato —</option>
                    {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </td>
                <td>{s.linked_client_id && <button onClick={() => unlink(s.site_id, s.linked_client_id)} className="text-red-300 hover:text-red-200" title="Scollega" data-testid={`omada-site-unlink-${s.site_id}`}><Unlink size={12} /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sites.length === 0 && <p className="text-center text-[11px] text-[var(--text-muted)] py-4">Nessun sito: salva le credenziali, fai "Test connessione" e poi "Sincronizza ora".</p>}
      </div>

      <div className="noc-panel" data-testid="omada-devices">
        <div className="px-3 py-2 border-b border-[var(--bg-border)] text-[11px] font-semibold">Dispositivi Omada ({devices.length})</div>
        <div className="overflow-x-auto"><table className="noc-table w-full text-[11px]">
          <thead><tr><th>Sito</th><th>Tipo</th><th>Nome</th><th>Modello</th><th>IP</th><th>Stato</th><th>Client</th><th>Cliente</th></tr></thead>
          <tbody>
            {devices.slice(0, 300).map(d => (
              <tr key={`${d.site_id}-${d.mac}`}>
                <td>{d.site_name}</td><td>{TYPE_LBL[d.device_type] || d.type_raw}</td><td className="font-semibold text-[var(--text-primary)]">{d.name}</td><td className="text-[var(--text-muted)]">{d.model}</td>
                <td className="font-mono">{d.ip || "—"}</td>
                <td><span className={d.online_status === "ONLINE" ? "text-emerald-300" : "text-red-300"}>{d.online_status}</span></td>
                <td className="font-mono">{d.clients ?? "—"}</td><td className="text-[var(--text-muted)]">{d.client_name || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </div>
    </div>
  );
}
