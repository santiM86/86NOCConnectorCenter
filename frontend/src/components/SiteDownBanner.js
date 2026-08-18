import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { AlertTriangle, ChevronRight } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function _downFor(sinceIso) {
  if (!sinceIso) return "";
  const start = new Date(sinceIso).getTime();
  if (Number.isNaN(start)) return "";
  const mins = Math.max(0, Math.floor((Date.now() - start) / 60000));
  if (mins < 60) return `giù da ${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `giù da ${h}h ${m}min`;
}

export default function SiteDownBanner() {
  const navigate = useNavigate();
  const [sites, setSites] = useState([]);
  const [idx, setIdx] = useState(0);
  const [, setTick] = useState(0);

  const load = useCallback(async () => {
    try {
      const token = localStorage.getItem("noc_token");
      if (!token) return;
      const { data } = await axios.get(`${API}/api/overview/site-down`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setSites(data.sites || []);
    } catch {
      /* silenzioso: il banner non deve mai rompere la UI */
    }
  }, []);

  useEffect(() => {
    load();
    const poll = setInterval(load, 20000);   // ricarica lista sedi giù ogni 20s
    const clock = setInterval(() => setTick((t) => t + 1), 30000); // aggiorna timer
    return () => { clearInterval(poll); clearInterval(clock); };
  }, [load]);

  // rotazione tra più sedi giù
  useEffect(() => {
    if (sites.length <= 1) { setIdx(0); return; }
    const r = setInterval(() => setIdx((i) => (i + 1) % sites.length), 5000);
    return () => clearInterval(r);
  }, [sites.length]);

  if (!sites.length) return null;
  const s = sites[Math.min(idx, sites.length - 1)];

  return (
    <div
      role="alert"
      data-testid="site-down-banner"
      onClick={() => navigate(`/client/${s.client_id}`)}
      className="site-down-banner sticky top-0 z-50 w-full cursor-pointer select-none
                 bg-red-600 text-white flex items-center gap-3 px-4 py-2.5
                 shadow-[0_2px_16px_rgba(220,38,38,0.5)] border-b border-red-800
                 animate-pulse-slow"
      style={{ animation: "sitedownglow 2s ease-in-out infinite" }}
    >
      <AlertTriangle size={20} className="shrink-0" />
      <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
        <span className="font-extrabold tracking-wide text-sm uppercase">Site Down</span>
        <span className="text-white/60">•</span>
        <span className="font-bold truncate" data-testid="site-down-name">{s.client_name}</span>
        <span className="text-xs font-mono bg-black/25 px-2 py-0.5 rounded-full" data-testid="site-down-timer">
          {_downFor(s.down_since)}
        </span>
        <span className="text-xs text-white/80 hidden sm:inline">
          agent + WAN irraggiungibili — sede totalmente isolata
        </span>
        {sites.length > 1 && (
          <span className="text-xs bg-white/20 px-2 py-0.5 rounded-full ml-1" data-testid="site-down-count">
            {sites.length} sedi giù
          </span>
        )}
      </div>
      <ChevronRight size={18} className="shrink-0 opacity-80" />
    </div>
  );
}
