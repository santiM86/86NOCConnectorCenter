import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API, useAuth } from "@/App";
import { toast } from "sonner";
import { ArrowLeft, Clock, HardDrive, MapPin, User, CheckCircle, Warning, Bell, XCircle, MoonStars, BellSlash, ArrowUp, BookOpen, Lightning, CaretRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function AlertDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [alert, setAlert] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notifLog, setNotifLog] = useState([]);
  const [notifLoading, setNotifLoading] = useState(false);
  const [runbookMatches, setRunbookMatches] = useState([]);
  const [runbookCtx, setRunbookCtx] = useState(null);
  const [runbookLoading, setRunbookLoading] = useState(false);
  const [openRunbookId, setOpenRunbookId] = useState(null);

  useEffect(() => { fetchAlert(); }, [id]);
  useEffect(() => {
    if (!id) return;
    setRunbookLoading(true);
    axios.get(`${API}/runbooks/match/alert/${id}`)
      .then(r => {
        setRunbookMatches(r.data?.matches || []);
        setRunbookCtx(r.data?.context || null);
      })
      .catch(() => { setRunbookMatches([]); setRunbookCtx(null); })
      .finally(() => setRunbookLoading(false));
  }, [id]);
  useEffect(() => {
    if (isAdmin && id) {
      setNotifLoading(true);
      axios.get(`${API}/alerts/${id}/notification-log`)
        .then(r => setNotifLog(r.data || []))
        .catch(() => setNotifLog([]))
        .finally(() => setNotifLoading(false));
    }
  }, [id, isAdmin]);

  const fetchAlert = async () => {
    try { const r = await axios.get(`${API}/alerts/${id}`); setAlert(r.data); }
    catch { toast.error("Alert non trovato"); navigate("/alerts"); }
    finally { setLoading(false); }
  };

  const handleAck = async () => {
    try { await axios.patch(`${API}/alerts/${id}`, { status: "acknowledged" }); fetchAlert(); toast.success("Alert confermato"); }
    catch { toast.error("Errore"); }
  };
  const handleResolve = async () => {
    try { await axios.patch(`${API}/alerts/${id}`, { status: "resolved" }); fetchAlert(); toast.success("Alert risolto"); }
    catch { toast.error("Errore"); }
  };

  if (loading) return <div className="p-6 flex items-center justify-center"><p className="text-[var(--text-muted)] text-xs">Caricamento...</p></div>;
  if (!alert) return null;

  const sevColors = {
    critical: { text: "var(--critical)", bg: "var(--critical-bg)", border: "var(--critical-border)" },
    high: { text: "var(--high)", bg: "var(--high-bg)", border: "var(--high-border)" },
    medium: { text: "var(--medium)", bg: "var(--medium-bg)", border: "var(--medium-border)" },
    low: { text: "var(--low)", bg: "var(--low-bg)", border: "var(--low-border)" }
  };
  const c = sevColors[alert.severity] || sevColors.low;

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="alert-detail-page">
      <Button variant="ghost" size="sm" onClick={() => navigate("/alerts")}
        className="mb-3 text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-md gap-1.5 text-xs h-7" data-testid="back-btn">
        <ArrowLeft size={14} /> Indietro
      </Button>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="space-y-3">
          <div className="noc-panel p-5" style={{ borderColor: c.border }}>
            <div className="flex items-start justify-between mb-3">
              <span className="severity-badge text-xs px-2.5 py-1" style={{ color: c.text, backgroundColor: c.bg, borderColor: c.border }}>
                {alert.severity.toUpperCase()}
              </span>
              <span className={`text-[10px] uppercase tracking-wider status-${alert.status}`} data-testid="alert-status">{alert.status}</span>
            </div>
            <h1 className="font-heading text-base font-bold text-[var(--text-primary)] mb-1.5" data-testid="alert-title">{alert.title}</h1>
            <p className="text-[var(--text-secondary)] text-xs mb-4">{alert.message}</p>
            <div className="flex gap-2">
              {alert.status === "active" && (
                <Button onClick={handleAck} className="rounded-md bg-[var(--bg-card)] hover:bg-[var(--bg-hover)] text-[var(--text-primary)] text-xs h-8 gap-1.5" data-testid="ack-btn">
                  <Warning size={14} /> Conferma
                </Button>
              )}
              {alert.status !== "resolved" && (
                <Button onClick={handleResolve} variant="outline" className="rounded-md border-[var(--low-border)] text-[var(--low)] hover:bg-[var(--low-bg)] text-xs h-8 gap-1.5" data-testid="resolve-btn">
                  <CheckCircle size={14} /> Risolvi
                </Button>
              )}
            </div>
          </div>

          <div className="noc-panel p-5">
            <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">Dettagli</h3>
            <div className="space-y-3">
              <DetailRow icon={<HardDrive size={16} />} label="Dispositivo" value={alert.device_name} sub={alert.device_type?.toUpperCase()} />
              <DetailRow icon={<MapPin size={16} />} label="IP" value={alert.ip_address} mono />
              <DetailRow icon={<User size={16} />} label="Cliente" value={alert.client_name} />
              <DetailRow icon={<Clock size={16} />} label="Data/Ora" value={new Date(alert.created_at).toLocaleString("it-IT")} mono />
              {alert.acknowledged_at && <DetailRow icon={<CheckCircle size={16} />} label="Confermato" value={`${alert.acknowledged_by} - ${new Date(alert.acknowledged_at).toLocaleString("it-IT")}`} />}
              {alert.resolved_at && <DetailRow icon={<CheckCircle size={16} />} label="Risolto" value={new Date(alert.resolved_at).toLocaleString("it-IT")} mono />}
            </div>
          </div>

          <div className="noc-panel p-5">
            <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-2">Fonte</h3>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="rounded-md border-[var(--bg-border)] text-[var(--text-secondary)] uppercase text-[10px]">{alert.source_type}</Badge>
              <span className="text-[var(--text-muted)] text-[10px]">ID: <span className="font-mono text-[var(--text-secondary)]">{alert.id.substring(0, 8)}</span></span>
            </div>
          </div>
        </div>

        <div className="noc-panel p-5">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">Dati Grezzi ({alert.source_type.toUpperCase()})</h3>
          <div className="terminal-block" data-testid="raw-data-block">
            <pre className="text-[var(--ok)] text-[11px] leading-relaxed"><code>
              {alert.raw_data ? (() => { try { return JSON.stringify(JSON.parse(alert.raw_data), null, 2); } catch { return alert.raw_data; } })() : "Nessun dato grezzo"}
            </code></pre>
          </div>
        </div>

        {isAdmin && (
          <div className="noc-panel p-5 lg:col-span-2" data-testid="notification-log-panel">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest flex items-center gap-1.5">
                <Bell size={13} /> Log notifiche (admin)
              </h3>
              <span className="text-[10px] text-[var(--text-muted)] font-mono">{notifLog.length} record</span>
            </div>
            {notifLoading ? (
              <p className="text-[var(--text-muted)] text-xs">Caricamento...</p>
            ) : notifLog.length === 0 ? (
              <p className="text-[var(--text-muted)] text-xs">Nessuna notifica registrata per questo alert.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="alert-table min-w-[680px]" data-testid="notification-log-table">
                  <thead>
                    <tr>
                      <th>Data/Ora</th>
                      <th>Tipo</th>
                      <th>Destinatario</th>
                      <th>Canale</th>
                      <th>Esito</th>
                      <th>Dettaglio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {notifLog.map((n, i) => {
                      const outcomeMeta = {
                        delivered: { icon: <CheckCircle size={12} weight="bold" />, color: "#34C759", label: "INVIATA" },
                        failed: { icon: <XCircle size={12} weight="bold" />, color: "#FF3B30", label: "FALLITA" },
                        expired: { icon: <XCircle size={12} />, color: "#FF9500", label: "SUB SCADUTA" },
                        skipped_quiet_hours: { icon: <MoonStars size={12} />, color: "#5E5CE6", label: "QUIET HOURS" },
                        no_subscriptions: { icon: <BellSlash size={12} />, color: "#8E8E93", label: "NESSUNA SUB" },
                        vapid_not_configured: { icon: <XCircle size={12} />, color: "#8E8E93", label: "NO VAPID" },
                      }[n.outcome] || { icon: null, color: "#8E8E93", label: n.outcome?.toUpperCase() };
                      const typeColor = n.type === "escalation" ? "#FF3B30" : "#5E5CE6";
                      return (
                        <tr key={i}>
                          <td className="font-mono text-[10px] text-[var(--text-muted)]">
                            {n.created_at ? new Date(n.created_at).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
                          </td>
                          <td>
                            <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded border font-bold uppercase"
                              style={{ color: typeColor, borderColor: `${typeColor}66`, background: `${typeColor}15` }}>
                              {n.type === "escalation" ? <ArrowUp size={10} weight="bold" /> : null}
                              {n.type || "initial"}
                            </span>
                          </td>
                          <td>
                            <div className="flex flex-col">
                              <span className="text-[var(--text-primary)] text-xs">{n.user_name || n.user_email || n.user_id?.substring(0, 8)}</span>
                              <span className="text-[9px] text-[var(--text-muted)] font-mono">{n.user_email}</span>
                            </div>
                          </td>
                          <td>
                            <span className="text-[9px] px-1.5 py-0.5 rounded border border-[var(--bg-border)] text-[var(--text-muted)] uppercase font-mono">
                              {n.channel || "web_push"}
                            </span>
                          </td>
                          <td>
                            <span className="inline-flex items-center gap-1 text-[10px] font-bold" style={{ color: outcomeMeta.color }}>
                              {outcomeMeta.icon} {outcomeMeta.label}
                            </span>
                          </td>
                          <td className="text-[9px] text-[var(--text-muted)] font-mono truncate max-w-[180px]" title={n.error || n.endpoint}>
                            {n.error || (n.endpoint ? `...${n.endpoint}` : "")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ============ RUNBOOK SUGGERITI (auto-match vendor + capability) ============ */}
        <div className="mt-5 bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded-lg p-4 sm:p-5" data-testid="alert-runbooks-panel">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div className="flex items-center gap-2">
              <BookOpen size={16} weight="bold" className="text-indigo-400" />
              <h2 className="text-sm font-bold text-[var(--text-primary)]">Runbook suggeriti</h2>
              {runbookMatches.length > 0 && (
                <span className="text-[9px] font-mono bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 rounded px-1.5 py-0.5">
                  {runbookMatches.length}
                </span>
              )}
            </div>
            {runbookCtx && (runbookCtx.profile_key || runbookCtx.vendor) && (
              <div className="flex items-center gap-1.5 text-[10px] font-mono text-white/50">
                <Lightning size={11} weight="bold" className="text-amber-400" />
                <span>device:</span>
                {runbookCtx.vendor && <span className="text-cyan-300">{runbookCtx.vendor}</span>}
                {runbookCtx.profile_key && <span className="text-indigo-300">/{runbookCtx.profile_key}</span>}
              </div>
            )}
          </div>

          {runbookLoading && (
            <p className="text-[11px] text-white/40">Analisi runbook...</p>
          )}

          {!runbookLoading && runbookMatches.length === 0 && (
            <div className="py-4 text-center">
              <p className="text-[12px] text-white/50">Nessun runbook corrisponde a questo alert.</p>
              <button
                onClick={() => navigate("/runbooks")}
                className="mt-2 text-[11px] text-indigo-400 hover:text-indigo-300 underline"
                data-testid="runbook-create-link"
              >
                Crea il primo runbook →
              </button>
            </div>
          )}

          {!runbookLoading && runbookMatches.length > 0 && (
            <div className="space-y-2">
              {runbookMatches.map((rb, idx) => (
                <RunbookMatchCard
                  key={rb.id}
                  rb={rb}
                  isTop={idx === 0}
                  expanded={openRunbookId === rb.id}
                  onToggle={() => setOpenRunbookId(openRunbookId === rb.id ? null : rb.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RunbookMatchCard({ rb, isTop, expanded, onToggle }) {
  const steps = rb.steps || [];
  return (
    <div
      className={`border rounded-md transition-all ${
        isTop
          ? "border-indigo-500/40 bg-indigo-500/5"
          : "border-[var(--bg-border)] bg-black/20 hover:border-indigo-500/20"
      }`}
      data-testid={`runbook-match-${rb.id}`}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-3 p-3 text-left"
        data-testid={`runbook-toggle-${rb.id}`}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            {isTop && (
              <span className="text-[8px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded px-1.5 py-0.5 uppercase tracking-widest">
                Best Match
              </span>
            )}
            <span className="text-[13px] font-bold text-white truncate">{rb.title}</span>
            <span className="text-[9px] font-mono text-white/40 ml-auto flex-shrink-0">
              score {rb._match_score}
            </span>
          </div>
          {rb.description && <p className="text-[11px] text-white/50 truncate">{rb.description}</p>}
          {rb._match_reasons && rb._match_reasons.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {rb._match_reasons.slice(0, 4).map((r, i) => (
                <span key={i} className="text-[8px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-white/50">
                  {r}
                </span>
              ))}
            </div>
          )}
        </div>
        <CaretRight size={14} className={`text-white/40 flex-shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`} />
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-white/5" data-testid={`runbook-steps-${rb.id}`}>
          <p className="text-[9px] uppercase tracking-widest text-white/40 mb-2 mt-2">
            Procedura — {steps.length} step
          </p>
          <ol className="space-y-2.5">
            {steps.map((s, i) => (
              <li key={i} className="pl-5 relative">
                <span className="absolute left-0 top-0 w-4 h-4 rounded-full bg-indigo-500/20 border border-indigo-500/40 text-[9px] font-bold text-indigo-200 flex items-center justify-center">
                  {s.order || i + 1}
                </span>
                <p className="text-[12px] font-bold text-white leading-tight">{s.title}</p>
                {s.description && <p className="text-[11px] text-white/60 mt-0.5">{s.description}</p>}
                {s.command && (
                  <pre className="mt-1 bg-black/60 border border-white/5 rounded p-2 text-[10px] font-mono text-emerald-300 whitespace-pre-wrap overflow-x-auto">
                    {s.command}
                  </pre>
                )}
                {s.expected_result && (
                  <p className="text-[10px] text-cyan-300/80 mt-1 font-mono">
                    → {s.expected_result}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function DetailRow({ icon, label, value, sub, mono }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="text-[var(--text-muted)] mt-0.5">{icon}</span>
      <div className="flex-1">
        <p className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest mb-0.5">{label}</p>
        <p className={`text-[var(--text-primary)] text-xs ${mono ? "font-mono" : ""}`}>
          {value}{sub && <span className="ml-1.5 text-[10px] text-[var(--text-muted)] uppercase">{sub}</span>}
        </p>
      </div>
    </div>
  );
}
