import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft, Plug, RefreshCw, Link2, Unlink, Info, Plus, Trash2, Pencil } from "lucide-react";
import { API } from "@/App";

const TYPE_LBL = { firewall: "Gateway", switch: "Switch", access_point: "Access Point", other: "Altro" };
const DEFAULT_URL = "https://euw1-omada-northbound.tplinkcloud.com";
const EMPTY = { name: "", base_url: DEFAULT_URL, omadac_id: "", client_id: "", client_secret: "", enabled: true };
const inp = "h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]";

function ControllerForm({ initial, onSaved, onCancel }) {
  const [f, setF] = useState(initial || EMPTY);
  const [busy, setBusy] = useState(false);
  const isEdit = !!initial?.id;
  const save = async () => {
    setBusy(true);
    try {
      if (isEdit) await axios.put(`${API}/omada/controllers/${initial.id}`, f);
      else await axios.post(`${API}/omada/controllers`, f);
      toast.success(isEdit ? "Controller aggiornato" : "Controller aggiunto (secret cifrato nel Vault)");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail?.[0]?.msg || e.response?.data?.detail || "Errore salvataggio"); }
    finally { setBusy(false); }
  };
  return (
    <div className="noc-panel p-3 space-y-2 border-cyan-500/30" data-testid="omada-ctrl-form">
      <p className="text-[11px] font-semibold text-cyan-200">{isEdit ? `Modifica ${initial.name}` : "Nuovo controller / organizzazione Omada"}</p>
      <div className="grid sm:grid-cols-2 gap-2">
        <label className="text-[10px] text-[var(--text-muted)]">Nome organizzazione (es. Galvan)<Input className={inp} value={f.name} onChange={e => setF({ ...f, name: e.target.value })} data-testid="omada-name" /></label>
        <label className="text-[10px] text-[var(--text-muted)]">Interface Access Address (URL API)<Input className={inp} value={f.base_url} onChange={e => setF({ ...f, base_url: e.target.value })} data-testid="omada-base-url" /></label>
        <label className="text-[10px] text-[var(--text-muted)]">Omada ID (omadacId)<Input className={inp} value={f.omadac_id} onChange={e => setF({ ...f, omadac_id: e.target.value })} data-testid="omada-omadac-id" /></label>
        <label className="text-[10px] text-[var(--text-muted)]">Client ID<Input className={inp} value={f.client_id} onChange={e => setF({ ...f, client_id: e.target.value })} data-testid="omada-client-id" /></label>
        <label className="text-[10px] text-[var(--text-muted)] sm:col-span-2">Client Secret {isEdit && <span className="text-emerald-300">(salvato: {initial.client_secret_masked} — lascia vuoto per non cambiarlo)</span>}<Input type="password" className={inp} value={f.client_secret || ""} onChange={e => setF({ ...f, client_secret: e.target.value })} data-testid="omada-client-secret" /></label>
      </div>
      <div className="flex items-center gap-2">
        <label className="text-[11px] flex items-center gap-1.5"><input type="checkbox" checked={f.enabled} onChange={e => setF({ ...f, enabled: e.target.checked })} className="accent-cyan-400" data-testid="omada-enabled" /> Sync automatico ogni 5 min</label>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" onClick={onCancel} className="h-8 text-xs">Annulla</Button>
          <Button size="sm" onClick={save} disabled={busy || !f.name || !f.omadac_id || !f.client_id || (!isEdit && !f.client_secret)} className="h-8 text-xs bg-cyan-600 hover:bg-cyan-700 text-white" data-testid="omada-save">Salva</Button>
        </div>
      </div>
    </div>
  );
}

export default function OmadaSettingsPage() {
  const navigate = useNavigate();
  const [ctrls, setCtrls] = useState([]);
  const [sites, setSites] = useState([]);
  const [devices, setDevices] = useState([]);
  const [clients, setClients] = useState([]);
  const [editing, setEditing] = useState(null); // null | "new" | controller
  const [busy, setBusy] = useState("");
  const [showGuide, setShowGuide] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/omada/settings`).then(r => { setCtrls(r.data.controllers || []); if (!(r.data.controllers || []).length) setShowGuide(true); }).catch(() => {});
    axios.get(`${API}/omada/sites`).then(r => setSites(r.data.sites || [])).catch(() => {});
    axios.get(`${API}/omada/devices`).then(r => setDevices(r.data.devices || [])).catch(() => {});
    axios.get(`${API}/clients`).then(r => setClients(r.data || [])).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const test = async (c) => {
    setBusy(`test-${c.id}`);
    try { const r = await axios.post(`${API}/omada/controllers/${c.id}/test`); toast.success(`${c.name}: connesso, ${r.data.sites.length} siti`); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Test fallito"); load(); }
    finally { setBusy(""); }
  };
  const sync = async (c) => {
    setBusy(c ? `sync-${c.id}` : "sync");
    try {
      const r = await axios.post(`${API}/omada/sync`, null, { params: c ? { ctrl_id: c.id } : {}, timeout: 180000 });
      const st = c ? r.data : null;
      toast.success(st ? (st.error ? `Errore: ${st.error}` : `${c.name}: ${st.sites} siti, ${st.devices} device, ${st.ports} porte`) : "Sync di tutti i controller completato");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Sync fallito"); }
    finally { setBusy(""); }
  };
  const del = async (c) => {
    if (!window.confirm(`Rimuovere il controller "${c.name}" e i suoi dati sincronizzati?`)) return;
    try { await axios.delete(`${API}/omada/controllers/${c.id}`); toast.success("Controller rimosso"); load(); } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const link = async (s, clientId) => {
    if (!clientId) return;
    try { await axios.put(`${API}/clients/${clientId}/omada/link`, { site_id: s.site_id, controller_id: s.controller_id }); toast.success("Sito collegato al cliente"); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore link"); }
  };
  const unlink = async (s) => {
    try { await axios.delete(`${API}/clients/${s.linked_client_id}/omada/link/${s.site_id}`); toast.success("Sito scollegato"); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  return (
    <div className="space-y-4 p-3 md:p-5" data-testid="omada-settings-page">
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="h-7 px-2" data-testid="omada-back"><ArrowLeft size={14} /></Button>
        <h1 className="text-base md:text-lg font-bold flex items-center gap-2"><Plug size={18} className="text-cyan-300" /> TP-Link Omada (Open API)</h1>
        <span className="text-[10px] text-[var(--text-muted)]" data-testid="omada-counts">{ctrls.length} controller · {sites.length} siti · {devices.length} device</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => setShowGuide(g => !g)} className="text-[11px] text-cyan-300 flex items-center gap-1 hover:underline" data-testid="omada-guide-toggle"><Info size={12} /> {showGuide ? "Nascondi guida" : "Dove trovo le credenziali?"}</button>
          {ctrls.length > 0 && <Button size="sm" variant="outline" onClick={() => sync(null)} disabled={busy === "sync"} className="h-7 text-xs" data-testid="omada-sync-all"><RefreshCw size={12} className={`mr-1 ${busy === "sync" ? "animate-spin" : ""}`} /> Sincronizza tutti</Button>}
          <Button size="sm" onClick={() => setEditing("new")} className="h-7 text-xs bg-cyan-600 hover:bg-cyan-700 text-white" data-testid="omada-add-ctrl"><Plus size={12} className="mr-1" /> Aggiungi organizzazione</Button>
        </div>
      </div>

      {showGuide && (
        <div className="noc-panel p-3 text-[11px] space-y-1.5 border-cyan-500/30" data-testid="omada-guide">
          <p className="font-semibold text-cyan-200">Omada Cloud: ogni <b>organizzazione</b> è un controller separato → una riga qui per ciascuna (stessa procedura, 2 minuti l'una)</p>
          <ol className="list-decimal ml-4 space-y-1 text-[var(--text-secondary)]">
            <li>Su omada.tplinkcloud.com clicca il <b>nome dell'organizzazione</b> (es. Galvan) per entrare nel suo controller, in <b>Global View</b>.</li>
            <li><b>Impostazioni → Integrazione piattaforma → Open API</b> → <b>Aggiungi nuova app</b>: Modalità <b>Client Credentials</b>, Ruolo <b>Viewer</b>, Privilegi <b>Tutti i siti</b>. Salva.</li>
            <li>Copia <b>Client ID</b> e <b>Client Secret</b> dalla riga dell'app (il secret si vede una sola volta: se perso, Rigenera).</li>
            <li>In alto nella pagina Open API copia <b>Omada ID</b> e <b>Interface Access Address</b> (Europa: di solito <code>{DEFAULT_URL}</code>; NON l'indirizzo della console <code>…-omada-cloud…</code>).</li>
            <li>Qui: "Aggiungi organizzazione" → nome = organizzazione → incolla i 4 dati → Salva → <b>Test</b> → <b>Sync</b> → collega i siti ai clienti nella tabella sotto.</li>
          </ol>
          <p className="text-amber-300">Se nella console non trovi "Integrazione piattaforma / Open API" o chiede un piano superiore a Essentials, mandami uno screenshot di quella pagina.</p>
        </div>
      )}

      {editing && <ControllerForm initial={editing === "new" ? null : editing} onSaved={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} />}

      <div className="noc-panel" data-testid="omada-controllers">
        <div className="px-3 py-2 border-b border-[var(--bg-border)] text-[11px] font-semibold">Controller / organizzazioni ({ctrls.length})</div>
        <table className="noc-table w-full text-[11px]">
          <thead><tr><th>Organizzazione</th><th>Omada ID</th><th>Siti</th><th>Device</th><th>Stato</th><th /></tr></thead>
          <tbody>
            {ctrls.map(c => (
              <tr key={c.id} data-testid={`omada-ctrl-${c.id}`}>
                <td className="font-semibold text-[var(--text-primary)]">{c.name}{!c.enabled && <span className="ml-1 text-[9px] text-neutral-400">(disattivato)</span>}<br /><span className="font-mono text-[9px] text-[var(--text-muted)]">{c.base_url}</span></td>
                <td className="font-mono text-[10px] text-[var(--text-muted)]">{c.omadac_id}</td>
                <td className="font-mono">{c.sites}</td><td className="font-mono">{c.devices}</td>
                <td>{c.last_error ? <span className="text-red-300" title={c.last_error} data-testid={`omada-ctrl-error-${c.id}`}>errore</span> : c.last_sync_at ? <span className="text-emerald-300">sync {new Date(c.last_sync_at).toLocaleTimeString("it-IT")}</span> : c.last_test_ok ? <span className="text-emerald-300">test ok</span> : <span className="text-amber-300">da testare</span>}</td>
                <td>
                  <div className="flex gap-1 justify-end">
                    <Button size="sm" variant="outline" onClick={() => test(c)} disabled={busy === `test-${c.id}`} className="h-6 px-2 text-[10px]" data-testid={`omada-ctrl-test-${c.id}`}><Plug size={11} className="mr-1" /> Test</Button>
                    <Button size="sm" variant="outline" onClick={() => sync(c)} disabled={busy === `sync-${c.id}`} className="h-6 px-2 text-[10px]" data-testid={`omada-ctrl-sync-${c.id}`}><RefreshCw size={11} className={`mr-1 ${busy === `sync-${c.id}` ? "animate-spin" : ""}`} /> Sync</Button>
                    <button onClick={() => setEditing(c)} className="px-1 text-[var(--text-muted)] hover:text-[var(--text-primary)]" data-testid={`omada-ctrl-edit-${c.id}`}><Pencil size={12} /></button>
                    <button onClick={() => del(c)} className="px-1 text-red-300 hover:text-red-200" data-testid={`omada-ctrl-del-${c.id}`}><Trash2 size={12} /></button>
                  </div>
                  {c.last_error && <p className="text-[9px] text-red-300 text-right mt-0.5 max-w-xs truncate" title={c.last_error}>{c.last_error}</p>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {ctrls.length === 0 && <p className="text-center text-[11px] text-[var(--text-muted)] py-4">Nessun controller: clicca "Aggiungi organizzazione" (una per ogni organizzazione Omada Cloud).</p>}
      </div>

      <div className="noc-panel" data-testid="omada-sites">
        <div className="px-3 py-2 border-b border-[var(--bg-border)] text-[11px] font-semibold flex items-center gap-2"><Link2 size={13} /> Siti Omada → Clienti ({sites.length})</div>
        <table className="noc-table w-full text-[11px]">
          <thead><tr><th>Organizzazione</th><th>Sito</th><th>Device</th><th>Cliente collegato</th><th /></tr></thead>
          <tbody>
            {sites.map(s => (
              <tr key={`${s.controller_id}-${s.site_id}`} data-testid={`omada-site-${s.site_id}`}>
                <td className="text-[var(--text-muted)]">{s.controller_name}</td>
                <td className="font-semibold text-[var(--text-primary)]">{s.name}</td><td className="font-mono">{s.devices}</td>
                <td>
                  <select value={s.linked_client_id || ""} onChange={e => link(s, e.target.value)} className="h-7 px-2 text-[11px] rounded border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]" data-testid={`omada-site-link-${s.site_id}`}>
                    <option value="">— non collegato —</option>
                    {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </td>
                <td>{s.linked_client_id && <button onClick={() => unlink(s)} className="text-red-300 hover:text-red-200" title="Scollega" data-testid={`omada-site-unlink-${s.site_id}`}><Unlink size={12} /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sites.length === 0 && <p className="text-center text-[11px] text-[var(--text-muted)] py-4">Nessun sito: aggiungi un controller, fai Test e poi Sync.</p>}
      </div>

      <div className="noc-panel" data-testid="omada-devices">
        <div className="px-3 py-2 border-b border-[var(--bg-border)] text-[11px] font-semibold">Dispositivi Omada ({devices.length})</div>
        <div className="overflow-x-auto"><table className="noc-table w-full text-[11px]">
          <thead><tr><th>Organizzazione</th><th>Sito</th><th>Tipo</th><th>Nome</th><th>Modello</th><th>IP</th><th>Stato</th><th>Client</th><th>Cliente</th></tr></thead>
          <tbody>
            {devices.slice(0, 300).map(d => (
              <tr key={`${d.controller_id}-${d.site_id}-${d.mac}`}>
                <td className="text-[var(--text-muted)]">{d.controller_name}</td><td>{d.site_name}</td><td>{TYPE_LBL[d.device_type] || d.type_raw}</td>
                <td className="font-semibold text-[var(--text-primary)]">{d.name}</td><td className="text-[var(--text-muted)]">{d.model}</td>
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
