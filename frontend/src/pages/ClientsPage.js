import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Plus, Trash, Buildings, EnvelopeSimple, Key, Copy, ArrowsClockwise,
  Globe, CaretRight, HardDrives, PlugsConnected, Bell, ShieldCheck,
  WifiHigh, WifiSlash, DownloadSimple, Desktop, Cloud
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export default function ClientsPage() {
  const [clients, setClients] = useState([]);
  const [overview, setOverview] = useState({ clients: [] });
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newClient, setNewClient] = useState({ name: "", description: "", contact_email: "" });
  // Versione del Connector v4 disponibile su GitHub Releases (latest).
  // Usata per mostrare "Installer v4.6.0" sui bottoni di download e per
  // confronto con la versione installata su ogni connector del cliente.
  const [latestAgentVersion, setLatestAgentVersion] = useState("");
  // Mappa client_id -> versione attualmente in esecuzione (preso dal piu'
  // recente managed_agents hello del cliente). Usata per disegnare il badge
  // "v4.5.0 -> v4.6.0" accanto al bottone Installer quando il cliente non
  // e' aggiornato.
  const [agentVersionByClient, setAgentVersionByClient] = useState({});
  // v2026-06-04: consistency audit globale (badge in header se ci sono incongruenze)
  const [consistencyAudit, setConsistencyAudit] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchClients();
    // Audit consistency in background, non blocca il render
    axios.get(`${API}/admin/consistency-audit`)
      .then(r => setConsistencyAudit(r.data))
      .catch(() => {});
  }, []);

  const fetchClients = async () => {
    try {
      const [clientsRes, overviewRes, agentsRes, verRes] = await Promise.allSettled([
        axios.get(`${API}/clients`),
        axios.get(`${API}/overview/clients`),
        axios.get(`${API}/agents`),
        axios.get(`${API}/agent/latest-version`),
      ]);
      if (clientsRes.status === "fulfilled") setClients(clientsRes.value.data);
      if (overviewRes.status === "fulfilled") setOverview(overviewRes.value.data);
      if (agentsRes.status === "fulfilled") {
        // Tengo l'agent_version PIU' RECENTE per ciascun client_id (ordinato
        // dal last_hello_at). Cosi' se un cliente ha un master v4.6.0 e uno
        // scanner v4.5.0 mostro la piu' alta (= quella effettiva di
        // riferimento per stabilire se serve update).
        const byClient = {};
        const docs = agentsRes.value.data?.agents || [];
        docs.forEach(a => {
          const cid = a.client_id;
          const v = a.agent_version;
          if (!cid || !v) return;
          if (!byClient[cid] || isNewerSemver(v, byClient[cid])) byClient[cid] = v;
        });
        setAgentVersionByClient(byClient);
      }
      if (verRes.status === "fulfilled") {
        const v = (verRes.value.data?.version || "").replace(/^v/, "");
        setLatestAgentVersion(v);
      }
    } catch { toast.error("Errore nel caricamento"); }
    finally { setLoading(false); }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/clients`, newClient);
      toast.success("Cliente creato");
      setDialogOpen(false);
      setNewClient({ name: "", description: "", contact_email: "" });
      fetchClients();
    } catch { toast.error("Errore nella creazione"); }
  };

  const handleDelete = async (clientId, e) => {
    e.stopPropagation();
    try { await axios.delete(`${API}/clients/${clientId}`); toast.success("Cliente eliminato"); fetchClients(); }
    catch { toast.error("Errore nell'eliminazione"); }
  };

  const handleRegenerateKey = async (clientId, clientName, e) => {
    e?.stopPropagation();
    try {
      const res = await axios.post(`${API}/clients/${clientId}/regenerate-key`);
      const newKey = res.data?.api_key;
      if (newKey) {
        // Auto-copy della nuova chiave negli appunti per facilitare l'aggiornamento del config.json del connector
        try { await navigator.clipboard.writeText(newKey); } catch {}
        toast.success(`API Key di "${clientName}" rigenerata e copiata`, {
          description: `${newKey.substring(0, 12)}…${newKey.substring(newKey.length - 4)} - aggiorna config.json del connector`,
          duration: 8000,
        });
        fetchClients();
      }
    } catch (err) {
      toast.error("Errore nella rigenerazione", { description: err?.response?.data?.detail || err.message });
    }
  };

  // Confronto semver-light (X.Y.Z) restituendo true se `a` > `b`.
  // Usato per scegliere la versione "piu' alta" tra connector multipli dello
  // stesso cliente e per evidenziare "outdated" quando installata < latest.
  function isNewerSemver(a, b) {
    if (!b) return true;
    const pa = String(a).replace(/^v/, "").split(".").map(n => parseInt(n, 10) || 0);
    const pb = String(b).replace(/^v/, "").split(".").map(n => parseInt(n, 10) || 0);
    for (let i = 0; i < 3; i++) {
      const ai = pa[i] || 0; const bi = pb[i] || 0;
      if (ai > bi) return true;
      if (ai < bi) return false;
    }
    return false;
  }

  const nocUrl = window.location.origin;

  const copyToClipboard = (text, label, e) => {
    if (e) e.stopPropagation();
    try {
      navigator.clipboard.writeText(text)
        .then(() => toast.success(`${label} copiato`))
        .catch(() => { const t=document.createElement("textarea"); t.value=text; document.body.appendChild(t); t.select(); document.execCommand("copy"); document.body.removeChild(t); toast.success(`${label} copiato`); });
    } catch {
      const t=document.createElement("textarea"); t.value=text; document.body.appendChild(t); t.select(); document.execCommand("copy"); document.body.removeChild(t); toast.success(`${label} copiato`);
    }
  };

  // v2026-06-29: Sync Datto sites → managed_clients. Prima fa dry-run per
  // mostrare anteprima (chiede conferma), poi se confermato applica.
  // Non distruttivo: aggiorna solo i campi datto_* sui clienti esistenti.
  const [dattoSyncing, setDattoSyncing] = useState(false);
  const handleSyncDatto = async () => {
    if (dattoSyncing) return;
    setDattoSyncing(true);
    try {
      const dr = await axios.post(`${API}/portal86-datto/sync-to-clients?dry_run=true`);
      const s = dr.data?.summary || {};
      const confirmMsg =
        `Sync Datto (anteprima):\n\n` +
        `  • Da creare : ${s.to_create || 0}\n` +
        `  • Da aggiornare : ${s.to_update || 0}\n` +
        `  • Invariati : ${s.no_change || 0}\n` +
        `  • Filtrati (sistema/vuoti) : ${s.filtered || 0}\n\n` +
        `Procedere con l'applicazione?`;
      if (!window.confirm(confirmMsg)) {
        toast.info("Sync Datto annullata");
        return;
      }
      const ap = await axios.post(`${API}/portal86-datto/sync-to-clients?dry_run=false`);
      const r = ap.data?.summary || {};
      toast.success(
        `Sync Datto OK — creati ${r.to_create || 0}, aggiornati ${r.to_update || 0}, invariati ${r.no_change || 0}`
      );
      fetchClients();
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      if (String(msg).includes("non configurato")) {
        toast.error("Sync Datto: configurazione mancante. Apri Impostazioni → Integrazioni Portal 86bit.");
      } else if (String(msg).includes("vault_mismatch")) {
        toast.error("Sync Datto: chiave vault ruotata. Re-salva la API key in Impostazioni.");
      } else {
        toast.error(`Sync Datto fallita: ${msg}`);
      }
    } finally {
      setDattoSyncing(false);
    }
  };

  // Build overview map by client id
  const overviewMap = {};
  (overview.clients || []).forEach(c => { overviewMap[c.id] = c; });

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="clients-page">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Clienti</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">Clicca su un cliente per vedere tutti i suoi servizi</p>
          {/* v2026-06-04 badge consistency audit: si accende solo se rileva incongruenze status */}
          {consistencyAudit && consistencyAudit.issues_count > 0 && (
            <div
              data-testid="consistency-audit-badge"
              className="mt-2 inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-amber-500/40 bg-amber-500/10 text-amber-300 text-[10px]"
              title={consistencyAudit.hint}
            >
              <span>⚠️ {consistencyAudit.issues_count} device potenzialmente incongruenti (status lista vs card)</span>
              <button
                type="button"
                onClick={() => {
                  const top = (consistencyAudit.issues || []).slice(0, 10).map(i =>
                    `• ${i.client_name} / ${i.device_name} (${i.device_ip}) — ${i.issue}`
                  ).join("\n");
                  window.alert(`${consistencyAudit.hint}\n\nPrimi 10:\n\n${top}`);
                }}
                className="underline hover:text-amber-200"
              >
                dettagli
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={handleSyncDatto}
            disabled={dattoSyncing}
            variant="outline"
            className="rounded-lg gap-1.5 text-xs h-8 border-[var(--bg-border)] text-[var(--text-primary)] hover:bg-indigo-600/10"
            data-testid="sync-datto-btn"
            title="Sincronizza i siti Datto dal portal 86bit. Mostra anteprima prima di applicare."
          >
            <Cloud size={14} className={dattoSyncing ? "animate-pulse" : ""} />
            {dattoSyncing ? "Sync in corso..." : "Sync Datto"}
          </Button>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button className="rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white gap-1.5 text-xs h-8" data-testid="add-client-btn">
              <Plus size={14} /> Nuovo Cliente
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
            <DialogHeader><DialogTitle className="font-heading text-[var(--text-primary)] text-sm">Nuovo Cliente</DialogTitle></DialogHeader>
            <form onSubmit={handleCreate} className="space-y-3 mt-3">
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Nome *</Label>
                <Input value={newClient.name} onChange={e => setNewClient(c => ({...c, name: e.target.value}))} placeholder="Acme Corp" required
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="client-name-input" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Descrizione</Label>
                <Input value={newClient.description} onChange={e => setNewClient(c => ({...c, description: e.target.value}))} placeholder="Cliente enterprise"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="client-description-input" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Email</Label>
                <Input type="email" value={newClient.contact_email} onChange={e => setNewClient(c => ({...c, contact_email: e.target.value}))} placeholder="it@acme.com"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8" data-testid="client-email-input" />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="ghost" size="sm" onClick={() => setDialogOpen(false)} className="rounded-md text-xs">Annulla</Button>
                <Button type="submit" size="sm" className="rounded-md bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="save-client-btn">Salva</Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
        </div>
      </div>

      {/* Client List */}
      <div className="space-y-2">
        {loading ? (
          <p className="text-[var(--text-muted)] text-center py-8 text-xs">Caricamento...</p>
        ) : clients.length === 0 ? (
          <div className="noc-panel p-8 text-center">
            <Buildings size={36} className="mx-auto text-[var(--text-muted)] mb-2" />
            <p className="text-[var(--text-secondary)] text-xs mb-1">Nessun cliente</p>
            <p className="text-[var(--text-muted)] text-[10px]">Aggiungi il primo cliente</p>
          </div>
        ) : (
          clients.map(client => {
            const ov = overviewMap[client.id] || {};
            const health = ov.health || "ok";
            const hColor = health === "critical" ? "#FF3B30" : health === "warning" ? "#FF9500" : health === "attention" ? "#FFCC00" : "#34C759";

            return (
              <div key={client.id}
                className="noc-panel p-0 overflow-hidden hover:border-indigo-500/30 transition-all group select-none relative"
                data-testid={`client-row-${client.id}`}>

                {/* Absolute overlay Link — copre l'intera riga come tap target unico.
                    Risolve il bug touch su mobile dove altri elementi interferivano col target.
                    Gli elementi interattivi (bottoni) sotto hanno z-10 per stare sopra l'overlay. */}
                <Link
                  to={`/client/${client.id}`}
                  className="absolute inset-0 z-0"
                  aria-label={`Apri ${client.name}`}
                  data-testid={`client-link-${client.id}`}
                />

                {/* Main Row */}
                <div className="flex items-center gap-4 px-4 py-4 md:py-3 relative pointer-events-none">
                  {/* Health dot + Name */}
                  <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: hColor, boxShadow: `0 0 8px ${hColor}50` }}></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-bold text-[var(--text-primary)]">{client.name}</h3>
                      {client.description && <span className="text-[10px] text-[var(--text-muted)] truncate hidden md:inline">{client.description}</span>}
                    </div>
                    {/* Compact status pills on mobile */}
                    <div className="flex items-center gap-1.5 mt-1 md:hidden text-[10px]">
                      <span className="font-mono" style={{ color: (ov.devices?.vital_total > 0 ? ((ov.devices?.vital_online || 0) < ov.devices.vital_total) : ov.devices?.offline > 0) ? "#FF9500" : "#34C759" }}>
                        {ov.devices?.vital_total > 0
                          ? `${ov.devices.vital_online || 0}/${ov.devices.vital_total} vitali`
                          : (ov.devices?.total > 0 ? `${ov.devices.online}/${ov.devices.total} disp.` : "— disp.")}
                      </span>
                      <span className="text-[var(--text-muted)]">·</span>
                      <span style={{ color: ov.connector_online ? "#34C759" : ov.connector_online === false ? "#FF3B30" : "#888" }}>
                        {ov.connector_online ? "ON" : ov.connector_online === false ? "OFF" : "—"}
                      </span>
                      {ov.alerts?.total > 0 && (
                        <>
                          <span className="text-[var(--text-muted)]">·</span>
                          <span style={{ color: ov.alerts?.critical > 0 ? "#FF3B30" : "#FF9500" }}>{ov.alerts.total} alert</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Quick Status Pills (desktop only — cliccabili per dettagli future, ora pass-through) */}
                  <div className="flex items-center gap-2 flex-shrink-0 hidden md:flex">
                    {/* Devices — se ci sono VITALI mostra vitali online/tot + totale secondario */}
                    {(() => {
                      const dv = ov.devices || {};
                      const hasVital = (dv.vital_total || 0) > 0;
                      if (hasVital) {
                        const vitalDown = (dv.vital_online || 0) < (dv.vital_total || 0);
                        return (
                          <StatusPill icon={HardDrives}
                            value={`${dv.vital_online || 0}/${dv.vital_total}`}
                            sub={`${dv.total || 0} tot`}
                            color={vitalDown ? "#FF3B30" : "#34C759"}
                            label="Vitali"
                            titleText={`Vitali online: ${dv.vital_online || 0}/${dv.vital_total} · ${dv.total || 0} dispositivi totali (${dv.online || 0} online)`} />
                        );
                      }
                      return (
                        <StatusPill icon={HardDrives}
                          value={dv.total > 0 ? `${dv.online}/${dv.total}` : "—"}
                          sub={dv.total > 0 ? "no vitali" : undefined}
                          color={dv.offline > 0 ? "#FF9500" : "#34C759"}
                          label="Disp."
                          titleText={dv.total > 0 ? `${dv.online}/${dv.total} online. Nessun dispositivo marcato VITALE: seleziona i vitali dalla tab Dispositivi.` : "Nessun dispositivo"} />
                      );
                    })()}
                    {/* Endpoints (PC/Mobile/IoT) — separati, non influenzano salute infra */}
                    {(ov.endpoints?.total || 0) > 0 && (
                      <StatusPill icon={Desktop}
                        value={`${ov.endpoints.online || 0}/${ov.endpoints.total}`}
                        color="#3B82F6"
                        label="Endpoint"
                        titleText={`${ov.endpoints.online || 0}/${ov.endpoints.total} endpoint online (PC/Mobile/IoT). Non influenzano lo stato dell'infrastruttura.`} />
                    )}
                    {/* WAN */}
                    <StatusPill icon={Globe} value={ov.wan?.status === "ok" ? "OK" : ov.wan?.status === "not_configured" ? "N/C" : (ov.wan?.status || "—").toUpperCase()} color={ov.wan?.status === "ok" ? "#34C759" : ov.wan?.status === "not_configured" ? "#555" : "#FF3B30"} label="WAN" />
                    {/* Connector */}
                    <StatusPill icon={PlugsConnected} value={ov.connector_online === true ? "ON" : ov.connector_online === false ? "OFF" : "—"} color={ov.connector_online ? "#34C759" : ov.connector_online === false ? "#FF3B30" : "#555"} label="Conn." />
                    {/* Alerts */}
                    <StatusPill icon={Bell} value={ov.alerts?.total || 0} color={ov.alerts?.critical > 0 ? "#FF3B30" : ov.alerts?.total > 0 ? "#FF9500" : "#34C759"} label="Alert" />
                    {/* Datto sync — visibile solo se il cliente e' Datto-linked */}
                    {client.datto_site_uid && (
                      <a
                        href={client.datto_portal_url || "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="pointer-events-auto"
                        data-testid={`datto-pill-${client.id}`}
                        title={`Apri sito Datto: ${client.name}${client.datto_last_sync_at ? `\nUltima sync: ${client.datto_last_sync_at}` : ""}`}
                      >
                        <StatusPill
                          icon={Cloud}
                          value={`${client.datto_devices_online ?? 0}/${client.datto_devices_total ?? 0}`}
                          color={(client.datto_devices_offline ?? 0) > 0 ? "#FF9500" : "#34C759"}
                          label="Datto"
                        />
                      </a>
                    )}
                  </div>

                  {/* Connector Info — pointer-events-auto + z-10 per stare sopra il Link overlay */}
                  <div className="hidden md:flex items-center gap-2 flex-shrink-0 pointer-events-auto relative z-10" onClick={e => e.stopPropagation()}>
                    {client.api_key && (
                      <button onClick={(e) => copyToClipboard(client.api_key, "API Key", e)}
                        className="text-[9px] px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-indigo-400 hover:border-indigo-500/30 transition-colors flex items-center gap-1"
                        title={`API Key: ${client.api_key}`}>
                        <Key size={10} /> API Key
                      </button>
                    )}
                    {client.api_key && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <button onClick={(e) => e.stopPropagation()}
                            data-testid={`regenerate-api-key-${client.id}`}
                            className="text-[9px] px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-amber-400 hover:border-amber-500/30 transition-colors flex items-center gap-1"
                            title="Rigenera API Key (invalida la precedente)">
                            <ArrowsClockwise size={10} /> Rigenera
                          </button>
                        </AlertDialogTrigger>
                        <AlertDialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg" onClick={e => e.stopPropagation()}>
                          <AlertDialogHeader>
                            <AlertDialogTitle className="text-[var(--text-primary)] text-sm">Rigenera API Key per {client.name}?</AlertDialogTitle>
                            <AlertDialogDescription className="text-[var(--text-muted)] text-xs">
                              La chiave attuale verrà <strong className="text-amber-400">invalidata immediatamente</strong>. Il connector smetterà di funzionare finché non aggiorni <code className="text-[10px] bg-[var(--bg-card)] px-1 rounded">C:\ProgramData\86NocConnector\config.json</code> con la nuova chiave e riavvii il servizio.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-secondary)] text-xs">Annulla</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={(e) => handleRegenerateKey(client.id, client.name, e)}
                              className="bg-amber-600 hover:bg-amber-700 text-white text-xs">
                              Rigenera e copia
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                    <button onClick={(e) => copyToClipboard(nocUrl, "NOC URL", e)}
                      className="text-[9px] px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] text-[var(--text-muted)] hover:text-indigo-400 hover:border-indigo-500/30 transition-colors flex items-center gap-1"
                      title={`URL: ${nocUrl}`}>
                      <Globe size={10} /> URL
                    </button>
                    {client.api_key && (() => {
                      const installedVer = agentVersionByClient[client.id] || "";
                      const latestVer = latestAgentVersion || "";
                      const hasRealLatest = latestVer && latestVer.toLowerCase() !== "latest";
                      const isOutdated = installedVer && hasRealLatest && isNewerSemver(latestVer, installedVer);
                      const btnLabel = hasRealLatest
                        ? `Setup GUI v${latestVer}`
                        : (latestVer ? "Setup GUI (latest)" : "Setup GUI");
                      const tooltip = hasRealLatest
                        ? `Scarica il wizard grafico 86NocAgent v${latestVer} pre-configurato per ${client.name} (installa SEMPRE l'ultima versione)` +
                          (installedVer ? ` (attualmente installato: v${installedVer})` : "")
                        : `Scarica il wizard grafico 86NocAgent (ultima release) pre-configurato per ${client.name}`;
                      return (
                        <>
                          {installedVer && (
                            <span
                              className="text-[9px] px-2 py-1 rounded-md border flex items-center gap-1"
                              style={{
                                borderColor: isOutdated ? "rgba(245,158,11,0.4)" : "rgba(34,197,94,0.3)",
                                color: isOutdated ? "#F59E0B" : "#22C55E",
                                background: "var(--bg-card)",
                              }}
                              title={isOutdated
                                ? `Connector installato (v${installedVer}) e' piu' vecchio della release piu' recente (v${latestVer}). Riscarica l'Installer.`
                                : `Connector installato: v${installedVer}.`}
                              data-testid={`installed-version-${client.id}`}>
                              v{installedVer}{isOutdated ? ` → v${latestVer}` : ""}
                            </span>
                          )}
                          <a
                            href={`${API}/agent/install/wizard-bundle.zip?token=${encodeURIComponent(client.api_key)}`}
                            onClick={(e) => { e.stopPropagation(); toast.success(`Wizard GUI 86NocAgent${hasRealLatest ? ` v${latestVer}` : ""} per "${client.name}" — estrai lo ZIP e tasto destro su Installa-86NocAgent.bat → Esegui come amministratore. Si apre il wizard grafico.`); }}
                            data-testid={`download-installer-${client.id}`}
                            className={`text-[10px] font-semibold px-2.5 py-1 rounded-md border transition-colors flex items-center gap-1 no-underline ${
                              isOutdated
                                ? "bg-amber-500/15 border-amber-500/50 text-amber-300 hover:bg-amber-500/25"
                                : "bg-emerald-500/15 border-emerald-500/50 text-emerald-300 hover:bg-emerald-500/25"
                            }`}
                            title={tooltip}>
                            <DownloadSimple size={11} weight="bold" /> {btnLabel}
                          </a>
                          {/* v2026-06-24: Setup .exe GUI personalizzato (no PowerShell).
                              Genera uno ZIP con setup.exe + sidecar nocinstall.cfg
                              pre-compilato col token del cliente. 3 varianti:
                              - "Setup .exe" (default): ROLE NON baked-in → installer
                                  chiede master/scanner durante la GUI Windows nativa.
                              - "Setup Master" / "Setup Scanner": ROLE baked-in →
                                  installer silenzioso per quel ruolo specifico. */}
                          <a
                            href={`${API}/agent/install/setup.zip?token=${encodeURIComponent(client.api_key)}&client_id=${encodeURIComponent(client.id)}&label=${encodeURIComponent(client.name)}${hasRealLatest ? `&version=v${latestVer}` : ""}`}
                            onClick={(e) => { e.stopPropagation(); toast.success(`Setup .exe per "${client.name}" — estrai ZIP, click destro su setup.exe → Esegui come amministratore. La GUI ti fara' scegliere master/scanner.`); }}
                            data-testid={`download-setup-exe-${client.id}`}
                            className="text-[9px] px-2 py-1 rounded-md bg-[var(--bg-card)] border border-cyan-500/30 text-cyan-300 hover:border-cyan-400 hover:text-cyan-200 transition-colors flex items-center gap-1 no-underline"
                            title={`Scarica Setup .exe GUI per ${client.name}. Doppio click su setup.exe: la GUI chiedera' Master o Scanner.`}>
                            <DownloadSimple size={10} /> Setup .exe
                          </a>
                          <a
                            href={`${API}/agent/install/setup.zip?token=${encodeURIComponent(client.api_key)}&client_id=${encodeURIComponent(client.id)}&role=master&label=${encodeURIComponent(client.name)}${hasRealLatest ? `&version=v${latestVer}` : ""}`}
                            onClick={(e) => { e.stopPropagation(); toast.success(`Setup MASTER per "${client.name}" — installer silenzioso, ruolo gia' baked-in.`); }}
                            data-testid={`download-setup-master-${client.id}`}
                            className="text-[9px] px-1.5 py-1 rounded-md bg-[var(--bg-card)] border border-cyan-500/20 text-cyan-400/70 hover:border-cyan-400 hover:text-cyan-300 transition-colors no-underline"
                            title={`Setup .exe per ${client.name} con ruolo MASTER pre-baked (no prompt GUI).`}>
                            M
                          </a>
                          <a
                            href={`${API}/agent/install/setup.zip?token=${encodeURIComponent(client.api_key)}&client_id=${encodeURIComponent(client.id)}&role=scanner&label=${encodeURIComponent(client.name)}${hasRealLatest ? `&version=v${latestVer}` : ""}`}
                            onClick={(e) => { e.stopPropagation(); toast.success(`Setup SCANNER per "${client.name}" — installer silenzioso, ruolo gia' baked-in.`); }}
                            data-testid={`download-setup-scanner-${client.id}`}
                            className="text-[9px] px-1.5 py-1 rounded-md bg-[var(--bg-card)] border border-cyan-500/20 text-cyan-400/70 hover:border-cyan-400 hover:text-cyan-300 transition-colors no-underline"
                            title={`Setup .exe per ${client.name} con ruolo SCANNER pre-baked (no prompt GUI).`}>
                            S
                          </a>
                        </>
                      );
                    })()}
                    <button onClick={(e) => { e.stopPropagation(); }}
                      className="hidden">
                    </button>
                  </div>

                  {/* Delete + Arrow — pointer-events-auto + z-10 per stare sopra il Link overlay */}
                  <div className="flex items-center gap-1 flex-shrink-0 pointer-events-auto relative z-10" onClick={e => e.stopPropagation()}>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-[var(--text-muted)] hover:text-[var(--critical)] hover:bg-[var(--critical-bg)] rounded-md opacity-0 group-hover:opacity-100 transition-opacity" data-testid={`delete-client-${client.id}`}>
                          <Trash size={13} />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                        <AlertDialogHeader>
                          <AlertDialogTitle className="text-[var(--text-primary)] text-sm">Eliminare {client.name}?</AlertDialogTitle>
                          <AlertDialogDescription className="text-[var(--text-muted)] text-xs">Azione irreversibile. Verranno eliminati tutti i dispositivi e dati associati.</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel className="rounded-md bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] text-xs">Annulla</AlertDialogCancel>
                          <AlertDialogAction onClick={(e) => handleDelete(client.id, e)} className="rounded-md bg-red-900 text-red-100 hover:bg-red-800 text-xs">Elimina</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                  <CaretRight size={16} className="text-[var(--text-muted)] group-hover:text-indigo-400 transition-colors flex-shrink-0" />
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function StatusPill({ icon: Icon, value, color, label, sub, titleText }) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-0.5 px-2 py-1 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] min-w-[52px]"
      title={titleText || label}
    >
      <div className="flex items-center gap-1">
        <Icon size={11} weight="bold" style={{ color }} />
        <span className="text-[9px] font-bold font-mono" style={{ color }}>{value}</span>
      </div>
      {sub && (
        <span className="text-[8px] font-mono text-[var(--text-muted)] leading-none">{sub}</span>
      )}
      {label && (
        <span className="text-[8px] uppercase tracking-wider text-[var(--text-muted)] leading-none">
          {label}
        </span>
      )}
    </div>
  );
}
