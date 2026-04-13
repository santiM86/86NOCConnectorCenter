import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function CorrelationPage() {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [aiResult, setAiResult] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [question, setQuestion] = useState("");
  const [aiHistory, setAiHistory] = useState([]);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    axios.get(`${API}/api/clients`, { headers }).then(r => {
      const cl = Array.isArray(r.data) ? r.data : r.data.clients || [];
      setClients(cl);
      if (cl.length > 0) setSelectedClient(cl[0].id);
    }).catch(() => {});
  }, []);

  const fetchCorrelations = useCallback(() => {
    if (!selectedClient) return;
    setLoading(true);
    axios.get(`${API}/api/correlation/${selectedClient}`, { headers })
      .then(r => setData(r.data))
      .catch(() => toast.error("Errore nel caricamento correlazioni"))
      .finally(() => setLoading(false));
  }, [selectedClient]);

  useEffect(() => { fetchCorrelations(); }, [fetchCorrelations]);

  const runAiAnalysis = (q = "") => {
    if (!selectedClient) return;
    setAiLoading(true);
    const payload = q ? { question: q } : {};
    axios.post(`${API}/api/ai/analyze/${selectedClient}`, payload, { headers })
      .then(r => {
        setAiResult(r.data);
        toast.success("Analisi AI completata!");
        // Refresh history
        axios.get(`${API}/api/ai/history/${selectedClient}`, { headers })
          .then(hr => setAiHistory(hr.data)).catch(() => {});
      })
      .catch(err => toast.error(err.response?.data?.detail || "Errore nell'analisi AI"))
      .finally(() => setAiLoading(false));
  };

  useEffect(() => {
    if (!selectedClient) return;
    axios.get(`${API}/api/ai/history/${selectedClient}`, { headers })
      .then(r => setAiHistory(r.data)).catch(() => {});
  }, [selectedClient]);

  const sevStyle = (sev) => ({
    critical: "border-red-500/40 bg-red-500/5",
    high: "border-orange-500/40 bg-orange-500/5",
    medium: "border-amber-500/40 bg-amber-500/5",
    low: "border-blue-500/40 bg-blue-500/5",
  }[sev] || "border-[var(--bg-border)]");

  const sevBadge = (sev) => ({
    critical: "bg-red-500/20 text-red-400",
    high: "bg-orange-500/20 text-orange-400",
    medium: "bg-amber-500/20 text-amber-400",
    low: "bg-blue-500/20 text-blue-400",
  }[sev] || "bg-gray-500/20 text-gray-400");

  const sevLabel = (sev) => ({
    critical: "CRITICO", high: "ALTO", medium: "MEDIO", low: "BASSO"
  }[sev] || sev?.toUpperCase());

  const typeIcon = (type) => ({
    upstream_failure: "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z",
    performance_degradation: "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75z",
    flapping: "M3 7.5L7.5 3m0 0L12 7.5M7.5 3v13.5m13.5-4.5L16.5 16.5m0 0L12 12m4.5 4.5V3",
    wan_failure: "M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582",
    security_event: "M12 9v3.75m0-10.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z",
    maintenance: "M11.42 15.17l-5.385 5.385a1.915 1.915 0 01-2.71-2.71l5.385-5.385",
  }[type] || "M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75");

  return (
    <div className="space-y-6" data-testid="correlation-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">SOC AI Correlation</h1>
          <p className="text-sm text-[var(--text-secondary)]">Analisi intelligente e correlazione degli eventi di rete</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={selectedClient} onChange={e => setSelectedClient(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="corr-client-select">
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={fetchCorrelations}
            className="h-8 px-4 text-xs font-semibold rounded-md bg-blue-600 text-white hover:bg-blue-700"
            data-testid="corr-refresh-btn">
            Aggiorna Analisi
          </button>
          <button onClick={() => runAiAnalysis()} disabled={aiLoading}
            className="h-8 px-4 text-xs font-semibold rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-1.5"
            data-testid="ai-analyze-btn">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
            {aiLoading ? "Analisi AI..." : "Analisi Gemini AI"}
          </button>
        </div>
      </div>

      {loading && <div className="text-center py-8 text-[var(--text-secondary)]">Analisi in corso...</div>}

      {data && !loading && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-4 gap-3">
            <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center">
              <p className="text-2xl font-bold text-[var(--text-primary)]">{data.total_devices}</p>
              <p className="text-xs text-[var(--text-secondary)]">Dispositivi</p>
            </div>
            <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center">
              <p className="text-2xl font-bold text-red-400">{data.offline_count}</p>
              <p className="text-xs text-[var(--text-secondary)]">Offline</p>
            </div>
            <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center">
              <p className="text-2xl font-bold text-amber-400">{data.active_alerts}</p>
              <p className="text-xs text-[var(--text-secondary)]">Alert Attivi</p>
            </div>
            <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 text-center">
              <p className="text-2xl font-bold text-[var(--text-primary)]">{data.correlation_count}</p>
              <p className="text-xs text-[var(--text-secondary)]">Correlazioni</p>
            </div>
          </div>

          {/* Maintenance Banner */}
          {data.maintenance_active && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-center gap-2">
              <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17l-5.385 5.385a1.915 1.915 0 01-2.71-2.71l5.385-5.385" />
              </svg>
              <span className="text-xs text-amber-400 font-semibold">Manutenzione attiva — gli alert potrebbero essere soppressi</span>
            </div>
          )}

          {/* AI Analysis Section */}
          {aiLoading && (
            <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-6 text-center" data-testid="ai-loading">
              <div className="inline-flex items-center gap-2">
                <svg className="w-5 h-5 text-indigo-400 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span className="text-sm text-indigo-400 font-semibold">Gemini sta analizzando la rete...</span>
              </div>
            </div>
          )}

          {aiResult && !aiLoading && (
            <div className="rounded-xl border border-indigo-500/30 bg-[var(--bg-card)] overflow-hidden" data-testid="ai-result">
              <div className="px-4 py-3 border-b border-indigo-500/20 bg-indigo-500/5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                  </svg>
                  <span className="text-sm font-bold text-indigo-400">Analisi Gemini AI</span>
                  {aiResult.analysis?.overall_status && (
                    <span className={`px-2 py-0.5 text-[10px] font-bold rounded ${
                      aiResult.analysis.overall_status === "critico" ? "bg-red-500/20 text-red-400" :
                      aiResult.analysis.overall_status === "attenzione" ? "bg-amber-500/20 text-amber-400" :
                      aiResult.analysis.overall_status === "ottimo" ? "bg-emerald-500/20 text-emerald-400" :
                      "bg-blue-500/20 text-blue-400"
                    }`}>{aiResult.analysis.overall_status?.toUpperCase()}</span>
                  )}
                  {aiResult.analysis?.risk_score !== undefined && (
                    <span className="text-xs text-[var(--text-secondary)]">Risk Score: {aiResult.analysis.risk_score}/100</span>
                  )}
                </div>
                <span className="text-[10px] text-[var(--text-secondary)]">{new Date(aiResult.timestamp).toLocaleString("it-IT")}</span>
              </div>

              <div className="p-4 space-y-4">
                {/* Summary */}
                {aiResult.analysis?.summary && (
                  <p className="text-sm text-[var(--text-primary)] leading-relaxed">{aiResult.analysis.summary}</p>
                )}

                {/* AI Correlations */}
                {aiResult.analysis?.correlations?.length > 0 && (
                  <div>
                    <h4 className="text-xs font-bold text-indigo-400 uppercase mb-2">Correlazioni Rilevate</h4>
                    <div className="space-y-2">
                      {aiResult.analysis.correlations.map((c, i) => (
                        <div key={i} className={`rounded-lg border p-3 ${sevStyle(c.severity)}`}>
                          <div className="flex items-center gap-2 mb-1">
                            <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${sevBadge(c.severity)}`}>{sevLabel(c.severity)}</span>
                            <span className="text-xs font-bold text-[var(--text-primary)]">{c.title}</span>
                            {c.confidence && <span className="text-[10px] text-[var(--text-secondary)]">{c.confidence}%</span>}
                          </div>
                          <p className="text-xs text-[var(--text-secondary)]">{c.description}</p>
                          {c.affected_devices?.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {c.affected_devices.map((d, j) => (
                                <span key={j} className="px-1.5 py-0.5 text-[10px] rounded bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--bg-border)]">{d}</span>
                              ))}
                            </div>
                          )}
                          {c.recommendation && (
                            <p className="text-xs text-indigo-300 mt-1.5"><span className="font-semibold">Azione:</span> {c.recommendation}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recommendations */}
                {aiResult.analysis?.recommendations?.length > 0 && (
                  <div>
                    <h4 className="text-xs font-bold text-indigo-400 uppercase mb-2">Raccomandazioni</h4>
                    <div className="space-y-1.5">
                      {aiResult.analysis.recommendations.map((r, i) => (
                        <div key={i} className="flex items-start gap-2 p-2 rounded-md bg-[var(--bg-surface)]">
                          <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded flex-shrink-0 ${
                            r.priority === "immediata" ? "bg-red-500/20 text-red-400" :
                            r.priority === "breve_termine" ? "bg-amber-500/20 text-amber-400" :
                            "bg-blue-500/20 text-blue-400"
                          }`}>{r.priority?.toUpperCase()}</span>
                          <div>
                            <p className="text-xs font-medium text-[var(--text-primary)]">{r.action}</p>
                            {r.reason && <p className="text-[10px] text-[var(--text-secondary)]">{r.reason}</p>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Patterns */}
                {aiResult.analysis?.patterns_detected?.length > 0 && (
                  <div>
                    <h4 className="text-xs font-bold text-indigo-400 uppercase mb-1">Pattern Rilevati</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {aiResult.analysis.patterns_detected.map((p, i) => (
                        <span key={i} className="px-2 py-1 text-[10px] rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">{p}</span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Raw response fallback */}
                {aiResult.analysis?.raw_response && (
                  <p className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap">{aiResult.analysis.summary}</p>
                )}
              </div>
            </div>
          )}

          {/* AI Chat Input */}
          <div className="flex items-center gap-2">
            <input type="text" value={question} onChange={e => setQuestion(e.target.value)}
              placeholder="Chiedi qualcosa alla AI sulla rete (es. 'Perche il server X e lento?')"
              className="flex-1 h-9 px-4 text-xs rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
              onKeyDown={e => { if (e.key === "Enter" && question.trim()) { runAiAnalysis(question); setQuestion(""); }}}
              data-testid="ai-question-input" />
            <button onClick={() => { if (question.trim()) { runAiAnalysis(question); setQuestion(""); }}}
              disabled={!question.trim() || aiLoading}
              className="h-9 px-4 text-xs font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
              data-testid="ai-ask-btn">
              Chiedi
            </button>
          </div>

          {/* AI History */}
          {aiHistory.length > 1 && (
            <details className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)]">
              <summary className="px-4 py-2 text-xs font-semibold text-[var(--text-secondary)] cursor-pointer hover:text-[var(--text-primary)]">
                Storico Analisi AI ({aiHistory.length})
              </summary>
              <div className="px-4 pb-3 space-y-1.5">
                {aiHistory.slice(1).map((h, i) => (
                  <div key={i} className="flex items-center justify-between text-xs p-2 rounded bg-[var(--bg-surface)]">
                    <div>
                      <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${
                        h.result?.overall_status === "critico" ? "bg-red-500/20 text-red-400" :
                        h.result?.overall_status === "attenzione" ? "bg-amber-500/20 text-amber-400" :
                        "bg-emerald-500/20 text-emerald-400"
                      }`}>{h.result?.overall_status?.toUpperCase() || "N/D"}</span>
                      <span className="ml-2 text-[var(--text-primary)]">{h.question || "Analisi automatica"}</span>
                    </div>
                    <span className="text-[var(--text-secondary)]">{new Date(h.timestamp).toLocaleString("it-IT")}</span>
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Correlations */}
          {data.correlations.length > 0 ? (
            <div className="space-y-3">
              {data.correlations.map((c, i) => (
                <div key={c.id || i} className={`rounded-xl border p-4 ${sevStyle(c.severity)}`} data-testid={`correlation-${i}`}>
                  <div className="flex items-start gap-3">
                    <svg className="w-5 h-5 mt-0.5 flex-shrink-0 text-[var(--text-primary)]" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d={typeIcon(c.type)} />
                    </svg>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${sevBadge(c.severity)}`}>
                          {sevLabel(c.severity)}
                        </span>
                        <span className="text-xs text-[var(--text-secondary)]">Confidenza: {c.confidence}%</span>
                      </div>
                      <h3 className="text-sm font-bold text-[var(--text-primary)]">{c.title}</h3>
                      <p className="text-xs text-[var(--text-secondary)] mt-1">{c.description}</p>

                      {/* Affected devices */}
                      {c.affected_devices?.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {c.affected_devices.slice(0, 8).map((d, j) => (
                            <span key={j} className="px-2 py-0.5 text-[10px] rounded-md bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--bg-border)]">
                              {d.name || d.ip} {d.ping_ms ? `(${d.ping_ms}ms)` : ""} {d.alert_count ? `(${d.alert_count} alert)` : ""}
                            </span>
                          ))}
                          {c.affected_devices.length > 8 && (
                            <span className="px-2 py-0.5 text-[10px] text-[var(--text-secondary)]">+{c.affected_devices.length - 8} altri</span>
                          )}
                        </div>
                      )}

                      {/* Recommendation */}
                      <div className="mt-2 p-2 rounded-md bg-[var(--bg-surface)] border border-[var(--bg-border)]">
                        <p className="text-xs text-[var(--text-primary)]">
                          <span className="font-semibold">Azione consigliata:</span> {c.recommendation}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-12 rounded-xl border border-emerald-500/20 bg-emerald-500/5">
              <svg className="w-10 h-10 mx-auto mb-2 text-emerald-500" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-sm font-semibold text-emerald-400">Nessuna anomalia rilevata</p>
              <p className="text-xs text-[var(--text-secondary)] mt-1">L'analisi di correlazione non ha trovato pattern di guasto o anomalie nella rete.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
