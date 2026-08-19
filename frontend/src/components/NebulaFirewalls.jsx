/**
 * NebulaFirewalls — scheda firewall Zyxel Nebula fissata in cima alla WAN.
 *
 * Legge i firewall sincronizzati da Nebula per il cliente:
 *   GET /api/clients/{clientId}/zyxel/devices  → { devices, count }
 * e mostra, per ogni firewall (device_type === "firewall"):
 *   - identita': nome, modello, S/N, MAC
 *   - stato online + stato linea WAN + IP pubblico
 *   - firmware (current/latest)
 *   - metriche live: CPU / Memoria / Sessioni
 *   - traffico interfacce (tx/rx)
 *   - stato porte (portNumber/portGroup/linkSpeed)
 *   - regole NAT (virtual server / 1:1)
 *
 * Si autonasconde se il cliente non ha firewall Nebula.
 */
import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import {
  ShieldCheck, Globe, Cpu, Database, Pulse, ArrowsClockwise,
  PlugsConnected, ArrowLineUp, ArrowLineDown, Swap, CaretDown, CaretRight,
} from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;
const REFRESH_INTERVAL_MS = 30000;

const C = {
  online: "#34C759", offline: "#FF3B30", warn: "#FFCC00", muted: "#8E8E93",
};

/** Byte → stringa human (KB/MB/GB). Null/0 → "0 B". */
function fmtBytes(n) {
  const v = Number(n) || 0;
  if (v <= 0) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(v) / Math.log(1024)));
  return `${(v / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

function FirewallCard({ fw }) {
  const [showNat, setShowNat] = useState(false);
  const online = fw.online_status === "ONLINE";
  const stColor = online ? C.online : C.offline;
  const ports = Array.isArray(fw.ports) ? fw.ports : [];
  const traffic = Array.isArray(fw.traffic) ? fw.traffic : [];
  const nat = Array.isArray(fw.nat_rules) ? fw.nat_rules : [];
  const lineUp = fw.line_state === "up";

  // Su Nebula spesso name === MAC: in tal caso usa il modello come titolo leggibile.
  const norm = (s) => String(s || "").toLowerCase().replace(/[:-]/g, "");
  const nameIsMac = fw.name && fw.mac && norm(fw.name) === norm(fw.mac);
  const title = (!fw.name || nameIsMac) ? (fw.model || "Firewall Zyxel") : fw.name;

  return (
    <div
      className="rounded-lg border p-3 space-y-2.5"
      style={{ borderColor: `${stColor}40`, background: `${stColor}0A` }}
      data-testid={`nebula-firewall-${fw.dev_id}`}
    >
      {/* Header: identita' + stato */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <ShieldCheck size={18} weight="bold" style={{ color: stColor }} />
          <div className="min-w-0">
            <p className="text-[12px] font-bold text-[var(--text-primary)] truncate" data-testid="nebula-fw-name">
              {title}
            </p>
            <p className="text-[9px] text-[var(--text-muted)] truncate">
              {fw.model} · {fw.site_name || fw.site_id}
            </p>
          </div>
        </div>
        <span
          className="text-[8px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider shrink-0"
          style={{ color: stColor, background: `${stColor}1A` }}
          data-testid="nebula-fw-status"
        >
          {online ? "Online" : (fw.online_status || "Offline")}
        </span>
      </div>

      {/* IP pubblico + stato linea WAN */}
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <span
          className="inline-flex items-center gap-1 px-2 py-1 rounded border"
          style={{ borderColor: lineUp ? `${C.online}40` : `${C.warn}40`, background: lineUp ? `${C.online}0F` : `${C.warn}0F` }}
          data-testid="nebula-fw-public-ip"
        >
          <Globe size={12} weight="bold" style={{ color: lineUp ? C.online : C.warn }} />
          <span className="text-[var(--text-muted)]">IP pubblico:</span>
          <span className="font-mono font-bold text-[var(--text-primary)]">{fw.public_ip || "—"}</span>
        </span>
        <span className="inline-flex items-center gap-1 text-[9px]">
          <PlugsConnected size={11} weight="bold" style={{ color: lineUp ? C.online : C.muted }} />
          <span className="text-[var(--text-muted)]">Linea WAN:</span>
          <span className="font-bold uppercase" style={{ color: lineUp ? C.online : C.muted }}>
            {fw.line_state || "n/d"}
          </span>
        </span>
      </div>

      {/* Identita' hardware */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[9px]">
        <div className="flex justify-between gap-2">
          <span className="text-[var(--text-muted)]">S/N</span>
          <span className="font-mono text-[var(--text-primary)] truncate" data-testid="nebula-fw-sn">{fw.sn || "—"}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-[var(--text-muted)]">MAC</span>
          <span className="font-mono text-[var(--text-primary)] truncate">{fw.mac || "—"}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-[var(--text-muted)]">Firmware</span>
          <span className="font-mono text-[var(--text-primary)] truncate">
            {fw.firmware?.current || "—"}
            {fw.firmware?.latest && fw.firmware.latest !== fw.firmware.current && (
              <span style={{ color: C.warn }}> → {fw.firmware.latest}</span>
            )}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-[var(--text-muted)]">Dev ID</span>
          <span className="font-mono text-[var(--text-muted)] truncate">{fw.dev_id}</span>
        </div>
      </div>

      {/* Metriche live: solo se online */}
      {online && (
        <div className="grid grid-cols-3 gap-1.5">
          {[
            { icon: Cpu, label: "CPU", val: fw.cpu_usage, unit: "%", warn: 70, crit: 90 },
            { icon: Database, label: "Memoria", val: fw.mem_usage, unit: "%", warn: 80, crit: 95 },
            { icon: Pulse, label: "Sessioni", val: fw.sessions, unit: "", warn: 50000, crit: 100000 },
          ].map((m) => {
            const v = m.val;
            const has = v !== null && v !== undefined;
            const col = !has ? C.muted : v >= m.crit ? C.offline : v >= m.warn ? C.warn : C.online;
            const MIcon = m.icon;
            return (
              <div key={m.label} className="rounded border border-[var(--bg-border)] p-1.5 text-center"
                   data-testid={`nebula-fw-metric-${m.label.toLowerCase()}`}>
                <MIcon size={12} weight="bold" style={{ color: col }} className="mx-auto mb-0.5" />
                <p className="font-mono font-bold text-[12px]" style={{ color: col }}>
                  {has ? `${v}${m.unit}` : "—"}
                </p>
                <p className="text-[7px] uppercase tracking-wider text-[var(--text-muted)]">{m.label}</p>
              </div>
            );
          })}
        </div>
      )}

      {/* Stato porte */}
      {ports.length > 0 && (
        <div>
          <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Porte ({ports.length})</p>
          <div className="flex flex-wrap gap-1" data-testid="nebula-fw-ports">
            {ports.map((p, i) => {
              const up = p.status === "up";
              const col = up ? C.online : C.muted;
              return (
                <span
                  key={`${p.port}-${i}`}
                  className="inline-flex flex-col items-center px-1.5 py-1 rounded border text-[8px] leading-tight min-w-[38px]"
                  style={{ borderColor: `${col}40`, background: `${col}12` }}
                  title={`${p.port}${p.group ? ` · ${p.group}` : ""} · ${p.speed || "no link"}`}
                  data-testid={`nebula-fw-port-${p.port}`}
                >
                  <span className="font-bold" style={{ color: col }}>{p.port}</span>
                  <span className="text-[7px] text-[var(--text-muted)]">{up ? (p.speed || "up") : "down"}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Traffico interfacce */}
      {traffic.length > 0 && (
        <div>
          <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)] mb-1">Traffico interfacce</p>
          <div className="space-y-0.5" data-testid="nebula-fw-traffic">
            {traffic.map((t, i) => (
              <div key={`${t.interface}-${i}`} className="flex items-center justify-between text-[9px]">
                <span className="font-mono text-[var(--text-primary)]">{t.interface || "wan"}</span>
                <span className="flex items-center gap-2 text-[var(--text-muted)]">
                  <span className="inline-flex items-center gap-0.5"><ArrowLineUp size={9} style={{ color: C.online }} />{fmtBytes(t.tx)}</span>
                  <span className="inline-flex items-center gap-0.5"><ArrowLineDown size={9} style={{ color: "#0A84FF" }} />{fmtBytes(t.rx)}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Regole NAT (collassabile) */}
      {nat.length > 0 && (
        <div>
          <button
            onClick={() => setShowNat((s) => !s)}
            className="flex items-center gap-1 text-[8px] uppercase tracking-widest text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
            data-testid="nebula-fw-nat-toggle"
          >
            {showNat ? <CaretDown size={9} weight="bold" /> : <CaretRight size={9} weight="bold" />}
            <Swap size={10} weight="bold" /> NAT ({nat.length})
          </button>
          {showNat && (
            <div className="mt-1 space-y-0.5" data-testid="nebula-fw-nat-list">
              {nat.map((r, i) => (
                <div key={i} className="flex items-center justify-between gap-2 text-[8px] px-1.5 py-1 rounded border border-[var(--bg-border)]">
                  <span className="flex items-center gap-1 min-w-0">
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: r.enabled ? C.online : C.muted }} />
                    <span className="font-bold text-[var(--text-primary)] truncate">{r.name || r.type}</span>
                  </span>
                  <span className="font-mono text-[var(--text-muted)] truncate">
                    {r.public_ip || "*"}{r.public_ports?.length ? `:${r.public_ports.join(",")}` : ""} → {r.server_ip || "*"}{r.server_ports?.length ? `:${r.server_ports.join(",")}` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function NebulaFirewalls({ clientId }) {
  const [firewalls, setFirewalls] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const token = localStorage.getItem("noc_token");
      const res = await axios.get(
        `${API}/api/clients/${encodeURIComponent(clientId)}/zyxel/devices`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const devs = Array.isArray(res.data?.devices) ? res.data.devices : [];
      setFirewalls(devs.filter((d) => d.device_type === "firewall"));
    } catch (e) {
      // endpoint assente/deploy parziale → nasconde silenziosamente
      setFirewalls([]);
    } finally {
      setLoaded(true);
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    const id = setInterval(fetchData, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchData]);

  // Autonasconde se nessun firewall Nebula per il cliente
  if (!loaded || firewalls.length === 0) return null;

  return (
    <div className="space-y-1.5" data-testid="nebula-firewalls">
      <div className="flex items-center justify-between">
        <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">
          Firewall Nebula ({firewalls.length})
        </p>
        <button
          onClick={fetchData}
          disabled={loading}
          className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors disabled:opacity-50"
          title="Aggiorna (auto 30s)"
          data-testid="nebula-firewalls-refresh"
        >
          <ArrowsClockwise size={11} weight="bold" className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <div className="space-y-2">
        {firewalls.map((fw) => (
          <FirewallCard key={fw.dev_id} fw={fw} />
        ))}
      </div>
    </div>
  );
}
