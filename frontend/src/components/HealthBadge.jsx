/**
 * HealthBadge — griglia compatta 4x2 di pallini per subsystem health.
 * Riutilizzabile: TV Dashboard, Client Overview header, Hardware iLO live strip.
 *
 * Props:
 *   subsystems: { system, thermal, fans, power, memory, storage, processors, network }
 *     Valori: "ok" | "warning" | "critical" | "unknown"
 *   size: "xs" (badge 4x4, no label) | "sm" (6x6 + label) | "md" (7x7 + label, default)
 *   labelled: true|false (default: auto based on size)
 */

const SUBSYSTEMS = [
  { key: "system",     label: "SYS", full: "Sistema" },
  { key: "thermal",    label: "TMP", full: "Thermal" },
  { key: "fans",       label: "FAN", full: "Ventole" },
  { key: "power",      label: "PSU", full: "PSU" },
  { key: "memory",     label: "MEM", full: "Memoria" },
  { key: "storage",    label: "STO", full: "Storage" },
  { key: "processors", label: "CPU", full: "CPU" },
  { key: "network",    label: "NIC", full: "Network" },
];

function statusColor(s) {
  switch ((s || "unknown").toLowerCase()) {
    case "ok":
    case "good":     return { bg: "#10b981", ring: "rgba(16,185,129,0.25)" };
    case "warning":
    case "degraded": return { bg: "#f59e0b", ring: "rgba(245,158,11,0.25)" };
    case "critical":
    case "failed":   return { bg: "#ef4444", ring: "rgba(239,68,68,0.3)" };
    default:         return { bg: "#475569", ring: "rgba(71,85,105,0.2)" };
  }
}

/** Aggregate worst-of across an array of {subsystems} objects (used for multi-server rollup). */
export function rollupSubsystems(list) {
  const rank = { critical: 3, warning: 2, ok: 1, unknown: 0 };
  const out = {};
  SUBSYSTEMS.forEach(({ key }) => {
    let worst = "unknown";
    for (const item of (list || [])) {
      const s = (item?.subsystems?.[key] || "unknown").toLowerCase();
      if ((rank[s] || 0) > (rank[worst] || 0)) worst = s;
    }
    out[key] = worst;
  });
  return out;
}

export default function HealthBadge({ subsystems, size = "md", labelled, className = "", testId }) {
  if (!subsystems || typeof subsystems !== "object") return null;

  const cfg = {
    xs: { dot: 4, label: 0,  gapX: 3,   gapY: 2,   fontSize: 0 },
    sm: { dot: 6, label: 8,  gapX: 6,   gapY: 3,   fontSize: 8 },
    md: { dot: 7, label: 9,  gapX: 8,   gapY: 4,   fontSize: 9 },
  }[size] || undefined;
  const c = cfg || { dot: 7, label: 9, gapX: 8, gapY: 4, fontSize: 9 };

  const showLabel = labelled == null ? (size !== "xs") : labelled;

  return (
    <div
      className={`inline-grid grid-cols-4 ${className}`}
      style={{ columnGap: c.gapX, rowGap: c.gapY }}
      data-testid={testId}
    >
      {SUBSYSTEMS.map(({ key, label, full }) => {
        const s = subsystems[key] || "unknown";
        const col = statusColor(s);
        return (
          <div
            key={key}
            className="flex items-center gap-1 cursor-default"
            title={`${full}: ${s.toUpperCase()}`}
            data-testid={testId ? `${testId}-${key}` : undefined}
          >
            <span
              className={s === "critical" ? "animate-pulse" : ""}
              style={{
                display: "inline-block",
                width: c.dot, height: c.dot,
                borderRadius: "50%",
                background: col.bg,
                boxShadow: `0 0 0 2px ${col.ring}`,
                flexShrink: 0,
              }}
            />
            {showLabel && (
              <span
                className="font-mono font-bold tracking-wider"
                style={{
                  fontSize: c.fontSize,
                  color: s === "unknown" ? "rgba(255,255,255,0.25)" : "rgba(255,255,255,0.6)",
                  lineHeight: 1,
                }}
              >
                {label}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
