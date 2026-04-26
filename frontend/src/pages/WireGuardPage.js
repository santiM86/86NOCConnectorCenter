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
