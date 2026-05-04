import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { CaretLeft, CaretRight, MagnifyingGlass, CheckCircle, Circle } from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * DattoBrowser - visualizzatore paginato dei siti e device Datto sincronizzati.
 *
 * Tabs: "Siti Datto" / "Dispositivi (privacy-safe)"
 * Paginazione server-side con Prev/Next + search client-side.
 * Ritorna SOLO name/mac/ip/matched per i device (nessun dato sensibile).
 */
export default function DattoBrowser() {
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };
  const [tab, setTab] = useState("sites");  // "sites" | "devices"
  const [page, setPage] = useState(0);
  const [size] = useState(25);
  const [data, setData] = useState({ items: [], total: 0, total_pages: 1, has_prev: false, has_next: false });
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = tab === "sites"
        ? `${API}/api/datto/browse/sites?page=${page}&size=${size}`
        : `${API}/api/datto/browse/devices?page=${page}&size=${size}${onlyMatched ? "&only_matched=true" : ""}`;
      const r = await axios.get(url, { headers });
      setData(r.data);
    } catch {
      setData({ items: [], total: 0, total_pages: 1, has_prev: false, has_next: false });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, page, size, onlyMatched]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); }, [tab, onlyMatched]);

  const filteredItems = data.items.filter((it) => {
    if (!search) return true;
    const q = search.toLowerCase();
    if (tab === "sites") {
      return (it.site_name || "").toLowerCase().includes(q);
    }
    return (it.name || "").toLowerCase().includes(q)
      || (it.mac || "").toLowerCase().includes(q)
      || (it.ip || "").includes(q);
  });

  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-panel)]" data-testid="datto-browser">
      {/* Tabs */}
      <div className="flex items-center border-b border-[var(--bg-border)]">
        <button
          type="button"
          onClick={() => setTab("sites")}
          className={`px-4 py-2 text-xs font-medium transition-colors ${tab === "sites"
            ? "text-fuchsia-300 border-b-2 border-fuchsia-400"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
          data-testid="datto-browser-tab-sites"
        >
          Siti Datto <span className="text-[10px] opacity-60">({tab === "sites" ? data.total : "…"})</span>
        </button>
        <button
          type="button"
          onClick={() => setTab("devices")}
          className={`px-4 py-2 text-xs font-medium transition-colors ${tab === "devices"
            ? "text-fuchsia-300 border-b-2 border-fuchsia-400"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
          data-testid="datto-browser-tab-devices"
        >
          Dispositivi sincronizzati <span className="text-[10px] opacity-60">({tab === "devices" ? data.total : "…"})</span>
        </button>
        {tab === "devices" && (
          <label className="ml-auto mr-3 flex items-center gap-1.5 text-[10px] text-[var(--text-secondary)] cursor-pointer">
            <input
              type="checkbox"
              checked={onlyMatched}
              onChange={(e) => setOnlyMatched(e.target.checked)}
              data-testid="datto-browser-only-matched"
            />
            Solo matched
          </label>
        )}
      </div>

      {/* Search */}
      <div className="p-3 border-b border-[var(--bg-border)]/50 flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <MagnifyingGlass size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={tab === "sites" ? "Cerca sito…" : "Cerca nome/MAC/IP…"}
            className="w-full h-7 pl-7 pr-2 text-xs rounded border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
            data-testid="datto-browser-search"
          />
        </div>
        <span className="text-[10px] text-[var(--text-muted)] ml-auto">
          Pagina <b>{data.page + 1}</b> di <b>{data.total_pages}</b> · <b>{data.total}</b> totali
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto min-h-[200px]">
        {loading ? (
          <div className="p-8 text-center text-[11px] text-[var(--text-muted)]">Caricamento…</div>
        ) : filteredItems.length === 0 ? (
          <div className="p-8 text-center text-[11px] text-[var(--text-muted)] italic">
            {tab === "sites" ? "Nessun sito Datto trovato." : "Nessun dispositivo sincronizzato. Collega almeno un cliente a un sito Datto."}
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-[9px] uppercase tracking-wider text-[var(--text-secondary)] border-b border-[var(--bg-border)]/50 bg-[var(--bg-hover)]/20">
              <tr>
                {tab === "sites" ? (
                  <>
                    <th className="text-left py-2 px-3">Nome sito</th>
                    <th className="text-right py-2 px-3">Device</th>
                    <th className="text-left py-2 px-3">Ultimo refresh</th>
                  </>
                ) : (
                  <>
                    <th className="text-left py-2 px-3">Nome dispositivo</th>
                    <th className="text-left py-2 px-3 font-mono">MAC</th>
                    <th className="text-left py-2 px-3 font-mono">IP</th>
                    <th className="text-left py-2 px-3">Sito</th>
                    <th className="text-center py-2 px-3">Match Center</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((it, i) => (
                <tr key={(it.site_id || it.mac || i) + "_" + i}
                    className="border-b border-[var(--bg-border)]/30 hover:bg-[var(--bg-hover)]/30"
                    data-testid={`datto-browser-row-${i}`}>
                  {tab === "sites" ? (
                    <>
                      <td className="py-2 px-3 font-medium text-[var(--text-primary)]">{it.site_name}</td>
                      <td className="py-2 px-3 text-right font-mono text-[var(--text-secondary)]">{it.device_count || 0}</td>
                      <td className="py-2 px-3 text-[10px] text-[var(--text-muted)]">
                        {it.fetched_at ? new Date(it.fetched_at).toLocaleString("it-IT") : "—"}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="py-2 px-3 font-medium text-[var(--text-primary)]">{it.name || "—"}</td>
                      <td className="py-2 px-3 font-mono text-[var(--text-secondary)]">{it.mac || "—"}</td>
                      <td className="py-2 px-3 font-mono text-[var(--text-secondary)]">{it.ip || "—"}</td>
                      <td className="py-2 px-3 text-[10px] text-[var(--text-muted)]">{it.site_name || "—"}</td>
                      <td className="py-2 px-3 text-center">
                        {it.matched ? (
                          <CheckCircle size={14} weight="fill" className="text-emerald-400 inline" title="Matchato con endpoint discovered del Center" />
                        ) : (
                          <Circle size={14} className="text-[var(--text-muted)] inline" title="Non ancora matchato" />
                        )}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Paginator */}
      <div className="flex items-center justify-between p-3 border-t border-[var(--bg-border)]/50">
        <button
          type="button"
          disabled={!data.has_prev || loading}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          className="flex items-center gap-1 px-3 h-7 text-xs rounded border border-[var(--bg-border)] bg-[var(--bg-surface)] hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid="datto-browser-prev"
        >
          <CaretLeft size={12} /> Precedente
        </button>
        <div className="flex items-center gap-1">
          {Array.from({ length: Math.min(7, data.total_pages) }, (_, i) => {
            let targetPage;
            if (data.total_pages <= 7) targetPage = i;
            else if (data.page < 4) targetPage = i;
            else if (data.page > data.total_pages - 4) targetPage = data.total_pages - 7 + i;
            else targetPage = data.page - 3 + i;
            const isActive = targetPage === data.page;
            return (
              <button
                key={targetPage}
                type="button"
                onClick={() => setPage(targetPage)}
                className={`w-7 h-7 text-xs rounded ${isActive
                  ? "bg-fuchsia-500/30 text-fuchsia-200 font-bold border border-fuchsia-400/50"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
                data-testid={`datto-browser-page-${targetPage}`}
              >
                {targetPage + 1}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          disabled={!data.has_next || loading}
          onClick={() => setPage((p) => p + 1)}
          className="flex items-center gap-1 px-3 h-7 text-xs rounded border border-[var(--bg-border)] bg-[var(--bg-surface)] hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid="datto-browser-next"
        >
          Successivo <CaretRight size={12} />
        </button>
      </div>
    </div>
  );
}
