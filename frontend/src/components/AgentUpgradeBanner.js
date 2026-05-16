import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { ArrowCircleUp, X, Spinner } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * AgentUpgradeBanner — banner di sistema visibile solo agli admin.
 *
 * Mostra "🆕 v4.10.3 disponibile, N agenti su versione precedente.
 * Aggiorna tutti" quando esistono connector con `agent_version` diverso
 * dalla `latest` di GitHub Releases. Bottone esegue bulk-update via WS
 * comando `update` su tutti gli agent live obsoleti.
 *
 * UX:
 *  - poll iniziale al mount + ogni 5min (cambia raramente)
 *  - dismiss persistente per sessione (sessionStorage)
 *  - hide automatica se N=0 (niente da aggiornare)
 *  - solo admin (l'endpoint backend impone require_admin)
 */
export default function AgentUpgradeBanner() {
  const token = localStorage.getItem("noc_token");
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const [data, setData] = useState(null);
  const [dismissed, setDismissed] = useState(() =>
    sessionStorage.getItem("agent_upgrade_banner_dismissed") === "1"
  );
  const [updating, setUpdating] = useState(false);

  // Fetch periodico stato upgrade.
  useEffect(() => {
    if (dismissed) return undefined;
    let cancelled = false;
    const fetchStatus = async () => {
      try {
        const r = await axios.get(`${API}/api/agents/upgrade-status`, { headers });
        if (!cancelled) setData(r.data);
      } catch (_e) {
        // 403 (non admin) → endpoint inutile per questo utente, abort silenzioso
        if (!cancelled) setData(null);
      }
    };
    fetchStatus();
    const id = setInterval(fetchStatus, 5 * 60 * 1000); // 5min
    return () => { cancelled = true; clearInterval(id); };
  }, [headers, dismissed]);

  const upgradeAll = async () => {
    if (!data?.outdated_count) return;
    const liveOutdated = (data.outdated || []).filter((a) => a.live);
    if (liveOutdated.length === 0) {
      toast.error("Nessun agent obsoleto è attualmente connesso. Attendi che si colleghino e ritenta.");
      return;
    }
    if (!confirm(`Inviare comando di aggiornamento a ${liveOutdated.length} connector live verso ${data.latest}?\n\nGli agent si riavvieranno autonomamente al termine del download.`)) return;
    setUpdating(true);
    try {
      const res = await axios.post(`${API}/api/agents/bulk-update`,
        { only_outdated: true, version: data.latest }, { headers });
      toast.success(`Comando inviato a ${res.data.sent_count} connector. Failed: ${res.data.failed_count}`);
      // Re-fetch dopo 30s per vedere il nuovo stato
      setTimeout(async () => {
        try {
          const r = await axios.get(`${API}/api/agents/upgrade-status`, { headers });
          setData(r.data);
        } catch { /* ignore */ }
      }, 30000);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore bulk-update");
    } finally {
      setUpdating(false);
    }
  };

  const dismiss = () => {
    setDismissed(true);
    sessionStorage.setItem("agent_upgrade_banner_dismissed", "1");
  };

  if (dismissed) return null;
  if (!data) return null;
  if ((data.outdated_count || 0) === 0) return null;

  const liveOutdated = (data.outdated || []).filter((a) => a.live).length;
  const total = data.outdated_count;

  return (
    <div
      data-testid="agent-upgrade-banner"
      className="sticky top-0 z-40 px-4 py-2.5 border-b border-amber-500/30 bg-amber-500/10 backdrop-blur-md flex flex-wrap items-center justify-center gap-3 text-sm"
    >
      <ArrowCircleUp size={18} weight="fill" className="text-amber-400 shrink-0" />
      <span className="text-amber-200">
        <span className="font-semibold">{data.latest}</span> disponibile.
        <span className="ml-1.5 text-amber-300/80">
          {total} {total === 1 ? "connector" : "connectors"} su versione precedente
          {liveOutdated > 0 && total !== liveOutdated && ` (${liveOutdated} online)`}
        </span>
      </span>
      <button
        onClick={upgradeAll}
        disabled={updating || liveOutdated === 0}
        data-testid="agent-upgrade-bulk-btn"
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md bg-amber-500/90 hover:bg-amber-500 text-amber-950 text-xs font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {updating ? (
          <>
            <Spinner size={12} className="animate-spin" />
            Invio comandi…
          </>
        ) : (
          <>Aggiorna {liveOutdated > 0 ? liveOutdated : ""} ora</>
        )}
      </button>
      <button
        onClick={dismiss}
        className="text-amber-300/70 hover:text-amber-200 transition-colors p-0.5"
        title="Nascondi per questa sessione"
        data-testid="agent-upgrade-dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}
