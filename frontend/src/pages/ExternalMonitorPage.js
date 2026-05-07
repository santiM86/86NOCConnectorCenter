import { useState, useEffect, useCallback } from "react";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";
import {
  Globe, WifiHigh, WifiSlash, Plus, Trash, ArrowClockwise,
  Lightning, ShieldCheck, HardDrives, Warning, CheckCircle, Clock, PencilSimple, Link as LinkIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";

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
  // v3.8.29: edit target dialog
  const [editTarget, setEditTarget] = useState(null);  // null oppure target da modificare
  const [editForm, setEditForm] = useState({ client_id: "", label: "", device_type: "firewall", public_ip: "", gateway_ip: "", check_ports: "443", check_ping: false });
  const [savingEdit, setSavingEdit] = useState(false);

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

  // v3.8.29: open edit dialog pre-filled with target's current values
  const openEdit = (t) => {
    setEditTarget(t);
    setEditForm({
      client_id: t.client_id || "",
      label: t.label || "",
      device_type: t.device_type || "firewall",
      public_ip: t.public_ip || "",
      gateway_ip: t.gateway_ip || "",
      check_ports: (t.check_ports || []).filter(p => typeof p === "number").join(", "),
      check_ping: !!t.check_ping,
    });
  };

  const saveEdit = async () => {
    if (!editTarget) return;
    if (!editForm.client_id) { toast.error("Seleziona un cliente"); return; }
    if (!editForm.label) { toast.error("Inserisci una label"); return; }
    if (!editForm.public_ip) { toast.error("Inserisci l'IP pubblico"); return; }
    setSavingEdit(true);
    try {
      const ports = (editForm.check_ports || "").split(",").map(p => parseInt(p.trim())).filter(p => !isNaN(p) && p > 0);
      const payload = {
        client_id: editForm.client_id,
        label: editForm.label,
        device_type: editForm.device_type,
        public_ip: editForm.public_ip,
        gateway_ip: editForm.gateway_ip || null,
        check_ports: ports,
        check_ping: editForm.check_ping,
      };
      await axios.put(`${API}/external-monitor/targets/${editTarget.id}`, payload);
      toast.success("Target aggiornato");
      setEditTarget(null);
      fetchAll();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSavingEdit(false);
    }
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

      {/* Per-client cards — schematic layout */}
      {Object.entries(byClient).map(([cid, cTargets]) => {
        const diag = diagMap[cid];
        const diagCode = diag?.diagnosis || "not_configured";
        const dc = DIAG_CONFIG[diagCode] || DIAG_CONFIG.unknown;
        const DiagIcon = dc.icon;

        // Split by device type
        const firewalls = cTargets.filter(t => t.device_type === "firewall");
        const routers = cTargets.filter(t => t.device_type === "router");
        const others = cTargets.filter(t => t.device_type !== "firewall" && t.device_type !== "router");

        return (
          <div key={cid} className="rounded-xl bg-[var(--bg-panel)] border border-[var(--bg-border)] overflow-hidden" data-testid={`wan-client-${cid}`}>
            {/* Client Header */}
            <div className="px-5 py-3 border-b border-[var(--bg-border)] flex items-center justify-between" style={{ borderLeft: `3px solid ${dc.color}` }}>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: `${dc.color}12` }}>
                  <DiagIcon size={18} weight="bold" style={{ color: dc.color }} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2" data-testid={`wan-client-name-${cid}`}>
                    {clientMap[cid] || (
                      <>
                        <span className="text-amber-400">Senza cliente</span>
                        <span className="text-[10px] text-amber-400/70 font-mono px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30">orfano</span>
                      </>
                    )}
                  </h3>
                  <p className="text-[10px] mt-0.5" style={{ color: dc.color }}>{diag?.diagnosis_text || "In attesa del primo probe..."}</p>
                  {!clientMap[cid] && (
                    <p className="text-[9px] mt-1 text-amber-400/80">Clicca <PencilSimple size={10} weight="bold" className="inline -mt-0.5" /> sul target per assegnarlo a un cliente esistente.</p>
                  )}
                </div>
              </div>
              {/* ISP badge from gateway */}
              {(() => {
                const gwTarget = cTargets.find(t => {
                  const r = resultMap[t.id];
                  return r?.gateway_ping;
                });
                const gwResult = gwTarget ? resultMap[gwTarget.id] : null;
                if (!gwResult?.gateway_ping) return null;
                const gwOk = gwResult.gateway_ping.reachable;
                return (
                  <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-[10px] font-semibold border ${gwOk ? "bg-emerald-500/8 text-emerald-400 border-emerald-500/20" : "bg-red-500/8 text-red-400 border-red-500/20"}`}>
                    <Globe size={14} weight="bold" />
                    <div>
                      <span className="block font-bold text-[11px]">ISP {gwOk ? "ONLINE" : "DOWN"}</span>
                      <span className="block opacity-60 font-mono">{gwResult.gateway_ip} {gwResult.gateway_ping.latency_ms != null ? `${gwResult.gateway_ping.latency_ms}ms` : ""}</span>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Schema rete: INTERNET → ROUTER → FIREWALL → LAN */}
            <div className="px-5 py-4">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* FIREWALL Column */}
                {firewalls.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <ShieldCheck size={13} weight="bold" className="text-indigo-400" />
                      <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-indigo-400">Firewall</span>
                      <div className="flex-1 h-px bg-indigo-500/20"></div>
                    </div>
                    {firewalls.map(t => <DeviceCard key={t.id} target={t} result={resultMap[t.id]} onDelete={deleteTarget} onEdit={openEdit} />)}
                  </div>
                )}

                {/* ROUTER Column */}
                {routers.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <HardDrives size={13} weight="bold" className="text-cyan-400" />
                      <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-cyan-400">Router</span>
                      <div className="flex-1 h-px bg-cyan-500/20"></div>
                    </div>
                    {routers.map(t => <DeviceCard key={t.id} target={t} result={resultMap[t.id]} onDelete={deleteTarget} onEdit={openEdit} />)}
                  </div>
                )}

                {/* Others */}
                {others.map(t => <DeviceCard key={t.id} target={t} result={resultMap[t.id]} onDelete={deleteTarget} onEdit={openEdit} />)}
              </div>
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

      {/* v3.8.29: Edit target dialog */}
      <Dialog open={!!editTarget} onOpenChange={(open) => { if (!open) setEditTarget(null); }}>
        <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] max-w-2xl" data-testid="edit-target-dialog">
          <DialogHeader>
            <DialogTitle className="text-[var(--text-primary)] flex items-center gap-2">
              <PencilSimple size={16} weight="bold" className="text-indigo-400" />
              Modifica target WAN
            </DialogTitle>
            <DialogDescription className="text-[var(--text-muted)] text-xs">
              {editTarget && (
                <span className="font-mono">{editTarget.id}</span>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3 py-2">
            <div className="space-y-1 col-span-2">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] flex items-center gap-1">
                <LinkIcon size={10} weight="bold" /> Cliente *
              </Label>
              <Select value={editForm.client_id} onValueChange={v => setEditForm(p => ({ ...p, client_id: v }))}>
                <SelectTrigger className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-target-client-select">
                  <SelectValue placeholder="Seleziona cliente..." />
                </SelectTrigger>
                <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                  {clients.map(c => <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Tipo *</Label>
              <Select value={editForm.device_type} onValueChange={v => setEditForm(p => ({ ...p, device_type: v }))}>
                <SelectTrigger className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-target-type-select">
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
              <Input value={editForm.label} onChange={e => setEditForm(p => ({ ...p, label: e.target.value }))} placeholder="Zyxel USG FLEX 200" className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-target-label-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">IP Pubblico *</Label>
              <Input value={editForm.public_ip} onChange={e => setEditForm(p => ({ ...p, public_ip: e.target.value }))} placeholder="85.42.xxx.xxx" className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-target-ip-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Gateway ISP</Label>
              <Input value={editForm.gateway_ip} onChange={e => setEditForm(p => ({ ...p, gateway_ip: e.target.value }))} placeholder="85.42.xxx.1 (opzionale)" className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-target-gateway-input" />
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Porte TCP</Label>
              <Input value={editForm.check_ports} onChange={e => setEditForm(p => ({ ...p, check_ports: e.target.value }))} placeholder="443, 80 (vuoto = solo ping)" className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-target-ports-input" />
            </div>
            <div className="space-y-1 col-span-2">
              <label className="flex items-center gap-2 cursor-pointer select-none" data-testid="edit-check-ping-toggle">
                <div
                  onClick={() => setEditForm(p => ({ ...p, check_ping: !p.check_ping }))}
                  className={`w-9 h-5 rounded-full transition-colors flex items-center px-0.5 cursor-pointer ${editForm.check_ping ? "bg-emerald-500" : "bg-[var(--bg-border)]"}`}
                >
                  <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${editForm.check_ping ? "translate-x-4" : "translate-x-0"}`} />
                </div>
                <span className="text-[10px] text-[var(--text-secondary)] whitespace-nowrap">Abilita Ping ICMP</span>
              </label>
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => setEditTarget(null)} disabled={savingEdit} data-testid="edit-target-cancel-btn">Annulla</Button>
            <Button size="sm" className="h-8 text-xs" onClick={saveEdit} disabled={savingEdit} data-testid="edit-target-save-btn">
              {savingEdit ? <ArrowClockwise size={12} className="animate-spin mr-1" /> : null}
              Salva modifiche
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}


/* ==================== DEVICE CARD (Expandable) ==================== */
function DeviceCard({ target: t, result: r, onDelete, onEdit }) {
  const [expanded, setExpanded] = useState(false);
  const st = STATUS_CONFIG[r?.status] || STATUS_CONFIG.unknown;
  const StIcon = st.icon;
  const latency = r?.ping?.latency_ms;
  const loss = r?.ping?.packet_loss_pct;
  const isFirewall = t.device_type === "firewall";

  return (
    <div
      className="rounded-lg border transition-all duration-200 cursor-pointer hover:shadow-md group"
      style={{ borderColor: `${st.color}30`, background: `${st.color}04` }}
      onClick={() => setExpanded(!expanded)}
      data-testid={`wan-target-${t.id}`}
    >
      {/* Main row */}
      <div className="px-3 py-2.5 flex items-center gap-3">
        {/* Status dot + device icon */}
        <div className="relative flex-shrink-0">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${st.color}12` }}>
            {isFirewall ? <ShieldCheck size={15} weight="bold" style={{ color: st.color }} /> : <HardDrives size={15} weight="bold" style={{ color: st.color }} />}
          </div>
          <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-[var(--bg-panel)]" style={{ backgroundColor: st.color }}></div>
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-[var(--text-primary)] truncate">{t.label}</span>
            <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase" style={{ color: st.color, background: `${st.color}15` }}>{st.label}</span>
          </div>
          <span className="text-[10px] text-[var(--text-muted)] font-mono">{t.public_ip}</span>
        </div>

        {/* Quick metrics */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {latency != null && (
            <span className="text-xs font-bold font-mono" style={{ color: latency > 100 ? "#FF3B30" : latency > 50 ? "#FFCC00" : "#34C759" }}>{latency}<span className="text-[8px] opacity-50">ms</span></span>
          )}
          {loss != null && loss > 0 && (
            <span className="text-[10px] font-bold font-mono text-red-400">{loss}%</span>
          )}
          {t.check_ping && <span className="text-[8px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-400 font-bold">ICMP</span>}
          <button
            onClick={(e) => { e.stopPropagation(); onEdit && onEdit(t); }}
            className="p-1 rounded hover:bg-indigo-500/10 text-[var(--text-muted)] hover:text-indigo-400 transition-all opacity-0 group-hover:opacity-100"
            title="Modifica target"
            data-testid={`edit-target-btn-${t.id}`}
          >
            <PencilSimple size={12} />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(t.id); }}
            className="p-1 rounded hover:bg-red-500/10 text-[var(--text-muted)] hover:text-red-400 transition-all opacity-0 group-hover:opacity-100"
            title="Elimina"
            data-testid={`delete-target-btn-${t.id}`}
          >
            <Trash size={12} />
          </button>
        </div>
      </div>

      {/* Expanded metrics panel */}
      {expanded && r && (
        <div className="px-3 pb-3 pt-0 border-t border-[var(--bg-border)]/30 mt-0" onClick={(e) => e.stopPropagation()}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2">
            {/* Ping ICMP */}
            <MetricBox label="Ping ICMP" value={r.ping?.reachable ? "OK" : "FAIL"} sub={latency != null ? `${latency}ms` : null}
              color={r.ping?.reachable ? "#34C759" : "#FF3B30"} />
            {/* Packet Loss */}
            <MetricBox label="Packet Loss" value={loss != null ? `${loss}%` : "—"} sub={loss === 0 ? "Nessuna perdita" : loss > 5 ? "Critico" : "Accettabile"}
              color={loss > 5 ? "#FF3B30" : loss > 0 ? "#FF9500" : "#34C759"} />
            {/* Uptime stimato */}
            <MetricBox label="Stato" value={st.label} sub={r.checked_at ? new Date(r.checked_at).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
              color={st.color} />
            {/* Gateway */}
            {r.gateway_ping ? (
              <MetricBox label="Gateway ISP" value={r.gateway_ping.reachable ? "ONLINE" : "DOWN"} sub={`${r.gateway_ip || "?"} ${r.gateway_ping.latency_ms != null ? `${r.gateway_ping.latency_ms}ms` : ""}`}
                color={r.gateway_ping.reachable ? "#34C759" : "#FF3B30"} />
            ) : (
              <MetricBox label="Gateway ISP" value="N/C" sub="Non configurato" color="#555" />
            )}
          </div>

          {/* TCP Ports detail */}
          {r.ports?.length > 0 && (
            <div className="mt-2">
              <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Porte TCP</p>
              <div className="flex gap-2 flex-wrap">
                {r.ports.map((p, i) => (
                  <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded-md border text-[10px] font-mono"
                    style={{ borderColor: p.open ? "#34C75930" : "#FF3B3030", background: p.open ? "#34C75908" : "#FF3B3008" }}>
                    <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: p.open ? "#34C759" : "#FF3B30" }}></div>
                    <span className="text-[var(--text-primary)] font-bold">{p.port}</span>
                    <span style={{ color: p.open ? "#34C759" : "#FF3B30" }}>{p.open ? "OPEN" : "CLOSED"}</span>
                    {p.response_ms && <span className="text-[var(--text-muted)] opacity-60">{p.response_ms}ms</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ==================== METRIC BOX ==================== */
function MetricBox({ label, value, sub, color }) {
  return (
    <div className="rounded-md px-2.5 py-2 bg-[var(--bg-card)] border border-[var(--bg-border)]">
      <p className="text-[7px] uppercase tracking-[0.15em] text-[var(--text-muted)] mb-0.5">{label}</p>
      <p className="text-sm font-bold font-mono leading-none" style={{ color }}>{value}</p>
      {sub && <p className="text-[9px] text-[var(--text-muted)] mt-0.5 opacity-60">{sub}</p>}
    </div>
  );
}
