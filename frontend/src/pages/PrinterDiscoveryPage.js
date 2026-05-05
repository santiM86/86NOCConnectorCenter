/**
 * Printer Discovery Page - v3.7.3
 * ================================
 * Lista tutte le stampanti rilevate per un cliente incrociando:
 *  - OUI MAC vendor (HP, Epson, Canon, Brother, Lexmark, ecc.)
 *  - SNMP sysDescr di managed devices type=printer
 *  - Datto RMM matched
 *  - Manual binding
 */
import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { Printer, ArrowsClockwise, DownloadSimple, MagnifyingGlass, CheckCircle, Circle, CaretUp, CaretDown } from "@phosphor-icons/react";

const SOURCE_BADGE = {
  oui:    { label: "OUI",   cls: "bg-amber-500/20 text-amber-300 border-amber-400/40", title: "Identificato via MAC vendor (OUI)" },
  snmp:   { label: "SNMP",  cls: "bg-cyan-500/20 text-cyan-300 border-cyan-400/40", title: "Rilevato via SNMP sysDescr" },
  datto:  { label: "DATTO", cls: "bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-400/40", title: "Matched con Datto RMM" },
  manual: { label: "MANUAL", cls: "bg-violet-500/20 text-violet-300 border-violet-400/40", title: "Binding manuale admin" },
};

export default function PrinterDiscoveryPage() {
  const { clientId } = useParams();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };
  const [data, setData] = useState({ items: [], count: 0, unique_ips: 0, by_vendor: {} });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [vendorFilter, setVendorFilter] = useState("");
  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState("asc");

  const load = async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/clients/${clientId}/printers-discovery`, { headers });
      setData(r.data);
    } catch {
      setData({ items: [], count: 0, unique_ips: 0, by_vendor: {} });
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [clientId]);

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortBy(col); setSortDir("asc"); }
  };

  const filtered = useMemo(() => {
    let list = data.items;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(p =>
        (p.name || "").toLowerCase().includes(q) ||
        (p.ip || "").includes(q) ||
        (p.mac || "").toLowerCase().includes(q) ||
        (p.vendor || "").toLowerCase().includes(q) ||
        (p.model || "").toLowerCase().includes(q)
      );
    }
    if (vendorFilter) list = list.filter(p => p.vendor === vendorFilter);
    const dir = sortDir === "asc" ? 1 : -1;
    const keyFn = {
      name: (p) => (p.name || "").toLowerCase(),
      ip: (p) => p.ip || "",
      mac: (p) => p.mac || "",
      vendor: (p) => p.vendor || "",
      switch: (p) => (p.switch_ip || "") + "/" + (p.switch_port || ""),
    }[sortBy] || ((p) => p.name || "");
    return [...list].sort((a, b) => {
      const ka = keyFn(a), kb = keyFn(b);
      if (ka < kb) return -1 * dir; if (ka > kb) return 1 * dir; return 0;
    });
  }, [data.items, search, vendorFilter, sortBy, sortDir]);

  const exportCsv = () => {
    const rows = [["Nome", "IP", "MAC", "Vendor", "Modello", "Switch", "Porta", "Sources"]];
    filtered.forEach(p => rows.push([
      p.name, p.ip, p.mac, p.vendor, p.model,
      p.switch_ip || "", p.switch_port || "",
      (p.sources || []).join(";"),
    ]));
    const csv = rows.map(r => r.map(v => `"${(v || "").toString().replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `stampanti-${clientId}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  const SortIcon = ({ col }) => sortBy !== col
    ? <CaretUp size={9} className="opacity-30 inline ml-0.5" />
    : (sortDir === "asc" ? <CaretUp size={9} className="inline ml-0.5 text-cyan-300" /> : <CaretDown size={9} className="inline ml-0.5 text-cyan-300" />);

  return (
    <div className="p-3 md:p-6 max-w-6xl mx-auto space-y-4" data-testid="printer-discovery-page">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Printer size={24} className="text-cyan-300" weight="duotone" />
        <div className="min-w-0 flex-1">
          <h1 className="text-base md:text-lg font-bold">Stampanti di rete</h1>
          <p className="text-[11px] text-[var(--text-muted)]">Aggregate da MAC OUI · SNMP sysDescr · Datto RMM · binding manuale</p>
        </div>
        <button onClick={load} className="h-8 px-3 rounded text-xs bg-[var(--bg-surface)] hover:bg-[var(--bg-hover)] border border-[var(--bg-border)] flex items-center gap-1.5" data-testid="printers-refresh">
          <ArrowsClockwise size={12} className={loading ? "animate-spin" : ""} /> Aggiorna
        </button>
        <button onClick={exportCsv} disabled={filtered.length === 0} className="h-8 px-3 rounded text-xs bg-cyan-500/20 text-cyan-200 hover:bg-cyan-500/30 border border-cyan-400/40 disabled:opacity-50 flex items-center gap-1.5" data-testid="printers-export-csv">
          <DownloadSimple size={12} /> Esporta CSV
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div className="rounded-lg p-3 bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="stat-total">
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Totale</div>
          <div className="text-2xl font-bold text-cyan-300">{data.count}</div>
        </div>
        <div className="rounded-lg p-3 bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="stat-ips">
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Indirizzi IP</div>
          <div className="text-2xl font-bold text-violet-300">{data.unique_ips}</div>
        </div>
        <div className="rounded-lg p-3 bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="stat-vendors">
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Produttori</div>
          <div className="text-2xl font-bold text-amber-300">{Object.keys(data.by_vendor).length}</div>
        </div>
        <div className="rounded-lg p-3 bg-[var(--bg-panel)] border border-[var(--bg-border)]" data-testid="stat-managed">
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Monitorate SNMP</div>
          <div className="text-2xl font-bold text-emerald-300">{data.items.filter(p => p.is_managed).length}</div>
        </div>
      </div>

      {/* Vendor chips */}
      {Object.keys(data.by_vendor).length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="vendor-breakdown">
          <button onClick={() => setVendorFilter("")} className={`px-2 py-1 rounded text-[10px] border ${vendorFilter === "" ? "bg-cyan-500/20 text-cyan-200 border-cyan-400/50" : "bg-[var(--bg-surface)] text-[var(--text-secondary)] border-[var(--bg-border)]"}`}>Tutti ({data.count})</button>
          {Object.entries(data.by_vendor).map(([v, n]) => (
            <button key={v} onClick={() => setVendorFilter(v === vendorFilter ? "" : v)} className={`px-2 py-1 rounded text-[10px] border ${vendorFilter === v ? "bg-amber-500/20 text-amber-200 border-amber-400/50" : "bg-[var(--bg-surface)] text-[var(--text-secondary)] border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"}`} data-testid={`vendor-filter-${v.replace(/\s+/g, "-").toLowerCase()}`}>
              {v} · {n}
            </button>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="relative max-w-md">
        <MagnifyingGlass size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
        <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cerca nome, IP, MAC, vendor o modello…" className="w-full h-8 pl-7 pr-2 text-xs rounded border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]" data-testid="printers-search" />
      </div>

      {/* Table */}
      <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-panel)] overflow-x-auto">
        {loading ? (
          <div className="p-8 text-center text-[11px] text-[var(--text-muted)]">Analisi dispositivi di rete in corso…</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-[11px] text-[var(--text-muted)] italic">Nessuna stampante rilevata. Assicurati che il connector abbia eseguito il polling SNMP degli switch.</div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[9px] uppercase tracking-wider text-[var(--text-secondary)] border-b border-[var(--bg-border)] bg-[var(--bg-hover)]/20">
                <th className="text-left py-2 px-3 cursor-pointer hover:text-cyan-300" onClick={() => toggleSort("name")}>Nome <SortIcon col="name" /></th>
                <th className="text-left py-2 px-3 cursor-pointer hover:text-cyan-300 font-mono" onClick={() => toggleSort("ip")}>IP <SortIcon col="ip" /></th>
                <th className="text-left py-2 px-3 cursor-pointer hover:text-cyan-300 font-mono" onClick={() => toggleSort("mac")}>MAC <SortIcon col="mac" /></th>
                <th className="text-left py-2 px-3 cursor-pointer hover:text-cyan-300" onClick={() => toggleSort("vendor")}>Vendor <SortIcon col="vendor" /></th>
                <th className="text-left py-2 px-3">Modello</th>
                <th className="text-left py-2 px-3 cursor-pointer hover:text-cyan-300" onClick={() => toggleSort("switch")}>Switch/Porta <SortIcon col="switch" /></th>
                <th className="text-left py-2 px-3">Sorgenti</th>
                <th className="text-center py-2 px-3">SNMP</th>
                <th className="text-center py-2 px-3">Datto</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p, i) => (
                <tr key={(p.mac || p.ip || i) + "_" + i} className="border-b border-[var(--bg-border)]/30 hover:bg-[var(--bg-hover)]/30" data-testid={`printer-row-${i}`}>
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-2">
                      <Printer size={13} className="text-cyan-400" weight="duotone" />
                      <span className="font-bold text-[11px] text-neutral-100">{p.name}</span>
                    </div>
                  </td>
                  <td className="py-2 px-3 font-mono text-cyan-300">
                    {p.ip ? <a href={`http://${p.ip}`} target="_blank" rel="noopener noreferrer" className="hover:underline" title="Apri Web UI">{p.ip}</a> : "—"}
                  </td>
                  <td className="py-2 px-3 font-mono text-neutral-300">{p.mac || "—"}</td>
                  <td className="py-2 px-3 text-amber-300">{p.vendor || "—"}</td>
                  <td className="py-2 px-3 text-[10px] text-[var(--text-secondary)] max-w-[200px] truncate" title={p.model}>{p.model || "—"}</td>
                  <td className="py-2 px-3 font-mono text-[10px]">
                    {p.switch_ip
                      ? <Link to={`/devices/${encodeURIComponent(p.switch_ip)}`} className="text-violet-300 hover:underline">{p.switch_ip} / {p.switch_port}</Link>
                      : <span className="text-[var(--text-muted)]">—</span>}
                  </td>
                  <td className="py-2 px-3">
                    <div className="flex flex-wrap gap-1">
                      {(p.sources || []).map(src => {
                        const b = SOURCE_BADGE[src];
                        if (!b) return null;
                        return <span key={src} title={b.title} className={`px-1.5 py-0.5 text-[8px] font-bold rounded border ${b.cls}`}>{b.label}</span>;
                      })}
                    </div>
                  </td>
                  <td className="py-2 px-3 text-center">
                    {p.is_managed ? <CheckCircle size={14} weight="fill" className="text-emerald-400 inline" /> : <Circle size={14} className="text-[var(--text-muted)] inline" />}
                  </td>
                  <td className="py-2 px-3 text-center">
                    {p.datto_matched ? <CheckCircle size={14} weight="fill" className="text-fuchsia-400 inline" /> : <Circle size={14} className="text-[var(--text-muted)] inline" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="text-[10px] text-[var(--text-muted)] flex flex-wrap gap-x-4 gap-y-1 px-1">
        <span><span className="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1" /> OUI: identificato via produttore MAC</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-cyan-400 mr-1" /> SNMP: rilevato via sysDescr</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-fuchsia-400 mr-1" /> DATTO: matched con Datto RMM</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-violet-400 mr-1" /> MANUAL: binding admin</span>
      </div>
    </div>
  );
}
