import { useState, useEffect } from "react";
import axios from "axios";
import {
  Desktop, Cpu, HardDrives, Thermometer, Info, MapPin, Package, Shield, Barcode,
  Calendar, Globe, ArrowsClockwise, Warning, CheckCircle, CircleNotch,
} from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

function Field({ label, value, mono = false, highlight = false }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex items-start justify-between gap-3 py-1 border-b border-[var(--bg-border)]/50">
      <span className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)] whitespace-nowrap pt-0.5">{label}</span>
      <span className={`text-xs text-right ${mono ? "font-mono" : ""} ${highlight ? "text-cyan-300 font-semibold" : "text-[var(--text-primary)]"}`}>
        {String(value)}
      </span>
    </div>
  );
}

function Section({ title, icon: Icon, children, testid, color = "text-[var(--text-primary)]" }) {
  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3" data-testid={testid}>
      <div className={`flex items-center gap-2 mb-2 ${color}`}>
        {Icon && <Icon size={16} weight="duotone" />}
        <h4 className="text-xs font-bold uppercase tracking-wide">{title}</h4>
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function fmtDate(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" });
  } catch {
    return iso;
  }
}

function fmtDateTime(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function DeviceInfoCard({ deviceIp, onClose = null, compact = false }) {
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const token = localStorage.getItem("noc_token");

  const fetchCard = () => {
    setLoading(true);
    setError(null);
    axios
      .get(`${API}/api/devices/by-ip/${deviceIp}/info-card`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setCard(r.data))
      .catch((e) => setError(e.response?.data?.detail || "Errore caricamento scheda"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchCard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceIp]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 text-[var(--text-secondary)]" data-testid="device-info-card-loading">
        <CircleNotch size={20} className="animate-spin mr-2" />
        Caricamento scheda device...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-300 text-sm" data-testid="device-info-card-error">
        <Warning size={16} className="inline mr-2" />
        {error}
      </div>
    );
  }

  if (!card) return null;

  const id = card.identity || {};
  const fw = card.firmware || {};
  const st = card.status || {};
  const hw = card.hardware || {};
  const net = card.network || {};
  const lc = card.lifecycle;
  const loc = card.location || {};
  const fwComp = fw.compliance;

  const sourcesBadges = {
    connector: { label: "Connector", color: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" },
    managed_devices: { label: "Manuale", color: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40" },
    cmdb: { label: "CMDB", color: "bg-indigo-500/20 text-indigo-300 border-indigo-500/40" },
    lifecycle: { label: "Lifecycle", color: "bg-violet-500/20 text-violet-300 border-violet-500/40" },
    redfish_ilo: { label: "iLO Redfish", color: "bg-orange-500/20 text-orange-300 border-orange-500/40" },
    device_profile: { label: "Profilo", color: "bg-blue-500/20 text-blue-300 border-blue-500/40" },
    entity_mib: { label: "ENTITY-MIB", color: "bg-teal-500/20 text-teal-300 border-teal-500/40" },
    sys_descr_parser: { label: "Parser SNMP", color: "bg-slate-500/20 text-slate-300 border-slate-500/40" },
  };

  return (
    <div className="space-y-3" data-testid="device-info-card">
      {/* Header riepilogo */}
      <div className="rounded-xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/5 to-transparent p-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <div className="flex items-center gap-2 mb-1">
              <Desktop size={18} className="text-cyan-400" weight="duotone" />
              <h3 className="text-base font-bold text-[var(--text-primary)]">
                {id.hostname || id.ip}
              </h3>
              {st.reachable === true && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                  <CheckCircle size={10} weight="fill" /> ONLINE
                </span>
              )}
              {st.reachable === false && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-red-500/20 text-red-300 border border-red-500/40">
                  <Warning size={10} weight="fill" /> OFFLINE
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-[var(--text-secondary)] flex-wrap">
              <span className="font-mono">{id.ip}</span>
              {id.mac_primary && <span className="font-mono">MAC: {id.mac_primary}</span>}
              {id.vendor && <span>· <strong className="text-[var(--text-primary)]">{id.vendor}</strong></span>}
              {id.model && <span>{id.model}</span>}
              {id.serial_number && <span className="font-mono text-violet-300">S/N: {id.serial_number}</span>}
            </div>
            {card.client?.name && (
              <div className="text-xs text-cyan-400 mt-1">Cliente: {card.client.name}</div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={fetchCard} title="Aggiorna" className="p-2 rounded-md hover:bg-white/5 text-[var(--text-secondary)]" data-testid="device-info-card-refresh">
              <ArrowsClockwise size={14} />
            </button>
            {onClose && (
              <button onClick={onClose} className="px-3 py-1 text-xs rounded-md border border-[var(--bg-border)] hover:bg-white/5" data-testid="device-info-card-close">
                Chiudi
              </button>
            )}
          </div>
        </div>
        {/* Data sources badges */}
        <div className="flex items-center gap-1 flex-wrap mt-3">
          <span className="text-[10px] uppercase text-[var(--text-secondary)]">Dati raccolti da:</span>
          {(card.data_sources || []).map((s) => {
            const b = sourcesBadges[s] || { label: s, color: "bg-slate-500/20 text-slate-300" };
            return (
              <span key={s} className={`px-2 py-0.5 text-[10px] rounded border ${b.color}`} data-testid={`source-${s}`}>
                {b.label}
              </span>
            );
          })}
        </div>
      </div>

      {!compact && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {/* Identity */}
          <Section title="Identità" icon={Info} testid="info-section-identity" color="text-cyan-300">
            <Field label="Hostname" value={id.hostname} mono />
            <Field label="IP" value={id.ip} mono highlight />
            <Field label="MAC primario" value={id.mac_primary} mono />
            <Field label="MAC totali" value={id.mac_count || null} />
            <Field label="Vendor" value={id.vendor} highlight />
            <Field label="Modello" value={id.model} highlight />
            <Field label="Serial Number" value={id.serial_number} mono />
            <Field label="Asset Tag" value={id.asset_tag} mono />
            <Field label="Tipo device" value={id.device_type} />
            <Field label="Profilo" value={id.profile_key} />
            <Field label="OS Family" value={id.os_family} />
          </Section>

          {/* Firmware & Security */}
          <Section title="Firmware & CVE" icon={Shield} testid="info-section-firmware" color="text-violet-300">
            <Field label="Firmware" value={fw.current} mono highlight />
            <Field label="BIOS" value={fw.bios} mono />
            {fwComp && (
              <>
                <Field label="Compliance" value={fwComp.status?.toUpperCase()} highlight />
                <Field label="CVE aperte" value={fwComp.cve_count} />
                <Field label="Severity" value={fwComp.severity} />
              </>
            )}
            {fwComp?.advisory_url && (
              <div className="pt-2">
                <a href={fwComp.advisory_url} target="_blank" rel="noopener noreferrer"
                   className="text-[11px] text-cyan-400 hover:underline">
                  → Vendor advisory
                </a>
              </div>
            )}
          </Section>

          {/* Status */}
          <Section title="Stato Live" icon={ArrowsClockwise} testid="info-section-status" color="text-emerald-300">
            <Field label="Reachable" value={st.reachable === true ? "Sì" : st.reachable === false ? "No" : null} />
            <Field label="Monitor tipo" value={st.monitor_type} />
            <Field label="Ultimo poll" value={fmtDateTime(st.last_poll)} />
            <Field label="Ultimo update" value={fmtDateTime(st.last_update)} />
            <Field label="Uptime (gg)" value={st.uptime_days} />
            <Field label="Connector" value={st.connector_hostname} mono />
            {st.unreachable_since && <Field label="Offline da" value={fmtDateTime(st.unreachable_since)} />}
          </Section>

          {/* Hardware */}
          <Section title="Hardware" icon={Cpu} testid="info-section-hardware" color="text-orange-300">
            <Field label="CPU %" value={hw.cpu_usage} />
            <Field label="Memoria %" value={hw.memory_usage} />
            <Field label="Temperatura °C" value={hw.temperature} />
            <Field label="Power (W)" value={hw.power_watts} />
            <Field label="Fan count" value={hw.fan_count} />
            <Field label="PSU count" value={hw.psu_count} />
            <Field label="Sensori temp." value={hw.temp_sensor_count} />
            <Field label="Dischi (storage)" value={hw.storage_drive_count} />
            <Field label="DIMM RAM" value={hw.memory_dimm_count} />
            <Field label="NIC count" value={hw.nic_count} />
            {hw.firewall_sessions != null && <Field label="Sessioni FW" value={hw.firewall_sessions.toLocaleString("it-IT")} />}
            <Field label="Flash usage %" value={hw.firewall_flash_usage_pct} />
          </Section>

          {/* Network */}
          <Section title="Rete" icon={Globe} testid="info-section-network" color="text-sky-300">
            <Field label="Interfacce" value={net.interfaces_count || null} />
            <Field label="Porte aperte" value={(net.open_ports || []).length ? net.open_ports.join(", ") : null} mono />
            <Field label="Ping (ms)" value={net.ping_ms} />
            {net.ping_stats?.avg != null && <Field label="Ping avg" value={`${net.ping_stats.avg}ms`} />}
            {net.ping_stats?.packet_loss != null && <Field label="Packet loss" value={`${net.ping_stats.packet_loss}%`} />}
            <Field label="Web Console" value={net.web_console_url} mono />
            <Field label="Porta WebUI" value={net.web_console_port} />
            <Field label="Web title" value={net.web_console_title} />
            <Field label="SNMP version" value={net.snmp_version} />
            <Field label="SNMP port" value={net.snmp_port} />
          </Section>

          {/* Lifecycle */}
          {lc && (
            <Section title="Lifecycle & Warranty" icon={Calendar} testid="info-section-lifecycle" color="text-indigo-300">
              <Field label="Acquisto" value={fmtDate(lc.purchase_date)} />
              <Field label="Fine garanzia" value={fmtDate(lc.warranty_end)} highlight={lc.risk_band === "high"} />
              <Field label="Fine manutenzione" value={fmtDate(lc.maintenance_end)} />
              <Field label="EOL" value={fmtDate(lc.eol_date)} />
              <Field label="EOSL" value={fmtDate(lc.eosl_date)} />
              <Field label="Risk score" value={lc.risk_score} highlight={lc.risk_band === "high"} />
              <Field label="Risk band" value={lc.risk_band?.toUpperCase()} highlight={lc.risk_band === "high"} />
              <Field label="Criticità" value={lc.criticality} />
              <Field label="Contratto" value={lc.contract_number} mono />
              <Field label="Supporto tier" value={lc.vendor_support_tier} />
            </Section>
          )}

          {/* Location */}
          {Object.values(loc).some((v) => v != null && v !== "") && (
            <Section title="Ubicazione" icon={MapPin} testid="info-section-location" color="text-rose-300">
              <Field label="Site" value={loc.site} />
              <Field label="Edificio" value={loc.building} />
              <Field label="Piano" value={loc.floor} />
              <Field label="Stanza" value={loc.room} />
              <Field label="Rack" value={loc.rack} />
              <Field label="U" value={loc.rack_unit} />
              <Field label="Responsabile" value={loc.owner} />
              <Field label="Costo mensile €" value={loc.cost_monthly} />
              {loc.notes && <Field label="Note" value={loc.notes} />}
            </Section>
          )}

          {/* Vendor metrics */}
          {card.vendor_metrics_summary?.count > 0 && (
            <Section title="Metriche Vendor" icon={HardDrives} testid="info-section-vendor-metrics" color="text-amber-300">
              <div className="text-xs text-[var(--text-secondary)] mb-1">
                {card.vendor_metrics_summary.count} metriche raccolte
              </div>
              <div className="flex flex-wrap gap-1">
                {card.vendor_metrics_summary.keys.map((k) => (
                  <span key={k} className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-[10px] font-mono text-amber-200">
                    {k}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </div>
      )}

      {/* Raw sys_descr (collapsible debug) */}
      {card.sys_descr_raw && (
        <details className="rounded-lg border border-[var(--bg-border)] bg-black/20 p-2">
          <summary className="text-[10px] uppercase text-[var(--text-secondary)] cursor-pointer">
            sys_descr raw (debug SNMP)
          </summary>
          <pre className="text-[10px] font-mono text-slate-300 mt-2 whitespace-pre-wrap break-all">
            {card.sys_descr_raw}
          </pre>
        </details>
      )}
    </div>
  );
}
