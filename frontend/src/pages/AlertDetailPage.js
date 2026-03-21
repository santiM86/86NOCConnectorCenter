import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { ArrowLeft, Clock, HardDrive, MapPin, User, CheckCircle, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function AlertDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [alert, setAlert] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { fetchAlert(); }, [id]);

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
      </div>
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
