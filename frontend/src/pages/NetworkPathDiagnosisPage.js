import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ArrowLeft, Route as RouteIcon, Play, Radio, MapPin, KeyRound, Copy, Download } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const API = process.env.REACT_APP_BACKEND_URL;

function lossColor(loss, timeout) {
  if (timeout || loss >= 100) return "text-rose-400";
  if (loss >= 50) return "text-amber-400";
  if (loss > 0) return "text-yellow-300";
  return "text-emerald-300";
}

export default function NetworkPathDiagnosisPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [agents, setAgents] = useState([]);
  const [clients, setClients] = useState({});
  const [probe, setProbe] = useState("");
  const [target, setTarget] = useState(searchParams.get("target") || "");
  const [mode, setMode] = useState("tcp");
  const [port, setPort] = useState("443");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [clientList, setClientList] = useState([]);
  const [probeClient, setProbeClient] = useState("");
  const [probeLabel, setProbeLabel] = useState("sonda-trace-86bit");
  const [genToken, setGenToken] = useState(null);
  const [genBusy, setGenBusy] = useState(false);
  const [geoByIp, setGeoByIp] = useState({});
  const [targetClient, setTargetClient] = useState("");

  const isPublicIp = (ip) => ip && !/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.|169\.254\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)/.test(ip);

  const pickClient = async (cid) => {
    setTargetClient(cid);
    if (!cid) return;
    const own = agents.find((a) => a.client_id === cid);
    const glob = agents.find((a) => a.client_id === "__global__");
    if (own) setProbe(own.agent_id);
    else if (glob) setProbe(glob.agent_id);
    try {
      const { data } = await axios.get(`${API}/api/external-monitor/detected-public-ip/${encodeURIComponent(cid)}`, { headers });
      if (data?.public_ip) { setTarget(data.public_ip); toast.success(`IP pubblico ${clients[cid] || ""}: ${data.public_ip}`); }
      else toast.info("IP pubblico non ancora rilevato per questo cliente");
    } catch { /* noop */ }
  };

  const enrichGeo = async (hops) => {
    const ips = [...new Set((hops || []).map((h) => h.ip).filter(isPublicIp))];
    if (!ips.length) { setGeoByIp({}); return; }
    const entries = await Promise.all(ips.map(async (ip) => {
      try { const { data } = await axios.get(`${API}/api/external-monitor/geo-ip/${encodeURIComponent(ip)}`, { headers }); return [ip, data]; }
      catch { return [ip, null]; }
    }));
    setGeoByIp(Object.fromEntries(entries));
  };

  useEffect(() => {
    (async () => {
      try {
        const [ag, cl] = await Promise.all([
          axios.get(`${API}/api/agents`, { headers }),
          axios.get(`${API}/api/clients`, { headers }),
        ]);
        const live = (Array.isArray(ag.data) ? ag.data : ag.data.agents || []).filter((a) => a.live);
        setAgents(live);
        const cmap = {};
        const list = (Array.isArray(cl.data) ? cl.data : cl.data.clients || []);
        list.forEach((c) => { cmap[c.id] = c.name; });
        setClients(cmap);
        setClientList(list);
        // default sonda: GLOBALE (una sola sonda per tutti i clienti)
        setProbeClient("__global__");
        if (live.length) setProbe(live[0].agent_id);
      } catch (e) {
        toast.error(`Caricamento agent fallito: ${e.response?.data?.detail || e.message}`);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runTrace = async () => {
    if (!probe) { toast.error("Seleziona un agent-sonda"); return; }
    if (!target.trim()) { toast.error("Inserisci IP o host di destinazione"); return; }
    setRunning(true);
    setResult(null);
    const tId = toast.loading("Traccia percorso in corso… (fino a ~45s)");
    try {
      const args = { target: target.trim(), mode, port: parseInt(port, 10) || 443, max_hops: 20, count: 3 };
      const { data } = await axios.post(
        `${API}/api/agents/${probe}/command`,
        { name: "net_trace", args, timeout: 45 },
        { headers, timeout: 60000 },
      );
      // La reply dell'agent è AgentReply { ok, error?, result } → il vero esito
      // net_trace è dentro `result` (unwrap, con fallback per PascalCase legacy).
      const reply = data.reply || {};
      const r = reply.result || reply.Result || reply;
      const replyErr = reply.error || reply.Error || r.error;
      setResult(r);
      enrichGeo(r.hops || []);
      if (replyErr) toast.error(`Trace: ${replyErr}`, { id: tId });
      else toast.success(`Trace completato (${r.tool || "?"}, ${r.hops?.length || 0} hop)`, { id: tId });
    } catch (e) {
      toast.error(`Trace fallito: ${e.response?.data?.detail || e.message}`, { id: tId });
    } finally { setRunning(false); }
  };

  const genProbeToken = async () => {
    if (!probeClient) { toast.error("Seleziona il cliente/sede per la sonda"); return; }
    setGenBusy(true);
    try {
      const { data } = await axios.post(
        `${API}/api/agents/register`,
        { client_id: probeClient, label: probeLabel || "sonda-trace" },
        { headers },
      );
      setGenToken(data);
      toast.success("Token agent-sonda creato");
    } catch (e) {
      toast.error(`Creazione token fallita: ${e.response?.data?.detail || e.message}`);
    } finally { setGenBusy(false); }
  };

  const copyText = (txt) => {
    navigator.clipboard?.writeText(txt);
    toast.success("Copiato negli appunti");
  };

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4" data-testid="path-trace-page">
      <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="mb-1 text-xs">
        <ArrowLeft size={14} className="mr-1" /> Indietro
      </Button>

      {/* Crea agent-sonda */}
      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5" data-testid="probe-enroll-card">
        <div className="flex items-center gap-2 mb-2">
          <KeyRound size={16} className="text-amber-400" />
          <h3 className="text-sm font-bold">Agent-sonda (installa nella tua sede/NOC)</h3>
        </div>
        <p className="text-[11px] text-[var(--text-secondary)] mb-3">
          Genera un token per installare l'agent-SONDA da cui partono i traceroute. Ti basta
          <b> UNA sonda globale</b> installata nella tua sede/NOC per tracciare il percorso verso
          <b> tutti i clienti</b> (non serve una sonda per cliente, né toccare gli agent dei clienti).
        </p>
        <div className="flex flex-col md:flex-row gap-3 md:items-end">
          <div className="flex-1">
            <Label className="text-[10px] uppercase tracking-wider">Sede / cliente della sonda</Label>
            <Select value={probeClient} onValueChange={setProbeClient}>
              <SelectTrigger className="mt-1 h-9 text-xs" data-testid="probe-client-select"><SelectValue placeholder="Seleziona…" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__global__" className="text-xs font-semibold text-cyan-400" data-testid="probe-client-global">
                  🌐 Sonda globale (tutti i clienti)
                </SelectItem>
                {clientList.map((c) => (
                  <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex-1">
            <Label className="text-[10px] uppercase tracking-wider">Etichetta</Label>
            <Input value={probeLabel} onChange={(e) => setProbeLabel(e.target.value)} className="mt-1 h-9 text-xs" data-testid="probe-label-input" />
          </div>
          <Button onClick={genProbeToken} disabled={genBusy} size="sm" className="h-9" data-testid="probe-create-token-btn">
            <KeyRound size={14} className="mr-1" /> {genBusy ? "Creo…" : "Genera comando installazione"}
          </Button>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5">
        <div className="flex items-center gap-2 mb-2">
          <RouteIcon size={18} className="text-cyan-400" />
          <h2 className="text-base font-bold">Diagnosi Percorso (traceroute / MTR)</h2>
        </div>
        <p className="text-[11px] text-[var(--text-secondary)] mb-4">
          Esegue un traceroute/MTR da un <b>agent-sonda</b> (idealmente installato nella tua sede/NOC)
          verso l'IP pubblico del cliente. Mostra loss% e latenza per ogni hop, così localizzi se
          l'interruzione è nel carrier o nell'ultimo miglio/CPE. TCP :443 aggira i blocchi ICMP.
        </p>

        <div className="mb-3">
          <Label className="text-[10px] uppercase tracking-wider flex items-center gap-1"><MapPin size={11} /> Cliente da tracciare (auto: sonda + IP pubblico)</Label>
          <Select value={targetClient} onValueChange={pickClient}>
            <SelectTrigger className="mt-1 h-9 text-xs" data-testid="path-trace-client-select">
              <SelectValue placeholder="Scegli un cliente → compila IP e sonda in automatico…" />
            </SelectTrigger>
            <SelectContent>
              {clientList.map((c) => (
                <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <Label className="text-[10px] uppercase tracking-wider flex items-center gap-1"><Radio size={11} /> Agent-sonda</Label>
            <Select value={probe} onValueChange={setProbe}>
              <SelectTrigger className="mt-1 h-9 text-xs" data-testid="path-trace-probe-select">
                <SelectValue placeholder="Seleziona agent…" />
              </SelectTrigger>
              <SelectContent>
                {agents.length === 0 && <SelectItem value="__none__" disabled>Nessun agent connesso</SelectItem>}
                {agents.map((a) => (
                  <SelectItem key={a.agent_id} value={a.agent_id} className="text-xs">
                    {a.hostname || a.agent_id?.slice(0, 8)} · {a.client_id === "__global__" ? "🌐 Sonda globale" : (clients[a.client_id] || "—")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-wider flex items-center gap-1"><MapPin size={11} /> Destinazione (IP/host)</Label>
            <Input value={target} onChange={(e) => setTarget(e.target.value)}
              placeholder="es. 93.40.xxx.xxx" className="mt-1 h-9 text-xs font-mono" data-testid="path-trace-target-input" />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-wider">Modalità</Label>
            <Select value={mode} onValueChange={setMode}>
              <SelectTrigger className="mt-1 h-9 text-xs" data-testid="path-trace-mode-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="tcp" className="text-xs">TCP (consigliato, aggira ICMP)</SelectItem>
                <SelectItem value="icmp" className="text-xs">ICMP</SelectItem>
                <SelectItem value="udp" className="text-xs">UDP</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-wider">Porta (TCP/UDP)</Label>
            <Input value={port} onChange={(e) => setPort(e.target.value)} disabled={mode === "icmp"}
              className="mt-1 h-9 text-xs font-mono" data-testid="path-trace-port-input" />
          </div>
        </div>
        <div className="mt-4">
          <Button onClick={runTrace} disabled={running} size="sm" className="h-9" data-testid="path-trace-run-btn">
            <Play size={14} className={`mr-1 ${running ? "animate-pulse" : ""}`} /> {running ? "In esecuzione…" : "Esegui trace"}
          </Button>
        </div>
      </div>

      {result && (
        <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 md:p-5" data-testid="path-trace-result">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold">
              Percorso verso {result.target}
              <span className="text-[var(--text-secondary)] font-normal"> · tool {result.tool} · {result.os}</span>
            </h3>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${result.reached ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
              {result.reached ? "DESTINAZIONE RAGGIUNTA" : "NON RAGGIUNTA"}
            </span>
          </div>
          {result.error && <div className="text-xs text-rose-300 mb-2">{result.error}</div>}
          {result.hops?.length > 0 && (
            <table className="w-full text-xs">
              <thead className="text-[var(--text-secondary)] text-[10px] uppercase tracking-wider">
                <tr className="border-b border-[var(--bg-border)]">
                  <th className="text-left py-2 px-2 w-12">Hop</th>
                  <th className="text-left py-2 px-2">IP / Host</th>
                  <th className="text-left py-2 px-2">Località · ISP · Organizzazione</th>
                  <th className="text-left py-2 px-2 w-20">Loss %</th>
                  <th className="text-left py-2 px-2 w-20">Latenza</th>
                </tr>
              </thead>
              <tbody>
                {result.hops.map((h) => {
                  const g = geoByIp[h.ip];
                  const priv = h.ip && !isPublicIp(h.ip);
                  return (
                  <tr key={h.hop} className="border-b border-[var(--bg-border)]/40" data-testid={`path-trace-hop-${h.hop}`}>
                    <td className="py-1.5 px-2 font-mono text-[var(--text-secondary)]">{h.hop}</td>
                    <td className="py-1.5 px-2 font-mono">{h.timeout ? <span className="text-rose-400">* * * (nessuna risposta)</span> : (h.ip || h.host || "—")}</td>
                    <td className="py-1.5 px-2 text-[11px]" data-testid={`path-trace-hop-geo-${h.hop}`}>
                      {h.timeout ? "—" : priv ? <span className="text-[var(--text-muted)]">Rete locale / privata</span>
                        : g ? (
                          <span>
                            {g.city ? `${g.city}${g.country ? ", " + g.country : ""}` : (g.country || "—")}
                            {g.isp && <span className="text-cyan-300"> · {g.isp}</span>}
                            {g.org && g.org !== g.isp && <span className="text-[var(--text-muted)]"> · {g.org}</span>}
                          </span>
                        ) : <span className="text-[var(--text-muted)]">…</span>}
                    </td>
                    <td className={`py-1.5 px-2 font-mono ${lossColor(h.loss_pct, h.timeout)}`}>{h.timeout ? "100" : (h.loss_pct ?? 0)}%</td>
                    <td className="py-1.5 px-2 font-mono">{h.timeout ? "—" : `${(h.avg_ms ?? 0).toFixed(1)} ms`}</td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <p className="text-[10px] text-[var(--text-secondary)] mt-3">
            Suggerimento: se il loss diventa 100% da un certo hop fino in fondo, l'interruzione è
            all'hop <b>precedente</b> a quel punto. Loss al 100% solo su hop intermedi (ma con hop
            successivi ok) è normale (rate-limiting ICMP dei router).
          </p>
        </div>
      )}

      <Dialog open={!!genToken} onOpenChange={(o) => !o && setGenToken(null)}>
        <DialogContent className="max-w-2xl" data-testid="probe-token-dialog">
          <DialogHeader>
            <DialogTitle className="text-sm flex items-center gap-2">
              <KeyRound size={16} className="text-amber-400" /> Comando installazione agent-sonda
            </DialogTitle>
          </DialogHeader>
          {genToken && (() => {
            const raw = "https://raw.githubusercontent.com/santiM86/86NOCConnectorCenter/main/noc-agent/build/install-noc-agent.ps1";
            const wsBase = (window.location.origin || "https://argus.86bit.it").replace(/^http/, "ws");
            const backendUrl = genToken.backend_url || `${wsBase}/api/agent/ws`;
            const installCmd = `powershell -ExecutionPolicy Bypass -Command "iwr -useb ${raw} -OutFile $env:TEMP\\i.ps1; & $env:TEMP\\i.ps1 -Token '${genToken.token}' -ClientId '${genToken.client_id}' -BackendUrl '${backendUrl}' -Role master"`;
            return (
              <div className="space-y-3 text-xs">
                <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 p-2 text-amber-200 text-[11px]">
                  ⚠️ Esegui in <b>PowerShell come Amministratore</b> su UNA macchina Windows della tua sede/NOC.
                  Il token è valido solo per questa sonda. Non condividerlo.
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <Label className="text-[10px] uppercase tracking-wider flex items-center gap-1"><Download size={12} /> Installazione (PowerShell)</Label>
                    <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => copyText(installCmd)} data-testid="probe-install-copy-btn">
                      <Copy size={12} className="mr-1" /> Copia
                    </Button>
                  </div>
                  <code className="block bg-black/40 rounded px-3 py-2.5 font-mono break-all text-[11px] leading-relaxed text-emerald-200 border border-[var(--bg-border)]" data-testid="probe-install-cmd">
                    {installCmd}
                  </code>
                </div>
                <p className="text-[10px] text-[var(--text-secondary)]">
                  Stessa installazione degli agent dei clienti. Dopo l'esecuzione la sonda apparirà tra gli agent connessi e potrai selezionarla qui sopra per lanciare i trace.
                </p>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}
