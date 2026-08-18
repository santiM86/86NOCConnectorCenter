import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ArrowLeft, Route as RouteIcon, Play, Radio, MapPin } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function lossColor(loss, timeout) {
  if (timeout || loss >= 100) return "text-rose-400";
  if (loss >= 50) return "text-amber-400";
  if (loss > 0) return "text-yellow-300";
  return "text-emerald-300";
}

export default function NetworkPathDiagnosisPage() {
  const navigate = useNavigate();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [agents, setAgents] = useState([]);
  const [clients, setClients] = useState({});
  const [probe, setProbe] = useState("");
  const [target, setTarget] = useState("");
  const [mode, setMode] = useState("tcp");
  const [port, setPort] = useState("443");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

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
        (Array.isArray(cl.data) ? cl.data : cl.data.clients || []).forEach((c) => { cmap[c.id] = c.name; });
        setClients(cmap);
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
    const tId = toast.loading("Traccia percorso in corso… (può richiedere fino a ~90s)");
    try {
      const args = { target: target.trim(), mode, port: parseInt(port, 10) || 443, max_hops: 30, count: 10 };
      const { data } = await axios.post(
        `${API}/api/agents/${probe}/command`,
        { name: "net_trace", args, timeout: 115 },
        { headers },
      );
      const r = data.reply || {};
      setResult(r);
      if (r.error) toast.error(`Trace: ${r.error}`, { id: tId });
      else toast.success(`Trace completato (${r.tool}, ${r.hops?.length || 0} hop)`, { id: tId });
    } catch (e) {
      toast.error(`Trace fallito: ${e.response?.data?.detail || e.message}`, { id: tId });
    } finally { setRunning(false); }
  };

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4" data-testid="path-trace-page">
      <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="mb-1 text-xs">
        <ArrowLeft size={14} className="mr-1" /> Indietro
      </Button>

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
                    {a.hostname || a.agent_id?.slice(0, 8)} · {clients[a.client_id] || "—"}
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
                  <th className="text-left py-2 px-2 w-24">Loss %</th>
                  <th className="text-left py-2 px-2 w-24">Latenza</th>
                </tr>
              </thead>
              <tbody>
                {result.hops.map((h) => (
                  <tr key={h.hop} className="border-b border-[var(--bg-border)]/40" data-testid={`path-trace-hop-${h.hop}`}>
                    <td className="py-1.5 px-2 font-mono text-[var(--text-secondary)]">{h.hop}</td>
                    <td className="py-1.5 px-2 font-mono">{h.timeout ? <span className="text-rose-400">* * * (nessuna risposta)</span> : (h.ip || h.host || "—")}</td>
                    <td className={`py-1.5 px-2 font-mono ${lossColor(h.loss_pct, h.timeout)}`}>{h.timeout ? "100" : (h.loss_pct ?? 0)}%</td>
                    <td className="py-1.5 px-2 font-mono">{h.timeout ? "—" : `${(h.avg_ms ?? 0).toFixed(1)} ms`}</td>
                  </tr>
                ))}
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
    </div>
  );
}
