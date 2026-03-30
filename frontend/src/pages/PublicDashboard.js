import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import {
  ShieldWarning, CheckCircle, XCircle, WifiHigh, WifiSlash,
  Warning, Clock, Shield
} from "@phosphor-icons/react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const PUB_API = `${BACKEND_URL}/api/public`;

export default function PublicDashboard() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [token]);

  const fetchData = () => {
    axios.get(`${PUB_API}/dashboard/${token}`)
      .then(r => { setData(r.data); setLastUpdate(new Date()); setError(null); })
      .catch(() => setError("Dashboard non trovata o disabilitata"));
  };

  if (error) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center">
        <div className="text-center">
          <ShieldWarning size={48} className="text-red-400 mx-auto mb-4" />
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center">
        <div className="text-zinc-400 text-sm animate-pulse">Caricamento dashboard...</div>
      </div>
    );
  }

  const devices = data.devices || {};
  const alerts = data.alerts || {};
  const sla = data.sla || {};

  return (
    <div className="min-h-screen bg-[#050505] text-zinc-100 p-4 md:p-8" data-testid="public-dashboard">
      {/* Header */}
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-600/20 flex items-center justify-center">
              <ShieldWarning size={20} weight="fill" className="text-indigo-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">{data.client_name}</h1>
              <p className="text-[10px] text-zinc-500 uppercase tracking-wider">86BIT NOC - Stato della Rete</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-zinc-500">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Auto-refresh 30s
            {lastUpdate && <span>| {lastUpdate.toLocaleTimeString("it-IT")}</span>}
          </div>
        </div>

        {/* SLA + Summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {sla.overall_pct != null && (
            <div className="rounded-xl bg-zinc-900/50 border border-zinc-800 p-5 text-center">
              <Shield size={20} className="text-indigo-400 mx-auto mb-2" weight="fill" />
              <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">SLA Uptime {sla.period_days}gg</p>
              <p className={`text-4xl font-bold ${sla.overall_pct >= 99.9 ? "text-emerald-400" : sla.overall_pct >= 95 ? "text-amber-400" : "text-red-400"}`}>
                {sla.overall_pct}%
              </p>
            </div>
          )}
          <div className="rounded-xl bg-zinc-900/50 border border-zinc-800 p-5 text-center">
            <WifiHigh size={20} className="text-emerald-400 mx-auto mb-2" />
            <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Dispositivi Online</p>
            <p className="text-4xl font-bold text-emerald-400">{devices.online || 0}<span className="text-lg text-zinc-500">/{devices.total || 0}</span></p>
          </div>
          <div className="rounded-xl bg-zinc-900/50 border border-zinc-800 p-5 text-center">
            <Warning size={20} className="text-amber-400 mx-auto mb-2" />
            <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Alert Attivi</p>
            <p className="text-4xl font-bold text-amber-400">{alerts.active_count || 0}</p>
          </div>
        </div>

        {/* Devices */}
        {devices.list && devices.list.length > 0 && (
          <div className="rounded-xl bg-zinc-900/50 border border-zinc-800 overflow-hidden">
            <div className="p-4 border-b border-zinc-800">
              <h2 className="text-xs font-bold text-zinc-300 uppercase tracking-wider">Dispositivi</h2>
            </div>
            <div className="divide-y divide-zinc-800/50">
              {devices.list.map((d, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-2.5 hover:bg-zinc-800/30 transition-colors">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${d.reachable ? "bg-emerald-400" : "bg-red-400"}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-zinc-200 truncate">{d.name || d.ip}</p>
                  </div>
                  <span className="text-[10px] font-mono text-zinc-500">{d.ip}</span>
                  {d.ping_ms != null && (
                    <span className="text-[10px] font-mono text-zinc-500">{d.ping_ms}ms</span>
                  )}
                  {d.reachable ? (
                    <CheckCircle size={14} className="text-emerald-400" weight="fill" />
                  ) : (
                    <XCircle size={14} className="text-red-400" weight="fill" />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Alerts */}
        {alerts.list && alerts.list.length > 0 && (
          <div className="rounded-xl bg-zinc-900/50 border border-zinc-800 overflow-hidden">
            <div className="p-4 border-b border-zinc-800">
              <h2 className="text-xs font-bold text-zinc-300 uppercase tracking-wider">Alert Attivi</h2>
            </div>
            <div className="divide-y divide-zinc-800/50">
              {alerts.list.map((a, i) => {
                const sevColor = { critical: "text-red-400", high: "text-orange-400", medium: "text-amber-400", low: "text-blue-400" };
                return (
                  <div key={i} className="flex items-center gap-3 px-4 py-2.5">
                    <span className={`text-[9px] font-bold uppercase ${sevColor[a.severity] || "text-zinc-400"}`}>
                      {a.severity?.substring(0, 4)}
                    </span>
                    <p className="flex-1 text-xs text-zinc-300 truncate">{a.title}</p>
                    <span className="text-[10px] text-zinc-500">{a.device_name}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="text-center text-[10px] text-zinc-600 pt-4">
          Powered by 86BIT NOC Command Center
        </div>
      </div>
    </div>
  );
}
