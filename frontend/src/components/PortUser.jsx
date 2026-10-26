import { User } from "@phosphor-icons/react";

export const shortUser = (u) => String(u || "").split("\\").pop().split("@")[0];

export const fmtSeen = (iso) => {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; }
};

export function PortUserLine({ u, idx, size = "sm" }) {
  if (!u?.user) return null;
  const txt = size === "xs" ? "text-[9px]" : "text-[10px]";
  return (
    <div className={`flex items-center gap-1 ${txt} text-sky-200`} title={`Ultimo utente collegato (Datto RMM)${u.last_seen ? ` · visto ${fmtSeen(u.last_seen)}` : ""}`} data-testid={`port-user-${size}-${idx}`}>
      <User size={size === "xs" ? 9 : 11} weight="bold" className={u.online === false ? "text-neutral-400" : "text-sky-300"} />
      <span className="font-mono truncate max-w-[200px]">{u.user}</span>
      {u.online === false && <span className="text-[8px] text-neutral-400">(PC offline)</span>}
    </div>
  );
}

export function TileUserLabel({ p, show }) {
  if (!show || !p.datto_user?.user) return null;
  return (
    <span className="mt-0.5 max-w-[50px] truncate text-[8px] font-mono text-sky-200 leading-none" title={p.datto_user.user} data-testid={`port-tile-user-${p.idx}`}>
      {shortUser(p.datto_user.user)}
    </span>
  );
}
