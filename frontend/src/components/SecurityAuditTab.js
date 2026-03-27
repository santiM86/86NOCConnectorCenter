import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  ShieldCheck, Warning, XCircle, Lock, Eye,
  ArrowClockwise, UserCircle, Globe, Prohibit,
  LockOpen, Gear, Plus, Trash, FloppyDisk
} from "@phosphor-icons/react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const severityColors = {
  critical: { text: "text-[var(--critical)]", bg: "bg-[var(--critical-bg)]", border: "border-[var(--critical-border)]", dot: "bg-[var(--critical)]" },
  warning: { text: "text-[var(--medium)]", bg: "bg-yellow-500/10", border: "border-yellow-500/20", dot: "bg-[var(--medium)]" },
  info: { text: "text-[var(--text-muted)]", bg: "bg-[var(--bg-hover)]", border: "border-[var(--bg-border)]", dot: "bg-blue-400" },
};

const actionLabels = {
  login_failed: "Login fallito",
  login_success: "Login riuscito",
  logout: "Logout",
  "2fa_verified": "2FA verificato",
  "2fa_failed": "2FA fallito",
  rate_limit_exceeded: "Rate limit superato",
  suspicious_activity: "Attivita' sospetta",
  ip_blocked: "IP bloccato",
  password_change: "Cambio password",
  user_update: "Modifica utente",
  user_delete: "Eliminazione utente",
};

function StatCard({ icon, label, value, variant = "default" }) {
  const variants = {
    default: "bg-[var(--bg-panel)] border-[var(--bg-border)]",
    danger: "bg-[var(--critical-bg)] border-[var(--critical-border)]",
    warning: "bg-yellow-500/5 border-yellow-500/20",
    success: "bg-[var(--low-bg)] border-[var(--low-border)]",
  };
  const textColors = {
    default: "text-[var(--text-primary)]",
    danger: "text-[var(--critical)]",
    warning: "text-[var(--medium)]",
    success: "text-[var(--ok)]",
  };
  return (
    <div className={`p-3 rounded-lg border ${variants[variant]}`} data-testid={`security-stat-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">{label}</span>
      </div>
      <p className={`text-xl font-mono font-bold ${textColors[variant]}`}>{value}</p>
    </div>
  );
}

function TimelineBar({ data }) {
  if (!data || data.length === 0) return null;
  const maxVal = Math.max(...data.map(d => d.total), 1);
  return (
    <div className="space-y-1" data-testid="security-timeline">
      <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-2">Attivita' ultimi 7 giorni</p>
      <div className="flex items-end gap-1 h-20">
        {data.map((d, i) => {
          const totalH = Math.max(4, (d.total / maxVal) * 100);
          const dayLabel = d.date.slice(5);
          return (
            <div key={i} className="flex-1 flex flex-col items-center gap-0.5" title={`${d.date}: ${d.success} OK, ${d.failed} falliti, ${d.total} totali`}>
              <div className="w-full relative rounded-t-sm overflow-hidden" style={{ height: `${totalH}%` }}>
                <div className="absolute bottom-0 w-full bg-indigo-500/40 rounded-t-sm" style={{ height: "100%" }} />
                {d.failed > 0 && (
                  <div className="absolute bottom-0 w-full bg-[var(--critical)]/60 rounded-t-sm" style={{ height: `${(d.failed / d.total) * 100}%` }} />
                )}
              </div>
              <span className="text-[8px] text-[var(--text-muted)]">{dayLabel}</span>
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-3 mt-1">
        <span className="flex items-center gap-1 text-[9px] text-[var(--text-muted)]"><div className="w-2 h-2 rounded-sm bg-indigo-500/40" />Totali</span>
        <span className="flex items-center gap-1 text-[9px] text-[var(--text-muted)]"><div className="w-2 h-2 rounded-sm bg-[var(--critical)]/60" />Falliti</span>
      </div>
    </div>
  );
}

function timeAgo(isoStr) {
  if (!isoStr) return "";
  const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
  if (diff < 60) return "adesso";
  if (diff < 3600) return `${Math.floor(diff / 60)}m fa`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h fa`;
  return `${Math.floor(diff / 86400)}g fa`;
}

function timeRemaining(isoStr) {
  if (!isoStr) return "Permanente";
  const diff = (new Date(isoStr).getTime() - Date.now()) / 1000;
  if (diff <= 0) return "Scaduto";
  if (diff < 3600) return `${Math.ceil(diff / 60)}m`;
  if (diff < 86400) return `${Math.ceil(diff / 3600)}h`;
  return `${Math.ceil(diff / 86400)}g`;
}

export function SecurityAuditTab() {
  const [data, setData] = useState(null);
  const [blockedIps, setBlockedIps] = useState({ active: [], history: [] });
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [showConfig, setShowConfig] = useState(false);
  const [showManualBlock, setShowManualBlock] = useState(false);
  const [blockForm, setBlockForm] = useState({ ip: "", reason: "", duration_hours: 6, permanent: false });
  const [config, setConfig] = useState(null);
  const [configForm, setConfigForm] = useState({});
  const [whitelistInput, setWhitelistInput] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [dashRes, blockedRes] = await Promise.all([
        axios.get(`${API}/audit/security-dashboard`),
        axios.get(`${API}/security/blocked-ips`)
      ]);
      setData(dashRes.data);
      setBlockedIps(blockedRes.data);
    } catch (e) {
      console.error("Security dashboard error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchConfig = async () => {
    try {
      const res = await axios.get(`${API}/security/ip-block-config`);
      setConfig(res.data);
      setConfigForm(res.data);
      setWhitelistInput((res.data.whitelist || []).join("\n"));
    } catch {}
  };

  useEffect(() => {
    fetchData();
    if (autoRefresh) {
      const interval = setInterval(fetchData, 15000);
      return () => clearInterval(interval);
    }
  }, [fetchData, autoRefresh]);

  const handleBlock = async (ip, reason) => {
    try {
      await axios.post(`${API}/security/block-ip`, { ip, reason: reason || "Blocco manuale", duration_hours: 6 });
      toast.success(`IP ${ip} bloccato`);
      fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nel blocco IP");
    }
  };

  const handleUnblock = async (ip) => {
    try {
      await axios.post(`${API}/security/unblock-ip`, { ip });
      toast.success(`IP ${ip} sbloccato`);
      fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nello sblocco IP");
    }
  };

  const handleManualBlock = async () => {
    if (!blockForm.ip.trim()) return toast.error("Inserisci un IP");
    try {
      await axios.post(`${API}/security/block-ip`, blockForm);
      toast.success(`IP ${blockForm.ip} bloccato`);
      setShowManualBlock(false);
      setBlockForm({ ip: "", reason: "", duration_hours: 6, permanent: false });
      fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    }
  };

  const handleSaveConfig = async () => {
    try {
      const payload = {
        ...configForm,
        whitelist: whitelistInput.split("\n").map(s => s.trim()).filter(Boolean)
      };
      await axios.post(`${API}/security/ip-block-config`, payload);
      toast.success("Configurazione salvata");
      setShowConfig(false);
      _ip_block_config_cache = null;
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nel salvataggio");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40">
        <ArrowClockwise size={20} className="animate-spin text-[var(--text-muted)]" />
      </div>
    );
  }

  if (!data) return <p className="text-[var(--text-muted)] text-sm">Errore nel caricamento.</p>;

  const s = data.stats;

  return (
    <div className="space-y-4" data-testid="security-audit-tab">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Eye size={18} className="text-red-400" />
          <h2 className="text-sm font-bold text-[var(--text-primary)]">Security Audit in Tempo Reale</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => { fetchConfig(); setShowConfig(true); }} className="h-7 text-[10px] gap-1" data-testid="ip-config-btn">
            <Gear size={12} /> Config
          </Button>
          <Button size="sm" variant="outline" onClick={() => setShowManualBlock(true)} className="h-7 text-[10px] gap-1 border-red-500/30 text-red-400 hover:bg-red-500/10" data-testid="manual-block-btn">
            <Prohibit size={12} /> Blocca IP
          </Button>
          <button onClick={() => setAutoRefresh(!autoRefresh)}
            className={`text-[10px] px-2 py-1 rounded-md border transition-colors ${autoRefresh ? "bg-[var(--ok)]/10 border-[var(--ok)]/20 text-[var(--ok)]" : "bg-[var(--bg-hover)] border-[var(--bg-border)] text-[var(--text-muted)]"}`}
            data-testid="toggle-auto-refresh"
          >
            {autoRefresh ? "Auto-refresh ON" : "Auto-refresh OFF"}
          </button>
          <Button size="sm" variant="outline" onClick={fetchData} className="h-7 text-[10px] gap-1">
            <ArrowClockwise size={12} /> Aggiorna
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        <StatCard icon={<XCircle size={14} className="text-[var(--critical)]" />} label="Login Falliti 24h" value={s.failed_logins_24h} variant={s.failed_logins_24h > 10 ? "danger" : s.failed_logins_24h > 0 ? "warning" : "default"} />
        <StatCard icon={<ShieldCheck size={14} className="text-[var(--ok)]" />} label="Login OK 24h" value={s.success_logins_24h} variant="success" />
        <StatCard icon={<Lock size={14} className="text-[var(--critical)]" />} label="Account Bloccati" value={s.locked_accounts} variant={s.locked_accounts > 0 ? "danger" : "default"} />
        <StatCard icon={<Prohibit size={14} className="text-red-500" />} label="IP Bloccati" value={s.blocked_ips || 0} variant={(s.blocked_ips || 0) > 0 ? "danger" : "default"} />
        <StatCard icon={<UserCircle size={14} className="text-indigo-400" />} label="Sessioni Attive" value={s.active_sessions} />
        <StatCard icon={<ArrowClockwise size={14} className="text-yellow-400" />} label="Token Revocati" value={s.revoked_tokens_24h} variant={s.revoked_tokens_24h > 5 ? "warning" : "default"} />
        <StatCard icon={<Warning size={14} className="text-[var(--critical)]" />} label="Eventi Critici" value={s.critical_events_24h} variant={s.critical_events_24h > 0 ? "danger" : "default"} />
        <StatCard icon={<ShieldCheck size={14} className="text-emerald-400" />} label="2FA Attivo" value={s.twofa_coverage} variant="success" />
      </div>

      {/* Blocked IPs Panel (always visible when there are blocked IPs) */}
      {blockedIps.active.length > 0 && (
        <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20" data-testid="blocked-ips-panel">
          <p className="text-[10px] text-red-400 uppercase tracking-wider font-bold mb-2 flex items-center gap-1">
            <Prohibit size={10} /> IP Attualmente Bloccati ({blockedIps.active.length})
          </p>
          <div className="space-y-1">
            {blockedIps.active.map((b, i) => (
              <div key={i} className="flex items-center justify-between px-2 py-1.5 rounded-md bg-[var(--bg-card)] border border-red-500/10 text-[10px]">
                <div className="flex items-center gap-3">
                  <span className="font-mono font-bold text-red-400">{b.ip}</span>
                  <span className="text-[var(--text-muted)] truncate max-w-[200px]">{b.reason}</span>
                  <span className="text-[var(--text-muted)]">{timeAgo(b.blocked_at)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`font-mono ${b.permanent ? "text-red-400 font-bold" : "text-[var(--medium)]"}`}>
                    {b.permanent ? "PERMANENTE" : timeRemaining(b.expires_at)}
                  </span>
                  <span className="text-[var(--text-muted)]">da {b.blocked_by}</span>
                  <Button size="sm" variant="ghost" onClick={() => handleUnblock(b.ip)} className="h-6 text-[9px] gap-1 text-[var(--ok)] hover:text-[var(--ok)] hover:bg-[var(--ok)]/10" data-testid={`unblock-${b.ip}`}>
                    <LockOpen size={10} /> Sblocca
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Timeline + Suspicious IPs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]">
          <TimelineBar data={data.timeline} />
        </div>
        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="suspicious-ips">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-2 flex items-center gap-1">
            <Globe size={10} /> IP Sospetti (24h)
          </p>
          {data.suspicious_ips.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)] py-4 text-center">Nessun IP sospetto</p>
          ) : (
            <ScrollArea className="h-32">
              <div className="space-y-1">
                {data.suspicious_ips.map((ip, i) => {
                  const isBlocked = blockedIps.active.some(b => b.ip === ip.ip);
                  return (
                    <div key={i} className={`flex items-center justify-between px-2 py-1.5 rounded-md text-[10px] ${ip.attempts >= 10 ? "bg-[var(--critical-bg)] border border-[var(--critical-border)]" : "bg-[var(--bg-hover)]"}`}>
                      <div className="flex items-center gap-2">
                        <span className={`font-mono font-bold ${ip.attempts >= 10 ? "text-[var(--critical)]" : "text-[var(--text-primary)]"}`}>{ip.ip}</span>
                        <span className="text-[var(--text-muted)]">{ip.targeted_emails.join(", ")}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`font-bold ${ip.attempts >= 10 ? "text-[var(--critical)]" : "text-[var(--medium)]"}`}>{ip.attempts}x</span>
                        {isBlocked ? (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 font-bold">BLOCCATO</span>
                        ) : (
                          <Button size="sm" variant="ghost" onClick={() => handleBlock(ip.ip, `Sospetto: ${ip.attempts} tentativi falliti`)} className="h-5 text-[9px] gap-0.5 text-red-400 hover:bg-red-500/10 px-1.5" data-testid={`block-${ip.ip}`}>
                            <Prohibit size={9} /> Blocca
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </div>
      </div>

      {/* Failed Logins + Critical Events */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="failed-logins-list">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-2 flex items-center gap-1">
            <XCircle size={10} className="text-[var(--critical)]" /> Ultimi Login Falliti
          </p>
          {data.failed_logins.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)] py-4 text-center">Nessun login fallito nelle ultime 24h</p>
          ) : (
            <ScrollArea className="h-48">
              <div className="space-y-1">
                {data.failed_logins.map((log, i) => (
                  <div key={i} className="flex items-center justify-between px-2 py-1.5 rounded-md bg-[var(--bg-hover)] text-[10px]">
                    <div className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 rounded-full bg-[var(--critical)]" />
                      <span className="font-mono text-[var(--text-primary)]">{log.user_email || "sconosciuto"}</span>
                      <span className="text-[var(--text-muted)]">da {log.ip_address || "?"}</span>
                    </div>
                    <span className="text-[var(--text-muted)]">
                      {log.timestamp ? new Date(log.timestamp).toLocaleString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}
                    </span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </div>

        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="critical-events-list">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-2 flex items-center gap-1">
            <Warning size={10} className="text-[var(--medium)]" /> Eventi Critici e Warning
          </p>
          {data.critical_events.length === 0 ? (
            <p className="text-xs text-[var(--ok)] py-4 text-center flex items-center justify-center gap-1">
              <ShieldCheck size={14} /> Nessun evento critico nelle ultime 24h
            </p>
          ) : (
            <ScrollArea className="h-48">
              <div className="space-y-1">
                {data.critical_events.map((evt, i) => {
                  const sev = severityColors[evt.severity] || severityColors.info;
                  return (
                    <div key={i} className={`flex items-center justify-between px-2 py-1.5 rounded-md ${sev.bg} border ${sev.border} text-[10px]`}>
                      <div className="flex items-center gap-2">
                        <div className={`w-1.5 h-1.5 rounded-full ${sev.dot}`} />
                        <span className={`font-medium ${sev.text}`}>{actionLabels[evt.action] || evt.action}</span>
                        <span className="text-[var(--text-muted)]">{evt.user_email || ""}</span>
                        {evt.ip_address && <span className="text-[var(--text-muted)] font-mono">{evt.ip_address}</span>}
                      </div>
                      <span className="text-[var(--text-muted)]">
                        {evt.timestamp ? new Date(evt.timestamp).toLocaleString("it-IT", { hour: "2-digit", minute: "2-digit" }) : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </div>
      </div>

      {/* Locked Accounts */}
      {data.locked_accounts.length > 0 && (
        <div className="p-3 rounded-lg bg-[var(--critical-bg)] border border-[var(--critical-border)]" data-testid="locked-accounts-panel">
          <p className="text-[10px] text-[var(--critical)] uppercase tracking-wider font-bold mb-2 flex items-center gap-1">
            <Lock size={10} /> Account Bloccati
          </p>
          <div className="space-y-1">
            {data.locked_accounts.map((acc, i) => (
              <div key={i} className="flex items-center justify-between px-2 py-1.5 rounded-md bg-[var(--bg-card)] text-[10px]">
                <span className="font-mono text-[var(--critical)]">{acc.email}</span>
                <span className="text-[var(--text-muted)]">
                  Bloccato: {acc.locked_at ? new Date(acc.locked_at).toLocaleString("it-IT") : "N/D"} | 
                  Sblocco: {acc.unlock_at ? new Date(acc.unlock_at).toLocaleString("it-IT") : "N/D"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Block History */}
      {blockedIps.history.length > 0 && (
        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="block-history">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-2">Storico Blocchi IP</p>
          <ScrollArea className="h-24">
            <div className="space-y-1">
              {blockedIps.history.slice(0, 20).map((b, i) => (
                <div key={i} className="flex items-center justify-between px-2 py-1 rounded-md bg-[var(--bg-hover)] text-[9px] text-[var(--text-muted)]">
                  <div className="flex items-center gap-2">
                    <span className="font-mono">{b.ip}</span>
                    <span>{b.reason}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span>{b.unblocked ? "Sbloccato" : "Scaduto"} {timeAgo(b.unblocked_at || b.expires_at)}</span>
                    {b.unblocked_by && <span>da {b.unblocked_by}</span>}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* Manual Block Dialog */}
      <Dialog open={showManualBlock} onOpenChange={setShowManualBlock}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-md">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <Prohibit size={18} className="text-red-400" /> Blocca IP Manualmente
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-[var(--text-muted)] text-xs">Indirizzo IP</Label>
              <Input value={blockForm.ip} onChange={e => setBlockForm({ ...blockForm, ip: e.target.value })} placeholder="192.168.1.100" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="block-ip-input" />
            </div>
            <div>
              <Label className="text-[var(--text-muted)] text-xs">Motivo</Label>
              <Input value={blockForm.reason} onChange={e => setBlockForm({ ...blockForm, reason: e.target.value })} placeholder="Tentativo di intrusione" className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)]" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[var(--text-muted)] text-xs">Durata (ore)</Label>
                <Input type="number" value={blockForm.duration_hours} onChange={e => setBlockForm({ ...blockForm, duration_hours: parseInt(e.target.value) || 6 })} min={1} className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)]" disabled={blockForm.permanent} />
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={blockForm.permanent} onChange={e => setBlockForm({ ...blockForm, permanent: e.target.checked })} className="rounded" />
                  <span className="text-xs text-red-400 font-medium">Permanente</span>
                </label>
              </div>
            </div>
            <Button onClick={handleManualBlock} className="w-full bg-red-600 hover:bg-red-700 text-white" data-testid="confirm-block-btn">
              <Prohibit size={14} className="mr-1" /> Blocca IP
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Config Dialog */}
      <Dialog open={showConfig} onOpenChange={setShowConfig}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-md">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <Gear size={18} className="text-indigo-400" /> Configurazione Blocco IP
            </DialogTitle>
          </DialogHeader>
          {config && (
            <div className="space-y-3">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={configForm.enabled ?? true} onChange={e => setConfigForm({ ...configForm, enabled: e.target.checked })} className="rounded" />
                <span className="text-xs text-[var(--text-primary)]">Blocco IP attivo</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={configForm.auto_ban_enabled ?? true} onChange={e => setConfigForm({ ...configForm, auto_ban_enabled: e.target.checked })} className="rounded" />
                <span className="text-xs text-[var(--text-primary)]">Auto-ban attivo</span>
              </label>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="text-[var(--text-muted)] text-[10px]">Max tentativi</Label>
                  <Input type="number" value={configForm.max_attempts ?? 10} onChange={e => setConfigForm({ ...configForm, max_attempts: parseInt(e.target.value) || 10 })} min={1} className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="config-max-attempts" />
                </div>
                <div>
                  <Label className="text-[var(--text-muted)] text-[10px]">Finestra (min)</Label>
                  <Input type="number" value={configForm.window_minutes ?? 30} onChange={e => setConfigForm({ ...configForm, window_minutes: parseInt(e.target.value) || 30 })} min={1} className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)]" />
                </div>
                <div>
                  <Label className="text-[var(--text-muted)] text-[10px]">Blocco (ore)</Label>
                  <Input type="number" value={configForm.block_duration_hours ?? 6} onChange={e => setConfigForm({ ...configForm, block_duration_hours: parseInt(e.target.value) || 6 })} min={1} className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)]" />
                </div>
              </div>
              <div>
                <Label className="text-[var(--text-muted)] text-[10px]">IP Whitelist (uno per riga)</Label>
                <textarea value={whitelistInput} onChange={e => setWhitelistInput(e.target.value)} placeholder="192.168.1.1&#10;10.0.0.1" rows={3} className="w-full rounded-md bg-[var(--bg-panel)] border border-[var(--bg-border)] text-[var(--text-primary)] text-xs p-2 font-mono" data-testid="config-whitelist" />
              </div>
              <Button onClick={handleSaveConfig} className="w-full bg-indigo-600 hover:bg-indigo-700 text-white" data-testid="save-config-btn">
                <FloppyDisk size={14} className="mr-1" /> Salva Configurazione
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
