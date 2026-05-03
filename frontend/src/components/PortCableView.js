/**
 * Vista Cavo - Cable Diagnostic Modal
 * Mostra uno schema verticale cablato della porta selezionata:
 * [Switch locale + porta] -> [cavo animato con velocita'] -> [device remoto]
 * Utile per help-desk: risponde a colpo d'occhio "porta X a cosa e' collegata?".
 */
import React, { useState } from "react";
import {
  Lightning, ArrowUp, ArrowDown, Plug, Link as LinkIcon,
  Cloud, WifiHigh, Monitor, HardDrives, X,
} from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import PortFlapHistory from "./PortFlapHistory";

const API = process.env.REACT_APP_BACKEND_URL;

function fmtBytes(n) {
  if (!n || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log10(n) / 3));
  return `${(n / Math.pow(1000, i)).toFixed(i ? 2 : 0)} ${units[i]}`;
}
function fmtBps(n) {
  if (!n || n <= 0) return "0 bps";
  const units = ["bps", "Kbps", "Mbps", "Gbps"];
  const i = Math.min(units.length - 1, Math.floor(Math.log10(n) / 3));
  return `${(n / Math.pow(1000, i)).toFixed(i ? 2 : 0)} ${units[i]}`;
}
function fmtSpeed(mbps) {
  if (!mbps || mbps <= 0) return "—";
  if (mbps >= 10000) return `${(mbps / 1000).toFixed(0)} Gbps`;
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(0)} Gbps`;
  return `${mbps} Mbps`;
}
function fmtDuration(seconds) {
  if (seconds == null || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s fa`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}min fa`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h fa`;
  return `${Math.round(seconds / 86400)}g fa`;
}
function portLabel(name, idx) {
  if (!name) return String(idx ?? "");
  const m = String(name).match(/\/(\d+)\s*$/);
  if (m) return m[1];
  const m2 = String(name).match(/(\d+)\s*$/);
  if (m2) return m2[1];
  return String(idx ?? "");
}

/** Device type -> (icon, color) helper for the remote endpoint */
function remoteIconFor(type, sysCap) {
  const cap = Number(sysCap || 0);
  // LLDP capability bitmap: bit0=other, 1=repeater, 2=bridge (switch), 3=wlan AP,
  // 4=router, 5=telephone, 6=docsis, 7=station only
  if (cap & 0x08) return { Icon: WifiHigh, color: "#06b6d4", label: "Access Point" };
  if (cap & 0x10) return { Icon: Cloud, color: "#a78bfa", label: "Router/Firewall" };
  if (cap & 0x04) return { Icon: LinkIcon, color: "#22d3ee", label: "Switch" };
  const t = (type || "").toLowerCase();
  if (t === "nas" || t === "server") return { Icon: HardDrives, color: "#34d399", label: t.toUpperCase() };
  if (t === "printer") return { Icon: Monitor, color: "#f59e0b", label: "Stampante" };
  if (t === "camera") return { Icon: Monitor, color: "#ec4899", label: "Camera IP" };
  if (t === "ap") return { Icon: WifiHigh, color: "#06b6d4", label: "Access Point" };
  if (t === "ups") return { Icon: Plug, color: "#fbbf24", label: "UPS" };
  return { Icon: Monitor, color: "#94a3b8", label: "Dispositivo" };
}

/** Match source -> badge */
function SourceBadge({ source }) {
  const map = {
    lldp: { bg: "bg-emerald-500/20", fg: "text-emerald-300", label: "LLDP" },
    datto_rmm: { bg: "bg-fuchsia-500/20", fg: "text-fuchsia-200", label: "DATTO" },
    mac_managed: { bg: "bg-cyan-500/20", fg: "text-cyan-300", label: "MAC" },
    mac_fdb_trunk: { bg: "bg-violet-500/20", fg: "text-violet-200", label: "FDB-TRUNK" },
    mac_manual: { bg: "bg-blue-500/20", fg: "text-blue-300", label: "MANUALE" },
    mac_oui: { bg: "bg-amber-500/20", fg: "text-amber-300", label: "OUI" },
    mac_unknown: { bg: "bg-neutral-500/20", fg: "text-neutral-300", label: "MAC?" },
  };
  const cfg = map[source] || map.mac_unknown;
  return (
    <span className={`px-1.5 py-0 rounded ${cfg.bg} ${cfg.fg} text-[9px] font-bold tracking-wider`}>
      {cfg.label}
    </span>
  );
}

export default function PortCableView({ p, switchIp, switchName, onClose, clientId, onRefresh }) {
  // ⚠️ React Rules of Hooks: tutti gli hooks DEVONO essere chiamati prima di qualsiasi early return.
  const [showBindModal, setShowBindModal] = useState(false);

  if (!p) return null;

  const isUp = p.oper === 1 && p.admin === 1;
  const isPoe = p.poe_status === 3;
  const isAdminDown = p.admin === 2;
  const n = p.neighbor;
  const remote = n ? remoteIconFor(n.remote_device_type, n.remote_sys_cap) : null;

  // Cable color by speed/status
  const cableColor = !isUp ? "#6b7280" : p.speed_mbps >= 10000 ? "#f59e0b" : p.speed_mbps >= 1000 ? "#10b981" : "#3b82f6";
  const cableAnimation = isUp && (p.rx_bps > 0 || p.tx_bps > 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      data-testid="port-cable-view-modal"
      onClick={onClose}
    >
      <div
        className="noc-panel relative w-full max-w-lg p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--bg-border)] pb-3">
          <div>
            <h3 className="text-lg font-bold">Vista Cavo · Porta {portLabel(p.name, p.idx)}</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono">{p.name}</p>
          </div>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] p-1" data-testid="port-cable-view-close" aria-label="Chiudi">
            <X size={18} />
          </button>
        </div>

        {/* Schema verticale */}
        <div className="flex flex-col items-stretch">

          {/* --- Blocco SWITCH --- */}
          <div className="relative">
            <div className="flex items-center gap-3 p-3 rounded-lg bg-gradient-to-br from-indigo-500/10 to-indigo-500/5 border border-indigo-400/30">
              <div className="w-10 h-10 rounded-md bg-indigo-500/20 border border-indigo-400/40 flex items-center justify-center flex-shrink-0">
                <LinkIcon size={18} className="text-indigo-300" weight="bold" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[9px] text-indigo-300/70 uppercase tracking-wider font-semibold">Switch locale</div>
                <div className="font-semibold text-sm truncate">{switchName || switchIp}</div>
                <div className="text-[10px] font-mono text-[var(--text-muted)]">{switchIp} · porta <span className="text-indigo-300 font-bold">{portLabel(p.name, p.idx)}</span></div>
              </div>
              <div className="flex flex-col items-end text-[10px] text-[var(--text-muted)] flex-shrink-0">
                {isUp && (
                  <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono text-[9px]">UP</span>
                )}
                {!isUp && !isAdminDown && (
                  <span className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 font-mono text-[9px]">DOWN</span>
                )}
                {isAdminDown && (
                  <span className="px-1.5 py-0.5 rounded bg-neutral-500/30 text-neutral-200 font-mono text-[9px]">ADMIN-DOWN</span>
                )}
                {isPoe && (
                  <span className="mt-1 px-1.5 py-0.5 rounded bg-amber-400/20 text-amber-200 font-mono text-[9px] flex items-center gap-0.5">
                    <Lightning size={8} weight="fill" /> PoE
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* --- CAVO animato --- */}
          <div className="relative flex justify-center" style={{ height: 90 }}>
            {/* Linea cavo */}
            <div
              className="absolute top-0 bottom-0 w-1 rounded"
              style={{
                background: cableColor,
                boxShadow: `0 0 8px ${cableColor}80`,
                opacity: isUp ? 1 : 0.4,
              }}
            />
            {/* Animazione traffico RX/TX */}
            {cableAnimation && (
              <>
                <div className="absolute left-1/2 -translate-x-[6px]" style={{ top: 4 }}>
                  <div className="w-1 h-2 bg-cyan-300 rounded animate-[slideDown_1.5s_linear_infinite]" />
                </div>
                <div className="absolute left-1/2 translate-x-[2px]" style={{ bottom: 4 }}>
                  <div className="w-1 h-2 bg-violet-300 rounded animate-[slideUp_1.5s_linear_infinite]" />
                </div>
              </>
            )}
            {/* Etichetta cavo (velocita' + traffico) */}
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-0.5">
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-[var(--bg-panel)] border" style={{ borderColor: cableColor, color: cableColor }}>
                {fmtSpeed(p.speed_mbps)}
              </span>
              {isUp && (
                <div className="flex items-center gap-2 text-[9px] font-mono bg-[var(--bg-panel)] rounded border border-[var(--bg-border)] px-2 py-0.5">
                  <span className="text-cyan-300 flex items-center gap-0.5"><ArrowDown size={9} weight="bold" /> {fmtBps(p.rx_bps)}</span>
                  <span className="text-violet-300 flex items-center gap-0.5"><ArrowUp size={9} weight="bold" /> {fmtBps(p.tx_bps)}</span>
                </div>
              )}
            </div>
          </div>

          {/* --- Blocco REMOTE DEVICE --- */}
          <div>
            {n && remote ? (
              <div className="flex items-center gap-3 p-3 rounded-lg bg-gradient-to-br from-cyan-500/10 to-cyan-500/5 border border-cyan-400/30">
                <div className="w-10 h-10 rounded-md border flex items-center justify-center flex-shrink-0" style={{ backgroundColor: `${remote.color}20`, borderColor: `${remote.color}60` }}>
                  <remote.Icon size={18} style={{ color: remote.color }} weight="bold" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[9px] uppercase tracking-wider font-semibold flex items-center gap-1" style={{ color: `${remote.color}dd` }}>
                    {remote.label}
                    <SourceBadge source={n.match_source} />
                  </div>
                  <div className="font-semibold text-sm truncate">
                    {n.remote_ip ? (
                      <Link to={`/devices/${encodeURIComponent(n.remote_ip)}`} className="hover:underline" style={{ color: remote.color }}>
                        {n.remote_device_name || n.remote_sys_name || n.remote_ip}
                      </Link>
                    ) : (
                      <span style={{ color: remote.color }}>{n.remote_device_name || n.remote_sys_name || "(sconosciuto)"}</span>
                    )}
                  </div>
                  <div className="text-[10px] font-mono text-[var(--text-muted)] break-all">
                    {n.remote_port_desc && <span>porta {n.remote_port_desc} </span>}
                    {n.remote_port_id && !n.remote_port_desc && <span>{n.remote_port_id} </span>}
                    {n.remote_ip && <span>· {n.remote_ip} </span>}
                    {!n.remote_ip && n.remote_chassis_id && <span>· {n.remote_chassis_id}</span>}
                  </div>
                  {n.remote_sys_desc && (
                    <div className="text-[9px] text-[var(--text-muted)] italic truncate mt-0.5">{n.remote_sys_desc}</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 p-3 rounded-lg bg-neutral-500/10 border border-neutral-500/30 border-dashed">
                <div className="w-10 h-10 rounded-md bg-neutral-500/20 border border-neutral-500/40 flex items-center justify-center flex-shrink-0">
                  <Plug size={18} className="text-neutral-400" />
                </div>
                <div className="flex-1">
                  <div className="text-[9px] text-neutral-400 uppercase tracking-wider font-semibold">Remote endpoint</div>
                  <div className="text-sm text-neutral-300">
                    {isAdminDown ? "Porta disabilitata amministrativamente" :
                     !isUp ? "Nessun cavo collegato / link down" :
                     "Dispositivo non identificato (nessun LLDP/MAC)"}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Dettagli tecnici inferiori */}
        <div className="grid grid-cols-2 gap-3 text-[11px] pt-2 border-t border-[var(--bg-border)]">
          <div className="col-span-2 flex items-center justify-between gap-2 pb-2 border-b border-[var(--bg-border)]">
            <div className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider font-semibold">Storia flap 24h</div>
            <PortFlapHistory deviceIp={switchIp} idx={p.idx} hours={24} width={200} />
          </div>
          <div>
            <div className="text-[9px] text-[var(--text-muted)] uppercase mb-0.5">Velocita' negoziata</div>
            <div className="font-mono font-semibold">{fmtSpeed(p.speed_mbps)}</div>
          </div>
          <div>
            <div className="text-[9px] text-[var(--text-muted)] uppercase mb-0.5">Ultimo cambio stato</div>
            <div className="font-mono font-semibold">{fmtDuration(p.last_change_s)}</div>
          </div>
          <div>
            <div className="text-[9px] text-[var(--text-muted)] uppercase mb-0.5">Traffico IN totale</div>
            <div className="font-mono font-semibold text-cyan-300">{fmtBytes(Number(p.in_octets || 0))}</div>
          </div>
          <div>
            <div className="text-[9px] text-[var(--text-muted)] uppercase mb-0.5">Traffico OUT totale</div>
            <div className="font-mono font-semibold text-violet-300">{fmtBytes(Number(p.out_octets || 0))}</div>
          </div>
          {isPoe && p.poe_power_used_w != null && (
            <div className="col-span-2">
              <div className="text-[9px] text-amber-400 uppercase mb-0.5 flex items-center gap-1"><Lightning size={9} weight="fill" /> PoE</div>
              <div className="font-mono font-semibold text-amber-200">
                {Number(p.poe_power_used_w).toFixed(1)} W · classe {Number(p.poe_class || 0) - 1}
              </div>
            </div>
          )}
          {p.alias && (
            <div className="col-span-2">
              <div className="text-[9px] text-[var(--text-muted)] uppercase mb-0.5">Descrizione/Alias</div>
              <div className="font-mono italic text-[var(--text-secondary)]">{p.alias}</div>
            </div>
          )}
        </div>

        {/* Footer suggerimento */}
        {(n?.match_source === "mac_oui" || n?.match_source === "mac_unknown") && (
          <div className="flex items-center justify-between gap-2 bg-amber-500/10 border border-amber-500/20 rounded p-2">
            <div className="text-[10px] text-amber-300/90 italic flex-1">
              {n?.match_source === "mac_oui"
                ? `🔍 Solo vendor identificato via OUI. Per nome+IP precisi: abilita LLDP sullo switch remoto, oppure...`
                : `⚠️ Vendor non identificato. Per ottenere nome+IP: abilita LLDP sullo switch remoto, oppure...`}
            </div>
            <button
              onClick={() => setShowBindModal(true)}
              className="h-7 px-3 text-xs font-semibold rounded-md bg-blue-600 text-white hover:bg-blue-700 whitespace-nowrap"
              data-testid="manual-bind-btn"
            >
              Associa manualmente
            </button>
          </div>
        )}
        {n?.match_source === "mac_fdb_trunk" && (
          <div className="text-[10px] text-violet-300/90 italic bg-violet-500/10 border border-violet-500/20 rounded p-2">
            🔗 Link trunk switch-to-switch dedotto via cross-correlation FDB. Per precisione 100% abilita LLDP su entrambi gli switch.
          </div>
        )}
        {n?.match_source === "mac_manual" && (
          <div className="text-[10px] text-blue-300/90 italic bg-blue-500/10 border border-blue-500/20 rounded p-2">
            ✋ Binding manuale impostato dall'admin. Persiste finche' non viene rimosso o sovrascritto da LLDP/MAC managed.
          </div>
        )}
      </div>

      {/* Manual MAC Binding Modal */}
      {showBindModal && (
        <ManualBindModal
          mac={n?.remote_chassis_id || ""}
          clientId={clientId}
          onClose={() => setShowBindModal(false)}
          onSaved={() => {
            setShowBindModal(false);
            if (onRefresh) onRefresh();
            onClose();
          }}
        />
      )}

      {/* Animations */}
      <style>{`
        @keyframes slideDown {
          0% { transform: translateY(-4px); opacity: 0; }
          30% { opacity: 1; }
          100% { transform: translateY(88px); opacity: 0; }
        }
        @keyframes slideUp {
          0% { transform: translateY(4px); opacity: 0; }
          30% { opacity: 1; }
          100% { transform: translateY(-88px); opacity: 0; }
        }
      `}</style>
    </div>
  );
}


// ===================================================================
// Manual MAC Binding Modal — input form per agganciare nome+IP a MAC
// ===================================================================
function ManualBindModal({ mac, clientId, onClose, onSaved }) {
  const [name, setName] = useState("");
  const [ip, setIp] = useState("");
  const [deviceType, setDeviceType] = useState("generic");
  const [alsoCreate, setAlsoCreate] = useState(true);
  const [saving, setSaving] = useState(false);
  const token = localStorage.getItem("noc_token");

  const macUpper = (mac || "").toUpperCase();
  const macValid = /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(macUpper);
  const ipValid = /^(\d{1,3}\.){3}\d{1,3}$/.test(ip.trim());
  const canSave = macValid && ipValid && name.trim().length >= 2 && !saving;

  const submit = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const r = await axios.post(
        `${API}/api/topology/mac-bindings`,
        {
          mac: macUpper,
          ip: ip.trim(),
          name: name.trim(),
          device_type: deviceType,
          client_id: clientId || "",
          also_create_managed_device: alsoCreate && Boolean(clientId),
        },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      const action = r.data.action === "created" ? "creato" : "aggiornato";
      toast.success(`Binding ${action}: ${name.trim()} (${ip.trim()}) → ${macUpper}`);
      if (onSaved) onSaved();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore salvataggio binding");
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/85 backdrop-blur-sm p-4"
      onClick={onClose}
      data-testid="manual-bind-modal"
    >
      <div
        className="noc-panel w-full max-w-md p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--bg-border)] pb-2">
          <h3 className="text-base font-bold">Associa dispositivo manualmente</h3>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] p-1" data-testid="manual-bind-close">
            <X size={18} />
          </button>
        </div>

        <div className="text-[11px] text-[var(--text-secondary)]">
          ARGUS non e' riuscito ad identificare il device su questa porta. Inserisci tu i dati: il MAC verra' agganciato in modo permanente.
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold">MAC (rilevato automaticamente)</label>
            <input
              type="text"
              value={macUpper}
              readOnly
              className={`w-full mt-0.5 h-8 px-2 text-xs font-mono rounded border ${macValid ? "border-[var(--bg-border)]" : "border-red-500/50"} bg-[var(--bg-surface)] text-[var(--text-primary)] cursor-not-allowed`}
              data-testid="manual-bind-mac-input"
            />
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold">Nome dispositivo *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Es. Switch02 HP 5130 52G"
              className="w-full mt-0.5 h-8 px-2 text-xs rounded border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] focus:outline-none focus:border-blue-500"
              data-testid="manual-bind-name-input"
            />
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold">Indirizzo IP *</label>
            <input
              type="text"
              value={ip}
              onChange={(e) => setIp(e.target.value)}
              placeholder="Es. 10.100.61.221"
              className={`w-full mt-0.5 h-8 px-2 text-xs font-mono rounded border ${ip && !ipValid ? "border-red-500/50" : "border-[var(--bg-border)]"} bg-[var(--bg-card)] text-[var(--text-primary)] focus:outline-none focus:border-blue-500`}
              data-testid="manual-bind-ip-input"
            />
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold">Tipo</label>
            <select
              value={deviceType}
              onChange={(e) => setDeviceType(e.target.value)}
              className="w-full mt-0.5 h-8 px-2 text-xs rounded border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)] focus:outline-none focus:border-blue-500"
              data-testid="manual-bind-type-select"
            >
              <option value="generic">Generico</option>
              <option value="server">Server</option>
              <option value="switch">Switch</option>
              <option value="firewall">Firewall</option>
              <option value="ap">Access Point</option>
              <option value="nas">NAS</option>
              <option value="printer">Stampante</option>
              <option value="camera">Camera IP</option>
              <option value="ups">UPS</option>
            </select>
          </div>

          {clientId && (
            <label className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)] cursor-pointer mt-2 select-none">
              <input
                type="checkbox"
                checked={alsoCreate}
                onChange={(e) => setAlsoCreate(e.target.checked)}
                className="rounded border-[var(--bg-border)]"
                data-testid="manual-bind-also-create"
              />
              <span>Crea anche il managed device in ARGUS (con questo IP) per attivare polling SNMP/ICMP</span>
            </label>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--bg-border)]">
          <button
            onClick={onClose}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"
            data-testid="manual-bind-cancel"
          >
            Annulla
          </button>
          <button
            onClick={submit}
            disabled={!canSave}
            className="h-8 px-4 text-xs font-semibold rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="manual-bind-save"
          >
            {saving ? "Salvataggio..." : "Salva e aggancia"}
          </button>
        </div>
      </div>
    </div>
  );
}

