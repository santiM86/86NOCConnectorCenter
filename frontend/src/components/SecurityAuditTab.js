import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import {
  ShieldCheck, Warning, XCircle, Lock, Eye,
  ArrowClockwise, UserCircle, Globe, Clock
} from "@phosphor-icons/react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";

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
          const failedH = d.total > 0 ? (d.failed / d.total) * totalH : 0;
          const dayLabel = d.date.slice(5);
          return (
            <div key={i} className="flex-1 flex flex-col items-center gap-0.5" title={`${d.date}: ${d.success} OK, ${d.failed} falliti, ${d.total} totali`}>
              <div className="w-full relative rounded-t-sm overflow-hidden" style={{ height: `${totalH}%` }}>
                <div className="absolute bottom-0 w-full bg-indigo-500/40 rounded-t-sm" style={{ height: "100%" }} />
                {failedH > 0 && (
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

export function SecurityAuditTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/audit/security-dashboard`);
      setData(res.data);
    } catch (e) {
      console.error("Security dashboard error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    if (autoRefresh) {
      const interval = setInterval(fetchData, 15000);
      return () => clearInterval(interval);
    }
  }, [fetchData, autoRefresh]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40">
        <ArrowClockwise size={20} className="animate-spin text-[var(--text-muted)]" />
      </div>
    );
  }

  if (!data) {
    return <p className="text-[var(--text-muted)] text-sm">Errore nel caricamento dei dati di sicurezza.</p>;
  }

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
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`text-[10px] px-2 py-1 rounded-md border transition-colors ${
              autoRefresh 
                ? "bg-[var(--ok)]/10 border-[var(--ok)]/20 text-[var(--ok)]" 
                : "bg-[var(--bg-hover)] border-[var(--bg-border)] text-[var(--text-muted)]"
            }`}
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
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        <StatCard
          icon={<XCircle size={14} className="text-[var(--critical)]" />}
          label="Login Falliti 24h"
          value={s.failed_logins_24h}
          variant={s.failed_logins_24h > 10 ? "danger" : s.failed_logins_24h > 0 ? "warning" : "default"}
        />
        <StatCard
          icon={<ShieldCheck size={14} className="text-[var(--ok)]" />}
          label="Login OK 24h"
          value={s.success_logins_24h}
          variant="success"
        />
        <StatCard
          icon={<Lock size={14} className="text-[var(--critical)]" />}
          label="Account Bloccati"
          value={s.locked_accounts}
          variant={s.locked_accounts > 0 ? "danger" : "default"}
        />
        <StatCard
          icon={<UserCircle size={14} className="text-indigo-400" />}
          label="Sessioni Attive"
          value={s.active_sessions}
        />
        <StatCard
          icon={<ArrowClockwise size={14} className="text-yellow-400" />}
          label="Token Revocati 24h"
          value={s.revoked_tokens_24h}
          variant={s.revoked_tokens_24h > 5 ? "warning" : "default"}
        />
        <StatCard
          icon={<Warning size={14} className="text-[var(--critical)]" />}
          label="Eventi Critici 24h"
          value={s.critical_events_24h}
          variant={s.critical_events_24h > 0 ? "danger" : "default"}
        />
        <StatCard
          icon={<ShieldCheck size={14} className="text-emerald-400" />}
          label="2FA Attivo"
          value={s.twofa_coverage}
          variant="success"
        />
      </div>

      {/* Timeline + Suspicious IPs row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Timeline */}
        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]">
          <TimelineBar data={data.timeline} />
        </div>

        {/* Suspicious IPs */}
        <div className="p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="suspicious-ips">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-2 flex items-center gap-1">
            <Globe size={10} /> IP Sospetti (24h)
          </p>
          {data.suspicious_ips.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)] py-4 text-center">Nessun IP sospetto rilevato</p>
          ) : (
            <ScrollArea className="h-32">
              <div className="space-y-1">
                {data.suspicious_ips.map((ip, i) => (
                  <div key={i} className={`flex items-center justify-between px-2 py-1.5 rounded-md text-[10px] ${
                    ip.attempts >= 5 ? "bg-[var(--critical-bg)] border border-[var(--critical-border)]" : "bg-[var(--bg-hover)]"
                  }`}>
                    <div className="flex items-center gap-2">
                      <span className={`font-mono font-bold ${ip.attempts >= 5 ? "text-[var(--critical)]" : "text-[var(--text-primary)]"}`}>{ip.ip}</span>
                      <span className="text-[var(--text-muted)]">{ip.targeted_emails.join(", ")}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`font-bold ${ip.attempts >= 5 ? "text-[var(--critical)]" : "text-[var(--medium)]"}`}>{ip.attempts}x</span>
                      {ip.attempts >= 5 && <Lock size={10} className="text-[var(--critical)]" />}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </div>
      </div>

      {/* Failed Logins + Critical Events */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Failed Logins */}
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

        {/* Critical Events */}
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
    </div>
  );
}
