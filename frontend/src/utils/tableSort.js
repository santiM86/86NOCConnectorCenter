// v3.8.30: Tabelle ordinabili — hook + header componente riutilizzabili.
// Usage:
//   const { sorted, sortKey, sortDir, requestSort } = useSortableTable(items, "name", "asc");
//   <SortableTh sortKey={sortKey} sortDir={sortDir} onSort={requestSort} field="name">Nome</SortableTh>
//
// Il valore di ordinamento per ogni riga e' di default item[field]. Si puo' passare
// un getter custom alla hook tramite il parametro accessors:
//   useSortableTable(items, "name", "asc", { name: it => (it.name || "").toLowerCase() })

import { useMemo, useState } from "react";

export function useSortableTable(items, defaultKey = null, defaultDir = "asc", accessors = {}) {
  const [sortKey, setSortKey] = useState(defaultKey);
  const [sortDir, setSortDir] = useState(defaultDir);

  const requestSort = (field) => {
    if (sortKey === field) {
      // Toggle asc -> desc -> nessun ordinamento (torna al default)
      if (sortDir === "asc") setSortDir("desc");
      else { setSortKey(null); setSortDir("asc"); }
    } else {
      setSortKey(field);
      setSortDir("asc");
    }
  };

  const sorted = useMemo(() => {
    if (!sortKey) return items || [];
    const arr = [...(items || [])];
    const getter = accessors[sortKey] || ((it) => {
      const v = it?.[sortKey];
      if (v == null) return "";
      // Convert ISO date strings to timestamp for proper chronological sort
      if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) {
        const t = Date.parse(v);
        if (!Number.isNaN(t)) return t;
      }
      return typeof v === "string" ? v.toLowerCase() : v;
    });
    arr.sort((a, b) => {
      const va = getter(a);
      const vb = getter(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return arr;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, sortKey, sortDir]);

  return { sorted, sortKey, sortDir, requestSort };
}

export function SortableTh({ sortKey, sortDir, onSort, field, children, className = "", testId }) {
  const active = sortKey === field;
  const arrow = active ? (sortDir === "asc" ? "▲" : "▼") : "↕";
  return (
    <th
      onClick={() => onSort(field)}
      className={`cursor-pointer select-none hover:text-cyan-300 transition-colors ${active ? "text-cyan-300" : ""} ${className}`}
      data-testid={testId || `sort-${field}`}
      title={`Ordina per ${typeof children === "string" ? children : field}`}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        <span className={`text-[8px] ${active ? "opacity-100" : "opacity-30"}`}>{arrow}</span>
      </span>
    </th>
  );
}
