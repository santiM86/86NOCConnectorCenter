import { useState, useEffect, useCallback } from "react";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";
import {
  Globe, WifiHigh, WifiSlash, Plus, Trash, ArrowClockwise,
  Lightning, ShieldCheck, HardDrives, Warning, CheckCircle, Clock,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const STATUS_CONFIG = {
  online: { color: "#34C759", label: "ONLINE", icon: WifiHigh },
  degraded: { color: "#FFCC00", label: "DEGRADATO", icon: Warning },
  offline: { color: "#FF3B30", label: "OFFLINE", icon: WifiSlash },
  unknown: { color: "#555", label: "---", icon: Clock },
  not_configured: { color: "#555", label: "NON CONFIG.", icon: Clock },
};

const DIAG_CONFIG = {
  ok: { color: "#34C759", icon: CheckCircle },
  isp_down: { color: "#FF3B30", icon: WifiSlash },
  firewall_down: { color: "#FF3B30", icon: ShieldCheck },
  router_down: { color: "#FF3B30", icon: HardDrives },
  firewall_degraded: { color: "#FFCC00", icon: Warning },
  router_degraded: { color: "#FFCC00", icon: Warning },
  unknown: { color: "#555", icon: Clock },
  not_configured: { color: "#555", icon: Clock },
};

export default function ExternalMonitorPage() {
  const [targets, setTargets] = useState([]);
  const [status, setStatus] = useState({ results: [], diagnoses: [] });
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ client_id: "", label: "", device_type: "firewall", public_ip: "", gateway_ip: "", check_ports: "443", check_ping: false });
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [t, s, c] = await Promise.all([
        axios.get(`${API}/external-monitor/targets`),
        axios.get(`${API}/external-monitor/status`),
        axios.get(`${API}/clients`),
      ]);
      setTargets(t.data.targets || []);
      setStatus(s.data || { results: [], diagnoses: [] });
      setClients(c.data || []);
    } catch {} finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchAll(); const i = setInterval(fetchAll, 30000); return () => clearInterval(i); }, [fetchAll]);

  const addTarget = async () => {
    try {
      const ports = form.check_ports.split(",").map(p => parseInt(p.trim())).filter(p => !isNaN(p) && p > 0);
      await axios.post(`${API}/external-monitor/targets`, { ...form, check_ports: ports, check_ping: form.check_ping, gateway_ip: form.gateway_ip || null });
      toast.success("Target aggiunto");
      setShowAdd(false);
      setForm({ client_id: "", label: "", device_type: "firewall", public_ip: "", gateway_ip: "", check_ports: "443", check_ping: false });
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const deleteTarget = async (id) => {
    if (!window.confirm("Eliminare questo target?")) return;
    try {
      await axios.delete(`${API}/external-monitor/targets/${id}`);
      toast.success("Target eliminato");
      fetchAll();
    } catch { toast.error("Errore"); }
  };

  const probeNow = async () => {
    try {
      await axios.post(`${API}/external-monitor/probe-now`);
      toast.success("Probe avviato, risultati tra pochi secondi");
      setTimeout(fetchAll, 5000);
    } catch { toast.error("Errore"); }
  };

  const testConnection = async () => {
    if (!form.public_ip) { toast.error("Inserisci un IP pubblico"); return; }
    setTesting(true);
    setTestResult(null);
    try {
      const ports = form.check_ports.split(",").map(p => parseInt(p.trim())).filter(p => !isNaN(p) && p > 0);
      const res = await axios.post(`${API}/external-monitor/test-connection`, {
        public_ip: form.public_ip,
        gateway_ip: form.gateway_ip || null,
        check_ports: ports,
        check_ping: form.check_ping,
      });
      setTestResult(res.data);
      if (res.data.reachable) {
        toast.success("Connessione OK — Dispositivo raggiungibile");
      } else {
        toast.error("Non raggiungibile — Verifica IP e configurazione");
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore test connessione");
    } finally { setTesting(false); }
  };

  const resultMap = {};
  (status.results || []).forEach(r => { resultMap[r.target_id] = r; });
  const diagMap = {};
  (status.diagnoses || []).forEach(d => { diagMap[d.client_id] = d; });
  const clientMap = {};
  clients.forEach(c => { clientMap[c.id] = c.name; });

  // Group targets by client
  const byClient = {};
  targets.forEach(t => {
    if (!byClient[t.client_id]) byClient[t.client_id] = [];
    byClient[t.client_id].push(t);
  });

  if (loading) return <div className="p-6 text-[var(--text-muted)]">Caricamento...</div>;

  return (
    <div className="p-4 md:p-6 space-y-5 max-w-6xl" data-testid="external-monitor-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-bold text-[var(--text-primary)] flex items-center gap-2">
            <Globe size={22} weight="bold" className="text-blue-400" />
            Monitoraggio WAN Esterno
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">Connettivita' internet clienti — Ping + TCP dall'esterno</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" className="h-7 text-xs gap-1" onClick={probeNow} data-testid="probe-now-btn">
            <Lightning size={12} /> Probe Ora
          </Button>
          <Button size="sm" className="h-7 text-xs gap-1" onClick={() => setShowAdd(!showAdd)} data-testid="add-target-btn">
            <Plus size={12} /> Aggiungi Target
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={fetchAll}>
            <ArrowClockwise size={12} /> Aggiorna
          </Button>
        </div>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] p-4 space-y-3" data-testid="add-target-form">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Cliente *</Label>
              <Select value={form.client_id} onValueChange={v => setForm(p => ({ ...p, client_id: v }))}>
                <SelectTrigger className="h-7 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="target-client-select">
                  <SelectValue placeholder="Seleziona..." />
                </SelectTrigger>
                <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                  {clients.map(c => <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Tipo *</Label>
              <Select value={form.device_type} onValueChange={v => setForm(p => ({ ...p, device_type: v }))}>
                <SelectTrigger className="h-7 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="target-type-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                  <SelectItem value="firewall" className="text-xs">Firewall</SelectItem>
                  <SelectItem value="router" className="text-xs">Router</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Label *</Label>
              <Input value={form.label} onChange={e => setForm(p => ({ ...p, label: e.target.value }))} placeholder="Zyxel USG FLEX 200" className="h-7 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="target-label-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">IP Pubblico *</Label>
              <Input value={form.public_ip} onChange={e => setForm(p => ({ ...p, public_ip: e.target.value }))} placeholder="85.42.xxx.xxx" className="h-7 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="target-ip-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Gateway ISP</Label>
              <Input value={form.gateway_ip} onChange={e => setForm(p => ({ ...p, gateway_ip: e.target.value }))} placeholder="85.42.xxx.1 (opzionale)" className="h-7 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="target-gateway-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Porte TCP</Label>
              <Input value={form.check_ports} onChange={e => setForm(p => ({ ...p, check_ports: e.target.value }))} placeholder="443, vuoto se solo ping" className="h-7 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="target-ports-input" />
            </div>
            <div className="flex items-end pb-0.5">
              <label className="flex items-center gap-2 cursor-pointer select-none" data-testid="check-ping-toggle">
                <div
                  onClick={() => setForm(p => ({ ...p, check_ping: !p.check_ping }))}
                  className={`w-9 h-5 rounded-full transition-colors flex items-center px-0.5 cursor-pointer ${form.check_ping ? "bg-emerald-500" : "bg-[var(--bg-border)]"}`}
                >
                  <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${form.check_ping ? "translate-x-4" : "translate-x-0"}`} />
                </div>
                <span className="text-[10px] text-[var(--text-secondary)] whitespace-nowrap">Ping ICMP</span>
              </label>
            </div>
            <div className="flex items-end gap-2">
              <Button size="sm" variant="outline" className="h-7 text-xs flex-1 gap-1 border-blue-500/30 text-blue-400 hover:bg-blue-500/10" onClick={testConnection} disabled={!form.public_ip || testing} data-testid="test-connection-btn">
                {testing ? <ArrowClockwise size={12} className="animate-spin" /> : <Lightning size={12} />}
                {testing ? "Testing..." : "Test"}
              </Button>
              <Button size="sm" className="h-7 text-xs flex-1" onClick={addTarget} disabled={!form.client_id || !form.public_ip || !form.label} data-testid="save-target-btn">Salva</Button>
            </div>
          </div>

          {/* Test result */}
          {testResult && (
            <div className={`rounded-md p-3 border text-xs ${testResult.reachable ? "bg-emerald-500/10 border-emerald-500/30" : "bg-red-500/10 border-red-500/30"}`} data-testid="test-result">
              <div className="flex items-center gap-2 mb-1.5">
                {testResult.reachable ? <CheckCircle size={14} weight="bold" className="text-emerald-400" /> : <Warning size={14} weight="bold" className="text-red-400" />}
                <span className={`font-semibold ${testResult.reachable ? "text-emerald-400" : "text-red-400"}`}>{testResult.summary}</span>
                <span className="text-[var(--text-muted)] ml-auto font-mono">{testResult.ip}</span>
              </div>
              <div className="flex gap-4 flex-wrap">
                {testResult.ping && (
                  <span className="text-[var(--text-muted)]">
                    Ping ICMP: <b style={{ color: testResult.ping.reachable ? "#34C759" : "#FF3B30" }}>{testResult.ping.reachable ? "OK" : "NON RISPONDE"}</b>
                    {testResult.ping.latency_ms != null && <span> ({testResult.ping.latency_ms}ms, loss {testResult.ping.packet_loss_pct}%)</span>}
                  </span>
                )}
                {testResult.gateway && (
                  <span className="text-[var(--text-muted)]">
                    Gateway ISP ({testResult.gateway.ip}): <b style={{ color: testResult.gateway.reachable ? "#34C759" : "#FF3B30" }}>{testResult.gateway.reachable ? "ONLINE" : "OFFLINE"}</b>
                    {testResult.gateway.latency_ms != null && <span> ({testResult.gateway.latency_ms}ms)</span>}
                  </span>
                )}
                {testResult.ports?.map((p, i) => (
                  <span key={i} className="text-[var(--text-muted)]">
                    TCP {p.port}: <b style={{ color: p.open ? "#34C759" : "#FF3B30" }}>{p.open ? "OPEN" : "CLOSED"}</b>
                    {p.response_ms ? <span className="text-[var(--text-muted)]"> ({p.response_ms}ms)</span> : ""}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Per-client diagnosis cards */}
      {Object.entries(byClient).map(([cid, cTargets]) => {
        const diag = diagMap[cid];
        const diagCode = diag?.diagnosis || "not_configured";
        const dc = DIAG_CONFIG[diagCode] || DIAG_CONFIG.unknown;
        const DiagIcon = dc.icon;

        return (
          <div key={cid} className="rounded-lg bg-[var(--bg-panel)] border border-[var(--bg-border)] overflow-hidden" data-testid={`wan-client-${cid}`}>
            <div className="flex items-center gap-3 p-3 border-b border-[var(--bg-border)]">
              <DiagIcon size={18} weight="bold" style={{ color: dc.color }} />
              <div className="flex-1">
                <span className="text-sm font-bold text-[var(--text-primary)]">{clientMap[cid] || cid}</span>
                <span className="ml-3 text-xs" style={{ color: dc.color }}>{diag?.diagnosis_text || "Non configurato"}</span>
                {diag?.gateway_status && (
                  <span className={`ml-3 text-[10px] px-1.5 py-0.5 rounded font-mono ${diag.gateway_status === "online" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"}`}>
                    GW {diag.gateway_ip}: {diag.gateway_status === "online" ? "OK" : "DOWN"}
                  </span>
                )}
              </div>
            </div>
            <div className="divide-y divide-[var(--bg-border)]">
              {cTargets.map(t => {
                const r = resultMap[t.id];
                const st = STATUS_CONFIG[r?.status] || STATUS_CONFIG.unknown;
                const StIcon = st.icon;
                return (
                  <div key={t.id} className="flex items-center gap-3 p-3 hover:bg-[var(--bg-app)]/50" data-testid={`wan-target-${t.id}`}>
                    <StIcon size={16} weight="bold" style={{ color: st.color }} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-[var(--text-primary)]">{t.label}</span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase" style={{ color: st.color, background: `${st.color}15` }}>{st.label}</span>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">{t.public_ip}</span>
                        <span className="text-[9px] text-[var(--text-muted)] uppercase">{t.device_type}</span>
                        {t.check_ping && <span className="text-[9px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-400 font-bold">ICMP</span>}
                      </div>
                      {r && (
                        <div className="flex items-center gap-4 mt-1 text-[10px] text-[var(--text-muted)] flex-wrap">
                          <span>Latenza: <b style={{ color: r.ping?.latency_ms > 100 ? "#FF3B30" : r.ping?.latency_ms > 50 ? "#FFCC00" : "#34C759" }}>{r.ping?.latency_ms ?? "—"}ms</b></span>
                          <span>Loss: <b style={{ color: r.ping?.packet_loss_pct > 5 ? "#FF3B30" : "#34C759" }}>{r.ping?.packet_loss_pct ?? "—"}%</b></span>
                          {r.gateway_ping && (
                            <span>GW {r.gateway_ip}: <b style={{ color: r.gateway_ping.reachable ? "#34C759" : "#FF3B30" }}>{r.gateway_ping.reachable ? "OK" : "DOWN"}</b>{r.gateway_ping.latency_ms != null && ` (${r.gateway_ping.latency_ms}ms)`}</span>
                          )}
                          {r.ports?.map((p, i) => (
                            <span key={i}>TCP {p.port}: <b style={{ color: p.open ? "#34C759" : "#FF3B30" }}>{p.open ? "OPEN" : "CLOSED"}</b>{p.response_ms ? ` (${p.response_ms}ms)` : ""}</span>
                          ))}
                          <span className="ml-auto">{r.checked_at ? new Date(r.checked_at).toLocaleTimeString("it-IT") : ""}</span>
                        </div>
                      )}
                    </div>
                    <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-[var(--text-muted)] hover:text-red-400" onClick={() => deleteTarget(t.id)}>
                      <Trash size={12} />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {targets.length === 0 && (
        <div className="text-center py-12 text-[var(--text-muted)]">
          <Globe size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Nessun target WAN configurato</p>
          <p className="text-xs mt-1">Aggiungi gli IP pubblici dei firewall e router dei clienti per iniziare il monitoraggio</p>
        </div>
      )}
    </div>
  );
}
