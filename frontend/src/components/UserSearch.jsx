import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { MagnifyingGlass, User, Desktop, Plug, X } from "@phosphor-icons/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const Result = ({ r, i, onGo }) => (
  <li className="px-3 py-2 hover:bg-white/[0.03] transition-colors" data-testid={`user-search-result-${i}`}>
    <div className="flex items-center gap-1.5 text-[11px]">
      <User size={12} className="text-sky-300" weight="bold" />
      <span className="font-mono font-semibold text-sky-100 truncate">{r.user}</span>
      <span className="ml-auto text-[9px] text-[var(--text-muted)] truncate max-w-[120px]">{r.client_name}</span>
    </div>
    <div className="flex items-center gap-1.5 text-[10px] mt-0.5 pl-4">
      <Desktop size={11} className="text-neutral-400" />
      <span className="font-semibold text-neutral-100">{r.pc_name}</span>
      {r.pc_ip && <span className="font-mono text-[9px] text-[var(--text-secondary)]">{r.pc_ip}</span>}
      <span className={`text-[9px] font-semibold ${r.online ? "text-emerald-400" : "text-neutral-500"}`} data-testid={`user-search-online-${i}`}>
        {r.online ? "● online" : r.online === false ? "○ offline" : ""}
      </span>
    </div>
    {r.location ? (
      <button onClick={() => onGo(r)} className="mt-1 ml-4 flex items-center gap-1.5 text-[10px] text-cyan-300 hover:text-cyan-100 hover:underline" data-testid={`user-search-location-${i}`}>
        <Plug size={11} weight="bold" />
        {r.location.switch_name} · Porta {r.location.port}{r.location.port_name ? ` (${r.location.port_name})` : ""} → Vista Cavo
      </button>
    ) : (
      <p className="mt-1 ml-4 text-[9px] text-[var(--text-muted)]" data-testid={`user-search-nolocation-${i}`}>Porta switch non rilevata (PC in Wi-Fi, VPN o switch non monitorato)</p>
    )}
  </li>
);

export default function UserSearch() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const boxRef = useRef(null);

  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    const t = setTimeout(() => {
      setLoading(true);
      axios.get(`${API}/datto/user-search`, { params: { q: q.trim() } })
        .then(({ data }) => setRes(data.results || [])).catch(() => setRes([])).finally(() => setLoading(false));
    }, 350);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const close = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const go = (r) => {
    setOpen(false);
    navigate(`/switch-ports/${encodeURIComponent(r.location.switch_ip)}?clientId=${r.client_id}&port=${r.location.port}&cable=1`);
  };

  return (
    <div ref={boxRef} className="relative w-full max-w-[360px]" data-testid="user-search">
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-[var(--bg-border)] bg-[var(--bg-panel)]/90 backdrop-blur-md focus-within:border-sky-500/60 transition-colors">
        <MagnifyingGlass size={13} className="text-[var(--text-muted)]" />
        <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
          placeholder="Dov'è… cerca utente (es. mario)" className="flex-1 bg-transparent text-[12px] text-white outline-none placeholder:text-[var(--text-muted)]"
          data-testid="user-search-input" />
        {q && <button onClick={() => { setQ(""); setRes(null); }} className="text-[var(--text-muted)] hover:text-white" data-testid="user-search-clear"><X size={12} /></button>}
      </div>
      {open && q.trim().length >= 2 && (
        <div className="absolute right-0 mt-1.5 w-[420px] max-w-[92vw] max-h-[70vh] overflow-y-auto rounded-xl border border-[var(--bg-border)] bg-[var(--bg-app)] shadow-2xl z-50" data-testid="user-search-dropdown">
          {loading && !res ? (
            <p className="px-3 py-3 text-[11px] text-[var(--text-muted)]">Ricerca…</p>
          ) : res && res.length === 0 ? (
            <p className="px-3 py-3 text-[11px] text-[var(--text-muted)]" data-testid="user-search-empty">Nessun PC con ultimo accesso di "{q}" in Datto RMM.</p>
          ) : (
            <ul className="divide-y divide-white/5">{(res || []).map((r, i) => <Result key={`${r.client_id}-${r.pc_name}-${i}`} r={r} i={i} onGo={go} />)}</ul>
          )}
          <p className="px-3 py-1.5 text-[9px] text-[var(--text-muted)] border-t border-white/5">Fonte: ultimo utente collegato secondo Datto RMM (aggiornato a ogni sync).</p>
        </div>
      )}
    </div>
  );
}
