import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Sparkle, X, CheckCircle } from "@phosphor-icons/react";

const scoreColor = (s) => (s >= 0.9 ? "#34C759" : s >= 0.72 ? "#FF9500" : "#8E8E93");
const pct = (s) => `${Math.round((s || 0) * 100)}%`;

export default function BackupAutoMapModal({ open, onClose, onApplied }) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [sel, setSel] = useState({}); // client_id -> {vm, tenant, include}
  const [onlyUnmapped, setOnlyUnmapped] = useState(true);
  const [applying, setApplying] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/admin/backup-automap/suggestions`);
      setData(data);
      const init = {};
      for (const s of data.suggestions) {
        const vm = !s.mapped && s.vm_suggestion ? s.vm_suggestion.name : (s.current_vm[0] || "");
        const tenant = !s.mapped && s.tenant_suggestion ? s.tenant_suggestion.name : (s.current_tenants[0] || "");
        init[s.client_id] = {
          vm, tenant,
          include: !s.mapped && (!!s.vm_suggestion || !!s.tenant_suggestion),
        };
      }
      setSel(init);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento suggerimenti");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (open) load(); }, [open, load]);

  if (!open) return null;

  const rows = (data?.suggestions || []).filter((s) => (onlyUnmapped ? !s.mapped : true));
  const setRow = (cid, patch) => setSel((p) => ({ ...p, [cid]: { ...p[cid], ...patch } }));
  const toApply = rows.filter((s) => sel[s.client_id]?.include && (sel[s.client_id]?.vm || sel[s.client_id]?.tenant));

  const apply = async () => {
    setApplying(true);
    let okCount = 0, errCount = 0;
    for (const s of toApply) {
      const row = sel[s.client_id];
      try {
        const ops = [];
        if (row.vm && !s.current_vm.includes(row.vm)) {
          ops.push(axios.put(`${API}/clients/${s.client_id}/backup/vmbackup/mapping`, { customers: [row.vm] }));
        }
        if (row.tenant && !s.current_tenants.includes(row.tenant)) {
          ops.push(axios.put(`${API}/clients/${s.client_id}/backup/hornetsecurity/mapping`, { tenants: [row.tenant] }));
        }
        if (ops.length) { await Promise.all(ops); okCount++; }
      } catch (e) { errCount++; }
    }
    setApplying(false);
    if (okCount === 0 && errCount === 0) {
      toast.info("Nessuna modifica necessaria");
    } else {
      toast.success(`Auto-mapping applicato: ${okCount} clienti${errCount ? ` · ${errCount} errori` : ""}`);
    }
    if (onApplied) onApplied();
    await load();
  };

  const renderSelect = (cid, field, candidates, current) => {
    const val = sel[cid]?.[field] ?? "";
    const opts = [];
    const seen = new Set();
    (candidates || []).forEach((c) => { if (!seen.has(c.name)) { seen.add(c.name); opts.push(c); } });
    (current || []).forEach((n) => { if (n && !seen.has(n)) { seen.add(n); opts.push({ name: n, score: null }); } });
    if (val && !seen.has(val)) opts.push({ name: val, score: null });
    return (
      <select
        key={`${cid}-${field}`}
        value={val}
        onChange={(e) => setRow(cid, { [field]: e.target.value, include: true })}
        className="w-full rounded border border-[var(--bg-border)] bg-[var(--bg-card)] px-2 py-1 text-[11px]"
        data-testid={`automap-${field}-${cid}`}
      >
        <option value="">— nessuno —</option>
        {opts.map((o) => (
          <option key={o.name} value={o.name}>
            {o.name}{o.score != null ? ` (${pct(o.score)})` : ""}
          </option>
        ))}
      </select>
    );
  };

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 p-4" data-testid="automap-modal">
      <div className="w-full max-w-4xl max-h-[88vh] flex flex-col rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel,#12121a)] shadow-2xl">
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--bg-border)]">
          <div className="flex items-center gap-2">
            <Sparkle size={18} className="text-indigo-400" weight="fill" />
            <h2 className="text-sm font-semibold">Auto-mappatura backup</h2>
            {data && (
              <span className="text-[11px] text-[var(--text-muted)]">
                {data.clients_total} clienti · {data.vm_customers_total} VM · {data.tenants_total} tenant 365
              </span>
            )}
          </div>
          <button onClick={onClose} data-testid="automap-close"><X size={18} /></button>
        </div>

        <div className="px-5 py-2 border-b border-[var(--bg-border)] flex items-center justify-between">
          <label className="flex items-center gap-2 text-[11px] cursor-pointer">
            <input type="checkbox" checked={onlyUnmapped} onChange={(e) => setOnlyUnmapped(e.target.checked)} data-testid="automap-only-unmapped" />
            Mostra solo clienti non ancora mappati
          </label>
          <span className="text-[11px] text-[var(--text-muted)]">Suggerimenti ≥{Math.round((data?.threshold || 0.72) * 100)}% pre-selezionati</span>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2">
          {loading && <p className="text-center text-xs text-[var(--text-muted)] py-8">Analisi somiglianze…</p>}
          {!loading && rows.length === 0 && <p className="text-center text-xs text-[var(--text-muted)] py-8">Nessun cliente da mappare 🎉</p>}
          {!loading && rows.map((s) => {
            const row = sel[s.client_id] || {};
            return (
              <div key={s.client_id} className="grid grid-cols-[24px_1.4fr_1.3fr_1.3fr] gap-2 items-center px-2 py-1.5 border-b border-[var(--bg-border)]/40" data-testid={`automap-row-${s.client_id}`}>
                <input type="checkbox" checked={!!row.include} onChange={(e) => setRow(s.client_id, { include: e.target.checked })} data-testid={`automap-include-${s.client_id}`} />
                <div className="min-w-0">
                  <div className="text-xs font-medium truncate">{s.client_name}</div>
                  {s.mapped && <div className="text-[9px] text-emerald-400 flex items-center gap-1"><CheckCircle size={10} weight="fill" />già mappato</div>}
                </div>
                <div>
                  <div className="text-[8px] uppercase tracking-wider text-violet-300/70 mb-0.5">VM Backup</div>
                  {renderSelect(s.client_id, "vm", s.vm_candidates, s.current_vm)}
                  {s.vm_suggestion && (
                    <span className="text-[10px]" style={{ color: scoreColor(s.vm_suggestion.score) }}>
                      suggerito: {s.vm_suggestion.name} ({pct(s.vm_suggestion.score)})
                    </span>
                  )}
                </div>
                <div>
                  <div className="text-[8px] uppercase tracking-wider text-cyan-300/70 mb-0.5">365 Total Backup</div>
                  {renderSelect(s.client_id, "tenant", s.tenant_candidates, s.current_tenants)}
                  {s.tenant_suggestion && (
                    <span className="text-[10px]" style={{ color: scoreColor(s.tenant_suggestion.score) }}>
                      suggerito: {s.tenant_suggestion.name} ({pct(s.tenant_suggestion.score)})
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="px-5 py-3 border-t border-[var(--bg-border)] flex items-center justify-between">
          <span className="text-[11px] text-[var(--text-muted)]">{toApply.length} associazioni selezionate</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={onClose} className="text-xs">Chiudi</Button>
            <Button size="sm" disabled={applying || toApply.length === 0} onClick={apply}
              className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="automap-apply">
              {applying ? "Applico…" : `Applica ${toApply.length}`}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
