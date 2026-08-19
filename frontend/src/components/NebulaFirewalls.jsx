/**
 * NebulaFirewalls — firewall Zyxel Nebula in cima alla WAN.
 *
 * Riga singola compatta (nome preciso del prodotto + IP pubblico + stato).
 * Al click apre una SCHEDA DISPOSITIVO con TUTTE le informazioni ricevute da
 * Nebula, ben leggibili:
 *  - identita' (modello, S/N, MAC, firmware, dev id, sito)
 *  - stato + metriche live (CPU / Memoria / Sessioni)
 *  - interfacce WAN (IP pubblico, gateway, netmask, DNS, VLAN per interfaccia)
 *  - interfacce LAN (IP per interfaccia / port-group)
 *  - porte fisiche (velocita' + stato link)
 *  - traffico per interfaccia (tx / rx)
 *  - regole NAT / porte aperte (virtual server + 1:1)
 *
 * Dati: GET /api/clients/{clientId}/zyxel/devices (filtra device_type==='firewall').
 * Si autonasconde se il cliente non ha firewall Nebula. Refresh 30s.
 */
import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import {
  ShieldCheck, Globe, Cpu, Database, Pulse, ArrowsClockwise, PlugsConnected,
   ArrowLineUp, ArrowLineDown, NetworkSlash, CaretRight, LockKey,
  ListMagnifyingGlass, Circle,
} from "@phosphor-icons/react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const API = process.env.REACT_APP_BACKEND_URL;
const REFRESH_INTERVAL_MS = 30000;

const C = { online: "#34C759", offline: "#FF3B30", warn: "#FFCC00", muted: "#8E8E93", blue: "#0A84FF" };

function fmtBytes(n) {
  const v = Number(n) || 0;
  if (v <= 0) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(v) / Math.log(1024)));
  return `${(v / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

const norm = (s) => String(s || "").toLowerCase().replace(/[:-]/g, "");
function productName(fw) {
  const nameIsMac = fw.name && fw.mac && norm(fw.name) === norm(fw.mac);
  return fw.model || (!nameIsMac ? fw.name : null) || "Firewall Zyxel";
}

/** Riga chiave→valore leggibile. */
function KV({ k, v, mono = true, color }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 border-b border-[var(--bg-border)]/50">
      <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] shrink-0">{k}</span>
      <span className={`text-[11px] text-right truncate ${mono ? "font-mono" : ""}`} style={{ color: color || "var(--text-primary)" }}>
        {v ?? "—"}
      </span>
    </div>
  );
}

function Section({ title, count, children }) {
  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)]/40 p-3">
      <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-cyan-400 mb-2">
        {title}{count != null ? ` (${count})` : ""}
      </p>
      {children}
    </div>
  );
}

function WanConnectivity({ wt }) {
  const [geo, setGeo] = useState(null);
  useEffect(() => {
    let alive = true;
    if (!wt?.public_ip) return;
    axios.get(`${API}/api/external-monitor/geo-ip/${encodeURIComponent(wt.public_ip)}`)
      .then((r) => alive && setGeo(r.data && !r.data.error ? r.data : null))
      .catch(() => {});
    return () => { alive = false; };
  }, [wt?.public_ip]);

  const r = wt.result || {};
  const st = r.status;
  const sc = st === "online" ? C.online : st === "offline" ? C.offline : st ? C.warn : C.muted;
  const gwOk = r.gateway_ping?.reachable;

  return (
    <Section title="Connettività WAN · ISP">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2" data-testid="nebula-fw-wan-conn">
        <div className="rounded border border-[var(--bg-border)] p-2">
          <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">IP pubblico</p>
          <p className="text-[12px] font-mono font-bold" style={{ color: sc }}>{wt.public_ip}</p>
        </div>
        <div className="rounded border border-[var(--bg-border)] p-2">
          <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">Stato</p>
          <p className="text-[12px] font-bold uppercase" style={{ color: sc }}>{st || "…"}</p>
        </div>
        <div className="rounded border border-[var(--bg-border)] p-2">
          <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">Latenza</p>
          <p className="text-[12px] font-mono font-bold text-[var(--text-primary)]">{r.ping?.latency_ms != null ? `${r.ping.latency_ms}ms` : "—"}</p>
        </div>
        <div className="rounded border border-[var(--bg-border)] p-2">
          <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">Packet loss</p>
          <p className="text-[12px] font-mono font-bold" style={{ color: (r.ping?.packet_loss_pct || 0) > 0 ? C.warn : C.online }}>
            {r.ping?.packet_loss_pct != null ? `${r.ping.packet_loss_pct}%` : "—"}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
        {r.gateway_ip && <KV k="Gateway ISP" v={`${r.gateway_ip}${r.gateway_ping?.latency_ms != null ? ` · ${r.gateway_ping.latency_ms}ms` : ""}`} color={gwOk ? C.online : C.offline} />}
        {geo && <KV k="ISP" v={geo.isp} mono={false} color={C.online} />}
        {geo && <KV k="ASN" v={geo.asn_name ? `${geo.asn} (${geo.asn_name})` : geo.asn} />}
        {geo && <KV k="Località" v={[geo.city, geo.region, geo.country_code].filter(Boolean).join(", ")} mono={false} />}
      </div>
    </Section>
  );
}

function FirewallDetail({ fw, wt }) {
  const online = fw.online_status === "ONLINE";
  const stColor = online ? C.online : C.offline;
  const ports = Array.isArray(fw.ports) ? fw.ports : [];
  const traffic = Array.isArray(fw.traffic) ? fw.traffic : [];
  const nat = Array.isArray(fw.nat_rules) ? fw.nat_rules : [];
  const wan = Array.isArray(fw.wan_interfaces) ? fw.wan_interfaces : [];
  const lan = Array.isArray(fw.lan_interfaces) ? fw.lan_interfaces : [];
  const clients = Array.isArray(fw.clients) ? fw.clients : [];
  const vpn = fw.vpn_status || {};
  const vpnCount = (vpn.sites?.length || 0) + (vpn.gateways?.length || 0) + (vpn.remote_aps?.length || 0);
  const lineUp = fw.line_state === "up";

  // Event logs on-demand (Nebula ne restituisce migliaia → caricamento manuale).
  const [logs, setLogs] = useState(null);
  const [logsBusy, setLogsBusy] = useState(false);
  const [logsErr, setLogsErr] = useState(null);
  const loadLogs = async () => {
    setLogsBusy(true); setLogsErr(null);
    try {
      const token = localStorage.getItem("noc_token");
      const r = await axios.get(
        `${API}/api/clients/${encodeURIComponent(fw.client_id)}/zyxel/devices/${encodeURIComponent(fw.dev_id)}/event-logs?minutes=60&limit=150`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setLogs(r.data);
    } catch (e) {
      setLogsErr(e.response?.data?.detail || "Errore nel caricamento dei log");
    } finally { setLogsBusy(false); }
  };

  return (
    <div className="space-y-3">
      {/* Stato sintetico */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full font-bold uppercase tracking-wider"
              style={{ color: stColor, background: `${stColor}1A` }} data-testid="nebula-fw-status">
          <PlugsConnected size={12} weight="bold" /> {online ? "Online" : (fw.online_status || "Offline")}
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded border"
              style={{ borderColor: lineUp ? `${C.online}40` : `${C.warn}40`, background: lineUp ? `${C.online}0F` : `${C.warn}0F` }}
              data-testid="nebula-fw-public-ip">
          <Globe size={12} weight="bold" style={{ color: lineUp ? C.online : C.warn }} />
          IP pubblico: <span className="font-mono font-bold">{wt?.public_ip || fw.public_ip || "—"}</span>
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
          Linea WAN: <span className="font-bold uppercase" style={{ color: lineUp ? C.online : C.muted }}>{fw.line_state || "n/d"}</span>
        </span>
      </div>

      {/* Connettività WAN reale (da target Monitor WAN collegato) */}
      {wt && <WanConnectivity wt={wt} />}

      {/* Metriche live */}
      {online && (
        <div className="grid grid-cols-3 gap-2" data-testid="nebula-fw-metrics">
          {[
            { icon: Cpu, label: "CPU", val: fw.cpu_usage, unit: "%", warn: 70, crit: 90 },
            { icon: Database, label: "Memoria", val: fw.mem_usage, unit: "%", warn: 80, crit: 95 },
            { icon: Pulse, label: "Sessioni", val: fw.sessions, unit: "", warn: 50000, crit: 100000 },
          ].map((m) => {
            const has = m.val !== null && m.val !== undefined;
            const col = !has ? C.muted : m.val >= m.crit ? C.offline : m.val >= m.warn ? C.warn : C.online;
            const MIcon = m.icon;
            return (
              <div key={m.label} className="rounded-lg border border-[var(--bg-border)] p-2 text-center">
                <MIcon size={14} weight="bold" style={{ color: col }} className="mx-auto mb-1" />
                <p className="font-mono font-bold text-[16px]" style={{ color: col }}>{has ? `${m.val}${m.unit}` : "—"}</p>
                <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)]">{m.label}</p>
              </div>
            );
          })}
        </div>
      )}

      {/* Identita' */}
      <Section title="Identità dispositivo">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
          <KV k="Modello" v={fw.model} mono={false} />
          <KV k="Nome (Nebula)" v={fw.name} />
          <KV k="S/N" v={fw.sn} />
          <KV k="MAC" v={fw.mac} />
          <KV k="Dev ID" v={fw.dev_id} color="var(--text-muted)" />
          <KV k="Sito" v={fw.site_name || fw.site_id} mono={false} />
          <KV k="Firmware" v={fw.firmware?.current} color={fw.firmware?.latest && fw.firmware.latest !== fw.firmware.current ? C.warn : undefined} />
          <KV k="Firmware disp." v={fw.firmware?.latest} color={fw.firmware?.latest && fw.firmware.latest !== fw.firmware.current ? C.warn : "var(--text-muted)"} />
        </div>
      </Section>

      {/* Interfacce WAN */}
      {wan.length > 0 && (
        <Section title="Interfacce WAN" count={wan.length}>
          <div className="space-y-2" data-testid="nebula-fw-wan-ifs">
            {wan.map((w, i) => (
              <div key={i} className="rounded border border-[var(--bg-border)] p-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono font-bold text-[11px] text-[var(--text-primary)]">{w.interface || `wan${i + 1}`}</span>
                  <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase"
                        style={{ color: w.enabled ? C.online : C.muted, background: w.enabled ? `${C.online}18` : `${C.muted}18` }}>
                    {w.enabled ? "attiva" : "disattiva"} · {w.ipv4_type || "?"}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-x-6">
                  <KV k="IP pubblico" v={w.public_ip} color={C.online} />
                  <KV k="Gateway" v={w.gateway} />
                  <KV k="Netmask" v={w.netmask} />
                  <KV k="VLAN" v={w.vlan} />
                  <KV k="DNS" v={(w.dns || []).join(", ") || "—"} />
                  <KV k="Port group" v={w.port_group} />
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Interfacce LAN */}
      {lan.length > 0 && (
        <Section title="Interfacce LAN" count={lan.length}>
          <div className="space-y-2" data-testid="nebula-fw-lan-ifs">
            {lan.map((l, i) => (
              <div key={i} className="rounded border border-[var(--bg-border)] p-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono font-bold text-[11px] text-[var(--text-primary)]">{l.interface || `lan${i + 1}`}</span>
                  <div className="flex items-center gap-1">
                    {l.guest_zone && <span className="text-[8px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold uppercase">guest</span>}
                    <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase"
                          style={{ color: l.enabled ? C.online : C.muted, background: l.enabled ? `${C.online}18` : `${C.muted}18` }}>
                      {l.enabled ? "attiva" : "disattiva"} · {l.ipv4_type || "?"}
                    </span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-x-6">
                  <KV k="IP" v={l.ip} color={C.blue} />
                  <KV k="Netmask" v={l.netmask} />
                  <KV k="Port group" v={l.port_group} />
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Porte fisiche */}
      {ports.length > 0 && (
        <Section title="Porte fisiche" count={ports.length}>
          <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-1.5" data-testid="nebula-fw-ports">
            {ports.map((p, i) => {
              const up = p.status === "up";
              const col = up ? C.online : C.muted;
              return (
                <div key={`${p.port}-${i}`} className="flex flex-col items-center px-1 py-1.5 rounded border"
                     style={{ borderColor: `${col}40`, background: `${col}12` }}
                     title={`Porta ${p.port}${p.group ? ` · ${p.group}` : ""} · ${p.speed || "no link"}`}
                     data-testid={`nebula-fw-port-${p.port}`}>
                  <span className="text-[11px] font-bold" style={{ color: col }}>{p.port}</span>
                  <span className="text-[7px] text-center leading-tight" style={{ color: up ? "var(--text-primary)" : C.muted }}>
                    {up ? (p.speed || "up") : "down"}
                  </span>
                  {p.group && <span className="text-[6px] text-[var(--text-muted)] truncate max-w-full">{p.group}</span>}
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Traffico per interfaccia */}
      {traffic.length > 0 && (
        <Section title="Traffico per interfaccia" count={traffic.length}>
          <div className="space-y-0.5" data-testid="nebula-fw-traffic">
            <div className="flex items-center justify-between text-[8px] uppercase tracking-wider text-[var(--text-muted)] pb-1">
              <span>Interfaccia</span>
              <span className="flex gap-4"><span>TX ▲</span><span>RX ▼</span></span>
            </div>
            {traffic.map((t, i) => (
              <div key={`${t.interface}-${i}`} className="flex items-center justify-between text-[11px] py-1 border-b border-[var(--bg-border)]/50">
                <span className="font-mono text-[var(--text-primary)]">{t.interface || "—"}</span>
                <span className="flex items-center gap-4 font-mono">
                  <span className="inline-flex items-center gap-1" style={{ color: C.online }}><ArrowLineUp size={10} />{fmtBytes(t.tx)}</span>
                  <span className="inline-flex items-center gap-1" style={{ color: C.blue }}><ArrowLineDown size={10} />{fmtBytes(t.rx)}</span>
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* NAT / porte aperte */}
      <Section title="NAT / Porte aperte" count={nat.length}>
        {nat.length === 0 ? (
          <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1">
            <NetworkSlash size={12} /> Nessuna regola NAT configurata sul firewall.
          </p>
        ) : (
          <div className="space-y-1" data-testid="nebula-fw-nat-list">
            {nat.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px] px-2 py-1.5 rounded border border-[var(--bg-border)]">
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: r.enabled ? C.online : C.muted }} />
                <span className="font-bold text-[var(--text-primary)] truncate min-w-[70px] max-w-[160px]">{r.name || r.type}</span>
                <span className="text-[8px] px-1 py-0.5 rounded bg-[var(--bg-card)] text-[var(--text-muted)] uppercase shrink-0">
                  {r.type === "virtual_server" ? "port fwd" : "1:1"}{r.protocol ? ` · ${r.protocol}` : ""}
                </span>
                <span className="ml-auto font-mono text-[var(--text-muted)] flex items-center gap-1 truncate">
                  <span style={{ color: C.warn }}>{r.public_ip || "*"}{r.public_ports?.length ? `:${r.public_ports.join(",")}` : ""}</span>
                  <CaretRight size={9} />
                  <span style={{ color: C.blue }}>{r.server_ip || "*"}{r.server_ports?.length ? `:${r.server_ports.join(",")}` : ""}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Client connessi */}
      {clients.length > 0 && (
        <Section title={`Client connessi · ${fw.clients_online ?? clients.filter(c => c.status === "ONLINE").length} online`} count={clients.length}>
          <div className="max-h-64 overflow-y-auto -mx-1 px-1" data-testid="nebula-fw-clients">
            <div className="grid grid-cols-[16px_1fr_1fr_auto] gap-x-2 text-[8px] uppercase tracking-wider text-[var(--text-muted)] pb-1 sticky top-0 bg-[var(--bg-card)]">
              <span></span><span>IP</span><span>Host / Vendor</span><span>VLAN</span>
            </div>
            {clients.map((c, i) => {
              const on = c.status === "ONLINE";
              const host = c.hostname && c.hostname !== c.mac ? c.hostname : (c.vendor || c.mac);
              return (
                <div key={`${c.mac}-${i}`} className="grid grid-cols-[16px_1fr_1fr_auto] gap-x-2 items-center text-[10px] py-1 border-b border-[var(--bg-border)]/40"
                     data-testid={`nebula-fw-client-${c.mac}`} title={`${c.mac} · ${c.vendor || ""} · ${c.os || ""}`}>
                  <Circle size={8} weight="fill" style={{ color: on ? C.online : C.muted }} />
                  <span className="font-mono text-[var(--text-primary)] truncate">{c.ip || "—"}</span>
                  <span className="truncate text-[var(--text-primary)]">{host}</span>
                  <span className="font-mono text-[var(--text-muted)] text-right">{c.vlan ?? "—"}</span>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Stato VPN */}
      <Section title="VPN" count={vpnCount}>
        {vpnCount === 0 ? (
          <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1">
            <LockKey size={12} /> Nessun tunnel VPN attivo sul sito.
          </p>
        ) : (
          <div className="space-y-2 text-[10px]" data-testid="nebula-fw-vpn">
            {[["Site-to-Site", vpn.sites], ["Gateway", vpn.gateways], ["Remote AP", vpn.remote_aps]].map(([lbl, arr]) =>
              (arr && arr.length > 0) ? (
                <div key={lbl}>
                  <p className="text-[8px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{lbl} ({arr.length})</p>
                  {arr.map((t, i) => (
                    <div key={i} className="flex items-center justify-between px-2 py-1 rounded border border-[var(--bg-border)] mb-0.5">
                      <span className="font-bold text-[var(--text-primary)] truncate">{t.name || t.peerName || t.remoteName || `#${i + 1}`}</span>
                      <span className="font-mono text-[var(--text-muted)]">{t.status || t.connectionStatus || "—"}</span>
                    </div>
                  ))}
                </div>
              ) : null
            )}
          </div>
        )}
      </Section>

      {/* Event Logs (on-demand) */}
      <Section title="Event Logs (ultima ora)">
        {!logs && !logsBusy && !logsErr && (
          <button onClick={loadLogs}
                  className="flex items-center gap-1.5 text-[10px] px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 transition-colors"
                  data-testid="nebula-fw-logs-load">
            <ListMagnifyingGlass size={13} weight="bold" /> Carica event-log del firewall
          </button>
        )}
        {logsBusy && <p className="text-[10px] text-[var(--text-muted)] flex items-center gap-1"><ArrowsClockwise size={12} className="animate-spin" /> Caricamento…</p>}
        {logsErr && <p className="text-[10px] text-red-400">{logsErr}</p>}
        {logs && (
          <div data-testid="nebula-fw-logs">
            <div className="flex items-center justify-between mb-1">
              <p className="text-[8px] text-[var(--text-muted)]">
                {logs.count} eventi (su {logs.total_window} negli ultimi {logs.minutes} min)
              </p>
              <button onClick={loadLogs} disabled={logsBusy} className="text-[var(--text-muted)] hover:text-cyan-300" title="Aggiorna" data-testid="nebula-fw-logs-refresh">
                <ArrowsClockwise size={11} weight="bold" className={logsBusy ? "animate-spin" : ""} />
              </button>
            </div>
            <div className="max-h-64 overflow-y-auto space-y-0.5">
              {logs.logs.map((l, i) => (
                <div key={i} className="text-[9px] px-2 py-1 rounded border border-[var(--bg-border)]/50 font-mono">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[8px] px-1 rounded uppercase shrink-0"
                          style={{ color: l.category === "Dropped" ? C.warn : "var(--text-muted)", background: "var(--bg-card)" }}>{l.category}</span>
                    <span className="text-[var(--text-muted)] text-[8px]">{l.timestamp ? new Date(l.timestamp).toLocaleTimeString("it-IT") : ""}</span>
                  </div>
                  <p className="text-[var(--text-primary)] mt-0.5 break-words">{l.message}</p>
                  {(l.src_ip || l.dst_ip) && (
                    <p className="text-[var(--text-muted)] mt-0.5">
                      {l.src_ip}{l.src_port ? `:${l.src_port}` : ""} <CaretRight size={8} className="inline" /> {l.dst_ip}{l.dst_port ? `:${l.dst_port}` : ""}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>
    </div>
  );
}

export default function NebulaFirewalls({ clientId, wanTargets = [] }) {
  const [firewalls, setFirewalls] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [openId, setOpenId] = useState(null);

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

  if (!loaded || firewalls.length === 0) return null;

  const active = firewalls.find((f) => f.dev_id === openId) || null;

  return (
    <div className="space-y-1.5" data-testid="nebula-firewalls">
      <div className="flex items-center justify-between">
        <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">Firewall Nebula ({firewalls.length})</p>
        <button onClick={fetchData} disabled={loading}
                className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors disabled:opacity-50"
                title="Aggiorna (auto 30s)" data-testid="nebula-firewalls-refresh">
          <ArrowsClockwise size={11} weight="bold" className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Righe compatte cliccabili */}
      <div className="space-y-1">
        {firewalls.map((fw) => {
          const online = fw.online_status === "ONLINE";
          const sc = online ? C.online : C.offline;
          const wt = wanTargets.find((t) => t.linked_nebula_dev_id && t.linked_nebula_dev_id === fw.dev_id);
          const pubIp = wt?.public_ip || fw.public_ip;
          const wr = wt?.result;
          const ispOk = wr?.gateway_ping?.reachable;
          return (
            <div
              key={fw.dev_id}
              onClick={() => setOpenId(fw.dev_id)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg border text-[11px] cursor-pointer hover:brightness-125 transition-all"
              style={{ borderColor: `${sc}30`, background: `${sc}06` }}
              data-testid={`nebula-firewall-${fw.dev_id}`}
              title="Clicca per la scheda dispositivo completa"
            >
              <ShieldCheck size={14} weight="bold" style={{ color: sc }} />
              <span className="font-bold text-[var(--text-primary)]" data-testid="nebula-fw-name">{productName(fw)}</span>
              {pubIp && <span className="font-mono text-[var(--text-muted)] text-[10px]">{pubIp}</span>}
              <span className="text-[8px] px-1 rounded bg-cyan-500/10 text-cyan-400">NEBULA</span>
              {wr?.ping?.latency_ms != null && <span className="font-mono text-[var(--text-muted)] text-[10px]">{wr.ping.latency_ms}ms</span>}
              {wr?.gateway_ping && (
                <span className="text-[8px] px-1.5 py-0.5 rounded font-bold" style={{ color: ispOk ? C.online : C.offline, background: ispOk ? `${C.online}12` : `${C.offline}12` }}>
                  ISP {ispOk ? "OK" : "DOWN"}
                </span>
              )}
              <span className="ml-auto font-mono font-bold uppercase" style={{ color: sc }}>{online ? "online" : (fw.online_status || "offline")}</span>
              <CaretRight size={12} weight="bold" className="text-[var(--text-muted)]" />
            </div>
          );
        })}
      </div>

      {/* Scheda dispositivo completa */}
      <Dialog open={!!active} onOpenChange={(o) => !o && setOpenId(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="nebula-fw-detail-dialog">
          {active && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2 text-[var(--text-primary)]">
                  <ShieldCheck size={20} weight="bold" style={{ color: active.online_status === "ONLINE" ? C.online : C.offline }} />
                  <span>{productName(active)}</span>
                  <span className="text-[10px] font-normal text-[var(--text-muted)]">· {active.site_name || active.site_id}</span>
                </DialogTitle>
              </DialogHeader>
              <FirewallDetail fw={active} wt={wanTargets.find((t) => t.linked_nebula_dev_id && t.linked_nebula_dev_id === active.dev_id)} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
