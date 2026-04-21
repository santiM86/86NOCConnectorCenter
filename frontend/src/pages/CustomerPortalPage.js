import { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { Warning, SignOut, Bell, Desktop, FireSimple } from "@phosphor-icons/react";

/** Customer Portal — pagina pubblica (no auth ARGUS), login separato. */
export default function CustomerPortalPage() {
  const [token, setToken] = useState(localStorage.getItem("customer_token"));
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const loadDashboard = async () => {
    try {
      const res = await axios.get(`${API}/customer/dashboard`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setData(res.data);
    } catch (e) {
      if (e.response?.status === 401) {
        localStorage.removeItem("customer_token");
        setToken(null);
      } else {
        setError(e.response?.data?.detail || e.message);
      }
    }
  };

  useEffect(() => {
    if (token) loadDashboard();
  }, [token]);

  const logout = () => {
    localStorage.removeItem("customer_token");
    setToken(null); setData(null);
  };

  if (!token) return <CustomerLogin onSuccess={(t) => { localStorage.setItem("customer_token", t); setToken(t); }} />;

  if (!data) return <div className="min-h-screen bg-[#0d0d12] flex items-center justify-center text-white/40">Caricamento...</div>;

  const { stats, client, recent_alerts } = data;

  return (
    <div className="min-h-screen bg-[#0d0d12]" data-testid="customer-portal">
      <header className="bg-[#12121a] border-b border-[#2a2a3e] px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-white">Customer Portal · {client?.name}</h1>
          <p className="text-[10px] text-white/40 font-mono">Self-service visibility · ARGUS Center</p>
        </div>
        <button onClick={logout} className="flex items-center gap-1 px-3 py-1.5 rounded bg-white/5 text-white/60 hover:bg-white/10 text-[11px]" data-testid="customer-logout">
          <SignOut size={12} /> Esci
        </button>
      </header>

      <div className="p-6 max-w-5xl mx-auto">
        <div className="grid grid-cols-4 gap-3 mb-6">
          <StatCard icon={Desktop} label="Device monitorati" value={stats.devices} color="#a78bfa" />
          <StatCard icon={Bell} label="Alert attivi" value={stats.alerts_active} color="#f59e0b" />
          <StatCard icon={FireSimple} label="Critici" value={stats.alerts_critical} color="#ef4444" />
          <StatCard icon={Warning} label="Incident aperti" value={stats.incidents_open} color="#06b6d4" />
        </div>

        <div className="bg-[#12121a] border border-[#2a2a3e] rounded-lg p-4" data-testid="customer-alerts-list">
          <h2 className="text-sm font-bold text-white mb-3">Ultimi alert (20)</h2>
          {recent_alerts.length === 0 ? <p className="text-[11px] text-white/40 text-center py-6">Nessun alert recente 🎉</p> : (
            <div className="space-y-1">
              {recent_alerts.map((a, i) => (
                <div key={i} className="flex items-start gap-3 py-2 border-b border-[#1e1e2e] last:border-0 text-[11px]">
                  <span className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ background: a.severity === "critical" ? "#ef4444" : a.severity === "warning" ? "#f59e0b" : "#06b6d4" }} />
                  <div className="flex-1 min-w-0">
                    <p className="text-white truncate">{a.title}</p>
                    <p className="text-white/40 font-mono text-[10px]">{a.device_ip || a.device_name} · {new Date(a.created_at).toLocaleString("it-IT")}</p>
                  </div>
                  <span className={`text-[9px] px-2 py-0.5 rounded uppercase font-mono ${a.status === "resolved" ? "bg-emerald-500/10 text-emerald-400" : "bg-amber-500/10 text-amber-400"}`}>{a.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-[#12121a] border border-[#2a2a3e] rounded-lg p-4">
      <Icon size={20} style={{ color }} className="mb-2" />
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-[10px] text-white/40 uppercase font-mono mt-1">{label}</div>
    </div>
  );
}

function CustomerLogin({ onSuccess }) {
  const [email, setEmail] = useState(""); const [pwd, setPwd] = useState("");
  const [err, setErr] = useState(null); const [loading, setLoading] = useState(false);

  const login = async () => {
    setLoading(true); setErr(null);
    try {
      const res = await axios.post(`${API}/customer/login`, { email, password: pwd });
      onSuccess(res.data.access_token);
    } catch (e) {
      setErr(e.response?.data?.detail || "Errore login");
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen bg-[#0d0d12] flex items-center justify-center p-4">
      <div className="bg-[#12121a] border border-[#2a2a3e] rounded-xl p-6 w-full max-w-sm">
        <h1 className="text-xl font-bold text-white mb-1">Customer Portal</h1>
        <p className="text-[11px] text-white/50 mb-4">Accesso dedicato clienti ARGUS</p>
        <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)}
          className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-3 py-2 text-white text-sm mb-2 focus:border-indigo-500 outline-none" data-testid="customer-email" />
        <input type="password" placeholder="Password" value={pwd} onChange={e => setPwd(e.target.value)}
          onKeyDown={e => e.key === "Enter" && login()}
          className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded px-3 py-2 text-white text-sm mb-2 focus:border-indigo-500 outline-none" data-testid="customer-password" />
        {err && <p className="text-red-400 text-xs mt-1">{err}</p>}
        <button onClick={login} disabled={!email || !pwd || loading}
          className="w-full mt-3 px-3 py-2 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/30 text-sm font-bold disabled:opacity-50"
          data-testid="customer-login-btn">
          {loading ? "Accesso..." : "Accedi"}
        </button>
      </div>
    </div>
  );
}
