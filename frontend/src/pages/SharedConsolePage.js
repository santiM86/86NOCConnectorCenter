import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { ShieldCheck, Warning, Eye, Clock } from "@phosphor-icons/react";

/**
 * SharedConsolePage — pagina pubblica (no auth) per aprire un iframe LIVE
 * condiviso tramite share_token.
 * URL: /shared-console/{token}
 */
export default function SharedConsolePage() {
  const { token } = useParams();
  const [state, setState] = useState("loading"); // loading | password | ready | error
  const [password, setPassword] = useState("");
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [remainingSec, setRemainingSec] = useState(null);

  const validate = async (pwd = null) => {
    setState("loading"); setError(null);
    try {
      const res = await axios.post(`${API}/web-console/shared/${token}/validate`, {
        password: pwd,
      });
      setInfo(res.data);
      setState("ready");
      if (res.data?.expires_at) {
        const expMs = new Date(res.data.expires_at).getTime();
        setRemainingSec(Math.max(0, Math.floor((expMs - Date.now()) / 1000)));
      }
    } catch (e) {
      const status = e.response?.status;
      const detail = e.response?.data?.detail || e.message;
      if (status === 401) { setState("password"); setError(pwd ? "Password errata" : null); }
      else if (status === 410) { setState("error"); setError("Il link è scaduto"); }
      else if (status === 404) { setState("error"); setError("Link non trovato o già revocato"); }
      else { setState("error"); setError(detail); }
    }
  };

  useEffect(() => { validate(null); /* eslint-disable-next-line */ }, [token]);

  useEffect(() => {
    if (remainingSec == null) return;
    const t = setInterval(() => {
      setRemainingSec(s => {
        if (s == null) return null;
        if (s <= 0) { setState("error"); setError("Il link è appena scaduto"); return 0; }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [remainingSec]);

  if (state === "loading") {
    return (
      <div className="min-h-screen bg-[#0d0d12] flex items-center justify-center">
        <div className="w-12 h-12 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin" />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="min-h-screen bg-[#0d0d12] flex items-center justify-center p-6">
        <div className="text-center max-w-md">
          <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
            <Warning size={28} className="text-red-400" />
          </div>
          <h1 className="text-red-400 font-bold text-lg mb-2">Link non disponibile</h1>
          <p className="text-white/60 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (state === "password") {
    return (
      <div className="min-h-screen bg-[#0d0d12] flex items-center justify-center p-6">
        <div className="bg-[#12121a] border border-[#2a2a3e] rounded-xl p-6 w-full max-w-sm">
          <div className="flex items-center gap-2 mb-4">
            <ShieldCheck size={18} className="text-indigo-400" />
            <h1 className="text-white font-bold text-sm">Console Condivisa · Protetta</h1>
          </div>
          <p className="text-white/60 text-xs mb-4 leading-relaxed">
            Questa console è protetta da password. Inserisci la password che ti è stata comunicata.
          </p>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === "Enter" && validate(password)}
            placeholder="Password"
            className="w-full bg-[#0f0f17] border border-[#2a2a3e] rounded-lg px-3 py-2.5 text-white text-sm focus:border-indigo-500 outline-none"
            data-testid="shared-password-input" autoFocus />
          {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
          <button onClick={() => validate(password)} disabled={!password}
            className="w-full mt-4 px-3 py-2.5 rounded-lg bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/30 text-sm font-bold disabled:opacity-50"
            data-testid="shared-unlock-btn">
            Sblocca
          </button>
        </div>
      </div>
    );
  }

  const mins = remainingSec != null ? Math.floor(remainingSec / 60) : null;
  const secs = remainingSec != null ? remainingSec % 60 : null;

  return (
    <div className="min-h-screen bg-[#0d0d12] flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 bg-[#12121a] border-b border-[#1e1e2e]">
        <div className="flex items-center gap-2">
          <ShieldCheck size={14} className="text-emerald-400" />
          <span className="text-[11px] text-white/80 font-mono">{info?.device_ip}:{info?.port}</span>
          <span className="text-[9px] uppercase text-purple-400 font-bold font-mono ml-2">Shared · Read-only</span>
        </div>
        <div className="flex items-center gap-3">
          {info?.shared_by && (
            <span className="text-[10px] text-white/40 font-mono flex items-center gap-1">
              <Eye size={11} /> {info.shared_by}
            </span>
          )}
          {mins != null && (
            <span className={`text-[10px] font-mono flex items-center gap-1 ${remainingSec < 60 ? "text-red-400" : "text-amber-400"}`}>
              <Clock size={11} /> scade in {mins}:{String(secs).padStart(2, "0")}
            </span>
          )}
        </div>
      </div>
      <div className="flex-1 bg-white relative">
        <iframe src={info?.iframe_url} className="w-full h-full border-0" title={`Shared Console ${info?.device_ip}`}
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads"
          data-testid="shared-console-iframe" />
      </div>
    </div>
  );
}
