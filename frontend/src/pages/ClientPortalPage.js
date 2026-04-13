import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL;

export default function ClientPortalPage() {
  const [clientId, setClientId] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [inputId, setInputId] = useState("");

  const fetchPortal = useCallback((cid) => {
    if (!cid) return;
    setLoading(true);
    axios.get(`${API}/api/portal/${cid}`)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const cid = params.get("id");
    if (cid) {
      setClientId(cid);
      fetchPortal(cid);
    } else {
      setLoading(false);
    }
  }, [fetchPortal]);

  const handleAccess = () => {
    if (!inputId.trim()) return;
    setClientId(inputId.trim());
    fetchPortal(inputId.trim());
  };

  if (loading) return (
    <div className="min-h-screen bg-[#0f172a] flex items-center justify-center">
      <p className="text-slate-400">Caricamento...</p>
    </div>
  );

  if (!clientId || !data) return (
    <div className="min-h-screen bg-[#0f172a] flex items-center justify-center">
      <div className="bg-[#1e293b] rounded-xl border border-slate-700 p-8 max-w-md w-full text-center">
        <h1 className="text-xl font-bold text-white mb-2">Portale Cliente</h1>
        <p className="text-sm text-slate-400 mb-6">Inserisci il tuo ID cliente per accedere alla dashboard</p>
        <input type="text" value={inputId} onChange={e => setInputId(e.target.value)}
          placeholder="ID Cliente"
          className="w-full h-10 px-4 text-sm rounded-lg border border-slate-600 bg-[#0f172a] text-white mb-3"
          data-testid="portal-client-id-input"
          onKeyDown={e => e.key === "Enter" && handleAccess()} />
        <button onClick={handleAccess}
          className="w-full h-10 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700"
          data-testid="portal-access-btn">
          Accedi
        </button>
      </div>
    </div>
  );

  const slaColor = data.sla_pct >= 99.9 ? "text-emerald-400" : data.sla_pct >= 99 ? "text-amber-400" : "text-red-400";

  return (
    <div className="min-h-screen bg-[#0f172a] text-white" data-testid="client-portal">
      {/* Header */}
      <div className="border-b border-slate-700 bg-[#1e293b]">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-400">86BIT NOC — Portale Cliente</p>
            <h1 className="text-lg font-bold">{data.client_name}</h1>
          </div>
          <p className="text-xs text-slate-500">{new Date(data.timestamp).toLocaleString("it-IT")}</p>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        {/* Maintenance banner */}
        {data.maintenance?.length > 0 && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
            <p className="text-xs text-amber-400 font-semibold">Manutenzione in corso: {data.maintenance[0].title}</p>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="rounded-lg bg-[#1e293b] border border-slate-700 p-4 text-center" data-testid="portal-total-devices">
            <p className="text-3xl font-bold">{data.total_devices}</p>
            <p className="text-xs text-slate-400">Dispositivi</p>
          </div>
          <div className="rounded-lg bg-[#1e293b] border border-slate-700 p-4 text-center" data-testid="portal-online">
            <p className="text-3xl font-bold text-emerald-400">{data.online}</p>
            <p className="text-xs text-slate-400">Online</p>
          </div>
          <div className="rounded-lg bg-[#1e293b] border border-slate-700 p-4 text-center" data-testid="portal-offline">
            <p className="text-3xl font-bold text-red-400">{data.offline}</p>
            <p className="text-xs text-slate-400">Offline</p>
          </div>
          <div className="rounded-lg bg-[#1e293b] border border-slate-700 p-4 text-center" data-testid="portal-sla">
            <p className={`text-3xl font-bold ${slaColor}`}>{data.sla_pct}%</p>
            <p className="text-xs text-slate-400">SLA 30gg</p>
          </div>
          <div className="rounded-lg bg-[#1e293b] border border-slate-700 p-4 text-center" data-testid="portal-alerts">
            <p className="text-3xl font-bold text-amber-400">{data.active_alerts}</p>
            <p className="text-xs text-slate-400">Alert Attivi</p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Devices */}
          <div className="rounded-xl bg-[#1e293b] border border-slate-700 overflow-hidden">
            <div className="p-3 border-b border-slate-700">
              <h3 className="text-sm font-semibold">Stato Dispositivi</h3>
            </div>
            <div className="divide-y divide-slate-700 max-h-96 overflow-y-auto">
              {data.devices?.map((d, i) => (
                <div key={i} className="flex items-center justify-between px-4 py-2">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${d.reachable ? "bg-emerald-500" : "bg-red-500"}`} />
                    <span className="text-xs font-medium">{d.name}</span>
                    <span className="text-[10px] text-slate-500">{d.ip}</span>
                  </div>
                  <span className="text-xs text-slate-400">{d.ping_ms ? `${d.ping_ms}ms` : "-"}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Alerts */}
          <div className="rounded-xl bg-[#1e293b] border border-slate-700 overflow-hidden">
            <div className="p-3 border-b border-slate-700">
              <h3 className="text-sm font-semibold">Alert Recenti</h3>
            </div>
            <div className="divide-y divide-slate-700 max-h-96 overflow-y-auto">
              {data.alerts?.length > 0 ? data.alerts.map((a, i) => (
                <div key={i} className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${
                      a.severity === "critical" ? "bg-red-500/20 text-red-400" :
                      a.severity === "high" ? "bg-orange-500/20 text-orange-400" :
                      "bg-amber-500/20 text-amber-400"
                    }`}>{a.severity?.toUpperCase()}</span>
                    <span className="text-xs text-slate-300">{a.device_name}</span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">{a.title}</p>
                </div>
              )) : (
                <div className="p-4 text-center text-xs text-slate-500">Nessun alert attivo</div>
              )}
            </div>
          </div>
        </div>

        <div className="text-center text-xs text-slate-500 py-4">
          86BIT NOC Command Center — Portale Cliente | www.86bit.it
        </div>
      </div>
    </div>
  );
}
