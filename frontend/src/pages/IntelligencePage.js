import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { Brain, Warning, ShieldCheck, TrendUp, ArrowRight, Lightning } from "@phosphor-icons/react";

const SEV_COLORS = {
  critical: "text-rose-400 bg-rose-500/10 border-rose-500/30",
  high: "text-orange-400 bg-orange-500/10 border-orange-500/30",
  medium: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  low: "text-sky-400 bg-sky-500/10 border-sky-500/30",
};

const BAND_COLORS = {
  high: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

export default function IntelligencePage() {
  const [tab, setTab] = useState("triage");
  const [triageStats, setTriageStats] = useState(null);
  const [triagedAlerts, setTriagedAlerts] = useState([]);
  const [patchCompliance, setPatchCompliance] = useState(null);
  const [patchStatus, setPatchStatus] = useState([]);
  const [predictive, setPredictive] = useState([]);
  const [loading, setLoading] = useState(true);
  const [triageBulkRunning, setTriageBulkRunning] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [ts, ta, pc, ps, pr] = await Promise.all([
        axios.get(`${API}/intel/triage/stats`).catch(() => ({ data: null })),
        axios.get(`${API}/alerts?limit=50`).catch(() => ({ data: { items: [] } })),
        axios.get(`${API}/intel/patch/compliance`).catch(() => ({ data: null })),
        axios.get(`${API}/intel/patch/status?only_non_compliant=true`).catch(() => ({ data: { items: [] } })),
        axios.get(`${API}/intel/predictive`).catch(() => ({ data: { items: [] } })),
      ]);
      setTriageStats(ts.data);
      setTriagedAlerts((ta.data?.items || []).filter(a => a.triage).slice(0, 30));
      setPatchCompliance(pc.data);
      setPatchStatus(ps.data?.items || []);
      setPredictive(pr.data?.items || []);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const runBulkTriage = async () => {
    setTriageBulkRunning(true);
    try {
      const res = await axios.post(`${API}/intel/triage-bulk`, null, { params: { hours: 24 } });
      alert(`Triaged ${res.data.triaged} alert delle ultime 24h`);
      load();
    } finally { setTriageBulkRunning(false); }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="intelligence-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Brain size={24} className="text-fuchsia-400" /> NOC Intelligence
          </h1>
          <p className="text-[12px] text-white/50 mt-1">Proactive Fault Triage · Patch Compliance · Predictive Failure Analysis.</p>
        </div>
      </div>

      <div className="flex gap-2 border-b border-white/10 mb-4">
        {[
          { id: "triage", label: "Fault Triage", icon: Lightning },
          { id: "patch", label: "Patch Compliance", icon: ShieldCheck },
          { id: "predictive", label: "Predictive Analysis", icon: TrendUp },
        ].map(t => {
          const Icon = t.icon;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition flex items-center gap-2 ${tab === t.id ? "text-fuchsia-400 border-fuchsia-400" : "text-white/60 border-transparent hover:text-white"}`}
              data-testid={`tab-${t.id}`}>
              <Icon size={14} /> {t.label}
            </button>
          );
        })}
      </div>

      {loading && <div className="text-white/50 text-sm p-4">Caricamento…</div>}

      {/* FAULT TRIAGE */}
      {tab === "triage" && (
        <div>
          <div className="flex justify-between items-center mb-4 flex-wrap gap-3">
            {triageStats && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 flex-1">
                <StatCard label="Alert triaged (7g)" value={triageStats.total_triaged} color="text-fuchsia-400" />
                <StatCard label="Severity innalzate" value={triageStats.severity_upgrades} color="text-rose-400" />
                <StatCard label="Severity ridotte" value={triageStats.severity_downgrades} color="text-emerald-400" />
                <StatCard label="Ricorrenti (>3x)" value={triageStats.recurring_issues} color="text-amber-400" />
              </div>
            )}
            <button onClick={runBulkTriage} disabled={triageBulkRunning} data-testid="bulk-triage-btn"
              className="px-3 py-2 rounded bg-fuchsia-500/20 text-fuchsia-400 border border-fuchsia-500/30 hover:bg-fuchsia-500/30 text-sm font-bold flex items-center gap-1 disabled:opacity-50">
              <Lightning size={14} /> {triageBulkRunning ? "In corso…" : "Triage bulk 24h"}
            </button>
          </div>

          <div className="grid gap-3">
            {triagedAlerts.map(a => {
              const t = a.triage || {};
              return (
                <div key={a.id} className="bg-white/[0.03] border border-white/10 rounded-lg p-3" data-testid={`triage-${a.id}`}>
                  <div className="flex items-start justify-between gap-2 flex-wrap">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase ${SEV_COLORS[a.severity]}`}>{a.severity}</span>
                        {t.suggested_severity && t.suggested_severity !== a.severity && (
                          <>
                            <ArrowRight size={12} className="text-white/40" />
                            <span className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase ${SEV_COLORS[t.suggested_severity]}`}>AI: {t.suggested_severity}</span>
                          </>
                        )}
                        {t.is_recurring && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 uppercase">Ricorrente {t.recurrence_30d}x</span>}
                      </div>
                      <div className="text-white/90 font-semibold mt-1 text-[13px]">{a.title}</div>
                      <div className="text-white/50 text-[11px]">{a.device_ip} · {a.device_name}</div>
                      {t.root_cause && (
                        <div className="mt-2 p-2 bg-fuchsia-500/5 border border-fuchsia-500/20 rounded">
                          <div className="text-[10px] uppercase text-fuchsia-400 font-bold mb-0.5">Root cause suggerita</div>
                          <div className="text-[12px] text-white/85">{t.root_cause}</div>
                        </div>
                      )}
                      {(t.recommended_actions || []).length > 0 && (
                        <div className="mt-2">
                          <div className="text-[10px] uppercase text-white/50 font-bold mb-1">Azioni raccomandate</div>
                          <ul className="text-[12px] text-white/75 space-y-0.5 list-disc list-inside">
                            {t.recommended_actions.map((ac, i) => <li key={i}>{ac}</li>)}
                          </ul>
                        </div>
                      )}
                      {(t.kb_matches || []).length > 0 && (
                        <div className="mt-2">
                          <div className="text-[10px] uppercase text-white/50 font-bold mb-1">Match KB (problemi noti)</div>
                          <div className="text-[12px] text-white/70">{t.kb_matches.map(k => k.title).join(" · ")}</div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
            {triagedAlerts.length === 0 && !loading && (
              <div className="text-white/40 text-sm py-6 text-center">Nessun alert triaged. Clicca "Triage bulk 24h" per iniziare.</div>
            )}
          </div>
        </div>
      )}

      {/* PATCH COMPLIANCE */}
      {tab === "patch" && (
        <div>
          {patchCompliance && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <StatCard label="Compliance %" value={`${patchCompliance.compliance_percentage}%`} color={patchCompliance.compliance_percentage >= 80 ? "text-emerald-400" : "text-amber-400"} />
              <StatCard label="Device totali" value={patchCompliance.total_devices} color="text-white" />
              <StatCard label="Con patch critiche" value={patchCompliance.devices_with_critical_patches} color="text-rose-400" />
              <StatCard label="CVE aperte" value={patchCompliance.total_open_cves} color="text-amber-400" />
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[900px]">
              <thead className="text-white/50 text-xs uppercase border-b border-white/10">
                <tr>
                  <th className="text-left py-2 px-2">Device</th>
                  <th className="text-left py-2 px-2">OS</th>
                  <th className="text-left py-2 px-2">Firmware</th>
                  <th className="text-left py-2 px-2">Patch pending</th>
                  <th className="text-left py-2 px-2">Critiche</th>
                  <th className="text-left py-2 px-2">CVE</th>
                  <th className="text-left py-2 px-2">Ultimo check</th>
                </tr>
              </thead>
              <tbody>
                {patchStatus.map(p => (
                  <tr key={p.device_ip} className="border-b border-white/5 hover:bg-white/[0.02]">
                    <td className="py-2 px-2 text-white/90 text-[12px] font-mono">{p.device_ip}</td>
                    <td className="py-2 px-2 text-white/70 text-[12px]">{p.os_name} {p.os_version}</td>
                    <td className="py-2 px-2 text-white/70 text-[12px]">{p.firmware_version || "—"}</td>
                    <td className="py-2 px-2 text-white/70 text-[12px]">{p.pending_patches || 0}</td>
                    <td className="py-2 px-2">
                      {(p.critical_patches || 0) > 0
                        ? <span className="px-2 py-0.5 rounded bg-rose-500/15 text-rose-400 border border-rose-500/30 text-[11px] font-bold">{p.critical_patches}</span>
                        : <span className="text-emerald-400 text-[12px]">0</span>}
                    </td>
                    <td className="py-2 px-2 text-white/70 text-[12px]">{p.cve_count || 0}</td>
                    <td className="py-2 px-2 text-white/50 text-[11px]">{(p.last_check_at || "").slice(0, 10)}</td>
                  </tr>
                ))}
                {patchStatus.length === 0 && !loading && (
                  <tr><td colSpan={7} className="py-6 text-center text-white/40">
                    Nessun dato patch compliance disponibile. Il connector dovra' inviare i dati patch via POST /api/intel/patch/status.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* PREDICTIVE */}
      {tab === "predictive" && (
        <div>
          <div className="bg-fuchsia-500/5 border border-fuchsia-500/20 rounded-lg p-3 mb-4 text-[12px] text-white/75">
            <strong className="text-fuchsia-400">Come funziona:</strong> analizziamo il trend delle ultime 24h di telemetria iLO Redfish (temperatura, RPM ventole, power draw)
            per prevedere guasti hardware 24-72h in anticipo. Rileva anomalie come rising temp, fan saturation, PSU anomaly.
          </div>
          <div className="grid gap-3">
            {predictive.map(p => (
              <div key={p.device_ip} className="bg-white/[0.03] border border-white/10 rounded-lg p-3 flex items-start justify-between gap-3 flex-wrap">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded border text-[11px] font-bold uppercase ${BAND_COLORS[p.risk_band]}`}>
                      {p.risk_band} · {p.risk_score}
                    </span>
                    <div className="text-white/90 font-mono text-[13px]">{p.device_ip}</div>
                  </div>
                  {p.top_prediction && (
                    <div className="mt-1 text-[12px]">
                      <span className={`font-bold ${SEV_COLORS[p.top_prediction.severity]?.split(" ")[0] || "text-white"}`}>[{p.top_prediction.type}]</span>
                      <span className="text-white/80 ml-1">{p.top_prediction.message}</span>
                    </div>
                  )}
                  {p.predicted_eta_hours && (
                    <div className="text-[11px] text-amber-400 mt-1">Finestra stimata guasto: entro {p.predicted_eta_hours}h</div>
                  )}
                </div>
              </div>
            ))}
            {predictive.length === 0 && !loading && (
              <div className="text-white/40 text-sm py-6 text-center">
                Nessuna analisi predittiva disponibile. Serve telemetria iLO (polling attivo per almeno 1h su device con telemetria).
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div className="bg-white/[0.03] border border-white/10 rounded-lg p-3">
      <div className="text-[11px] text-white/50 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color}`}>{value ?? 0}</div>
    </div>
  );
}
