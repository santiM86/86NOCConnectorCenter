import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ArrowLeft, Globe, Lightning, ArrowsClockwise, CheckCircle, XCircle, WarningCircle,
} from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

function SourceRow({ s }) {
  const okColor = s.ok === true ? "text-emerald-400" : s.ok === false ? "text-rose-400" : "text-[var(--text-muted)]";
  const Icon = s.ok === true ? CheckCircle : s.ok === false ? XCircle : WarningCircle;
  return (
    <div className="flex items-start justify-between py-2.5 border-b border-[var(--bg-border)]/50 last:border-0" data-testid={`outage-source-${s.key}`}>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[var(--text-primary)]">{s.name}</span>
          {s.requires_key
            ? <span className="text-[9px] px-1.5 rounded-full bg-amber-500/15 text-amber-300">richiede token</span>
            : <span className="text-[9px] px-1.5 rounded-full bg-emerald-500/15 text-emerald-300">gratuito · no key</span>}
        </div>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{s.kind}</p>
        {s.note && <p className={`text-[10px] mt-0.5 ${okColor}`}>{s.note}</p>}
      </div>
      <div className="flex items-center gap-2 pl-3">
        <span className={`text-[10px] font-mono ${s.enabled ? "text-[var(--text-secondary)]" : "text-[var(--text-muted)]"}`}>
          {s.enabled ? "ATTIVA" : "DISATTIVA"}
        </span>
        <Icon size={18} className={okColor} weight="fill" />
      </div>
    </div>
  );
}

export default function OutageSourcesSettingsPage() {
  const navigate = useNavigate();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [asn, setAsn] = useState("AS3269");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/external-monitor/outage-sources/status?test=true`, { headers });
      setStatus(r.data);
    } catch (e) {
      toast.error("Errore caricamento stato fonti outage");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const runTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      const r = await axios.post(`${API}/api/external-monitor/outage-sources/test?asn=${encodeURIComponent(asn.trim() || "AS3269")}`, {}, { headers });
      setTestResult(r.data);
      toast.success("Correlazione eseguita");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore test correlazione");
    } finally {
      setTesting(false);
    }
  };

  const sourceList = status?.sources
    ? Object.entries(status.sources).map(([key, v]) => ({ key, ...v }))
    : [];

  return (
    <div className="p-4 md:p-6 max-w-3xl mx-auto" data-testid="outage-sources-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate("/settings")}
          className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)]"
          data-testid="outage-sources-back">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-bold flex items-center gap-2">
            <Globe size={20} className="text-sky-400" weight="duotone" />
            Correlazione Outage ISP
          </h1>
          <p className="text-[11px] text-[var(--text-muted)]">
            Fonti pubbliche che stabiliscono se un disservizio è un <strong>guasto diffuso dell'operatore</strong> o è
            <strong> isolato alla singola sede</strong>. Usate da "⚖️ Diagnosi colpa" (tab WAN) e dagli alert proattivi.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Stato fonti */}
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">Fonti configurate</span>
            <Button onClick={reload} disabled={loading} size="sm" variant="outline" className="gap-1 h-7 text-xs" data-testid="outage-sources-reload">
              <ArrowsClockwise size={13} className={loading ? "animate-spin" : ""} /> Ricontrolla
            </Button>
          </div>
          {loading ? (
            <p className="text-[11px] text-[var(--text-muted)] py-3">Verifica fonti in corso…</p>
          ) : (
            <div>
              {sourceList.map((s) => <SourceRow key={s.key} s={s} />)}
              <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--bg-border)] text-[10px] text-[var(--text-muted)]">
                <span>Outage diffusi attivi ora: <strong className={status?.active_outages > 0 ? "text-rose-300" : "text-emerald-300"} data-testid="outage-active-count">{status?.active_outages ?? 0}</strong></span>
                <span>Controllo automatico ogni {Math.round((status?.watch_interval_sec || 300) / 60)} min</span>
              </div>
            </div>
          )}
        </div>

        {/* Nota Cloudflare token */}
        {!loading && status?.sources?.cloudflare && !status.sources.cloudflare.enabled && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
            <p className="text-xs font-semibold text-amber-300 mb-1">Cloudflare Radar non attivo</p>
            <p className="text-[11px] text-[var(--text-secondary)]">
              Manca il token. È opzionale (IODA + RIPEstat funzionano già). Per attivarlo, imposta la variabile
              d'ambiente <code className="font-mono text-amber-200">CLOUDFLARE_RADAR_TOKEN</code> sul server (account Cloudflare gratuito, permesso Account &gt; Radar &gt; Read).
            </p>
          </div>
        )}

        {/* Test correlazione */}
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center justify-between mb-3 gap-2">
            <div className="flex-1">
              <p className="text-xs font-semibold">Test correlazione dal vivo</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                Interroga tutte le fonti per un ASN e mostra il verdetto combinato (diffuso vs isolato).
              </p>
            </div>
            <Input value={asn} onChange={(e) => setAsn(e.target.value)} placeholder="AS3269"
              className="w-28 h-8 text-xs font-mono bg-[var(--bg-input)]" data-testid="outage-test-asn" />
            <Button onClick={runTest} disabled={testing} size="sm" className="gap-1 bg-sky-600 hover:bg-sky-700" data-testid="outage-test-run">
              {testing ? <ArrowsClockwise size={14} className="animate-spin" /> : <Lightning size={14} />}
              {testing ? "…" : "Esegui"}
            </Button>
          </div>
          {testResult && (
            <div className={`rounded p-3 text-[11px] ${testResult.widespread ? "bg-rose-500/10 border border-rose-500/30" : "bg-emerald-500/10 border border-emerald-500/30"}`}
              data-testid="outage-test-result">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold">{testResult.isp_name || testResult.asn}</span>
                <span className={`text-[9px] px-1.5 rounded-full font-bold ${testResult.widespread ? "bg-rose-500/20 text-rose-300" : "bg-emerald-500/20 text-emerald-300"}`}>
                  {testResult.widespread ? "DIFFUSO" : "ISOLATO / OK"}
                </span>
                {testResult.sources?.length > 0 && <span className="text-[10px] text-[var(--text-muted)]">fonti: {testResult.sources.join(", ")}</span>}
              </div>
              <p className="text-[10px] text-[var(--text-secondary)] mb-1">{testResult.summary}</p>
              {(testResult.signals || []).map((sig, i) => <div key={i} className="text-[10px] text-[var(--text-muted)]">• {sig}</div>)}
              {(testResult.external_links || []).length > 0 && (
                <div className="flex flex-wrap gap-2 mt-1.5">
                  {testResult.external_links.map((l, i) => (
                    <a key={i} href={l.url} target="_blank" rel="noreferrer" className="text-[10px] text-sky-400 hover:underline" data-testid={`outage-test-link-${i}`}>{l.name} ↗</a>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Come funziona */}
        <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-4">
          <p className="text-xs font-semibold text-sky-300 mb-2">Come funziona</p>
          <ul className="text-[11px] text-[var(--text-secondary)] space-y-1.5 list-disc pl-4">
            <li><strong>IODA</strong> (Georgia Tech): rileva outage per ASN e per Paese via BGP + active probing + darknet. Gratis, nessuna chiave.</li>
            <li><strong>RIPEstat</strong>: verifica se l'ASN dell'operatore annuncia ancora rotte BGP (crollo = operatore offline). Gratis, nessuna chiave.</li>
            <li><strong>Cloudflare Radar</strong>: annotazioni ufficiali di outage per ASN/Paese. Opzionale (token gratuito).</li>
            <li><strong>Downdetector / Open Fiber</strong>: non hanno API pubblica → forniti come link pre-compilati nel verdetto.</li>
            <li>Un task automatico controlla ogni 5 min gli operatori dei tuoi clienti e invia un <strong>alert Telegram proattivo</strong> se un guasto è diffuso, prima che cada la linea.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
