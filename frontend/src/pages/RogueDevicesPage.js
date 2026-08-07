import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  ShieldWarning, ArrowsClockwise, CheckCircle, ShieldSlash, Warning, ListChecks, Trash,
} from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("it-IT"); } catch { return iso; }
}

export default function RogueDevicesPage() {
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [status, setStatus] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [allowlist, setAllowlist] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [remedy, setRemedy] = useState(null);
  const [tab, setTab] = useState("alerts");

  const reload = useCallback(async () => {
    try {
      const [s, a, al] = await Promise.all([
        axios.get(`${API}/api/security/rogue/status`, { headers }),
        axios.get(`${API}/api/security/rogue/alerts`, { headers, params: { status_filter: "active" } }),
        axios.get(`${API}/api/security/rogue/allowlist`, { headers }),
      ]);
      setStatus(s.data); setAlerts(a.data.items || []); setAllowlist(al.data.items || []);
    } catch { toast.error("Errore caricamento Rogue Detection"); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const scan = async () => {
    setScanning(true);
    try {
      const r = await axios.post(`${API}/api/security/rogue/scan`, {}, { headers });
      const res = r.data.result || {};
      toast.success(`Scansione: ${res.new ?? 0} nuovi, ${res.alerts ?? 0} alert`);
      await reload();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore scansione"); }
    finally { setScanning(false); }
  };

  const authorize = async (a) => {
    if (!window.confirm(`Autorizzare il dispositivo ${a.raw_data}? Non riceverai più alert per questo MAC.`)) return;
    try {
      await axios.post(`${API}/api/security/rogue/authorize`,
        { client_id: a.client_id, mac: a.raw_data }, { headers });
      toast.success("Dispositivo autorizzato");
      await reload();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const showRemediation = async (a) => {
    try {
      const r = await axios.get(`${API}/api/security/rogue/remediation/${a.id}`, { headers });
      setRemedy(r.data);
    } catch (e) { toast.error("Errore remediation"); }
  };

  const removeAllow = async (item) => {
    if (!window.confirm(`Rimuovere ${item.mac} dall'allow-list?`)) return;
    try {
      await axios.delete(`${API}/api/security/rogue/allowlist`,
        { headers, data: { client_id: item.client_id, mac: item.mac } });
      toast.success("Rimosso"); await reload();
    } catch { toast.error("Errore"); }
  };

  const toggleEnabled = async (v) => {
    try {
      await axios.put(`${API}/api/security/rogue/config`, { enabled: v }, { headers });
      toast.success(v ? "Rilevamento attivo" : "Rilevamento disattivato");
      await reload();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const cfg = status?.config || {};

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto" data-testid="rogue-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <ShieldWarning size={26} className="text-orange-400" weight="duotone" />
          <div>
            <h1 className="text-lg font-bold">Rilevamento Dispositivi Rogue</h1>
            <p className="text-[11px] text-[var(--text-muted)]">
              Rileva dispositivi/MAC mai visti prima sulla rete di un cliente. Risposta suggerita a conferma umana.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase text-[var(--text-muted)]">Rilevamento</span>
            <Switch checked={!!cfg.enabled} onCheckedChange={toggleEnabled} data-testid="rogue-enabled-toggle" />
          </div>
          <Button onClick={scan} disabled={scanning} size="sm"
            className="gap-1 bg-orange-600 hover:bg-orange-700" data-testid="rogue-scan-btn">
            <ArrowsClockwise size={14} className={scanning ? "animate-spin" : ""} />
            {scanning ? "Scansione…" : "Scansiona ora"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-6">
        <Kpi icon={Warning} color="text-orange-400" label="Rogue attivi" value={status?.active_alerts} testid="rogue-kpi-active" />
        <Kpi icon={CheckCircle} color="text-emerald-400" label="MAC autorizzati" value={status?.allowlist_total} testid="rogue-kpi-allow" />
        <Kpi icon={ListChecks} color="text-cyan-400" label="Clienti monitorati" value={status?.clients_watched} testid="rogue-kpi-watched" />
      </div>

      <div className="flex gap-2 mb-3">
        <TabBtn active={tab === "alerts"} onClick={() => setTab("alerts")} testid="rogue-tab-alerts">Rilevati ({alerts.length})</TabBtn>
        <TabBtn active={tab === "allow"} onClick={() => setTab("allow")} testid="rogue-tab-allow">Allow-list ({allowlist.length})</TabBtn>
      </div>

      {tab === "alerts" && (
        alerts.length === 0 ? (
          <p className="text-[11px] text-[var(--text-muted)]" data-testid="rogue-empty">
            Nessun dispositivo rogue attivo. I nuovi dispositivi comparsi dopo l'attivazione verranno elencati qui.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--bg-border)]">
            <table className="w-full text-xs" data-testid="rogue-alerts-table">
              <thead className="bg-[var(--bg-card)] text-[var(--text-muted)]">
                <tr>
                  <th className="text-left px-3 py-2">Cliente</th>
                  <th className="text-left px-3 py-2">MAC</th>
                  <th className="text-left px-3 py-2">Dettaglio</th>
                  <th className="text-left px-3 py-2">Rilevato</th>
                  <th className="text-left px-3 py-2">Azioni</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((a) => (
                  <tr key={a.id} className="border-t border-[var(--bg-border)]" data-testid={`rogue-row-${a.raw_data}`}>
                    <td className="px-3 py-2">{a.client_name || "—"}</td>
                    <td className="px-3 py-2 font-mono text-orange-300">{a.raw_data}</td>
                    <td className="px-3 py-2 text-[10px] max-w-[380px] truncate">{a.message}</td>
                    <td className="px-3 py-2 text-[10px] text-[var(--text-muted)]">{fmt(a.created_at)}</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1">
                        <Button size="sm" onClick={() => authorize(a)}
                          className="h-6 text-[10px] gap-1 bg-emerald-600 hover:bg-emerald-700"
                          data-testid={`rogue-authorize-${a.raw_data}`}>
                          <CheckCircle size={11} /> Autorizza
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => showRemediation(a)}
                          className="h-6 text-[10px] gap-1 border-orange-500/40 text-orange-300 hover:bg-orange-500/10"
                          data-testid={`rogue-isolate-${a.raw_data}`}>
                          <ShieldSlash size={11} /> Isola (guida)
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {tab === "allow" && (
        allowlist.length === 0 ? (
          <p className="text-[11px] text-[var(--text-muted)]">Nessun MAC in allow-list.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--bg-border)]">
            <table className="w-full text-xs" data-testid="rogue-allow-table">
              <thead className="bg-[var(--bg-card)] text-[var(--text-muted)]">
                <tr>
                  <th className="text-left px-3 py-2">Cliente</th>
                  <th className="text-left px-3 py-2">MAC</th>
                  <th className="text-left px-3 py-2">Autorizzato da</th>
                  <th className="text-left px-3 py-2">Quando</th>
                  <th className="text-left px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {allowlist.map((it) => (
                  <tr key={`${it.client_id}-${it.mac}`} className="border-t border-[var(--bg-border)]">
                    <td className="px-3 py-2">{it.client_name || "—"}</td>
                    <td className="px-3 py-2 font-mono text-emerald-300">{it.mac}</td>
                    <td className="px-3 py-2 text-[10px]">{it.added_by || "—"}</td>
                    <td className="px-3 py-2 text-[10px] text-[var(--text-muted)]">{fmt(it.added_at)}</td>
                    <td className="px-3 py-2">
                      <Button size="sm" variant="outline" onClick={() => removeAllow(it)}
                        className="h-6 text-[10px] gap-1 border-red-500/40 text-red-300 hover:bg-red-500/10">
                        <Trash size={11} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      <Dialog open={!!remedy} onOpenChange={(o) => !o && setRemedy(null)}>
        <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] max-w-lg" data-testid="rogue-remediation-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-orange-300">
              <ShieldSlash size={18} /> Guida di isolamento
            </DialogTitle>
          </DialogHeader>
          {remedy && (
            <div className="space-y-3 text-xs">
              <p className="font-mono text-orange-300">{remedy.mac}</p>
              <ol className="list-decimal list-inside space-y-1.5 text-[var(--text-secondary)]">
                {remedy.steps.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
              <p className="text-[10px] text-amber-400 border-t border-[var(--bg-border)] pt-2">
                ⚠️ {remedy.note}
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Kpi({ icon: Icon, color, label, value, testid }) {
  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3" data-testid={testid}>
      <Icon size={18} className={color} weight="duotone" />
      <p className="text-2xl font-bold mt-1">{value ?? "—"}</p>
      <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
    </div>
  );
}

function TabBtn({ active, onClick, children, testid }) {
  return (
    <button onClick={onClick} data-testid={testid}
      className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${
        active ? "bg-orange-600 border-orange-600 text-white"
          : "border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-card)]"}`}>
      {children}
    </button>
  );
}
