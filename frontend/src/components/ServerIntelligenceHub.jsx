/* eslint-disable react-hooks/exhaustive-deps */
import { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Cpu, ShieldCheck, Drop, Activity, Lightning, Pulse, MagnifyingGlass,
  Key, Warning, CheckCircle, Clock, Stack, HardDrives, ArrowsClockwise,
  Cloud, Sparkle, Eye, Trophy, ChartLine, ListBullets,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";

const GRADE_COLOR = {
  A: "#10B981", B: "#84CC16", C: "#F59E0B", D: "#F97316", F: "#EF4444",
};

const fmt = (n, suffix = "") => (n === null || n === undefined ? "—" : `${n}${suffix}`);

const timeAgo = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const m = Math.round((Date.now() - d.getTime()) / 60000);
    if (m < 1) return "ora";
    if (m < 60) return `${m}min fa`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h fa`;
    return `${Math.round(h / 24)}g fa`;
  } catch { return "—"; }
};

// ============================================================================
// PROBE VENDOR — identifica vendor dei server senza credenziali
// ============================================================================
export function ProbeVendorButton({ servers, onComplete }) {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState(null);

  const run = async () => {
    if (!servers || servers.length === 0) return;
    setRunning(true);
    try {
      const ips = servers.map(s => s.ip).filter(Boolean).slice(0, 50);
      const r = await axios.post(`${API}/servers/probe-vendor`, { ips });
      setResults(r.data);
      toast.success(`Vendor identificati su ${r.data.ok_count}/${ips.length} server`);
      onComplete?.(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore probe");
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <Button
        onClick={run} disabled={running}
        className="bg-cyan-600 hover:bg-cyan-700 text-white h-8 text-xs gap-1"
        data-testid="probe-vendor-btn"
        title="Probe anonimo /redfish/v1/ — identifica HP/Dell/Lenovo/Supermicro senza autenticazione"
      >
        <MagnifyingGlass size={13} weight="bold" />
        {running ? "Probing…" : "Probe Vendor"}
      </Button>
      <Dialog open={!!results} onOpenChange={(o) => !o && setResults(null)}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-2xl" data-testid="probe-vendor-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><MagnifyingGlass className="text-cyan-400" size={16} /> Risultati Probe Vendor</DialogTitle>
            <DialogDescription className="text-xs">Vendor identificati via Redfish anonimo (HTTP 200/401 su /redfish/v1/)</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5 max-h-96 overflow-y-auto">
            {results?.probes?.map((p, i) => (
              <div key={i} className={`flex items-center gap-3 p-2 rounded border ${p.ok ? "border-emerald-500/30 bg-emerald-500/5" : "border-[var(--bg-border)]"}`}>
                <div className={`w-1.5 h-1.5 rounded-full ${p.ok ? "bg-emerald-400" : "bg-zinc-500"}`}></div>
                <span className="font-mono text-xs flex-1">{p.ip}</span>
                <span className="text-xs font-bold" style={{ color: p.ok ? "#10B981" : "#64748B" }}>
                  {p.vendor || (p.ok ? "Redfish Yes" : (p.error || "no Redfish"))}
                </span>
                {p.product && <span className="text-[9px] text-[var(--text-muted)]">{p.product}</span>}
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ============================================================================
// TRY DEFAULT CREDENTIALS — tenta credenziali OEM factory
// ============================================================================
export function TryDefaultCredsButton({ server, onSuccess }) {
  const [running, setRunning] = useState(false);

  const run = async () => {
    if (!window.confirm(`Tentare credenziali OEM di default su ${server.ip}?\n\nUSO LECITO: serve a identificare server con credenziali factory MAI cambiate (security audit).\n\nAUDIT: ogni tentativo viene loggato.`)) return;
    setRunning(true);
    try {
      const r = await axios.post(`${API}/servers/try-default-credentials`, {
        ip: server.ip, vendor: server.vendor_guess || "",
      });
      if (r.data.ok) {
        toast.warning(`⚠️ Cred factory trovata: ${r.data.username} (${r.data.vendor}). CAMBIARE password!`, { duration: 12000 });
        onSuccess?.(r.data);
      } else {
        toast.info(`Nessuna credenziale default valida su ${server.ip}`);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    } finally { setRunning(false); }
  };

  return (
    <button onClick={run} disabled={running}
      className="text-[9px] px-2 py-0.5 rounded border border-amber-500/40 hover:bg-amber-500/10 text-amber-300 disabled:opacity-50"
      data-testid={`try-default-creds-${server.ip}`}
      title="Tenta credenziali OEM di factory">
      <Key size={10} weight="bold" className="inline -mt-0.5 mr-1" />
      {running ? "…" : "Try Default"}
    </button>
  );
}

// ============================================================================
// BULK CREDENTIALS — applica stessa cred a N server
// ============================================================================
export function BulkCredentialsDialog({ servers, clientId, open, onOpenChange, onSaved }) {
  const [form, setForm] = useState({ username: "", password: "", port: 443 });
  const [selected, setSelected] = useState(new Set(servers.map(s => s.ip)));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setSelected(new Set(servers.map(s => s.ip)));
  }, [open, servers]);

  const save = async () => {
    if (!form.username || !form.password) { toast.error("Username/password obbligatori"); return; }
    if (selected.size === 0) { toast.error("Nessun server selezionato"); return; }
    setSaving(true);
    try {
      const r = await axios.post(`${API}/servers/bulk-credentials`, {
        client_id: clientId,
        ips: Array.from(selected),
        username: form.username,
        password: form.password,
        port: Number(form.port) || 443,
      });
      toast.success(`Credenziali applicate a ${r.data.applied_count} server`);
      onSaved?.();
      onOpenChange(false);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-xl" data-testid="bulk-creds-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Stack className="text-indigo-400" size={16} weight="bold" /> Bulk Credentials</DialogTitle>
          <DialogDescription className="text-xs">Applica le stesse credenziali iLO/Redfish a più server in un click.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-1">
              <Label className="text-[10px] uppercase text-[var(--text-muted)]">Username</Label>
              <Input value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} placeholder="Administrator" className="h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="bulk-username" />
            </div>
            <div className="col-span-1">
              <Label className="text-[10px] uppercase text-[var(--text-muted)]">Password</Label>
              <Input type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} className="h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="bulk-password" />
            </div>
            <div className="col-span-1">
              <Label className="text-[10px] uppercase text-[var(--text-muted)]">Porta</Label>
              <Input type="number" value={form.port} onChange={e => setForm({ ...form, port: e.target.value })} className="h-8 text-xs font-mono bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="bulk-port" />
            </div>
          </div>
          <div className="border border-[var(--bg-border)] rounded-lg p-2 max-h-64 overflow-y-auto">
            <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] mb-2">
              <span>{selected.size}/{servers.length} server selezionati</span>
              <button className="text-cyan-300 hover:underline" onClick={() => setSelected(selected.size === servers.length ? new Set() : new Set(servers.map(s => s.ip)))}>
                {selected.size === servers.length ? "deseleziona tutti" : "seleziona tutti"}
              </button>
            </div>
            {servers.map(s => (
              <label key={s.ip} className="flex items-center gap-2 py-1 cursor-pointer hover:bg-indigo-500/5 rounded px-1">
                <Checkbox checked={selected.has(s.ip)} onCheckedChange={(v) => {
                  const ns = new Set(selected);
                  if (v) ns.add(s.ip); else ns.delete(s.ip);
                  setSelected(ns);
                }} data-testid={`bulk-select-${s.ip}`} />
                <span className="font-mono text-xs flex-1">{s.ip}</span>
                <span className="text-[9px] text-[var(--text-muted)]">{s.name || s.hostname}</span>
                {s.vendor_guess && <span className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300">{s.vendor_guess}</span>}
              </label>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} variant="outline">Annulla</Button>
          <Button onClick={save} disabled={saving} className="bg-indigo-600 hover:bg-indigo-700 text-white" data-testid="bulk-save">
            {saving ? "Salvataggio…" : `Applica a ${selected.size} server`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// HEALTH SCORE WIDGET
// ============================================================================
export function HealthScoreWidget({ clientId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchScore = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/servers/health-score/${clientId}`);
      setData(r.data);
    } catch { setData(null); } finally { setLoading(false); }
  }, [clientId]);

  useEffect(() => { fetchScore(); }, [fetchScore]);

  if (loading) return <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 text-xs text-[var(--text-muted)]">Calcolo Health Score…</div>;
  if (!data || data.total_servers === 0) return null;

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid="health-score-widget">
      <div className="flex items-center gap-2">
        <Trophy size={14} weight="bold" className="text-amber-400" />
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-amber-300">Server Health Score</h3>
        <div className="flex-1 h-px bg-amber-500/15"></div>
        <span className="text-[9px] text-amber-300/70">{data.total_servers} server</span>
      </div>
      {/* Average score */}
      <div className="flex items-center gap-4">
        <div className="relative w-16 h-16">
          <svg viewBox="0 0 36 36" className="w-16 h-16 -rotate-90">
            <circle cx="18" cy="18" r="15" fill="none" stroke="#1f2937" strokeWidth="3" />
            <circle cx="18" cy="18" r="15" fill="none"
              stroke={GRADE_COLOR[data.avg_score >= 90 ? "A" : data.avg_score >= 75 ? "B" : data.avg_score >= 60 ? "C" : data.avg_score >= 40 ? "D" : "F"]}
              strokeWidth="3" strokeDasharray={`${(data.avg_score || 0) * 0.94} 94`} strokeLinecap="round" />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center text-base font-black">{data.avg_score ?? "—"}</div>
        </div>
        <div className="flex-1">
          <div className="flex gap-2 mb-1">
            {Object.entries(data.grade_distribution).map(([grade, count]) => (
              <span key={grade} className="text-[10px] px-2 py-0.5 rounded font-bold" style={{ background: `${GRADE_COLOR[grade]}20`, color: GRADE_COLOR[grade] }}>
                {grade}: {count}
              </span>
            ))}
          </div>
          <div className="text-[9px] text-[var(--text-muted)]">Media flotta · grade su 5 (A=ottimo, F=critico)</div>
        </div>
      </div>
      {/* Per-server scores */}
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {data.servers.map(s => (
          <div key={s.device_ip} className="flex items-center gap-2 text-[10px] p-1.5 rounded bg-[var(--bg-card)] border border-[var(--bg-border)]" data-testid={`health-score-${s.device_ip}`}>
            <span className="w-7 text-center font-black tabular-nums" style={{ color: GRADE_COLOR[s.grade] }}>{s.grade}</span>
            <span className="font-mono w-24 truncate">{s.device_ip}</span>
            <span className="flex-1 truncate text-[var(--text-primary)]">{s.device_name}</span>
            <span className="tabular-nums font-bold" style={{ color: GRADE_COLOR[s.grade] }}>{s.score}/100</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// HARDWARE LIFECYCLE
// ============================================================================
export function LifecyclePanel({ clientId }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    axios.get(`${API}/servers/lifecycle/${clientId}`)
      .then(r => alive && setData(r.data))
      .catch(() => {});
    return () => { alive = false; };
  }, [clientId]);

  if (!data || data.total === 0) return null;
  const recColor = (rec) => rec?.includes("END_OF_LIFE") ? "#EF4444" : rec?.includes("WARNING") ? "#F59E0B" : "#10B981";

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-2" data-testid="lifecycle-panel">
      <div className="flex items-center gap-2">
        <Clock size={14} weight="bold" className="text-rose-400" />
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-rose-300">Hardware Lifecycle Forecast</h3>
        <div className="flex-1 h-px bg-rose-500/15"></div>
        <span className="text-[9px] text-rose-300/70">{data.total} server</span>
      </div>
      <div className="space-y-1">
        {data.servers.map(s => (
          <div key={s.device_ip} className="grid grid-cols-12 gap-2 text-[10px] p-1.5 rounded bg-[var(--bg-card)] border border-[var(--bg-border)] items-center" data-testid={`lifecycle-${s.device_ip}`}>
            <span className="col-span-2 font-mono truncate">{s.device_ip}</span>
            <span className="col-span-3 truncate text-[var(--text-primary)]">{s.device_name}</span>
            <span className="col-span-2 text-[var(--text-muted)] truncate">{s.server_model || "—"}</span>
            <span className="col-span-1 text-center font-bold tabular-nums">{s.age_years ?? "—"}<span className="text-[9px] opacity-60">y</span></span>
            <span className="col-span-4 truncate font-bold" style={{ color: recColor(s.recommendation) }}>{s.recommendation}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// iLO EVENTS DIALOG
// ============================================================================
export function IloEventsButton({ deviceIp }) {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchEvents = async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/servers/ilo-events/${deviceIp}?limit=50`);
      setEvents(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore eventi");
      setEvents({ events: [], error: true });
    } finally { setLoading(false); }
  };

  return (
    <>
      <button onClick={() => { setOpen(true); fetchEvents(); }}
        className="text-[9px] px-2 py-0.5 rounded border border-orange-500/40 hover:bg-orange-500/10 text-orange-300"
        data-testid={`ilo-events-btn-${deviceIp}`}
        title="IML/SEL events hardware">
        <ListBullets size={10} weight="bold" className="inline -mt-0.5 mr-1" />Events
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)] max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><ListBullets size={16} className="text-orange-400" weight="bold" /> IML/SEL Events — {deviceIp}</DialogTitle>
            <DialogDescription className="text-xs">Eventi hardware dal LogService Redfish (PSU, fan, drive, BIOS, ecc.)</DialogDescription>
          </DialogHeader>
          {loading && <div className="text-center py-8 text-[var(--text-muted)]">Caricamento eventi…</div>}
          {events && !loading && (
            <div className="space-y-1 max-h-96 overflow-y-auto">
              {events.events?.length === 0 && (
                <div className="text-center py-6 text-[var(--text-muted)] text-xs">Nessun evento disponibile o LogService non accessibile</div>
              )}
              {events.events?.map((e, i) => (
                <div key={i} className="flex gap-2 p-2 rounded border border-[var(--bg-border)] bg-[var(--bg-card)] text-[10px]">
                  <span className="font-mono text-[var(--text-muted)] w-24 shrink-0">{e.created?.substring(0, 16)?.replace("T", " ")}</span>
                  <span className={`px-1.5 py-0.5 rounded font-bold uppercase shrink-0 ${e.severity === "critical" ? "bg-red-500/20 text-red-300" : e.severity === "warning" ? "bg-amber-500/20 text-amber-300" : "bg-zinc-500/20 text-zinc-300"}`}>
                    {e.severity || "info"}
                  </span>
                  <span className="flex-1 text-[var(--text-primary)]">{e.message}</span>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

// ============================================================================
// HYPER-V PANEL
// ============================================================================
export function HyperVPanel({ clientId }) {
  const [data, setData] = useState(null);
  const [polling, setPolling] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/servers/hyperv/${clientId}`);
      setData(r.data);
    } catch { setData(null); }
  }, [clientId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const pollNow = async () => {
    setPolling(true);
    try {
      const r = await axios.post(`${API}/servers/hyperv/poll-now/${clientId}`);
      toast.success(`Hyper-V poll inviato a ${r.data.sent_to} agent: ${r.data.agents?.join(", ")}`);
      setTimeout(fetchData, 8000);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore poll");
    } finally { setPolling(false); }
  };

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid="hyperv-panel">
      <div className="flex items-center gap-2">
        <Sparkle size={14} weight="bold" className="text-blue-400" />
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-blue-300">Hyper-V Hosts & VMs</h3>
        <div className="flex-1 h-px bg-blue-500/15"></div>
        <button onClick={pollNow} disabled={polling} className="text-[9px] px-2 py-0.5 rounded border border-blue-500/40 hover:bg-blue-500/10 text-blue-300 disabled:opacity-50" data-testid="hyperv-poll-btn">
          {polling ? "Poll…" : "Poll now"}
        </button>
      </div>
      {(!data || data.count === 0) && (
        <div className="text-[10px] text-[var(--text-muted)] py-4 text-center">
          Nessun host Hyper-V rilevato.<br />
          <span className="text-[9px] opacity-60">Clicca "Poll now" per chiedere agli agent Windows v4.19+ di raccogliere via WMI.</span>
        </div>
      )}
      {data?.hosts?.map((h, i) => (
        <div key={i} className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-2.5 space-y-2" data-testid={`hyperv-host-${i}`}>
          <div className="flex items-center justify-between">
            <div>
              <span className="text-sm font-bold text-[var(--text-primary)]">{h.hostname}</span>
              {h.cluster?.name && <span className="ml-2 text-[9px] px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-300">Cluster: {h.cluster.name}</span>}
            </div>
            <span className="text-[9px] text-[var(--text-muted)]">{timeAgo(h.collected_at)}</span>
          </div>
          {h.host_info && (
            <div className="grid grid-cols-4 gap-2 text-[10px]">
              <div><span className="text-[var(--text-muted)]">CPU</span><div className="font-bold">{h.host_info.LogicalProcessors || "?"} core</div></div>
              <div><span className="text-[var(--text-muted)]">RAM</span><div className="font-bold">{h.host_info.MemoryGB || "?"} GB</div></div>
              <div><span className="text-[var(--text-muted)]">Switch</span><div className="font-bold">{h.host_info.VirtSwitches ?? "?"}</div></div>
              <div><span className="text-[var(--text-muted)]">VM count</span><div className="font-bold">{(h.vms || []).length}</div></div>
            </div>
          )}
          {h.vms && h.vms.length > 0 && (
            <div className="border-t border-[var(--bg-border)] pt-2 space-y-1 max-h-48 overflow-y-auto">
              {h.vms.map((vm, vi) => {
                const c = vm.state === "Running" ? "#10B981" : vm.state === "Paused" ? "#F59E0B" : "#64748B";
                return (
                  <div key={vi} className="flex items-center gap-2 text-[10px]">
                    <div className="w-1.5 h-1.5 rounded-full" style={{ background: c }}></div>
                    <span className="flex-1 font-mono truncate">{vm.name}</span>
                    <span className="text-[var(--text-muted)] w-16">{vm.cpu_usage}% CPU</span>
                    <span className="text-[var(--text-muted)] w-16">{vm.memory_mb} MB</span>
                    <span className="font-bold w-14 text-right" style={{ color: c }}>{vm.state}</span>
                  </div>
                );
              })}
            </div>
          )}
          {h.replicas && h.replicas.length > 0 && (
            <div className="border-t border-[var(--bg-border)] pt-2 text-[10px]">
              <span className="text-[var(--text-muted)] uppercase tracking-wider text-[9px]">Hyper-V Replica</span>
              {h.replicas.map((r, ri) => (
                <div key={ri} className="flex justify-between mt-1">
                  <span>{r.vm}</span>
                  <span style={{ color: r.health === "Normal" ? "#10B981" : "#F59E0B" }}>{r.state} / {r.health}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// VCENTER PANEL
// ============================================================================
export function VCenterPanel({ clientId }) {
  const [data, setData] = useState(null);
  const [polling, setPolling] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const [form, setForm] = useState({ vcenter_host: "", username: "", password: "", port: 443 });

  const fetchData = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/servers/vcenter/${clientId}`);
      setData(r.data);
    } catch { setData(null); }
  }, [clientId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const saveConfig = async () => {
    if (!form.vcenter_host || !form.username) return toast.error("Host e username richiesti");
    try {
      await axios.post(`${API}/servers/vcenter/configure`, { client_id: clientId, ...form });
      toast.success(`vCenter ${form.vcenter_host} configurato`);
      setShowConfig(false);
      fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };

  const pollNow = async () => {
    setPolling(true);
    try {
      const r = await axios.post(`${API}/servers/vcenter/poll-now/${clientId}`);
      const okCount = r.data.results.filter(x => x.ok).length;
      toast.success(`vCenter poll: ${okCount} OK su ${r.data.results.length}`);
      setTimeout(fetchData, 2000);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setPolling(false); }
  };

  return (
    <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 space-y-3" data-testid="vcenter-panel">
      <div className="flex items-center gap-2">
        <Cloud size={14} weight="bold" className="text-emerald-400" />
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-emerald-300">VMware vSphere / ESXi</h3>
        <div className="flex-1 h-px bg-emerald-500/15"></div>
        <button onClick={() => setShowConfig(true)} className="text-[9px] px-2 py-0.5 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300" data-testid="vcenter-config-btn">+ vCenter</button>
        {data?.configs?.length > 0 && (
          <button onClick={pollNow} disabled={polling} className="text-[9px] px-2 py-0.5 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300 disabled:opacity-50" data-testid="vcenter-poll-btn">
            {polling ? "Poll…" : "Poll now"}
          </button>
        )}
      </div>
      {(!data || data.configs?.length === 0) && (
        <div className="text-[10px] text-[var(--text-muted)] py-4 text-center">
          Nessun vCenter configurato.<br />
          <span className="text-[9px] opacity-60">Clicca "+ vCenter" e inserisci host+credenziali (read-only).</span>
        </div>
      )}
      {data?.snapshots?.map((s, i) => (
        <div key={i} className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-2.5" data-testid={`vcenter-snapshot-${i}`}>
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-[var(--text-primary)]">{s.vcenter_host}</span>
            <span className="text-[9px] text-[var(--text-muted)]">{timeAgo(s.collected_at)}</span>
          </div>
          <div className="grid grid-cols-4 gap-2 text-[10px] mt-1.5">
            <div><span className="text-[var(--text-muted)]">Cluster</span><div className="font-bold text-emerald-300">{s.counts?.clusters || 0}</div></div>
            <div><span className="text-[var(--text-muted)]">Host</span><div className="font-bold text-emerald-300">{s.counts?.hosts || 0}</div></div>
            <div><span className="text-[var(--text-muted)]">VM</span><div className="font-bold text-emerald-300">{s.counts?.vms || 0}</div></div>
            <div><span className="text-[var(--text-muted)]">Datastore</span><div className="font-bold text-emerald-300">{s.counts?.datastores || 0}</div></div>
          </div>
        </div>
      ))}

      <Dialog open={showConfig} onOpenChange={setShowConfig}>
        <DialogContent className="bg-[var(--bg-card)] border-[var(--bg-border)]">
          <DialogHeader>
            <DialogTitle>Configura vCenter</DialogTitle>
            <DialogDescription className="text-xs">Le credenziali sono cifrate prima del salvataggio.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <div>
              <Label className="text-[10px] uppercase text-[var(--text-muted)]">Host vCenter</Label>
              <Input value={form.vcenter_host} onChange={e => setForm({ ...form, vcenter_host: e.target.value })} placeholder="vcenter.example.local" className="h-8 text-xs font-mono bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="vcenter-host" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-[10px] uppercase text-[var(--text-muted)]">Username</Label>
                <Input value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} placeholder="administrator@vsphere.local" className="h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="vcenter-user" />
              </div>
              <div>
                <Label className="text-[10px] uppercase text-[var(--text-muted)]">Password</Label>
                <Input type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} className="h-8 text-xs bg-[var(--bg-panel)] border-[var(--bg-border)]" data-testid="vcenter-pass" />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setShowConfig(false)} variant="outline">Annulla</Button>
            <Button onClick={saveConfig} className="bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="vcenter-save">Salva</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
