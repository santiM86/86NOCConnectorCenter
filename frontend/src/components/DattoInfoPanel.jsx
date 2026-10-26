import { useEffect, useState } from "react";
import axios from "axios";
import { CaretDown, CaretRight, WindowsLogo } from "@phosphor-icons/react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmt = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; }
};

const Item = ({ label, value, tid, warn }) => (
  <div className="min-w-0">
    <div className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
    <div className={`text-[10px] font-medium truncate ${warn ? "text-amber-300" : "text-neutral-100"}`} title={value || ""} data-testid={tid}>{value || "—"}</div>
  </div>
);

export default function DattoInfoPanel({ clientId, ip, mac, defaultOpen = false, testIdSuffix = "" }) {
  const [open, setOpen] = useState(defaultOpen);
  const [d, setD] = useState(null);
  const sfx = testIdSuffix || ip || mac;

  useEffect(() => {
    if (!open || d || (!ip && !mac)) return;
    axios.get(`${API}/datto/device-info`, { params: { client_id: clientId || undefined, ip: ip || undefined, mac: mac || undefined } })
      .then(({ data }) => setD(data)).catch(() => setD({ found: false }));
  }, [open, d, clientId, ip, mac]);

  if ((!clientId && !mac) || (!ip && !mac)) return null;
  return (
    <div className="mt-1.5 rounded-md border border-fuchsia-500/25 bg-fuchsia-500/[0.04]" data-testid={`datto-info-${sfx}`}>
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-1.5 px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-fuchsia-300 hover:text-fuchsia-200 transition-colors" data-testid={`datto-info-toggle-${sfx}`}>
        {open ? <CaretDown size={10} /> : <CaretRight size={10} />}
        <WindowsLogo size={11} /> Info Datto RMM · sistema e utente
      </button>
      {open && (
        <div className="px-2 pb-2">
          {!d ? (
            <p className="text-[10px] text-[var(--text-muted)]">Caricamento…</p>
          ) : !d.found ? (
            <p className="text-[10px] text-[var(--text-muted)]" data-testid={`datto-info-notfound-${sfx}`}>Dispositivo non presente in Datto RMM.</p>
          ) : (
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
              <div className="col-span-2"><Item label="Sistema operativo" value={[d.operating_system, d.os_version && `(${d.os_version})`, d.os_architecture].filter(Boolean).join(" ")} tid={`datto-os-${sfx}`} /></div>
              <Item label="Ultimo utente" value={d.last_logged_user} tid={`datto-user-${sfx}`} />
              <Item label="Dominio" value={d.domain} tid={`datto-domain-${sfx}`} />
              <Item label="Ultimo riavvio" value={fmt(d.last_reboot)} tid={`datto-reboot-${sfx}`} />
              <Item label="Riavvio necessario" value={d.reboot_required == null ? "—" : d.reboot_required ? "Sì" : "No"} warn={d.reboot_required} tid={`datto-reboot-required-${sfx}`} />
              <Item label="Stato Datto" value={d.online == null ? "—" : d.online ? "Online" : "Offline"} warn={d.online === false} tid={`datto-online-${sfx}`} />
              <Item label="Ultimo contatto" value={fmt(d.last_seen)} tid={`datto-lastseen-${sfx}`} />
              <Item label="Tipo" value={d.device_type} tid={`datto-type-${sfx}`} />
              <Item label="Sito" value={d.site_name} tid={`datto-site-${sfx}`} />
              {d.description && <div className="col-span-2"><Item label="Descrizione" value={d.description} tid={`datto-desc-${sfx}`} /></div>}
              <p className="col-span-2 text-[8px] text-[var(--text-muted)]">Dati aggiornati alla sync Datto del {fmt(d.fetched_at)}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
