import { useState, useEffect, useCallback } from "react";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";
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
  Prohibit,
  UserCircleMinus,
  Detective,
  Password,
  ShieldStar,
  Keyhole,
  MapPin,
  Virus,
  ArrowsDownUp,
  Export,
  Trash,
  DownloadSimple,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

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
  ip_whitelist: Prohibit,
  session_invalidation: UserCircleMinus,
  suspicious_login: Detective,
  password_policy: Password,
  csrf_protection: ShieldStar,
  api_key_rotation: Keyhole,
  geo_ip_detection: MapPin,
  honeypot: Virus,
  body_size_limit: ArrowsDownUp,
  siem_export: Export,
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
  ip_whitelist: "#dc2626",
  session_invalidation: "#7c3aed",
  suspicious_login: "#d97706",
  password_policy: "#059669",
  csrf_protection: "#4f46e5",
  api_key_rotation: "#0891b2",
  geo_ip_detection: "#be185d",
  honeypot: "#b91c1c",
  body_size_limit: "#0d9488",
  siem_export: "#475569",
};

const CATEGORY_LABELS = {
  autenticazione: "Autenticazione",
  rete: "Rete & Trasporto",
  dati: "Protezione Dati",
  accesso: "Controllo Accesso",
  monitoraggio: "Monitoraggio & Alerting",
  difesa_attiva: "Difesa Attiva",
};

const CATEGORY_ORDER = ["autenticazione", "rete", "accesso", "dati", "monitoraggio", "difesa_attiva"];

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
        className="w-full flex items-center gap-3 p-3 text-left"
        onClick={onToggle}
        data-testid={`protection-toggle-${protection.id}`}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: `${color}15`, color }}
        >
          <Icon size={16} weight="bold" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[var(--text-primary)] truncate">
              {protection.name}
            </span>
            {isActive ? (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-emerald-500/10 text-emerald-400" data-testid={`protection-status-${protection.id}`}>
                <CheckCircle size={9} weight="fill" /> ATTIVA
              </span>
            ) : (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-red-500/10 text-red-400">
                <XCircle size={9} weight="fill" /> OFF
              </span>
            )}
          </div>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 truncate">
            {protection.description}
          </p>
        </div>
        <div className="text-[var(--text-muted)]">
          {expanded ? <CaretDown size={12} /> : <CaretRight size={12} />}
        </div>
      </button>

      {expanded && protection.details && (
        <div className="px-3 pb-3 border-t border-[var(--bg-border)]">
          <div className="pt-2 grid grid-cols-2 gap-2">
            {Object.entries(protection.details).map(([key, value]) => {
              if (Array.isArray(value)) {
                return (
                  <div key={key} className="col-span-2">
                    <span className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">
                      {key.replace(/_/g, " ")}
                    </span>
                    <div className="mt-1 space-y-0.5">
                      {value.map((item, i) => (
                        <div key={i} className="text-[10px] text-[var(--text-secondary)] bg-[var(--bg-app)] rounded px-2 py-0.5 font-mono">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }
              return (
                <div key={key}>
                  <span className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">
                    {key.replace(/_/g, " ")}
                  </span>
                  <p className="text-xs font-medium text-[var(--text-primary)] mt-0.5">
                    {typeof value === "boolean" ? (value ? "Si" : "No") : typeof value === "number" ? value.toLocaleString() : String(value)}
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
    <div className="flex items-center gap-2 py-1.5 px-3 border-b border-[var(--bg-border)] last:border-0 hover:bg-[var(--bg-app)]/50 transition-colors">
      <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase ${sev}`}>
        {event.severity || "info"}
      </span>
      <span className="text-[10px] font-medium text-[var(--text-primary)] flex-1 truncate">
        {event.action?.replace(/_/g, " ")}
        {event.user_email && <span className="text-[var(--text-muted)] ml-1">{event.user_email}</span>}
      </span>
      <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">{event.ip_address}</span>
      <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">
        {event.timestamp ? new Date(event.timestamp).toLocaleTimeString("it-IT") : ""}
      </span>
    </div>
  );
}

function SessionPanel({ onClose }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/security/sessions`).then(r => {
      setSessions(r.data.sessions || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const killSession = async (sid) => {
    try {
      await axios.delete(`${API}/security/sessions/${sid}`);
      setSessions(prev => prev.filter(s => s.session_id !== sid));
      toast.success("Sessione terminata");
    } catch { toast.error("Errore nella terminazione"); }
  };

  const killAllUser = async (uid) => {
    try {
      await axios.delete(`${API}/security/sessions/user/${uid}`);
      setSessions(prev => prev.filter(s => s.user_id !== uid));
      toast.success("Tutte le sessioni dell'utente terminate");
    } catch { toast.error("Errore"); }
  };

  return (
    <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-4" data-testid="session-panel">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <UserCircleMinus size={16} /> Sessioni Attive ({sessions.length})
        </h3>
        <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"><X size={16} /></button>
      </div>
      {loading ? (
        <p className="text-xs text-[var(--text-muted)]">Caricamento...</p>
      ) : sessions.length === 0 ? (
        <p className="text-xs text-[var(--text-muted)]">Nessuna sessione attiva nel DB</p>
      ) : (
        <div className="space-y-2 max-h-60 overflow-y-auto">
          {sessions.map(s => (
            <div key={s.session_id} className="flex items-center gap-2 text-xs bg-[var(--bg-app)] rounded p-2">
              <div className="flex-1 min-w-0">
                <div className="font-medium text-[var(--text-primary)]">{s.user_email || s.user_name}</div>
                <div className="text-[var(--text-muted)] text-[10px]">{s.ip_address} — {s.last_activity ? new Date(s.last_activity).toLocaleString("it-IT") : ""}</div>
              </div>
              <Button size="sm" variant="destructive" className="h-6 text-[10px] px-2" onClick={() => killSession(s.session_id)} data-testid={`kill-session-${s.session_id}`}>
                <Trash size={10} className="mr-1" /> Termina
              </Button>
              <Button size="sm" variant="outline" className="h-6 text-[10px] px-2 border-red-500/30 text-red-400 hover:bg-red-500/10" onClick={() => killAllUser(s.user_id)}>
                Tutte
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WhitelistPanel({ onClose }) {
  const [ips, setIps] = useState([]);
  const [enabled, setEnabled] = useState(false);
  const [newIp, setNewIp] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/security/ip-whitelist`).then(r => {
      setIps(r.data.ips || []);
      setEnabled(r.data.enabled || false);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const save = async () => {
    try {
      await axios.post(`${API}/security/ip-whitelist`, { ips, enabled });
      toast.success("Whitelist aggiornata");
    } catch { toast.error("Errore nel salvataggio"); }
  };

  const addIp = () => {
    if (newIp && !ips.includes(newIp)) {
      setIps(prev => [...prev, newIp]);
      setNewIp("");
    }
  };

  return (
    <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-4" data-testid="whitelist-panel">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <Prohibit size={16} /> IP Whitelist Admin
        </h3>
        <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"><X size={16} /></button>
      </div>
      {loading ? <p className="text-xs text-[var(--text-muted)]">Caricamento...</p> : (
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} className="accent-emerald-500" />
            Whitelist abilitata
          </label>
          <div className="flex gap-2">
            <input
              className="flex-1 bg-[var(--bg-app)] border border-[var(--bg-border)] rounded px-2 py-1 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)]"
              placeholder="192.168.1.0/24 o IP singolo"
              value={newIp} onChange={e => setNewIp(e.target.value)}
              onKeyDown={e => e.key === "Enter" && addIp()}
              data-testid="whitelist-input"
            />
            <Button size="sm" className="h-7 text-xs" onClick={addIp}>Aggiungi</Button>
          </div>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {ips.map((ip, i) => (
              <div key={i} className="flex items-center justify-between bg-[var(--bg-app)] rounded px-2 py-1 text-xs">
                <span className="font-mono text-[var(--text-primary)]">{ip}</span>
                <button className="text-red-400 hover:text-red-300" onClick={() => setIps(prev => prev.filter((_, j) => j !== i))}>
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
          <Button size="sm" className="w-full h-7 text-xs" onClick={save} data-testid="whitelist-save-btn">Salva Whitelist</Button>
        </div>
      )}
    </div>
  );
}

export default function SecurityDashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedCards, setExpandedCards] = useState({});
  const [activePanel, setActivePanel] = useState(null); // "sessions" | "whitelist" | null

  const fetchStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/security/status`);
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err.response?.data?.detail || "Errore nel caricamento");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const toggleCard = (id) => setExpandedCards((prev) => ({ ...prev, [id]: !prev[id] }));

  const exportLogs = async (format) => {
    try {
      const res = await axios.get(`${API}/security/export/audit-logs?format=${format}&days=30`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_logs.${format}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Export ${format.toUpperCase()} scaricato`);
    } catch {
      toast.error("Errore nell'export");
    }
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
          <button onClick={fetchStatus} className="ml-auto text-xs text-red-400 hover:text-red-300">Riprova</button>
        </div>
      </div>
    );
  }

  const { protections = [], summary = {}, recent_events = [] } = data || {};

  // Group protections by category
  const grouped = {};
  for (const p of protections) {
    const cat = p.category || "altro";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(p);
  }

  return (
    <div className="p-4 md:p-6 space-y-5 max-w-6xl" data-testid="security-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-bold text-[var(--text-primary)] flex items-center gap-2">
            <ShieldCheck size={22} weight="bold" className="text-emerald-400" />
            Security Dashboard
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {summary.total_protections || 0} protezioni anti-hacker attive
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => setActivePanel(activePanel === "whitelist" ? null : "whitelist")} data-testid="open-whitelist-btn">
            <Prohibit size={12} /> IP Whitelist
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => setActivePanel(activePanel === "sessions" ? null : "sessions")} data-testid="open-sessions-btn">
            <UserCircleMinus size={12} /> Sessioni
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => exportLogs("csv")} data-testid="export-csv-btn">
            <DownloadSimple size={12} /> CSV
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => exportLogs("json")} data-testid="export-json-btn">
            <DownloadSimple size={12} /> JSON
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={fetchStatus} data-testid="security-refresh-btn">
            <ArrowClockwise size={12} /> Aggiorna
          </Button>
        </div>
      </div>

      {/* Management Panels */}
      {activePanel === "sessions" && <SessionPanel onClose={() => setActivePanel(null)} />}
      {activePanel === "whitelist" && <WhitelistPanel onClose={() => setActivePanel(null)} />}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="security-summary">
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">Protezioni</div>
          <div className="text-2xl font-bold text-emerald-400 mt-1" data-testid="summary-total-protections">
            {summary.total_protections || 0}
            <span className="text-xs font-normal text-[var(--text-muted)]">/21</span>
          </div>
        </div>
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">IP Bloccati</div>
          <div className="text-2xl font-bold text-red-400 mt-1" data-testid="summary-blocked-ips">
            {summary.blocked_ips || 0}
          </div>
        </div>
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">Login Falliti 24h</div>
          <div className="text-2xl font-bold text-amber-400 mt-1" data-testid="summary-failed-logins">
            {summary.failed_logins_24h || 0}
          </div>
        </div>
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">Utenti 2FA</div>
          <div className="text-2xl font-bold text-violet-400 mt-1" data-testid="summary-2fa-users">
            {summary.users_with_2fa || 0}
          </div>
        </div>
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-3">
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">Stato</div>
          <div className="text-2xl font-bold mt-1" data-testid="summary-all-active">
            {summary.all_active ? (
              <span className="text-emerald-400 flex items-center gap-1"><CheckCircle size={20} weight="fill" /> OK</span>
            ) : (
              <span className="text-amber-400 flex items-center gap-1"><Warning size={20} weight="fill" /> ALERT</span>
            )}
          </div>
        </div>
      </div>

      {/* Grouped Protection Cards */}
      {CATEGORY_ORDER.map(cat => {
        const items = grouped[cat];
        if (!items || items.length === 0) return null;
        return (
          <div key={cat}>
            <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2 flex items-center gap-2">
              {CATEGORY_LABELS[cat] || cat} <span className="text-[var(--text-muted)]/60">({items.length})</span>
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2" data-testid={`protections-grid-${cat}`}>
              {items.map(p => (
                <ProtectionCard key={p.id} protection={p} expanded={expandedCards[p.id] || false} onToggle={() => toggleCard(p.id)} />
              ))}
            </div>
          </div>
        );
      })}

      {/* Recent Security Events */}
      {recent_events.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2 flex items-center gap-2">
            <Eye size={14} /> Ultimi Eventi di Sicurezza (24h)
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
