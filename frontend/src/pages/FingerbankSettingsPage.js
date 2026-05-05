import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ArrowLeft, ShieldCheck, Trash, Plug, Lightning, ArrowsClockwise, Lock, Question,
} from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function FingerbankSettingsPage() {
  const navigate = useNavigate();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [status, setStatus] = useState(null);
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const reload = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/admin/integrations/fingerbank`, { headers });
      setStatus(r.data);
    } catch (e) {
      toast.error("Errore caricamento stato Fingerbank");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const save = async () => {
    if (!apiKey || apiKey.trim().length < 8) {
      toast.error("API key non valida (min 8 caratteri)");
      return;
    }
    setSaving(true);
    try {
      await axios.put(`${API}/api/admin/integrations/fingerbank`,
        { api_key: apiKey.trim() }, { headers });
      toast.success("API key salvata (cifrata AES-256-GCM)");
      setApiKey("");
      await reload();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Eliminare la API key Fingerbank? La classificazione avanzata si disattivera'.")) return;
    try {
      await axios.delete(`${API}/api/admin/integrations/fingerbank`, { headers });
      toast.success("API key rimossa");
      setTestResult(null);
      await reload();
    } catch (e) {
      toast.error("Errore");
    }
  };

  const test = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await axios.post(`${API}/api/admin/integrations/fingerbank/test`,
        {}, { headers });
      setTestResult(r.data);
      if (r.data.ok) toast.success("Test OK — Fingerbank risponde");
      else toast.warning("Test fallito — vedi dettaglio");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore test");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="p-4 md:p-6 max-w-3xl mx-auto" data-testid="fingerbank-settings-page">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => navigate("/settings")}
          className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)]"
          data-testid="fingerbank-back">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-bold flex items-center gap-2">
            <Plug size={20} className="text-fuchsia-400" weight="duotone" />
            Fingerbank Device Identification
          </h1>
          <p className="text-[11px] text-[var(--text-muted)]">
            Identifica modelli di device sconosciuti via DHCP fingerprint, MAC e user-agent.
            API key cifrata AES-256-GCM. Free tier: <strong>250 query/giorno</strong>.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Stato corrente */}
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Lock size={14} className="text-cyan-400" />
              <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                Stato configurazione
              </span>
            </div>
            {!loading && status && (
              <span className={`text-[11px] px-2 py-0.5 rounded font-mono ${
                status.configured ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"
              }`} data-testid="fingerbank-status-badge">
                {status.configured ? "ATTIVA" : "NON CONFIGURATA"}
              </span>
            )}
          </div>
          {loading ? (
            <p className="text-[11px] text-[var(--text-muted)]">Caricamento…</p>
          ) : status?.configured ? (
            <div className="space-y-2 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-[var(--text-muted)]">API key (mascherata)</span>
                <code className="font-mono text-cyan-300">{status.masked_key || "—"}</code>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[var(--text-muted)]">Ultimo aggiornamento</span>
                <span className="font-mono text-[var(--text-secondary)]">
                  {status.updated_at ? new Date(status.updated_at).toLocaleString("it-IT") : "—"}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-[11px] text-[var(--text-muted)]">
              Inserisci la tua API key qui sotto per attivare l'integrazione.
            </p>
          )}
        </div>

        {/* Input nuova key */}
        <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-4">
          <Label className="text-xs font-semibold mb-2 block">
            {status?.configured ? "Aggiorna API key" : "Inserisci API key Fingerbank"}
          </Label>
          <div className="flex gap-2">
            <Input
              type="password"
              autoComplete="off"
              placeholder="es. 69fe2f73939fe736…"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="flex-1 bg-[var(--bg-input)] text-xs font-mono"
              data-testid="fingerbank-key-input"
            />
            <Button onClick={save} disabled={saving || !apiKey} size="sm"
              className="gap-1 bg-fuchsia-600 hover:bg-fuchsia-700"
              data-testid="fingerbank-save-btn">
              <ShieldCheck size={14} />
              {saving ? "Salvataggio…" : "Salva (cifrata)"}
            </Button>
          </div>
          <p className="text-[10px] text-[var(--text-muted)] mt-2 flex items-center gap-1">
            <Question size={10} />
            La key viene cifrata immediatamente con AES-256-GCM e non viene mai mostrata in chiaro nemmeno a te dopo il salvataggio.
            Ottienila gratis su <a href="https://api.fingerbank.org" target="_blank" rel="noreferrer"
              className="text-cyan-400 hover:underline">api.fingerbank.org</a>.
          </p>
        </div>

        {/* Test */}
        {status?.configured && (
          <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-xs font-semibold">Test connessione</p>
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                  Esegue una query interrogate con MAC OUI HP per verificare che la key sia accettata.
                </p>
              </div>
              <Button onClick={test} disabled={testing} size="sm" variant="outline"
                className="gap-1" data-testid="fingerbank-test-btn">
                {testing ? <ArrowsClockwise size={14} className="animate-spin" /> : <Lightning size={14} />}
                {testing ? "Test in corso…" : "Esegui test"}
              </Button>
            </div>
            {testResult && (
              <div className={`rounded p-3 text-[11px] ${testResult.ok ? "bg-emerald-500/10 border border-emerald-500/30" : "bg-amber-500/10 border border-amber-500/30"}`}
                data-testid="fingerbank-test-result">
                <div className="font-semibold mb-1">
                  {testResult.ok ? "OK — Risposta valida" : "Nessun risultato"}
                </div>
                {testResult.result ? (
                  <pre className="text-[10px] font-mono whitespace-pre-wrap text-[var(--text-secondary)]">
                    {JSON.stringify(testResult.result, null, 2)}
                  </pre>
                ) : (
                  <p className="text-[10px] text-[var(--text-muted)]">{testResult.note}</p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Cosa fa */}
        <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-4">
          <p className="text-xs font-semibold text-cyan-300 mb-2">A cosa serve</p>
          <ul className="text-[11px] text-[var(--text-secondary)] space-y-1.5 list-disc pl-4">
            <li>Identifica modelli precisi (es. <em>HP LaserJet M404</em>, <em>Polycom VVX 411</em>) dei device sconosciuti rilevati come "Hewlett Packard" generico.</li>
            <li>I risultati vengono cacheati 30 giorni in MongoDB per non riconsumare la quota gratuita.</li>
            <li>Combinato con le euristiche locali (OUI vendor, LLDP-MED, PoE class), aumenta drasticamente la precisione del rilevamento dispositivi PoE.</li>
            <li>Quota gratuita: <strong>250 query/giorno</strong> (sufficiente per la maggior parte delle reti SMB).</li>
          </ul>
        </div>

        {/* Delete */}
        {status?.configured && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold text-red-300">Rimuovi configurazione</p>
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                  Elimina la API key dal DB. La classificazione tornera' a usare solo le fonti locali (OUI, LLDP, sysDescr).
                </p>
              </div>
              <Button onClick={remove} size="sm" variant="outline"
                className="gap-1 border-red-500/40 text-red-300 hover:bg-red-500/10"
                data-testid="fingerbank-delete-btn">
                <Trash size={14} /> Elimina
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
