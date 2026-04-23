/**
 * VendorDetailsPanel.js
 *
 * Modulare: renderizza la telemetria vendor-specific appropriata per il device
 * basandosi su profile_key. Supporta Synology, APC UPS / generic UPS, Fortinet,
 * HPE Comware, HP ProCurve, MikroTik, Cisco, QNAP, Zyxel.
 *
 * Uso:
 *   <VendorDetailsPanel deviceIp="10.100.61.35" />
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { HardDrives, Thermometer, BatteryMedium as Battery, Lightning, ShieldCheck, Pulse as Activity, Fan, Plugs, WarningCircle } from "@phosphor-icons/react";

// =======================  HELPERS  =======================
const severityColor = (v, warn, crit) => {
  if (typeof v !== "number") return "text-white/50";
  if (v >= crit) return "text-red-400";
  if (v >= warn) return "text-amber-400";
  return "text-emerald-400";
};

const synologyRaidLabel = (code) => {
  const map = { 1: "Normal", 2: "Repairing", 3: "Migrating", 4: "Expanding", 11: "Degraded", 12: "Crashed", 20: "Crashed" };
  return map[parseInt(code)] || `Code ${code}`;
};
const synologyDiskStatus = (code) => {
  const map = { 1: "Normal", 2: "Init", 3: "SysPart Failed", 4: "Crashed", 5: "Failed" };
  return map[parseInt(code)] || `?`;
};
const upsBattStatus = (code) => ({ 1: "Unknown", 2: "Normal", 3: "Low", 4: "Depleted" }[parseInt(code)] || "?");
const upsOutputSource = (code) => ({ 1: "Other", 2: "None", 3: "Normal", 4: "Bypass", 5: "On Battery", 6: "Booster", 7: "Reducer" }[parseInt(code)] || "?");

// =======================  SUB-PANELS  =======================

function Card({ title, icon: Icon, children, testid }) {
  return (
    <div className="bg-[#151522] border border-[#252535] rounded-lg p-4" data-testid={testid}>
      <div className="flex items-center gap-2 mb-3 pb-2 border-b border-[#252535]">
        {Icon && <Icon size={16} className="text-fuchsia-400" />}
        <h3 className="text-sm font-semibold text-white/80">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function Metric({ label, value, unit, colorClass = "text-white", small = false }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[11px] text-white/60">{label}</span>
      <span className={`${small ? "text-xs" : "text-sm"} font-mono ${colorClass}`}>
        {value === null || value === undefined ? "—" : value}
        {unit && value !== null && value !== undefined && <span className="text-white/40 text-[10px] ml-1">{unit}</span>}
      </span>
    </div>
  );
}

function SynologyPanel({ vm, thresholds }) {
  const raid = vm.raidStatus;
  const diskTemps = vm.diskTemperature || {};
  const diskStatuses = vm.diskStatus || {};
  const sysStatus = vm.systemStatus;
  const tCrit = thresholds?.disk_temp_crit_c || 55;
  const tWarn = thresholds?.disk_temp_warn_c || 45;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Card title="Sistema" icon={ShieldCheck} testid="vendor-synology-system">
        <Metric label="Model" value={vm.modelName} />
        <Metric label="Serial" value={vm.serialNumber} />
        <Metric label="DSM" value={vm.dsmVersion} />
        <Metric label="System Status"
          value={sysStatus === 1 ? "Normal" : sysStatus === 2 ? "FAILED" : "?"}
          colorClass={sysStatus === 2 ? "text-red-400 font-bold" : "text-emerald-400"}
        />
        <Metric label="Temperatura" value={vm.temperatureC} unit="°C" />
      </Card>

      <Card title="RAID" icon={HardDrives} testid="vendor-synology-raid">
        <Metric label="Stato"
          value={raid ? synologyRaidLabel(raid) : "—"}
          colorClass={parseInt(raid) === 1 ? "text-emerald-400" : parseInt(raid) >= 11 ? "text-red-400 font-bold" : "text-amber-400"}
        />
        {vm.raidName && <Metric label="Volume" value={vm.raidName} />}
        {vm.raidTotalSize && <Metric label="Size" value={Math.round(vm.raidTotalSize / 1e9)} unit="GB" />}
      </Card>

      <Card title="Dischi" icon={HardDrives} testid="vendor-synology-disks">
        <div className="space-y-2 text-[11px]">
          {Object.keys({ ...diskTemps, ...diskStatuses }).map((idx) => {
            const t = diskTemps[idx];
            const st = diskStatuses[idx];
            const tempColor = typeof t === "number" ? (t >= tCrit ? "text-red-400" : t >= tWarn ? "text-amber-400" : "text-emerald-400") : "text-white/50";
            const stColor = st === 1 ? "text-emerald-400" : st && st >= 3 ? "text-red-400" : "text-white/50";
            return (
              <div key={idx} className="flex items-center justify-between border-b border-[#1e1e2e] pb-1">
                <span className="text-white/60">Disk {idx}</span>
                <div className="flex items-center gap-3">
                  {st !== undefined && <span className={`font-mono ${stColor}`}>{synologyDiskStatus(st)}</span>}
                  {t !== undefined && <span className={`font-mono ${tempColor}`}>{t}°C</span>}
                </div>
              </div>
            );
          })}
          {Object.keys(diskTemps).length === 0 && Object.keys(diskStatuses).length === 0 && (
            <p className="text-white/30 italic">Nessun dato disco disponibile. Verifica polling SNMP.</p>
          )}
        </div>
      </Card>

      <Card title="CPU / RAM" icon={Activity} testid="vendor-synology-cpu">
        <Metric label="CPU User" value={vm.cpuUserUsage} unit="%" />
        <Metric label="CPU System" value={vm.cpuSystemUsage} unit="%" />
        {vm.memTotalReal && vm.memAvailReal && (
          <Metric label="RAM usata" value={Math.round(100 - (vm.memAvailReal / vm.memTotalReal) * 100)} unit="%" />
        )}
      </Card>
    </div>
  );
}

function UpsPanel({ vm, thresholds }) {
  const battStat = vm.upsBatteryStatus;
  const src = vm.upsOutputSource;
  const charge = vm.upsEstimatedChargeRemaining;
  const runtime = vm.upsEstimatedMinutesRemaining;
  const bCrit = thresholds?.battery_pct_crit || thresholds?.battery_crit_pct || 30;
  const bWarn = thresholds?.battery_pct_warn || thresholds?.battery_warn_pct || 50;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Card title="Batteria" icon={Battery} testid="vendor-ups-battery">
        <Metric label="Stato"
          value={battStat ? upsBattStatus(battStat) : "—"}
          colorClass={parseInt(battStat) === 2 ? "text-emerald-400" : parseInt(battStat) >= 3 ? "text-red-400 font-bold" : "text-white/50"}
        />
        <Metric label="Carica"
          value={charge}
          unit="%"
          colorClass={severityColor(-parseFloat(charge || 100), -bCrit, -100) || "text-emerald-400"}
        />
        <Metric label="Runtime residuo" value={runtime} unit="min" />
        <Metric label="Tensione batteria" value={vm.upsBatteryVoltage ? (vm.upsBatteryVoltage / 10).toFixed(1) : null} unit="V" />
        <Metric label="Temperatura batt." value={vm.upsBatteryTemperature} unit="°C" />
      </Card>

      <Card title="Alimentazione" icon={Lightning} testid="vendor-ups-power">
        <Metric label="Fonte output"
          value={src ? upsOutputSource(src) : "—"}
          colorClass={parseInt(src) === 3 ? "text-emerald-400" : parseInt(src) === 5 ? "text-red-400 font-bold" : "text-amber-400"}
        />
        <Metric label="Load output" value={vm.upsOutputPercentLoad || vm.apcUpsOutputLoad} unit="%" />
        <Metric label="Tensione input" value={vm.upsInputVoltage || vm.apcUpsInputVoltage} unit="V" />
        <Metric label="Frequenza input" value={vm.upsInputFrequency ? (vm.upsInputFrequency / 10).toFixed(1) : null} unit="Hz" />
        <Metric label="Seconds on battery" value={vm.upsSecondsOnBattery} unit="s" />
      </Card>

      <Card title="Identificazione" icon={ShieldCheck} testid="vendor-ups-id">
        <Metric label="Manufacturer" value={vm.upsIdentManufacturer || vm.apcUpsName} />
        <Metric label="Model" value={vm.upsIdentModel} />
        <Metric label="Firmware" value={vm.upsIdentUpsFirmware} />
      </Card>
    </div>
  );
}

function FortinetPanel({ vm }) {
  const vpns = vm.fgVpnTunnelStatus || {};
  const haSync = vm.fgHaStatsSyncStatus;
  const cpu = vm.fgSysCpuUsage;
  const mem = vm.fgSysMemUsage;
  const sessions = vm.fgSysSesCount;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Card title="Sistema" icon={Activity} testid="vendor-fortinet-system">
        <Metric label="CPU" value={cpu} unit="%" colorClass={severityColor(cpu, 70, 90)} />
        <Metric label="Memoria" value={mem} unit="%" colorClass={severityColor(mem, 80, 95)} />
        <Metric label="Sessioni attive" value={sessions} />
        <Metric label="HA cluster"
          value={haSync !== undefined ? (parseInt(haSync) === 1 ? "In-sync" : "OUT-OF-SYNC") : "—"}
          colorClass={parseInt(haSync) === 1 ? "text-emerald-400" : "text-red-400 font-bold"}
        />
      </Card>

      <Card title="VPN Tunnels" icon={ShieldCheck} testid="vendor-fortinet-vpns">
        {Object.keys(vpns).length === 0 ? (
          <p className="text-white/30 italic text-xs">Nessun tunnel VPN configurato o in polling.</p>
        ) : (
          <div className="space-y-1 text-[11px]">
            {Object.entries(vpns).map(([name, st]) => (
              <div key={name} className="flex items-center justify-between border-b border-[#1e1e2e] py-1">
                <span className="text-white/70 truncate max-w-[200px]">{name}</span>
                <span className={`font-mono ${parseInt(st) === 2 ? "text-emerald-400" : "text-red-400"}`}>
                  {parseInt(st) === 2 ? "UP" : "DOWN"}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function SwitchPanel({ vm, thresholds, profileKey }) {
  const cpuMetric = vm.h3cEntityExtCpuUsage || vm.cpuUtil || vm.zyxelCpuCurrent;
  const memMetric = vm.h3cEntityExtMemUsage;
  const tempMetric = vm.h3cEntityExtTemperature;
  const fanStates = vm.h3cFanState || vm.fanStatus || {};
  const psuStates = vm.h3cPowerState || vm.psuStatus || {};
  const cpu = typeof cpuMetric === "object" ? Math.max(...Object.values(cpuMetric).filter(v => typeof v === "number")) : cpuMetric;
  const mem = typeof memMetric === "object" ? Math.max(...Object.values(memMetric).filter(v => typeof v === "number")) : memMetric;
  const temp = typeof tempMetric === "object" ? Math.max(...Object.values(tempMetric).filter(v => typeof v === "number")) : tempMetric;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Card title="Performance" icon={Activity} testid="vendor-switch-perf">
        <Metric label="CPU" value={cpu ? Math.round(cpu) : null} unit="%"
          colorClass={severityColor(cpu, thresholds?.cpu_warn_pct || 70, thresholds?.cpu_crit_pct || 90)} />
        <Metric label="Memoria" value={mem ? Math.round(mem) : null} unit="%"
          colorClass={severityColor(mem, thresholds?.mem_warn_pct || 80, thresholds?.mem_crit_pct || 95)} />
        <Metric label="Temperatura" value={temp ? Math.round(temp) : null} unit="°C"
          colorClass={severityColor(temp, thresholds?.temp_warn_c || 55, thresholds?.temp_crit_c || 70)} />
      </Card>

      <Card title="Hardware" icon={Plugs} testid="vendor-switch-hardware">
        <div className="space-y-2 text-[11px]">
          {Object.entries(psuStates).map(([idx, st]) => (
            <div key={`psu${idx}`} className="flex items-center justify-between">
              <span className="text-white/60">PSU {idx}</span>
              <span className={`font-mono ${parseInt(st) <= 2 ? "text-emerald-400" : "text-red-400"}`}>
                {parseInt(st) <= 2 ? "OK" : `FAULT (${st})`}
              </span>
            </div>
          ))}
          {Object.entries(fanStates).map(([idx, st]) => (
            <div key={`fan${idx}`} className="flex items-center justify-between">
              <span className="text-white/60">Fan {idx}</span>
              <span className={`font-mono ${parseInt(st) <= 2 ? "text-emerald-400" : "text-red-400"}`}>
                {parseInt(st) <= 2 ? "OK" : `FAULT (${st})`}
              </span>
            </div>
          ))}
          {Object.keys(psuStates).length === 0 && Object.keys(fanStates).length === 0 && (
            <p className="text-white/30 italic">Hardware detail non disponibile per {profileKey || "profilo sconosciuto"}.</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function GenericPanel({ vm }) {
  if (!vm || Object.keys(vm).length === 0) {
    return (
      <div className="text-center py-12 text-white/40 text-sm">
        <WarningCircle size={32} className="mx-auto mb-2 text-white/20" />
        Nessuna metrica vendor-specific raccolta per questo device.
        <p className="mt-2 text-[11px]">Verifica che il profilo sia assegnato e che il connector sia v3.4.4+.</p>
      </div>
    );
  }
  return (
    <Card title="Metriche raw" icon={Activity} testid="vendor-generic-raw">
      <div className="space-y-1 text-[10px] font-mono">
        {Object.entries(vm).map(([k, v]) => {
          const val = typeof v === "object" && v !== null ? JSON.stringify(v).slice(0, 80) : String(v);
          return (
            <div key={k} className="flex items-start justify-between py-0.5 border-b border-[#1e1e2e]">
              <span className="text-white/60 truncate max-w-[150px]">{k}</span>
              <span className="text-emerald-400 truncate max-w-[300px] text-right">{val}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// =======================  MAIN  =======================

export function VendorDetailsPanel({ deviceIp }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    setLoading(true);
    axios.get(`${API}/devices/by-ip/${encodeURIComponent(deviceIp)}/vendor-details`)
      .then((r) => { setData(r.data); setError(null); })
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000); // refresh every 30s
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceIp]);

  if (loading && !data) return <div className="p-6 text-center text-white/50 text-xs" data-testid="vendor-details-loading">Caricamento telemetria vendor...</div>;
  if (error) return <div className="p-6 text-red-400 text-sm" data-testid="vendor-details-error">Errore: {error}</div>;
  if (!data) return null;

  const vm = data.vendor_metrics || {};
  const pk = data.profile_key;
  const thresholds = data.profile?.thresholds;

  return (
    <div className="p-4 space-y-3" data-testid="vendor-details-panel">
      <div className="flex items-center justify-between pb-2 border-b border-[#252535]">
        <div>
          <h2 className="text-base font-semibold text-white">{data.name}</h2>
          <p className="text-[11px] text-white/40 font-mono">
            {deviceIp} · {data.profile?.label || pk || "Nessun profilo"} · last poll: {data.last_poll || "—"}
          </p>
        </div>
        <button
          onClick={load}
          className="px-2 py-1 text-[10px] font-mono rounded bg-fuchsia-500/10 hover:bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-500/30"
          data-testid="vendor-details-refresh"
        >
          Refresh
        </button>
      </div>

      {pk === "synology_dsm" ? (
        <SynologyPanel vm={vm} thresholds={thresholds} />
      ) : pk === "apc_ups" || pk === "generic_ups" || pk === "xanto_ups" ? (
        <UpsPanel vm={vm} thresholds={thresholds} />
      ) : pk === "fortinet_fortigate" ? (
        <FortinetPanel vm={vm} />
      ) : pk === "hpe_comware" || pk === "hp_procurve" || pk === "cisco_ios" || pk === "mikrotik_routeros" || pk === "zyxel_nebula" || pk === "ubiquiti_unifi" ? (
        <SwitchPanel vm={vm} thresholds={thresholds} profileKey={pk} />
      ) : (
        <GenericPanel vm={vm} />
      )}
    </div>
  );
}

export default VendorDetailsPanel;
