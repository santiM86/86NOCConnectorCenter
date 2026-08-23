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
  filtered: { color: "#FFCC00", label: "FILTRATO", icon: ShieldCheck },
  offline: { color: "#FF3B30", label: "OFFLINE", icon: WifiSlash },
  unknown: { color: "#555", label: "---", icon: Clock },
  not_configured: { color: "#555", label: "NON CONFIG.", icon: Clock },
};

// v2026-02-14: stati distinti per ogni porta TCP (RFC 793 / nmap-like).
// Prima si mostrava sempre "OPEN" o "CLOSED": ora distinguiamo
// chiuso reale (RST) da firewall drop silente (timeout = filtered).
const PORT_STATUS_CONFIG = {
  open:        { color: "#34C759", label: "OPEN",        tooltip: "Connessione TCP accettata (SYN/ACK ricevuto)" },
  closed:      { color: "#FF3B30", label: "CLOSED",      tooltip: "Porta non in ascolto (RST esplicito ricevuto)" },
  filtered:    { color: "#FFCC00", label: "FILTERED",    tooltip: "Firewall blocca silenziosamente i probe (timeout senza risposta) — la porta puo' essere aperta ma e' irraggiungibile da Argus per geo-IP / whitelist / DDoS protection" },
  unreachable: { color: "#FF9500", label: "UNREACHABLE", tooltip: "Network/host unreachable (errore di routing ICMP)" },
  error:       { color: "#888",    label: "ERROR",       tooltip: "Errore durante il probe (DNS, SSL, ecc.)" },
};
const portStatus = (p) => PORT_STATUS_CONFIG[p?.status] || (p?.open ? PORT_STATUS_CONFIG.open : PORT_STATUS_CONFIG.closed);

const DIAG_CONFIG = {
  ok: { color: "#34C759", icon: CheckCircle },
  isp_down: { color: "#FF3B30", icon: WifiSlash },
  firewall_down: { color: "#FF3B30", icon: ShieldCheck },
  router_down: { color: "#FF3B30", icon: HardDrives },
  firewall_degraded: { color: "#FFCC00", icon: Warning },
  router_degraded: { color: "#FFCC00", icon: Warning },
  filtered: { color: "#FFCC00", icon: ShieldCheck },
  unknown: { color: "#555", icon: Clock },
  not_configured: { color: "#555", icon: Clock },
};

export default function ExternalMonitorPage() {
  const [targets, setTargets] = useState([]);
  const [status, setStatus] = useState({ results: [], diagnoses: [] });
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ client_id: "", label: "", device_type: "firewall", public_ip: "", gateway_ip: "", check_ports: "443", check_ping: false, backup_enabled: false, backup_label: "", backup_public_ip: "", backup_gateway_ip: "" });
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);
  const [backupTestResult, setBackupTestResult] = useState(null);
  const [testingBackup, setTestingBackup] = useState(false);
  // v3.8.29: edit target dialog
  const [editTarget, setEditTarget] = useState(null);  // null oppure target da modificare
  const [editForm, setEditForm] = useState({ client_id: "", label: "", device_type: "firewall", public_ip: "", gateway_ip: "", check_ports: "443", check_ping: false, backup_enabled: false, backup_label: "", backup_public_ip: "", backup_gateway_ip: "" });
  const [savingEdit, setSavingEdit] = useState(false);
  const [nebulaFws, setNebulaFws] = useState([]);  // firewall Nebula del cliente del target in edit
  // Auto-target: IP pubblico WAN auto-rilevato dagli agent del cliente selezionato.
  const [detectedIp, setDetectedIp] = useState(null); // {public_ip, seen_at, hostname} | null

  const onClientChange = async (cid) => {
    setForm(p => ({ ...p, client_id: cid }));
    setDetectedIp(null);
    if (!cid) return;
    try {
      const res = await axios.get(`${API}/external-monitor/detected-public-ip/${cid}`);
      const ip = res.data?.public_ip;
      if (ip) {
        setDetectedIp(res.data);
        // pre-compila SOLO se l'utente non ha gia' digitato un IP
        setForm(p => (p.public_ip ? p : { ...p, public_ip: ip }));
      }
    } catch {}
  };

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
      await axios.post(`${API}/external-monitor/targets`, { ...form, check_ports: ports, check_ping: form.check_ping, gateway_ip: form.gateway_ip || null, backup_public_ip: form.backup_public_ip || null, backup_gateway_ip: form.backup_gateway_ip || null, backup_label: form.backup_label || null, backup_enabled: !!(form.backup_public_ip && form.backup_enabled) });
      toast.success("Target aggiunto");
      setShowAdd(false);
      setForm({ client_id: "", label: "", device_type: "firewall", public_ip: "", gateway_ip: "", check_ports: "443", check_ping: false, backup_enabled: false, backup_label: "", backup_public_ip: "", backup_gateway_ip: "" });
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
      backup_enabled: !!t.backup_enabled,
      backup_label: t.backup_label || "",
      backup_public_ip: t.backup_public_ip || "",
      backup_gateway_ip: t.backup_gateway_ip || "",
      linked_nebula_dev_id: t.linked_nebula_dev_id || "",
      linked_nebula_site_id: t.linked_nebula_site_id || "",
    });
    setNebulaFws([]);
    if (t.client_id) {
      axios.get(`${API}/clients/${encodeURIComponent(t.client_id)}/zyxel/devices`)
        .then(r => setNebulaFws((r.data?.devices || []).filter(d => d.device_type === "firewall")))
        .catch(() => setNebulaFws([]));
    }
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
        backup_public_ip: editForm.backup_public_ip || null,
        backup_gateway_ip: editForm.backup_gateway_ip || null,
        backup_label: editForm.backup_label || null,
        backup_enabled: !!(editForm.backup_public_ip && editForm.backup_enabled),
        linked_nebula_dev_id: editForm.linked_nebula_dev_id || "",
        linked_nebula_site_id: editForm.linked_nebula_site_id || "",
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

  const autoLinkNebula = async () => {
    try {
      const res = await axios.post(`${API}/external-monitor/auto-link-nebula`);
      const n = res.data?.linked ?? 0;
      toast.success(n > 0 ? `${n} target collegati automaticamente a Nebula` : "Nessun nuovo collegamento (già tutti linkati o nessun match)");
      setTimeout(fetchAll, 800);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore auto-collegamento Nebula"); }
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
      const anyFiltered = (res.data.ports || []).some(p => p?.status === "filtered");
      const pingOk = res.data.ping?.reachable === true;
      if (res.data.reachable) {
        // Ping OK o porta open → device raggiungibile
        toast.success("Connessione OK — Dispositivo raggiungibile");
      } else if (anyFiltered && !pingOk) {
        toast.warning("Probe filtrato dal firewall — Possibile falso negativo");
      } else {
        toast.error("Non raggiungibile — Verifica IP e configurazione");
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore test connessione");
    } finally { setTesting(false); }
  };

  const testBackupConnection = async () => {
    if (!form.backup_public_ip) { toast.error("Inserisci l'IP pubblico della linea di backup"); return; }
    setTestingBackup(true);
    setBackupTestResult(null);
    try {
      // Linea di backup: solo raggiungibilita' (ping + gateway), niente porte TCP
      const res = await axios.post(`${API}/external-monitor/test-connection`, {
        public_ip: form.backup_public_ip,
        gateway_ip: form.backup_gateway_ip || null,
        check_ports: [],
        check_ping: true,
      });
      setBackupTestResult(res.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore test backup");
    } finally { setTestingBackup(false); }
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
          <Button variant="outline" size="sm" className="h-7 text-xs gap-1 border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10" onClick={autoLinkNebula} data-testid="auto-link-nebula-btn" title="Collega automaticamente i target WAN ai firewall Nebula corrispondenti (per IP pubblico / sito)">
            <LinkIcon size={12} /> Auto-collega Nebula
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
              <Select value={form.client_id} onValueChange={onClientChange}>
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
              {detectedIp?.public_ip && (
                <div className="text-[10px] text-sky-400 flex items-center gap-1 flex-wrap" data-testid="detected-ip-hint">
                  <span>WAN rilevata dagli agent: <span className="font-mono">{detectedIp.public_ip}</span></span>
                  {form.public_ip !== detectedIp.public_ip && (
                    <button type="button" className="underline hover:text-sky-300"
                      onClick={() => setForm(p => ({ ...p, public_ip: detectedIp.public_ip }))}
                      data-testid="use-detected-ip-btn">usa</button>
                  )}
                </div>
              )}
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

          {/* ===== LINEA DI BACKUP (opzionale) ===== */}
          <div className="rounded-md border border-amber-500/25 bg-amber-500/[0.04] p-3 space-y-2" data-testid="backup-line-section">
            <label className="flex items-center gap-2 cursor-pointer select-none" data-testid="backup-enabled-toggle"
              onClick={() => setForm(p => ({ ...p, backup_enabled: !p.backup_enabled }))}>
              <div
                className={`w-9 h-5 rounded-full transition-colors flex items-center px-0.5 cursor-pointer ${form.backup_enabled ? "bg-amber-500" : "bg-[var(--bg-border)]"}`}
              >
                <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${form.backup_enabled ? "translate-x-4" : "translate-x-0"}`} />
              </div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400">Linea di backup (2ª WAN)</span>
              <span className="text-[9px] text-[var(--text-muted)] normal-case font-normal">— rileva failover e doppio-down</span>
            </label>
            {form.backup_enabled && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
                <div className="space-y-1">
                  <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Label backup</Label>
                  <Input value={form.backup_label} onChange={e => setForm(p => ({ ...p, backup_label: e.target.value }))} placeholder="FWA / 4G / 2ª linea" className="h-7 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="backup-label-input" />
                </div>
                <div className="space-y-1">
                  <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">IP Pubblico backup</Label>
                  <Input value={form.backup_public_ip} onChange={e => setForm(p => ({ ...p, backup_public_ip: e.target.value }))} placeholder="x.x.x.x" className="h-7 text-xs font-mono bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="backup-ip-input" />
                </div>
                <div className="space-y-1">
                  <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Gateway ISP backup</Label>
                  <Input value={form.backup_gateway_ip} onChange={e => setForm(p => ({ ...p, backup_gateway_ip: e.target.value }))} placeholder="next-hop 2ª linea (opz.)" className="h-7 text-xs font-mono bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="backup-gateway-input" />
                </div>
                <div className="flex items-end">
                  <Button size="sm" variant="outline" className="h-7 text-xs w-full gap-1 border-amber-500/40 text-amber-400 hover:bg-amber-500/10" onClick={testBackupConnection} disabled={!form.backup_public_ip || testingBackup} data-testid="test-backup-btn">
                    {testingBackup ? <ArrowClockwise size={12} className="animate-spin" /> : <Lightning size={12} />}
                    {testingBackup ? "Testing..." : "Test backup"}
                  </Button>
                </div>
              </div>
            )}
            {form.backup_enabled && backupTestResult && (
              <div className={`rounded-md p-2 border text-xs ${backupTestResult.ping?.reachable ? "bg-emerald-500/10 border-emerald-500/30" : "bg-red-500/10 border-red-500/30"}`} data-testid="backup-test-result">
                <div className="flex items-center gap-2">
                  {backupTestResult.ping?.reachable ? <CheckCircle size={14} weight="bold" className="text-emerald-400" /> : <Warning size={14} weight="bold" className="text-red-400" />}
                  <span className={`font-semibold ${backupTestResult.ping?.reachable ? "text-emerald-400" : "text-red-400"}`}>
                    Linea backup {backupTestResult.ping?.reachable ? "RAGGIUNGIBILE" : "NON raggiungibile"}
                  </span>
                  <span className="text-[var(--text-muted)] ml-auto font-mono">{backupTestResult.ip}{backupTestResult.ping?.latency_ms != null ? ` · ${backupTestResult.ping.latency_ms}ms` : ""}</span>
                </div>
              </div>
            )}
          </div>

          {/* Test result */}
          {testResult && (() => {
            const anyFiltered = (testResult.ports || []).some(p => p?.status === "filtered");
            const anyOpen = (testResult.ports || []).some(p => p?.open);
            const pingOk = testResult.ping?.reachable === true;
            const success = testResult.reachable;
            // v2026-02-14-bis: warn solo se filtered E ping fail. Se ping OK e
            // porta filtered → device vivo, mostra success verde (banner ambra
            // sarebbe fuorviante: il monitor e' OK).
            const warn = !success && anyFiltered && !pingOk;
            const bg = success ? "bg-emerald-500/10 border-emerald-500/30" : warn ? "bg-amber-500/10 border-amber-500/30" : "bg-red-500/10 border-red-500/30";
            const tone = success ? "text-emerald-400" : warn ? "text-amber-400" : "text-red-400";
            const Icon = success ? CheckCircle : Warning;
            // Nota informativa quando le porte sono filtered ma device raggiungibile via ping
            const showFilteredInfo = success && anyFiltered && !anyOpen;
            return (
            <div className={`rounded-md p-3 border text-xs ${bg}`} data-testid="test-result">
              <div className="flex items-center gap-2 mb-1.5">
                <Icon size={14} weight="bold" className={tone} />
                <span className={`font-semibold ${tone}`}>{testResult.summary}</span>
                <span className="text-[var(--text-muted)] ml-auto font-mono">{testResult.ip}</span>
              </div>
              {warn && (
                <div className="text-[10px] text-amber-300/80 mb-2 leading-snug">
                  Almeno una porta risulta <b>filtered</b>: significa che il firewall del cliente sta scartando silenziosamente i nostri probe (timeout senza RST). La porta potrebbe essere realmente aperta ma irraggiungibile dall'IP del NOC (geo-IP, whitelist, DDoS protection).
                </div>
              )}
              {showFilteredInfo && (
                <div className="text-[10px] text-emerald-300/70 mb-2 leading-snug">
                  ℹ️ Il device risponde al ping ICMP dal nostro IP → è vivo e raggiungibile. Le porte marcate <b>filtered</b> indicano solo che il firewall non risponde sui probe TCP dalla nostra rete (whitelist normale).
                </div>
              )}
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
                {testResult.ports?.map((p, i) => {
                  const ps = portStatus(p);
                  return (
                    <span key={i} className="text-[var(--text-muted)]" title={ps.tooltip + (p.error_detail ? `\n${p.error_detail}` : "")}>
                      TCP {p.port}: <b style={{ color: ps.color }}>{ps.label}</b>
                      {p.response_ms ? <span className="text-[var(--text-muted)]"> ({p.response_ms}ms)</span> : ""}
                      {p.resolved_ip && p.resolved_ip !== testResult.ip && (
                        <span className="text-[8px] opacity-60 ml-1 font-mono">→ {p.resolved_ip}</span>
                      )}
                    </span>
                  );
                })}
              </div>
            </div>
            );
          })()}
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
            {/* Collegamento firewall Nebula (dedup + arricchimento) */}
            {editForm.device_type === "firewall" && (
              <div className="col-span-2 rounded-md border border-cyan-500/25 bg-cyan-500/[0.04] p-3 space-y-1">
                <Label className="text-[9px] uppercase tracking-widest text-cyan-300 flex items-center gap-1">
                  <LinkIcon size={10} weight="bold" /> Collega a firewall Zyxel Nebula
                </Label>
                <p className="text-[9px] text-[var(--text-muted)] mb-1">
                  Unifica questo target con il firewall Nebula del cliente: niente doppioni, dati dispositivo + connettività in un'unica scheda.
                </p>
                <Select
                  value={editForm.linked_nebula_dev_id || "__none__"}
                  onValueChange={(v) => {
                    if (v === "__none__") { setEditForm(p => ({ ...p, linked_nebula_dev_id: "", linked_nebula_site_id: "" })); return; }
                    const fw = nebulaFws.find(d => d.dev_id === v);
                    setEditForm(p => ({ ...p, linked_nebula_dev_id: v, linked_nebula_site_id: fw?.site_id || "" }));
                  }}
                >
                  <SelectTrigger className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-target-nebula-select">
                    <SelectValue placeholder={nebulaFws.length ? "Seleziona firewall Nebula..." : "Nessun firewall Nebula per questo cliente"} />
                  </SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                    <SelectItem value="__none__" className="text-xs">— Nessun collegamento —</SelectItem>
                    {nebulaFws.map(d => (
                      <SelectItem key={d.dev_id} value={d.dev_id} className="text-xs">
                        {d.model || d.name} · {d.site_name || d.site_id} {d.sn ? `· ${d.sn}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {/* ===== Linea di backup ===== */}
            <div className="col-span-2 rounded-md border border-amber-500/25 bg-amber-500/[0.04] p-3 space-y-2">
              <label className="flex items-center gap-2 cursor-pointer select-none" data-testid="edit-backup-enabled-toggle"
                onClick={() => setEditForm(p => ({ ...p, backup_enabled: !p.backup_enabled }))}>
                <div
                  className={`w-9 h-5 rounded-full transition-colors flex items-center px-0.5 cursor-pointer ${editForm.backup_enabled ? "bg-amber-500" : "bg-[var(--bg-border)]"}`}
                >
                  <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${editForm.backup_enabled ? "translate-x-4" : "translate-x-0"}`} />
                </div>
                <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400">Linea di backup (2ª WAN)</span>
              </label>
              {editForm.backup_enabled && (
                <div className="grid grid-cols-3 gap-2 pt-1">
                  <div className="space-y-1">
                    <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Label backup</Label>
                    <Input value={editForm.backup_label} onChange={e => setEditForm(p => ({ ...p, backup_label: e.target.value }))} placeholder="4G / 2ª linea" className="h-8 text-xs bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-backup-label-input" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">IP Pubblico backup</Label>
                    <Input value={editForm.backup_public_ip} onChange={e => setEditForm(p => ({ ...p, backup_public_ip: e.target.value }))} placeholder="x.x.x.x" className="h-8 text-xs font-mono bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-backup-ip-input" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[9px] uppercase tracking-widest text-[var(--text-muted)]">Gateway ISP backup</Label>
                    <Input value={editForm.backup_gateway_ip} onChange={e => setEditForm(p => ({ ...p, backup_gateway_ip: e.target.value }))} placeholder="next-hop (opz.)" className="h-8 text-xs font-mono bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)]" data-testid="edit-backup-gateway-input" />
                  </div>
                </div>
              )}
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
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-bold text-[var(--text-primary)] truncate">{t.nebula?.model || t.label}</span>
            <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase" style={{ color: st.color, background: `${st.color}15` }}>{st.label}</span>
            {t.nebula && (
              <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase bg-cyan-500/12 text-cyan-400 flex items-center gap-1" data-testid={`nebula-chip-${t.id}`}>
                NEBULA {t.nebula.online_status === "ONLINE" ? "· ON" : "· OFF"}
              </span>
            )}
            {r?.line_state === "failover" && (
              <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase bg-amber-500/15 text-amber-400" data-testid={`line-failover-${t.id}`}>FAILOVER</span>
            )}
            {r?.line_state === "isolated" && (
              <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase bg-red-500/15 text-red-400" data-testid={`line-isolated-${t.id}`}>ISOLATO</span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-[var(--text-muted)] font-mono">{t.public_ip}</span>
            {t.nebula?.sn && <span className="text-[9px] text-[var(--text-muted)] font-mono">S/N {t.nebula.sn}</span>}
            {t.nebula?.ports_total > 0 && (
              <span className="text-[9px] font-mono text-emerald-400/80">porte {t.nebula.ports_up}/{t.nebula.ports_total}</span>
            )}
            {r?.backup && (
              <span className="text-[9px] font-mono flex items-center gap-1" title="Linea di backup" data-testid={`backup-badge-${t.id}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${r.backup.status === "online" ? "bg-emerald-400" : "bg-red-400"}`}></span>
                <span className="text-amber-400/80">{r.backup.label || "Backup"}</span>
                <span className="text-[var(--text-muted)]">{r.backup.public_ip}</span>
              </span>
            )}
          </div>
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

      {/* Placeholder finché non arriva il primo probe */}
      {expanded && !r && (
        <div className="px-3 pb-3 pt-2 border-t border-[var(--bg-border)]/30 text-[10px] text-[var(--text-muted)] flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <ArrowClockwise size={11} className="animate-spin opacity-60" /> In attesa del primo probe…
        </div>
      )}
      {/* Expanded metrics panel */}
      {expanded && r && (
        <div className="px-3 pb-3 pt-0 border-t border-[var(--bg-border)]/30 mt-0" onClick={(e) => e.stopPropagation()}>
          {(r.line_state === "failover" || r.line_state === "isolated") && (
            <div className={`mt-2 rounded-md p-2 border text-[10px] font-semibold flex items-center gap-2 ${r.line_state === "failover" ? "bg-amber-500/10 border-amber-500/30 text-amber-400" : "bg-red-500/10 border-red-500/30 text-red-400"}`} data-testid={`line-banner-${t.id}`}>
              <Warning size={13} weight="bold" />
              {r.line_state === "failover"
                ? `FAILOVER attivo — linea primaria giù, cliente online via backup (${r.backup?.public_ip || "?"})`
                : `CLIENTE ISOLATO — entrambe le linee giù (primaria ${t.public_ip} + backup ${r.backup?.public_ip || "?"})`}
            </div>
          )}
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

          {/* Linea di backup */}
          {r.backup && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2">
              <MetricBox label="Linea backup" value={r.backup.status === "online" ? "ONLINE" : "OFFLINE"}
                sub={`${r.backup.label || "2ª WAN"} · ${r.backup.public_ip}`} color={r.backup.status === "online" ? "#34C759" : "#FF3B30"} />
              <MetricBox label="Ping backup" value={r.backup.ping?.reachable ? "OK" : "FAIL"}
                sub={r.backup.ping?.latency_ms != null ? `${r.backup.ping.latency_ms}ms` : null}
                color={r.backup.ping?.reachable ? "#34C759" : "#FF3B30"} />
              {r.backup.gateway_ping ? (
                <MetricBox label="Gateway backup" value={r.backup.gateway_ping.reachable ? "ONLINE" : "DOWN"}
                  sub={`${r.backup.gateway_ip || "?"} ${r.backup.gateway_ping.latency_ms != null ? `${r.backup.gateway_ping.latency_ms}ms` : ""}`}
                  color={r.backup.gateway_ping.reachable ? "#34C759" : "#FF3B30"} />
              ) : (
                <MetricBox label="Gateway backup" value="N/C" sub="Non configurato" color="#555" />
              )}
            </div>
          )}

          {/* TCP Ports detail */}
          {r.ports?.length > 0 && (
            <div className="mt-2">
              <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Porte TCP</p>
              <div className="flex gap-2 flex-wrap">
                {r.ports.map((p, i) => {
                  const ps = portStatus(p);
                  return (
                    <div key={i}
                      className="flex items-center gap-1.5 px-2 py-1 rounded-md border text-[10px] font-mono"
                      style={{ borderColor: `${ps.color}30`, background: `${ps.color}08` }}
                      title={ps.tooltip + (p.error_detail ? `\n\n${p.error_detail}` : "")}
                      data-testid={`port-status-${p.port}`}
                    >
                      <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: ps.color }}></div>
                      <span className="text-[var(--text-primary)] font-bold">{p.port}</span>
                      <span style={{ color: ps.color }}>{ps.label}</span>
                      {p.response_ms && <span className="text-[var(--text-muted)] opacity-60">{p.response_ms}ms</span>}
                    </div>
                  );
                })}
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
