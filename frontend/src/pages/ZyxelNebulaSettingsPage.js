import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft, Cloud, RefreshCw, Trash2, PlugZap, Cpu, MemoryStick,
  Activity, Server, ShieldCheck, CheckCircle2, AlertCircle, Link2,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function StatusDot({ status }) {
  const online = status === "ONLINE";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full ${online ? "bg-emerald-400" : "bg-rose-500"}`} />
      <span className={`text-[11px] font-semibold ${online ? "text-emerald-300" : "text-rose-300"}`}>
        {status || "—"}
      </span>
    </span>
  );
}

function MetricPill({ icon: Icon, value, suffix, warn, crit }) {
  if (value === null || value === undefined) return <span className="text-[var(--text-secondary)] text-xs">—</span>;
  const v = Number(value);
  let color = "text-slate-200";
  if (crit != null && v >= crit) color = "text-rose-300";
  else if (warn != null && v >= warn) color = "text-amber-300";
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-mono ${color}`}>
      <Icon size={13} className="opacity-70" />{v}{suffix}
    </span>
  );
}

export default function ZyxelNebulaSettingsPage() {
  const navigate = useNavigate();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [config, setConfig] = useState(null);
  const [apiKey, setApiKey] = useState("");
  const [orgs, setOrgs] = useState([]);
  const [clients, setClients] = useState([]);
  const [links, setLinks] = useState([]);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [cfg, cl] = await Promise.all([
        axios.get(`${API}/api/admin/zyxel/config`, { headers }),
        axios.get(`${API}/api/clients`, { headers }),
      ]);
      setConfig(cfg.data);
      setClients(Array.isArray(cl.data) ? cl.data : (cl.data.clients || []));
      if (cfg.data.configured) {
        const [og, lk, dv] = await Promise.all([
          axios.get(`${API}/api/zyxel/organizations`, { headers }),
          axios.get(`${API}/api/zyxel/links`, { headers }),
          axios.get(`${API}/api/zyxel/devices`, { headers }),
        ]);
        setOrgs(og.data.organizations || []);
        setLinks(lk.data.links || []);
        setDevices(dv.data.devices || []);
      }
    } catch (e) {
      toast.error(`Caricamento fallito: ${e.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const saveConfig = async () => {
    if (!apiKey.trim()) { toast.error("Inserisci la chiave OpenAPI"); return; }
    setSaving(true);
    try {
      await axios.put(`${API}/api/admin/zyxel/config`, { api_key: apiKey.trim() }, { headers });
      toast.success("Chiave Nebula salvata (cifrata)");
      setApiKey("");
      await reload();
    } catch (e) {
      toast.error(`Salvataggio fallito: ${e.response?.data?.detail || e.message}`);
    } finally { setSaving(false); }
  };

  const testConn = async () => {
    setTesting(true);
    try {
      const r = await axios.post(`${API}/api/admin/zyxel/test`, {}, { headers });
      toast.success(`Connessione OK · ${r.data.org_count} organizzazioni (${r.data.pro_org_count} PRO)`);
      await reload();
    } catch (e) {
      toast.error(`Test fallito: ${e.response?.data?.detail || e.message}`);
    } finally { setTesting(false); }
  };

  const refreshOrgs = async () => {
    try {
      const r = await axios.get(`${API}/api/zyxel/organizations?refresh=true`, { headers });
      setOrgs(r.data.organizations || []);
      toast.success(`${(r.data.organizations || []).length} organizzazioni aggiornate`);
    } catch (e) { toast.error(`Errore: ${e.response?.data?.detail || e.message}`); }
  };

  const removeConfig = async () => {
    if (!window.confirm("Rimuovere la configurazione Zyxel Nebula? Tutti i mapping e i device sincronizzati saranno eliminati.")) return;
    try {
      await axios.delete(`${API}/api/admin/zyxel/config`, { headers });
      toast.success("Configurazione rimossa");
      await reload();
    } catch (e) { toast.error("Errore rimozione"); }
  };

  const linkClient = async (clientId, orgId) => {
    try {
      if (orgId === "__unlink__") {
        await axios.delete(`${API}/api/clients/${clientId}/zyxel/link`, { headers });
        toast.success("Mapping rimosso");
      } else {
        const r = await axios.put(`${API}/api/clients/${clientId}/zyxel/link`, { org_id: orgId }, { headers });
        toast.success(`Cliente mappato · ${r.data.device_count} device (sync avviato)`);
      }
      await reload();
    } catch (e) {
      toast.error(`Errore mapping: ${e.response?.data?.detail || e.message}`);
    }
  };

  const syncNow = async () => {
    setSyncing(true);
    const tId = toast.loading("Sincronizzazione flotta Zyxel in corso…");
    try {
      const r = await axios.post(`${API}/api/zyxel/sync-now`, {}, { headers });
      toast.success(`✅ ${r.data.devices_synced} device sincronizzati su ${r.data.clients} clienti`, { id: tId });
      await reload();
    } catch (e) {
      toast.error(`Sync fallita: ${e.response?.data?.detail || e.message}`, { id: tId });
    } finally { setSyncing(false); }
  };

  const linkByClient = Object.fromEntries(links.map((l) => [l.client_id, l]));

  if (loading) return <div className="p-6 text-[var(--text-secondary)]">Caricamento…</div>;

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4" data-testid="zyxel-settings-page">
      <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="mb-1 text-xs">
        <ArrowLeft size={14} className="mr-1" /> Indietro
      </Button>

      {/* Config */}
      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5">
        <div className="flex items-center gap-2 mb-3">
          <Cloud size={18} className="text-emerald-400" />
          <h2 className="text-base font-bold">Zyxel Nebula (NCC OpenAPI)</h2>
          {config?.configured && (
            <span className="ml-2 px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-[10px] font-bold">
              CONFIGURATA · {config.api_key_preview}
            </span>
          )}
        </div>
        <p className="text-[11px] text-[var(--text-secondary)] mb-3">
          Monitoraggio cloud dei dispositivi Zyxel (firewall USG FLEX serie H, switch, AP) via Nebula Control Center.
          Una sola chiave OpenAPI legge stato, firmware e metriche (CPU/memoria/sessioni/traffico) di tutte le organizzazioni.
          Richiede licenza <span className="font-semibold">Nebula Professional Pack</span>. La chiave è salvata cifrata (AES).
        </p>

        <div className="flex flex-col md:flex-row gap-3 md:items-end">
          <div className="flex-1">
            <Label className="text-[10px] uppercase tracking-wider">OpenAPI Key</Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={config?.configured ? `(salvata: ${config.api_key_preview})` : "Incolla la NCC OpenAPI Key…"}
              className="mt-1 h-9 text-xs font-mono"
              data-testid="zyxel-api-key-input"
            />
          </div>
          <Button onClick={saveConfig} disabled={saving} size="sm" className="h-9" data-testid="zyxel-save-btn">
            <ShieldCheck size={14} className="mr-1" /> {saving ? "Salvo…" : "Salva"}
          </Button>
          <Button onClick={testConn} disabled={testing || !config?.configured} variant="outline" size="sm" className="h-9" data-testid="zyxel-test-btn">
            <PlugZap size={14} className="mr-1" /> {testing ? "Test…" : "Test connessione"}
          </Button>
          {config?.configured && (
            <Button onClick={removeConfig} variant="destructive" size="sm" className="h-9" data-testid="zyxel-delete-btn">
              <Trash2 size={14} />
            </Button>
          )}
        </div>
        {config?.last_error && (
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-rose-300">
            <AlertCircle size={13} /> {config.last_error}
          </div>
        )}
      </div>

      {config?.configured && (
        <>
          {/* Mapping clienti -> org */}
          <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5" data-testid="zyxel-mapping-card">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Link2 size={16} className="text-cyan-400" />
                <h3 className="text-sm font-bold">Mapping clienti → organizzazione Nebula</h3>
              </div>
              <Button onClick={refreshOrgs} variant="outline" size="sm" className="h-8 text-xs">
                <RefreshCw size={13} className="mr-1" /> Aggiorna org ({orgs.length})
              </Button>
            </div>
            <div className="space-y-2 max-h-[360px] overflow-auto">
              {clients.map((c) => {
                const link = linkByClient[c.id];
                return (
                  <div key={c.id} className="flex items-center gap-3 py-1.5 border-b border-[var(--bg-border)]/50" data-testid={`zyxel-client-row-${c.id}`}>
                    <span className="flex-1 text-xs font-medium truncate">{c.name}</span>
                    {link && (
                      <Badge variant="outline" className="text-[10px] text-emerald-300 border-emerald-500/40">
                        {link.device_count} device
                      </Badge>
                    )}
                    <Select
                      value={link?.org_id || "__none__"}
                      onValueChange={(v) => v !== "__none__" && linkClient(c.id, v)}
                    >
                      <SelectTrigger className="w-[240px] h-8 text-xs" data-testid={`zyxel-org-select-${c.id}`}>
                        <SelectValue placeholder="Nessuna org" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" disabled>Seleziona organizzazione…</SelectItem>
                        {link && <SelectItem value="__unlink__">✕ Rimuovi mapping</SelectItem>}
                        {orgs.map((o) => (
                          <SelectItem key={o.org_id} value={o.org_id} className="text-xs">
                            {o.name} {o.mode === "PRO" ? "· PRO" : `· ${o.mode}`}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                );
              })}
              {clients.length === 0 && <div className="text-xs text-[var(--text-secondary)]">Nessun cliente Argus.</div>}
            </div>
          </div>

          {/* Flotta Zyxel */}
          <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5" data-testid="zyxel-fleet-card">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Server size={16} className="text-emerald-400" />
                <h3 className="text-sm font-bold">Flotta Zyxel · {devices.length} dispositivi</h3>
              </div>
              <Button onClick={syncNow} disabled={syncing} size="sm" className="h-8 text-xs" data-testid="zyxel-sync-btn">
                <RefreshCw size={13} className={`mr-1 ${syncing ? "animate-spin" : ""}`} /> {syncing ? "Sync…" : "Sincronizza ora"}
              </Button>
            </div>
            <div className="overflow-auto max-h-[520px]">
              <table className="w-full text-xs">
                <thead className="text-[var(--text-secondary)] text-[10px] uppercase tracking-wider">
                  <tr className="border-b border-[var(--bg-border)]">
                    <th className="text-left py-2 px-2">Cliente</th>
                    <th className="text-left py-2 px-2">Modello</th>
                    <th className="text-left py-2 px-2">Sito</th>
                    <th className="text-left py-2 px-2">Stato</th>
                    <th className="text-left py-2 px-2">CPU</th>
                    <th className="text-left py-2 px-2">Mem</th>
                    <th className="text-left py-2 px-2">Sessioni</th>
                    <th className="text-left py-2 px-2">Firmware</th>
                  </tr>
                </thead>
                <tbody>
                  {devices.map((d) => (
                    <tr key={d.dev_id} className="border-b border-[var(--bg-border)]/40 hover:bg-white/5" data-testid={`zyxel-device-row-${d.dev_id}`}>
                      <td className="py-2 px-2 text-[var(--text-secondary)]">{d.client_name || "—"}</td>
                      <td className="py-2 px-2 font-medium">{d.model || d.name}</td>
                      <td className="py-2 px-2 text-[var(--text-secondary)]">{d.site_name || "—"}</td>
                      <td className="py-2 px-2"><StatusDot status={d.online_status} /></td>
                      <td className="py-2 px-2"><MetricPill icon={Cpu} value={d.cpu_usage} suffix="%" warn={70} crit={90} /></td>
                      <td className="py-2 px-2"><MetricPill icon={MemoryStick} value={d.mem_usage} suffix="%" warn={80} crit={95} /></td>
                      <td className="py-2 px-2"><MetricPill icon={Activity} value={d.sessions} suffix="" /></td>
                      <td className="py-2 px-2">
                        {d.firmware ? (
                          <span className={`text-[11px] ${d.firmware.status === "UP_TO_DATE" ? "text-emerald-300" : "text-amber-300"}`}>
                            {d.firmware.current || "—"}
                          </span>
                        ) : <span className="text-[var(--text-secondary)]">—</span>}
                      </td>
                    </tr>
                  ))}
                  {devices.length === 0 && (
                    <tr><td colSpan={8} className="py-6 text-center text-[var(--text-secondary)]">
                      Nessun device sincronizzato. Mappa un cliente a un'organizzazione qui sopra.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
