import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  Lock, Plug, ArrowLeft, Plus, X, Warning, ShieldCheck, Pulse, Globe, Power,
  ListBullets, ClockClockwise, Copy
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from "@/components/ui/select";

export default function WireGuardPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("sessions"); // 'sessions' | 'peers' | 'history'
  const [serverStatus, setServerStatus] = useState({ ready: false });
  const [peers, setPeers] = useState([]);
  const [activeSessions, setActiveSessions] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showStartDialog, setShowStartDialog] = useState(false);
  const [startForm, setStartForm] = useState({ client_id: "", target_device_ip: "", reason: "", ttl_minutes: 30 });
  const [starting, setStarting] = useState(false);
  const [embeddedStatus, setEmbeddedStatus] = useState(null);
  const [embeddedBusy, setEmbeddedBusy] = useState(false);
  const [systemVersion, setSystemVersion] = useState(null);
  const [updateStatus, setUpdateStatus] = useState({ phase: "idle", progress: 0, message: "" });
  const [updating, setUpdating] = useState(false);
  const [showUpdateDialog, setShowUpdateDialog] = useState(false);

  const loadSystemVersion = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/system/version`);
      setSystemVersion(r.data);
    } catch (e) { setSystemVersion(null); }
  }, []);

  const loadUpdateStatus = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/system/self-update/status`);
      setUpdateStatus(r.data);
      const phase = r.data.phase;
      // Quando l'update e` finito o fallito, smetti di pollare e ricarica la pagina dati
      if (phase === "done") {
        setUpdating(false);
        setTimeout(() => { window.location.reload(); }, 2000);
      } else if (phase === "failed" || phase === "stale" || phase === "error") {
        setUpdating(false);
      } else if (phase !== "idle") {
        setUpdating(true);
      }
    } catch (e) { /* ignore */ }
  }, []);

  const triggerUpdate = async (enableWireguard, customUrl) => {
    setUpdating(true);
    setShowUpdateDialog(false);
    setUpdateStatus({ phase: "queued", progress: 0, message: "Invio richiesta..." });
    try {
      // Calcola hostname pubblico dal browser (es. argus.86bit.it)
      const wgHost = window.location.hostname;
      const payload = {
        enable_wireguard: !!enableWireguard,
        wireguard_host: wgHost,
      };
      if (customUrl && customUrl.trim()) {
        payload.package_url = customUrl.trim();
      }
      const res = await axios.post(`${API}/admin/system/self-update`, payload);
      const src = res.data?.url_source || "";
      const srcLabel = src === "remote-fallback" ? " (fallback CDN remoto)"
                     : src === "custom" ? " (URL custom)"
                     : src === "local" ? " (CDN locale)" : "";
      toast.success("Aggiornamento avviato", { description: `Download da ${res.data?.package_url}${srcLabel}. Non chiudere la pagina.` });
    } catch (e) {
      const det = e?.response?.data?.detail || e.message;
      toast.error("Errore avvio update", { description: det });
      setUpdating(false);
      setUpdateStatus({ phase: "failed", progress: 0, error: det, message: det });
    }
  };

  const precheckUrl = async (customUrl) => {
    try {
      const params = customUrl && customUrl.trim()
        ? { params: { url: customUrl.trim() } } : undefined;
      const r = await axios.get(`${API}/admin/system/self-update/resolve-url`, params);
      const { resolved_url, source, reachable, http_status, content_length } = r.data;
      if (reachable) {
        toast.success(
          `URL raggiungibile (${source})`,
          { description: `${resolved_url} — ${(content_length/1024/1024).toFixed(2)} MB` },
        );
      } else {
        toast.error(
          `URL NON raggiungibile (HTTP ${http_status || "?"})`,
          { description: `Risolto: ${resolved_url}. Inserisci un URL custom o configura ARGUS_UPDATE_ARTIFACT_BASE_URL.` },
        );
      }
    } catch (e) {
      toast.error("Pre-check fallito", { description: e?.response?.data?.detail || e.message });
    }
  };

  const loadEmbedded = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/wireguard/embedded/status`);
      setEmbeddedStatus(r.data);
    } catch (e) {
      // Endpoint optional (older backend versions). Silently ignore.
      setEmbeddedStatus(null);
    }
  }, []);

  const startEmbedded = async () => {
    setEmbeddedBusy(true);
    try {
      const r = await axios.post(`${API}/admin/wireguard/embedded/start`);
      setEmbeddedStatus(r.data);
      if (r.data.running) toast.success("Server WireGuard embedded avviato");
      else toast.error("Server NON avviato", { description: r.data.last_error || "Verifica i prerequisiti host" });
    } catch (e) {
      toast.error("Errore avvio embedded", { description: e?.response?.data?.detail || e.message });
    } finally { setEmbeddedBusy(false); }
  };

  const stopEmbedded = async () => {
    if (!window.confirm("Fermare il server WireGuard embedded? Le sessioni VPN attive verranno interrotte.")) return;
    setEmbeddedBusy(true);
    try {
      const r = await axios.post(`${API}/admin/wireguard/embedded/stop`);
      setEmbeddedStatus(r.data);
      toast.success("Server WireGuard embedded fermato");
    } catch (e) {
      toast.error("Errore stop embedded", { description: e?.response?.data?.detail || e.message });
    } finally { setEmbeddedBusy(false); }
  };

  const syncNowEmbedded = async () => {
    setEmbeddedBusy(true);
    try {
      await axios.post(`${API}/admin/wireguard/embedded/sync-now`);
      await loadEmbedded();
      toast.success("Sync peer eseguita");
    } catch (e) {
      toast.error("Errore sync", { description: e?.response?.data?.detail || e.message });
    } finally { setEmbeddedBusy(false); }
  };

  const copyPubkey = () => {
    const pk = embeddedStatus?.public_key || "";
    if (!pk) return;
    navigator.clipboard?.writeText(pk);
    toast.success("Public key copiata");
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, p, sess] = await Promise.all([
        axios.get(`${API}/admin/wireguard/server-status`),
        axios.get(`${API}/admin/wireguard/peers`),
        axios.get(`${API}/admin/wireguard/sessions?limit=200`),
      ]);
      setServerStatus(s.data);
      setPeers(p.data.items || []);
      const allSessions = sess.data.items || [];
      setActiveSessions(allSessions.filter(x => x.status === "active"));
      setHistory(allSessions);
    } catch (e) {
      toast.error("Errore caricamento WireGuard", { description: e?.response?.data?.detail || e.message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [load]);
  useEffect(() => { loadEmbedded(); const t = setInterval(loadEmbedded, 10000); return () => clearInterval(t); }, [loadEmbedded]);
  useEffect(() => { loadSystemVersion(); }, [loadSystemVersion]);
  useEffect(() => {
    loadUpdateStatus();
    // Polling piu` aggressivo durante un update in corso (1s vs 10s a riposo)
    const interval = updating ? 1000 : 10000;
    const t = setInterval(loadUpdateStatus, interval);
    return () => clearInterval(t);
  }, [loadUpdateStatus, updating]);

  const startSession = async () => {
    if (!startForm.client_id) { toast.error("Seleziona un cliente"); return; }
    setStarting(true);
    try {
      await axios.post(`${API}/admin/wireguard/session/start`, {
        client_id: startForm.client_id,
        target_device_ip: startForm.target_device_ip || undefined,
        reason: startForm.reason || undefined,
        ttl_minutes: parseInt(startForm.ttl_minutes, 10) || 30,
      });
      toast.success("Sessione VPN avviata", { description: "Il connector attiverà il tunnel entro pochi secondi." });
      setShowStartDialog(false);
      setStartForm({ client_id: "", target_device_ip: "", reason: "", ttl_minutes: 30 });
      await load();
    } catch (e) {
      toast.error("Errore avvio sessione", { description: e?.response?.data?.detail || e.message });
    } finally {
      setStarting(false);
    }
  };

  const stopSession = async (sessionId) => {
    try {
      await axios.post(`${API}/admin/wireguard/session/${sessionId}/stop`);
      toast.success("Sessione chiusa");
      await load();
    } catch (e) {
      toast.error("Errore chiusura", { description: e?.response?.data?.detail || e.message });
    }
  };

  const disablePeer = async (clientId) => {
    if (!confirm("Disabilitare il peer? Il connector di questo cliente non potrà più creare tunnel finché non lo riabiliti.")) return;
    try {
      await axios.post(`${API}/admin/wireguard/peer/${clientId}/disable`);
      toast.success("Peer disabilitato");
      await load();
    } catch (e) {
      toast.error("Errore", { description: e?.response?.data?.detail || e.message });
    }
  };

  const rotateKeys = async (clientId, clientName) => {
    if (!confirm(
      `Forzare la rotazione delle chiavi del peer "${clientName}"?\n\n` +
      `Il connector rigenererà coppia chiavi + PSK al prossimo polling (~5 min).\n` +
      `Eventuali sessioni VPN attive si chiuderanno temporaneamente.`
    )) return;
    try {
      await axios.post(`${API}/admin/wireguard/peer/${clientId}/force-key-rotation`);
      toast.success("Rotazione chiavi richiesta", {
        description: "Il connector ruoterà le chiavi al prossimo polling cycle (~5 min max)",
      });
      await load();
    } catch (e) {
      toast.error("Errore rotazione", { description: e?.response?.data?.detail || e.message });
    }
  };

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto" data-testid="wireguard-page">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 mb-5">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate("/settings")}
            className="h-8 px-2" data-testid="back-btn">
            <ArrowLeft size={14} />
          </Button>
          <div>
            <h1 className="text-[var(--text-primary)] text-base md:text-lg font-semibold flex items-center gap-2">
              <Lock size={18} className="text-emerald-400" /> WireGuard VPN — Accesso Remoto Military-Grade
            </h1>
            <p className="text-[var(--text-muted)] text-xs mt-0.5">
              Tunnel on-demand verso i dispositivi del cliente attraverso il connector ARGUS. Crittografia ChaCha20-Poly1305, isolamento per-tenant.
            </p>
          </div>
        </div>
        <Button onClick={() => setShowStartDialog(true)} disabled={!serverStatus.ready || peers.length === 0}
          size="sm" className="rounded-md text-xs h-8" data-testid="start-session-btn">
          <Plus size={13} className="mr-1" /> Avvia Sessione VPN
        </Button>
      </div>

      {/* Server status banner */}
      <ServerStatusBanner status={serverStatus} />

      {/* System self-update banner (1-click backend upgrade from UI) */}
      {systemVersion?.self_update_supported && (
        <SystemUpdateBanner
          version={systemVersion}
          updateStatus={updateStatus}
          updating={updating}
          embeddedRunning={!!embeddedStatus?.running}
          embeddedReady={!!embeddedStatus?.environment?.ready_to_start}
          onTrigger={() => setShowUpdateDialog(true)}
        />
      )}

      {/* Embedded runtime banner (Fase 2 — server WireGuard self-hosted nel Center) */}
      {embeddedStatus && (
        <EmbeddedRuntimeBanner
          status={embeddedStatus}
          busy={embeddedBusy}
          onStart={startEmbedded}
          onStop={stopEmbedded}
          onSync={syncNowEmbedded}
          onCopyPubkey={copyPubkey}
        />
      )}

      {/* HARDENING summary banner */}
      <div className="noc-panel p-3 mb-4 border-l-2 border-emerald-400" data-testid="hardening-summary">
        <div className="flex items-start gap-3">
          <ShieldCheck size={18} className="text-emerald-400 mt-0.5 shrink-0" />
          <div className="flex-1 text-[10px] leading-relaxed">
            <p className="text-emerald-400 font-semibold mb-1">🛡️ MILITARY-GRADE HARDENING ATTIVO</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-3 gap-y-0.5 text-[var(--text-secondary)]">
              <div>✓ ChaCha20-Poly1305 + Curve25519</div>
              <div>✓ Forward secrecy</div>
              <div>✓ Pre-Shared Key (quantum-resistant)</div>
              <div>✓ Restrict mode (solo device registrati)</div>
              <div>✓ TTL session 30 min default</div>
              <div>✓ Audit log + key rotation</div>
              <div>✓ IP source whitelist (firewall)</div>
              <div>✓ Rate limit 10/sec/source</div>
              <div>✓ Fail2Ban auto-ban</div>
              <div>✓ Porta UDP non-default</div>
              <div>✓ Sysctl hardening</div>
              <div>✓ Per-tenant isolation</div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-4 border-b border-[var(--bg-border)]">
        {[
          { id: "sessions", label: `Sessioni Attive (${activeSessions.length})`, icon: <Pulse size={13} /> },
          { id: "peers", label: `Peer Registrati (${peers.length})`, icon: <Plug size={13} /> },
          { id: "history", label: "Storico", icon: <ClockClockwise size={13} /> },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-xs flex items-center gap-1.5 border-b-2 transition-colors ${
              tab === t.id ? 'border-emerald-400 text-emerald-400' : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
            data-testid={`tab-${t.id}`}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {loading ? (
        <div className="noc-panel p-8 text-center text-xs text-[var(--text-muted)]">Caricamento...</div>
      ) : (
        <>
          {tab === "sessions" && (
            <SessionsTab sessions={activeSessions} onStop={stopSession} />
          )}
          {tab === "peers" && (
            <PeersTab peers={peers} onDisable={disablePeer} onRotate={rotateKeys} />
          )}
          {tab === "history" && (
            <HistoryTab history={history} />
          )}
        </>
      )}

      {/* Start session dialog */}
      <Dialog open={showStartDialog} onOpenChange={setShowStartDialog}>
        <DialogContent className="sm:max-w-md" data-testid="start-session-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Plug size={16} /> Avvia sessione VPN</DialogTitle>
            <DialogDescription className="text-xs">
              Il connector del cliente attiverà il tunnel WireGuard al prossimo poll (~entro 5 secondi).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-xs">Cliente *</Label>
              <Select value={startForm.client_id} onValueChange={(v) => setStartForm(f => ({ ...f, client_id: v }))}>
                <SelectTrigger className="mt-1 h-9 text-xs" data-testid="client-select">
                  <SelectValue placeholder="Seleziona cliente con peer registrato" />
                </SelectTrigger>
                <SelectContent>
                  {peers.filter(p => p.active).map(p => (
                    <SelectItem key={p.client_id} value={p.client_id}>
                      {p.client_name} ({p.tunnel_ip})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">IP dispositivo target (opzionale, audit)</Label>
              <Input value={startForm.target_device_ip} onChange={(e) => setStartForm(f => ({ ...f, target_device_ip: e.target.value }))}
                placeholder="es. 10.100.61.220" className="mt-1 font-mono text-xs h-9"
                data-testid="target-ip-input" />
            </div>
            <div>
              <Label className="text-xs">Motivo (opzionale, audit)</Label>
              <Input value={startForm.reason} onChange={(e) => setStartForm(f => ({ ...f, reason: e.target.value }))}
                placeholder="es. Manutenzione switch, ticket #1234" className="mt-1 text-xs h-9"
                data-testid="reason-input" />
            </div>
            <div>
              <Label className="text-xs">Durata massima (min)</Label>
              <Input type="number" min="1" max="240" value={startForm.ttl_minutes}
                onChange={(e) => setStartForm(f => ({ ...f, ttl_minutes: e.target.value }))}
                className="mt-1 text-xs h-9 w-24" data-testid="ttl-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowStartDialog(false)}>Annulla</Button>
            <Button onClick={startSession} disabled={starting || !startForm.client_id} data-testid="confirm-start-btn">
              {starting ? "Avvio..." : "Avvia"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* System self-update confirm dialog */}
      <Dialog open={showUpdateDialog} onOpenChange={setShowUpdateDialog}>
        <DialogContent className="sm:max-w-md" data-testid="update-confirm-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldCheck size={16} className="text-cyan-400" /> Aggiorna Backend Center
            </DialogTitle>
            <DialogDescription className="text-xs">
              Il backend si scarichera` da solo l'ultima versione, fara` backup, sostituira` i file e si riavviera`. Tempo stimato: ~60 secondi.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-xs">
            <div className="p-3 rounded bg-amber-500/10 border border-amber-500/30">
              <p className="text-amber-300 font-semibold mb-1.5">⚠️ Cosa succede esattamente</p>
              <ul className="text-[var(--text-secondary)] space-y-1 ml-4 list-disc text-[11px]">
                <li>Backup completo del backend in <code className="text-cyan-300">/opt/argus/backups/backend-&lt;timestamp&gt;</code></li>
                <li>Stop backend, sostituzione file, restore <code className="text-cyan-300">.env</code> + <code className="text-cyan-300">data/</code>, pip install, restart</li>
                <li>Health check post-restart con <strong>rollback automatico</strong> se la nuova versione non risponde</li>
                <li>La pagina si ricarichera` automaticamente al termine</li>
              </ul>
            </div>
            <div className="p-3 rounded bg-cyan-500/5 border border-cyan-500/30">
              <label className="flex items-start gap-2 cursor-pointer">
                <input type="checkbox" id="enable-wg-checkbox" defaultChecked className="mt-0.5"
                  data-testid="enable-wg-checkbox" />
                <span>
                  <span className="text-cyan-300 font-semibold">Attiva contestualmente il server WireGuard embedded</span>
                  <span className="block text-[11px] text-[var(--text-muted)] mt-0.5">
                    Aggiunge <code>WG_EMBEDDED_ENABLED=true</code> al .env, prova ad aprire UDP 51820 sul firewall (se ufw rilevato), e fa partire il server VPN. Se i prerequisiti host non sono soddisfatti il banner ti dira` cosa manca dopo il riavvio.
                  </span>
                </span>
              </label>
            </div>
            <details className="p-3 rounded bg-violet-500/5 border border-violet-500/30">
              <summary className="text-violet-300 font-semibold cursor-pointer text-[11px]">⚙️ Opzioni avanzate · URL pacchetto custom</summary>
              <div className="mt-2 space-y-1.5">
                <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wide">URL tarball backend</label>
                <input
                  type="text"
                  id="custom-url-input"
                  placeholder="lascia vuoto per usare il default"
                  className="w-full text-[11px] font-mono px-2 py-1.5 rounded bg-black/30 border border-[var(--bg-border)] text-cyan-300 placeholder:text-[var(--text-muted)]/50 focus:outline-none focus:border-violet-500"
                  data-testid="custom-package-url-input"
                />
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 text-[10px] px-2"
                    data-testid="precheck-url-btn"
                    onClick={() => {
                      const v = document.getElementById("custom-url-input")?.value || "";
                      precheckUrl(v);
                    }}
                  >
                    Pre-check URL
                  </Button>
                  <span className="text-[10px] text-[var(--text-muted)]">verifica raggiungibilita` prima di lanciare</span>
                </div>
                <p className="text-[10px] text-[var(--text-muted)] leading-relaxed">
                  Ordine di risoluzione: <strong>custom</strong> → <strong>locale</strong> <code className="text-cyan-300">https://{typeof window !== "undefined" ? window.location.hostname : "argus.86bit.it"}/downloads/argus-backend-latest.tar.gz</code> → <strong>fallback remoto</strong> (env <code>ARGUS_UPDATE_ARTIFACT_BASE_URL</code>{systemVersion?.update_artifact_fallback ? ` = ${systemVersion.update_artifact_fallback}` : " non configurata"}).
                </p>
              </div>
            </details>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowUpdateDialog(false)}>Annulla</Button>
            <Button onClick={() => {
              const cb = document.getElementById("enable-wg-checkbox");
              const customUrl = document.getElementById("custom-url-input")?.value || "";
              triggerUpdate(cb?.checked, customUrl);
            }} data-testid="confirm-update-btn">
              Aggiorna Adesso
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ServerStatusBanner({ status }) {
  if (status.ready) {
    return (
      <div className="noc-panel p-4 mb-5 flex items-center gap-3" data-testid="server-status-ready">
        <div className="w-9 h-9 rounded-full flex items-center justify-center bg-emerald-400/10 text-emerald-400">
          <ShieldCheck size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[var(--text-primary)] text-xs font-medium">WireGuard Server: ATTIVO</p>
          <p className="text-[var(--text-muted)] text-[10px] mt-0.5 font-mono">
            Endpoint: {status.server_endpoint} · Pool: {status.pool_base} · TTL session default: {status.session_ttl_minutes} min
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="noc-panel p-4 mb-5 border-l-2 border-amber-400" data-testid="server-status-not-ready">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-full flex items-center justify-center bg-amber-400/10 text-amber-400 shrink-0">
          <Warning size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-amber-400 text-xs font-semibold mb-1">WireGuard Server NON CONFIGURATO</p>
          <p className="text-[var(--text-secondary)] text-xs leading-relaxed mb-2">
            I peer connector possono registrarsi ma le sessioni VPN non verranno effettivamente instradate. Per attivare:
          </p>
          <ol className="text-[10px] text-[var(--text-secondary)] list-decimal pl-4 space-y-1 mb-2">
            <li>Sul server Argus, esegui: <code className="bg-black/30 px-1.5 py-0.5 rounded text-emerald-400">sudo bash /app/scripts/setup-wireguard-server.sh</code></li>
            <li>Lo script genera <code className="text-emerald-400">WG_SERVER_PUBKEY</code> e <code className="text-emerald-400">WG_SERVER_ENDPOINT</code></li>
            <li>Aggiungili a <code className="text-emerald-400">/app/backend/.env</code> e <code className="text-emerald-400">sudo supervisorctl restart backend</code></li>
          </ol>
          <p className="text-[10px] text-[var(--text-muted)]">
            Pool subnet attuale: <span className="font-mono">{status.pool_base}</span> · Session TTL default: {status.session_ttl_minutes} min
          </p>
        </div>
      </div>
    </div>
  );
}

function SessionsTab({ sessions, onStop }) {
  if (sessions.length === 0) {
    return (
      <div className="noc-panel p-12 text-center" data-testid="no-active-sessions">
        <Pulse size={32} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
        <p className="text-[var(--text-muted)] text-xs">Nessuna sessione VPN attiva.</p>
        <p className="text-[var(--text-muted)] text-[10px] mt-1">Clicca "Avvia Sessione VPN" per aprire un tunnel verso il connector di un cliente.</p>
      </div>
    );
  }
  return (
    <div className="space-y-2" data-testid="active-sessions-list">
      {sessions.map(s => (
        <div key={s.id} className="noc-panel p-3 flex items-center gap-3" data-testid={`session-${s.id}`}>
          <div className="w-8 h-8 rounded-full bg-emerald-400/10 flex items-center justify-center">
            <Plug size={15} className="text-emerald-400 animate-pulse" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[var(--text-primary)] text-xs font-medium">{s.client_name}</span>
              <span className="text-[10px] px-1.5 py-0.5 bg-emerald-400/10 text-emerald-400 rounded font-mono">{s.tunnel_ip}</span>
              {s.target_device_ip && (
                <span className="text-[10px] text-[var(--text-muted)]">→ <span className="font-mono">{s.target_device_ip}</span></span>
              )}
            </div>
            <div className="text-[10px] text-[var(--text-muted)] mt-0.5">
              Avviata da {s.started_by} · scade {formatRelative(s.expires_at)}
              {s.reason && ` · "${s.reason}"`}
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => onStop(s.id)}
            className="rounded-md text-xs h-7 border-red-500/30 text-red-400 hover:bg-red-500/10 hover:border-red-500"
            data-testid={`stop-${s.id}`}>
            <Power size={12} className="mr-1" /> Disconnetti
          </Button>
        </div>
      ))}
    </div>
  );
}

function PeersTab({ peers, onDisable, onRotate }) {
  if (peers.length === 0) {
    return (
      <div className="noc-panel p-12 text-center" data-testid="no-peers">
        <Plug size={32} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
        <p className="text-[var(--text-muted)] text-xs">Nessun peer registrato.</p>
        <p className="text-[var(--text-muted)] text-[10px] mt-1">I connector che supportano WireGuard si registreranno automaticamente al primo avvio.</p>
      </div>
    );
  }
  return (
    <div className="noc-panel overflow-hidden" data-testid="peers-table">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider bg-[var(--bg-hover)]/50">
            <th className="text-left px-3 py-2 font-medium">Cliente</th>
            <th className="text-left px-3 py-2 font-medium">Tunnel IP</th>
            <th className="text-left px-3 py-2 font-medium">Public Key</th>
            <th className="text-center px-3 py-2 font-medium">PSK</th>
            <th className="text-left px-3 py-2 font-medium">Ultima rotazione</th>
            <th className="text-center px-3 py-2 font-medium">Stato</th>
            <th className="text-right px-3 py-2 font-medium">Azioni</th>
          </tr>
        </thead>
        <tbody>
          {peers.map(p => (
            <tr key={p.id || p.client_id} className="border-t border-[var(--bg-border)]" data-testid={`peer-${p.client_id}`}>
              <td className="px-3 py-2 text-[var(--text-primary)] font-medium">{p.client_name || p.client_id}</td>
              <td className="px-3 py-2 font-mono text-emerald-400">{p.tunnel_ip}</td>
              <td className="px-3 py-2 font-mono text-[10px] text-[var(--text-muted)]">
                <div className="flex items-center gap-1.5">
                  <span className="truncate max-w-[140px]">{p.public_key}</span>
                  <button onClick={() => { navigator.clipboard.writeText(p.public_key); toast.success("Copiata"); }}
                    className="hover:text-emerald-400" title="Copia">
                    <Copy size={11} />
                  </button>
                </div>
              </td>
              <td className="px-3 py-2 text-center">
                {p.preshared_key ? (
                  <span className="text-[9px] px-1.5 py-0.5 bg-emerald-400/10 text-emerald-400 rounded" title="Pre-Shared Key abilitato (quantum-resistant)">
                    ✓ ON
                  </span>
                ) : (
                  <span className="text-[9px] px-1.5 py-0.5 bg-amber-400/10 text-amber-400 rounded" title="PSK non configurato (peer pre-v3.5.20)">
                    OFF
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-[10px] text-[var(--text-muted)]">
                {p.last_rotation_at ? formatDate(p.last_rotation_at) : formatDate(p.created_at)}
                {p.force_rotation_pending && (
                  <div className="text-amber-400 mt-0.5">⏳ rotazione pending</div>
                )}
              </td>
              <td className="px-3 py-2 text-center">
                {p.active ? (
                  <span className="text-[10px] px-1.5 py-0.5 bg-emerald-400/10 text-emerald-400 rounded">attivo</span>
                ) : (
                  <span className="text-[10px] px-1.5 py-0.5 bg-red-500/10 text-red-400 rounded">disabilitato</span>
                )}
              </td>
              <td className="px-3 py-2 text-right">
                <div className="flex items-center justify-end gap-1">
                  {p.active && (
                    <>
                      <Button size="sm" variant="ghost" onClick={() => onRotate(p.client_id, p.client_name)}
                        className="h-7 text-[10px] text-blue-400 hover:bg-blue-500/10"
                        title="Rigenera coppia chiavi (anti-compromissione)"
                        data-testid={`rotate-${p.client_id}`}>
                        ↻ Ruota
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => onDisable(p.client_id)}
                        className="h-7 text-[10px] text-red-400 hover:bg-red-500/10"
                        data-testid={`disable-${p.client_id}`}>
                        Disabilita
                      </Button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HistoryTab({ history }) {
  if (history.length === 0) {
    return <div className="noc-panel p-8 text-center text-xs text-[var(--text-muted)]">Nessuna sessione storica</div>;
  }
  return (
    <div className="noc-panel overflow-hidden">
      <table className="w-full text-xs" data-testid="history-table">
        <thead>
          <tr className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider bg-[var(--bg-hover)]/50">
            <th className="text-left px-3 py-2">Cliente</th>
            <th className="text-left px-3 py-2">Target</th>
            <th className="text-left px-3 py-2">Avviata da</th>
            <th className="text-left px-3 py-2">Motivo</th>
            <th className="text-left px-3 py-2">Inizio</th>
            <th className="text-left px-3 py-2">Fine</th>
            <th className="text-center px-3 py-2">Stato</th>
          </tr>
        </thead>
        <tbody>
          {history.map(s => (
            <tr key={s.id} className="border-t border-[var(--bg-border)]">
              <td className="px-3 py-2 text-[var(--text-primary)]">{s.client_name}</td>
              <td className="px-3 py-2 font-mono text-[var(--text-muted)]">{s.target_device_ip || "—"}</td>
              <td className="px-3 py-2 text-[var(--text-muted)]">{s.started_by}</td>
              <td className="px-3 py-2 text-[var(--text-muted)] truncate max-w-[200px]">{s.reason || "—"}</td>
              <td className="px-3 py-2 text-[10px] text-[var(--text-muted)]">{formatDate(s.started_at)}</td>
              <td className="px-3 py-2 text-[10px] text-[var(--text-muted)]">{s.ended_at ? formatDate(s.ended_at) : "—"}</td>
              <td className="px-3 py-2 text-center">
                <StatusBadge status={s.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    active: { c: "bg-emerald-400/10 text-emerald-400", l: "attiva" },
    expired: { c: "bg-amber-400/10 text-amber-400", l: "scaduta" },
    stopped: { c: "bg-blue-400/10 text-blue-400", l: "chiusa" },
    superseded: { c: "bg-gray-400/10 text-gray-400", l: "sostituita" },
  };
  const s = map[status] || { c: "bg-gray-400/10 text-gray-400", l: status };
  return <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.c}`}>{s.l}</span>;
}

function formatDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

function formatRelative(iso) {
  if (!iso) return "—";
  try {
    const diff = new Date(iso).getTime() - Date.now();
    if (diff < 0) return "scaduta";
    const min = Math.floor(diff / 60000);
    if (min < 60) return `tra ${min} min`;
    return `tra ${Math.floor(min / 60)}h ${min % 60}m`;
  } catch { return iso; }
}


function EmbeddedRuntimeBanner({ status, busy, onStart, onStop, onSync, onCopyPubkey }) {
  if (!status) return null;
  const env = status.environment || {};
  const sync = status.peer_sync || {};
  const running = !!status.running;
  const ready = !!env.ready_to_start;
  const missing = env.missing_prerequisites || [];

  // Stato visivo principale
  const stateColor = running ? "emerald" : (ready ? "amber" : "rose");
  const stateLabel = running
    ? "RUNTIME ATTIVO"
    : (ready ? "PRONTO ALL'AVVIO" : "PREREQUISITI MANCANTI");

  return (
    <div className="noc-panel p-4 mb-4 border-l-2" data-testid="embedded-runtime-banner"
      style={{ borderLeftColor: `var(--${stateColor === "emerald" ? "noc-emerald" : stateColor === "amber" ? "noc-amber" : "noc-rose"})` }}>
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full bg-${stateColor}-400 ${running ? "animate-pulse" : ""}`} />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[var(--text-primary)] text-sm font-semibold">Server WireGuard Embedded</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded bg-${stateColor}-400/15 text-${stateColor}-400 font-mono`}>{stateLabel}</span>
            </div>
            <p className="text-[var(--text-muted)] text-[11px] mt-0.5">
              Server VPN self-hosted dentro il Center — zero installazioni esterne.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {!running && (
            <Button onClick={onStart} disabled={busy || !ready} size="sm" variant="default"
              className="rounded-md text-xs h-7" data-testid="embedded-start-btn">
              <Power size={12} className="mr-1" /> Avvia
            </Button>
          )}
          {running && (
            <>
              <Button onClick={onSync} disabled={busy} size="sm" variant="secondary"
                className="rounded-md text-xs h-7" data-testid="embedded-sync-btn">
                <Pulse size={12} className="mr-1" /> Sync
              </Button>
              <Button onClick={onStop} disabled={busy} size="sm" variant="destructive"
                className="rounded-md text-xs h-7" data-testid="embedded-stop-btn">
                <X size={12} className="mr-1" /> Stop
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Grid info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-2 text-[11px]">
        <div>
          <span className="text-[var(--text-muted)]">Interfaccia</span>
          <div className="text-[var(--text-primary)] font-mono mt-0.5">{status.interface}</div>
        </div>
        <div>
          <span className="text-[var(--text-muted)]">Porta UDP</span>
          <div className="text-[var(--text-primary)] font-mono mt-0.5">{status.listen_port}</div>
        </div>
        <div>
          <span className="text-[var(--text-muted)]">Subnet tunnel</span>
          <div className="text-[var(--text-primary)] font-mono mt-0.5">{status.tunnel_cidr}</div>
        </div>
        <div>
          <span className="text-[var(--text-muted)]">Endpoint pubblico</span>
          <div className="text-[var(--text-primary)] font-mono mt-0.5 truncate" title={status.endpoint || "non configurato"}>
            {status.endpoint || <span className="text-amber-400">—</span>}
          </div>
        </div>
      </div>

      {/* Public key */}
      {status.public_key && (
        <div className="mt-3 p-2 rounded bg-[var(--bg-darker)]/40 border border-[var(--bg-border)] flex items-center gap-2">
          <span className="text-[var(--text-muted)] text-[10px]">Server Public Key</span>
          <code className="flex-1 text-[10px] text-emerald-400 font-mono truncate" data-testid="embedded-server-pubkey">
            {status.public_key}
          </code>
          <Button onClick={onCopyPubkey} size="sm" variant="ghost" className="h-6 px-2 text-[10px]" data-testid="embedded-copy-pubkey">
            <Copy size={11} />
          </Button>
        </div>
      )}

      {/* Missing prerequisites */}
      {!ready && missing.length > 0 && (
        <div className="mt-3 p-2 rounded bg-rose-500/10 border border-rose-500/30 text-[11px]">
          <div className="flex items-center gap-1.5 text-rose-400 font-semibold mb-1">
            <Warning size={12} /> Prerequisiti host non soddisfatti
          </div>
          <ul className="text-[var(--text-secondary)] space-y-0.5 ml-4 list-disc">
            {missing.map((m, i) => (<li key={i} className="text-[10px]">{m}</li>))}
          </ul>
          <p className="text-[var(--text-muted)] text-[10px] mt-1.5">
            In produzione su un Linux normale (non container limitato) questi sono soddisfatti automaticamente. Se sei in container Docker/K8s aggiungi <code className="text-cyan-300">--cap-add=NET_ADMIN</code> e <code className="text-cyan-300">--device=/dev/net/tun</code>.
          </p>
        </div>
      )}

      {/* Environment readiness checks */}
      {ready && !running && (
        <div className="mt-3 p-2 rounded bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-300">
          <Warning size={12} className="inline mr-1" />
          Tutti i prerequisiti sono soddisfatti. Premi <strong>Avvia</strong> per attivare il server VPN, oppure setta <code className="text-cyan-300">WG_EMBEDDED_ENABLED=true</code> nell'env del backend per auto-start al boot.
        </div>
      )}

      {/* Last error */}
      {status.last_error && (
        <div className="mt-3 p-2 rounded bg-rose-500/5 border border-rose-500/20 text-[10px] text-rose-300 font-mono">
          <strong>last_error:</strong> {status.last_error}
        </div>
      )}

      {/* Peer sync state */}
      {running && (
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1 text-[10px]">
          <div>
            <span className="text-[var(--text-muted)]">Peer sync</span>
            <div className={sync.running ? "text-emerald-400" : "text-amber-400"}>
              {sync.running ? "ATTIVO (5s)" : "FERMO"}
            </div>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">Ultima sync</span>
            <div className="text-[var(--text-primary)] font-mono">
              {sync.last_sync_at ? new Date(sync.last_sync_at).toLocaleTimeString("it-IT") : "—"}
            </div>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">Peer attivi</span>
            <div className="text-[var(--text-primary)] font-mono">
              {(status.uapi?.peers || []).length}
            </div>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">Diff ultima sync</span>
            <div className="text-[var(--text-primary)] font-mono">
              +{(sync.last_diff?.added || []).length} / -{(sync.last_diff?.removed || []).length} / Δ{(sync.last_diff?.updated || []).length}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function SystemUpdateBanner({ version, updateStatus, updating, embeddedRunning, embeddedReady, onTrigger }) {
  if (!version) return null;
  const phase = updateStatus?.phase || "idle";
  const progress = updateStatus?.progress || 0;
  const isRunning = updating || (phase !== "idle" && phase !== "done" && phase !== "failed" && phase !== "stale" && phase !== "error");
  const isFailed = phase === "failed" || phase === "stale" || phase === "error";
  const isDone = phase === "done";

  const phaseLabels = {
    queued: "In coda",
    starting: "Avvio",
    downloading: "Download",
    extracting: "Estrazione",
    "backing-up": "Backup",
    stopping: "Stop backend",
    replacing: "Sostituzione",
    installing: "pip install",
    "starting-backend": "Restart",
    "health-check": "Health check",
    cleanup: "Pulizia",
    done: "Completato",
    failed: "Fallito",
    stale: "Bloccato",
    error: "Errore",
  };

  // Banner colore secondo stato
  let borderColor = "var(--noc-cyan, #22d3ee)";
  let badgeClass = "bg-cyan-400/15 text-cyan-400";
  let badgeLabel = "AGGIORNAMENTO BACKEND";
  if (isRunning) { borderColor = "var(--noc-amber, #f59e0b)"; badgeClass = "bg-amber-400/15 text-amber-400"; badgeLabel = `${phaseLabels[phase] || phase} ${progress}%`; }
  if (isDone)    { borderColor = "var(--noc-emerald, #10b981)"; badgeClass = "bg-emerald-400/15 text-emerald-400"; badgeLabel = "COMPLETATO"; }
  if (isFailed)  { borderColor = "var(--noc-rose, #f43f5e)"; badgeClass = "bg-rose-400/15 text-rose-400"; badgeLabel = "FALLITO"; }

  return (
    <div className="noc-panel p-4 mb-4 border-l-2" style={{ borderLeftColor: borderColor }} data-testid="system-update-banner">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${isRunning ? "bg-amber-400 animate-pulse" : isDone ? "bg-emerald-400" : isFailed ? "bg-rose-400" : "bg-cyan-400"}`} />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[var(--text-primary)] text-sm font-semibold">Aggiorna Backend Center</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${badgeClass}`}>{badgeLabel}</span>
              <span className="text-[10px] text-[var(--text-muted)] ml-1">v{version.version}</span>
            </div>
            <p className="text-[var(--text-muted)] text-[11px] mt-0.5">
              Aggiornamento 1-click del backend con backup + rollback automatico. Zero SSH richiesto.
            </p>
          </div>
        </div>
        {!isRunning && (
          <Button onClick={onTrigger} disabled={updating} size="sm"
            variant={isFailed ? "destructive" : "default"}
            className="rounded-md text-xs h-8" data-testid="system-update-trigger-btn">
            {isFailed ? "Riprova" : isDone ? "Re-aggiorna" : "Aggiorna Backend"}
          </Button>
        )}
      </div>

      {/* Progress bar */}
      {isRunning && (
        <div className="mt-3">
          <div className="h-1.5 bg-[var(--bg-darker)] rounded-full overflow-hidden">
            <div className="h-full bg-amber-400 transition-all duration-500 ease-out"
              style={{ width: `${progress}%` }} data-testid="update-progress-bar" />
          </div>
          <p className="text-[var(--text-secondary)] text-[10px] mt-1.5 font-mono">
            {updateStatus.message || phaseLabels[phase] || phase}
          </p>
        </div>
      )}

      {/* Successo */}
      {isDone && (
        <div className="mt-3 p-2 rounded bg-emerald-500/10 border border-emerald-500/30 text-[11px] text-emerald-300">
          ✓ {updateStatus.message || "Backend aggiornato. La pagina si ricaricherà tra pochi secondi."}
        </div>
      )}

      {/* Errore */}
      {isFailed && (
        <div className="mt-3 p-2 rounded bg-rose-500/10 border border-rose-500/30 text-[11px] text-rose-300">
          <strong>{phaseLabels[phase] || phase}:</strong> {updateStatus.error || updateStatus.message || "Errore non specificato"}
          <p className="text-[10px] mt-1 text-rose-200/70">
            Il backend è stato ripristinato alla versione precedente automaticamente. Controlla i log su <code>/tmp/argus-update-runner.log</code> per dettagli.
          </p>
        </div>
      )}
    </div>
  );
}
