import { useState, useEffect, useCallback } from "react";
import { API } from "@/App";
import axios from "axios";
import {
  Shield,
  ShieldCheck,
  Lock,
  Key,
  Eye,
  Clock,
  Warning,
  ArrowClockwise,
  CaretDown,
  CaretRight,
  CheckCircle,
  XCircle,
  Fingerprint,
  Globe,
  Timer,
  FileText,
  Database as DatabaseIcon,
  LockKey,
} from "@phosphor-icons/react";

const PROTECTION_ICONS = {
  brute_force: Lock,
  rate_limiting: Globe,
  two_factor: Fingerprint,
  password_security: Key,
  session_management: Clock,
  encryption: LockKey,
  security_headers: Shield,
  cors: Globe,
  request_timeout: Timer,
  audit_logging: FileText,
  cache_control: DatabaseIcon,
};

const PROTECTION_COLORS = {
  brute_force: "#ef4444",
  rate_limiting: "#f59e0b",
  two_factor: "#8b5cf6",
  password_security: "#10b981",
  session_management: "#3b82f6",
  encryption: "#06b6d4",
  security_headers: "#6366f1",
  cors: "#ec4899",
  request_timeout: "#f97316",
  audit_logging: "#14b8a6",
  cache_control: "#64748b",
};

function ProtectionCard({ protection, expanded, onToggle }) {
  const Icon = PROTECTION_ICONS[protection.id] || Shield;
  const color = PROTECTION_COLORS[protection.id] || "#6366f1";
  const isActive = protection.status === "active";

  return (
    <div
      className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-panel)] overflow-hidden transition-all duration-200 hover:border-[var(--bg-border-hover)]"
      data-testid={`protection-card-${protection.id}`}
    >
      <button
        className="w-full flex items-center gap-3 p-4 text-left"
        onClick={onToggle}
        data-testid={`protection-toggle-${protection.id}`}
      >
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: `${color}15`, color }}
        >
          <Icon size={18} weight="bold" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-[var(--text-primary)] truncate">
              {protection.name}
            </span>
            {isActive ? (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400" data-testid={`protection-status-${protection.id}`}>
                <CheckCircle size={10} weight="fill" /> ATTIVA
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-500/10 text-red-400">
                <XCircle size={10} weight="fill" /> INATTIVA
              </span>
            )}
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 truncate">
            {protection.description}
          </p>
        </div>
        <div className="text-[var(--text-muted)]">
          {expanded ? <CaretDown size={14} /> : <CaretRight size={14} />}
        </div>
      </button>

      {expanded && protection.details && (
        <div className="px-4 pb-4 border-t border-[var(--bg-border)]">
          <div className="pt-3 grid grid-cols-2 gap-2">
            {Object.entries(protection.details).map(([key, value]) => {
              if (Array.isArray(value)) {
                return (
                  <div key={key} className="col-span-2">
                    <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                      {key.replace(/_/g, " ")}
                    </span>
                    <div className="mt-1 space-y-1">
                      {value.map((item, i) => (
                        <div
                          key={i}
                          className="text-xs text-[var(--text-secondary)] bg-[var(--bg-app)] rounded px-2 py-1 font-mono"
                        >
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }
              return (
                <div key={key}>
                  <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                    {key.replace(/_/g, " ")}
                  </span>
                  <p className="text-sm font-medium text-[var(--text-primary)] mt-0.5">
                    {typeof value === "number"
                      ? value.toLocaleString()
                      : String(value)}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function EventRow({ event }) {
  const severityColors = {
    critical: "text-red-400 bg-red-500/10",
    warning: "text-amber-400 bg-amber-500/10",
    info: "text-blue-400 bg-blue-500/10",
  };
  const sev = severityColors[event.severity] || severityColors.info;

  return (
    <div className="flex items-center gap-3 py-2 px-3 border-b border-[var(--bg-border)] last:border-0 hover:bg-[var(--bg-app)]/50 transition-colors">
      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase ${sev}`}>
        {event.severity || "info"}
      </span>
      <div className="flex-1 min-w-0">
        <span className="text-xs font-medium text-[var(--text-primary)]">
          {event.action?.replace(/_/g, " ")}
        </span>
        {event.user_email && (
          <span className="text-xs text-[var(--text-muted)] ml-2">
            {event.user_email}
          </span>
        )}
      </div>
      <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">
        {event.ip_address}
      </span>
      <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">
        {event.timestamp ? new Date(event.timestamp).toLocaleTimeString("it-IT") : ""}
      </span>
    </div>
  );
}

export default function SecurityDashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedCards, setExpandedCards] = useState({});

  const fetchStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/security/status`);
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err.response?.data?.detail || "Errore nel caricamento dello stato di sicurezza");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const toggleCard = (id) => {
    setExpandedCards((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]" data-testid="security-loading">
        <div className="text-[var(--text-muted)] flex items-center gap-2">
          <ArrowClockwise size={16} className="animate-spin" />
          Caricamento stato sicurezza...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6" data-testid="security-error">
        <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-4 flex items-center gap-3">
          <Warning size={20} className="text-red-400" />
          <div>
            <p className="text-sm font-medium text-red-400">Errore</p>
            <p className="text-xs text-red-400/70">{error}</p>
          </div>
          <button onClick={fetchStatus} className="ml-auto text-xs text-red-400 hover:text-red-300">
            Riprova
          </button>
        </div>
      </div>
    );
  }

  const { protections = [], summary = {}, recent_events = [] } = data || {};

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-6xl" data-testid="security-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-[var(--text-primary)] flex items-center gap-2">
            <ShieldCheck size={22} weight="bold" className="text-emerald-400" />
            Security Dashboard
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Stato delle protezioni anti-hacker attive
          </p>
        </div>
        <button
          onClick={fetchStatus}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--text-secondary)] bg-[var(--bg-panel)] border border-[var(--bg-border)] hover:bg-[var(--bg-app)] transition-colors"
          data-testid="security-refresh-btn"
        >
          <ArrowClockwise size={14} />
          Aggiorna
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="security-summary">
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Protezioni Attive</div>
          <div className="text-2xl font-bold text-emerald-400 mt-1" data-testid="summary-total-protections">
            {summary.total_protections || 0}
            <span className="text-xs font-normal text-[var(--text-muted)]">/11</span>
          </div>
        </div>
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">IP Bloccati</div>
          <div className="text-2xl font-bold text-red-400 mt-1" data-testid="summary-blocked-ips">
            {summary.blocked_ips || 0}
          </div>
        </div>
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Login Falliti 24h</div>
          <div className="text-2xl font-bold text-amber-400 mt-1" data-testid="summary-failed-logins">
            {summary.failed_logins_24h || 0}
          </div>
        </div>
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Utenti con 2FA</div>
          <div className="text-2xl font-bold text-violet-400 mt-1" data-testid="summary-2fa-users">
            {summary.users_with_2fa || 0}
          </div>
        </div>
      </div>

      {/* Protection Cards Grid */}
      <div>
        <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
          Protezioni Attive ({protections.length})
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="protections-grid">
          {protections.map((p) => (
            <ProtectionCard
              key={p.id}
              protection={p}
              expanded={expandedCards[p.id] || false}
              onToggle={() => toggleCard(p.id)}
            />
          ))}
        </div>
      </div>

      {/* Recent Security Events */}
      {recent_events.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
            <Eye size={16} />
            Ultimi Eventi di Sicurezza (24h)
          </h2>
          <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] overflow-hidden" data-testid="security-events-list">
            {recent_events.map((evt, i) => (
              <EventRow key={i} event={evt} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
