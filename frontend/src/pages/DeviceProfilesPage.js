import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  Cpu, Cube, CheckCircle, PencilSimple, ArrowCounterClockwise,
  MagnifyingGlass, X, WarningCircle,
} from "@phosphor-icons/react";

/**
 * DeviceProfilesPage — Library dei profili auto-configurazione device.
 * - 10 profili seed (HP, Synology, QNAP, Fortinet, UniFi, Zyxel, APC UPS, Cisco, Dell, generic)
 * - Override editabili per admin (thresholds, porte, OID, API endpoints)
 * - Fingerprint tester (incolla sysDescr + sysObjectID → dice che profilo è)
 */

const FAMILY_META = {
  switch:      { icon: Cube,  color: "#60a5fa", label: "Switch" },
  firewall:    { icon: Cube,  color: "#f59e0b", label: "Firewall" },
  nas:         { icon: Cube,  color: "#10b981", label: "NAS" },
  ups:         { icon: Cube,  color: "#a855f7", label: "UPS" },
  unifi:       { icon: Cube,  color: "#06b6d4", label: "UniFi" },
  server_oob:  { icon: Cpu,   color: "#ef4444", label: "Server OOB" },
  generic:     { icon: Cube,  color: "#64748b", label: "Generico" },
};

export default function DeviceProfilesPage() {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterFamily, setFilterFamily] = useState("all");
  const [selected, setSelected] = useState(null);
  const [showFingerprint, setShowFingerprint] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/device-profiles`);
      setProfiles(res.data?.profiles || []);
    } catch (e) {
      toast.error("Errore caricamento profili: " + (e.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = profiles.filter(p => {
    if (filterFamily !== "all" && p.family !== filterFamily) return false;
    if (search) {
      const q = search.toLowerCase();
      return (p.label || "").toLowerCase().includes(q)
          || (p.vendor || "").toLowerCase().includes(q)
          || (p.key || "").toLowerCase().includes(q);
    }
    return true;
  });

  const families = Array.from(new Set(profiles.map(p => p.family)));

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="device-profiles-page">
      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight flex items-center gap-2">
            <Cpu size={22} weight="bold" className="text-indigo-400" />
            Device Profiles
            <span className="text-[10px] font-mono text-white/40 border border-white/10 rounded px-1.5 py-0.5 ml-2">
              {profiles.length} vendor
            </span>
          </h1>
          <p className="text-[var(--text-muted)] text-xs mt-1">
            Auto-configurazione SNMP, OID e web-console per multi-vendor. I nuovi device vengono classificati automaticamente tramite <code className="text-indigo-300">sysObjectID</code> + <code className="text-indigo-300">sysDescr</code>.
          </p>
        </div>
        <button
          onClick={() => setShowFingerprint(true)}
          className="shrink-0 px-3 py-2 rounded-md bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 text-[11px] font-bold inline-flex items-center gap-1.5"
          data-testid="open-fingerprint-tester"
        >
          <MagnifyingGlass size={13} />
          Tester fingerprint
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-sm">
          <MagnifyingGlass size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            type="text"
            placeholder="Cerca vendor, label, key..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-7 pr-3 py-1.5 rounded-md bg-[var(--bg-panel)] border border-[var(--bg-border)] text-[12px] text-white placeholder-white/30 focus:border-indigo-500 outline-none"
            data-testid="profile-search"
          />
        </div>
        <select
          value={filterFamily}
          onChange={e => setFilterFamily(e.target.value)}
          className="px-2.5 py-1.5 rounded-md bg-[var(--bg-panel)] border border-[var(--bg-border)] text-[11px] text-white focus:border-indigo-500 outline-none"
          data-testid="profile-family-filter"
        >
          <option value="all">Tutte le famiglie</option>
          {families.map(f => (
            <option key={f} value={f}>{FAMILY_META[f]?.label || f}</option>
          ))}
        </select>
      </div>

      {/* Grid */}
      {loading ? (
        <div className="text-center py-12 text-white/40">Caricamento...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map(p => <ProfileCard key={p.key} profile={p} onOpen={() => setSelected(p)} />)}
          {filtered.length === 0 && (
            <div className="col-span-full text-center py-8 text-white/40 text-sm">
              Nessun profilo corrisponde ai filtri.
            </div>
          )}
        </div>
      )}

      {selected && <ProfileDetailModal profile={selected} onClose={() => setSelected(null)} onRefresh={load} />}
      {showFingerprint && <FingerprintTesterModal onClose={() => setShowFingerprint(false)} />}
    </div>
  );
}

/* ---------------- PROFILE CARD ---------------- */

function ProfileCard({ profile, onOpen }) {
  const meta = FAMILY_META[profile.family] || FAMILY_META.generic;
  const Icon = meta.icon;
  const snmp = profile.snmp || {};
  const wc = profile.web_console || {};
  const oidsCount = Object.keys(profile.oids || {}).length;
  const hasApi = profile.api_endpoints && Object.keys(profile.api_endpoints).length > 0;
  return (
    <button
      onClick={onOpen}
      className="group text-left bg-[var(--bg-panel)] border border-[var(--bg-border)] hover:border-indigo-500/40 rounded-lg p-4 transition-all"
      data-testid={`profile-card-${profile.key}`}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-10 h-10 rounded-md flex items-center justify-center flex-shrink-0"
          style={{ background: `${meta.color}15`, border: `1px solid ${meta.color}40` }}
        >
          <Icon size={20} weight="bold" style={{ color: meta.color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-[13px] font-bold text-white truncate">{profile.vendor}</span>
            {profile._has_overrides && (
              <span className="text-[8px] font-bold bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded uppercase">
                custom
              </span>
            )}
          </div>
          <p className="text-[11px] text-white/60 truncate" title={profile.label}>{profile.label}</p>
          <p className="text-[9px] text-white/30 font-mono mt-0.5">{profile.key}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 text-[9px] font-mono">
        <span className="px-1.5 py-0.5 rounded bg-white/5 text-white/50">SNMP {snmp.version || "?"}:{snmp.port || "?"}</span>
        <span className="px-1.5 py-0.5 rounded bg-white/5 text-white/50">Web {wc.scheme || "?"}:{wc.port || "?"}</span>
        <span className="px-1.5 py-0.5 rounded bg-white/5 text-white/50">{oidsCount} OID</span>
        {hasApi && <span className="px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300">API</span>}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {(profile.capabilities || []).slice(0, 4).map(c => (
          <span key={c} className="text-[8px] uppercase tracking-wider px-1 text-white/40">{c.replace(/_/g, " ")}</span>
        ))}
      </div>
    </button>
  );
}

/* ---------------- DETAIL / EDIT MODAL ---------------- */

function ProfileDetailModal({ profile, onClose, onRefresh }) {
  const [editing, setEditing] = useState(false);
  const [thresholds, setThresholds] = useState(JSON.stringify(profile.thresholds || {}, null, 2));
  const [snmp, setSnmp] = useState(JSON.stringify(profile.snmp || {}, null, 2));
  const [webConsole, setWebConsole] = useState(JSON.stringify(profile.web_console || {}, null, 2));
  const [pollingInterval, setPollingInterval] = useState(profile.polling_interval_seconds || 60);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const body = {};
      try { body.thresholds = JSON.parse(thresholds); } catch { toast.error("JSON thresholds non valido"); setSaving(false); return; }
      try { body.snmp = JSON.parse(snmp); } catch { toast.error("JSON SNMP non valido"); setSaving(false); return; }
      try { body.web_console = JSON.parse(webConsole); } catch { toast.error("JSON web_console non valido"); setSaving(false); return; }
      body.polling_interval_seconds = Number(pollingInterval) || 60;
      await axios.put(`${API}/device-profiles/${profile.key}/override`, body);
      toast.success("Override salvato");
      setEditing(false);
      onRefresh();
      onClose();
    } catch (e) {
      toast.error("Errore salvataggio: " + (e.response?.data?.detail || e.message));
    } finally { setSaving(false); }
  };

  const reset = async () => {
    if (!window.confirm(`Ripristinare i valori di default per ${profile.label}?`)) return;
    try {
      await axios.delete(`${API}/device-profiles/${profile.key}/override`);
      toast.success("Override rimosso");
      onRefresh();
      onClose();
    } catch (e) {
      toast.error("Errore reset: " + (e.response?.data?.detail || e.message));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        className="bg-[#0d0d12] border border-[var(--bg-border)] rounded-xl w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}
        data-testid={`profile-modal-${profile.key}`}
      >
        <div className="flex items-start justify-between gap-3 p-5 border-b border-[var(--bg-border)]">
          <div>
            <h2 className="font-bold text-white text-lg">{profile.vendor}</h2>
            <p className="text-[11px] text-white/50 mt-0.5">{profile.label}</p>
            <p className="text-[10px] text-white/30 font-mono mt-0.5">key: {profile.key}</p>
          </div>
          <div className="flex items-center gap-1.5">
            {profile._has_overrides && (
              <button onClick={reset} className="p-1.5 rounded hover:bg-amber-500/10 text-amber-300 text-[11px] inline-flex items-center gap-1" title="Ripristina default" data-testid="reset-override-btn">
                <ArrowCounterClockwise size={13} /> Reset
              </button>
            )}
            {!editing && (
              <button onClick={() => setEditing(true)} className="p-1.5 rounded hover:bg-indigo-500/10 text-indigo-300 text-[11px] inline-flex items-center gap-1" data-testid="edit-profile-btn">
                <PencilSimple size={13} /> Modifica
              </button>
            )}
            <button onClick={onClose} className="p-1.5 rounded hover:bg-white/5 text-white/50" data-testid="close-profile-modal">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <p className="text-[12px] text-white/70 leading-relaxed">{profile.description}</p>

          {/* Fingerprint */}
          <Section label="Fingerprint (auto-detection)">
            <div className="space-y-1 text-[11px] text-white/70 font-mono">
              {(profile.fingerprint?.sysobjectid_prefixes || []).map((p, i) => (
                <div key={`oid-${i}`}>
                  sysObjectID starts with <span className="text-cyan-300">{p}</span>
                </div>
              ))}
              {(profile.fingerprint?.sysdescr_patterns || []).map((p, i) => (
                <div key={`dsc-${i}`}>
                  sysDescr matches <span className="text-emerald-300">/{p}/i</span>
                </div>
              ))}
              {!(profile.fingerprint?.sysobjectid_prefixes?.length || profile.fingerprint?.sysdescr_patterns?.length) && (
                <div className="text-white/30">Nessun fingerprint (fallback profile)</div>
              )}
            </div>
          </Section>

          {/* SNMP */}
          <Section label="SNMP" editable={editing}>
            {editing
              ? <JsonArea value={snmp} onChange={setSnmp} testId="edit-snmp" />
              : <KeyValueGrid data={profile.snmp} />}
          </Section>

          {/* Web Console */}
          <Section label="Web Console" editable={editing}>
            {editing
              ? <JsonArea value={webConsole} onChange={setWebConsole} testId="edit-webconsole" />
              : <KeyValueGrid data={profile.web_console} />}
          </Section>

          {/* Thresholds */}
          <Section label="Soglie Alert" editable={editing}>
            {editing
              ? <JsonArea value={thresholds} onChange={setThresholds} testId="edit-thresholds" />
              : <KeyValueGrid data={profile.thresholds} />}
          </Section>

          {/* Polling */}
          <Section label="Intervallo Polling (sec)" editable={editing}>
            {editing
              ? <input type="number" value={pollingInterval} onChange={e => setPollingInterval(e.target.value)}
                  className="bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2.5 py-1 text-[12px] w-32 text-white" data-testid="edit-polling" />
              : <span className="text-[12px] text-white font-mono">{profile.polling_interval_seconds}s</span>}
          </Section>

          {/* OIDs */}
          <Section label={`OID Monitorati (${Object.keys(profile.oids || {}).length})`}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 text-[10px] font-mono max-h-64 overflow-y-auto bg-black/30 rounded p-2 border border-white/5">
              {Object.entries(profile.oids || {}).map(([name, oid]) => (
                <div key={name} className="flex justify-between gap-2">
                  <span className="text-emerald-300">{name}</span>
                  <span className="text-white/50 truncate">{oid}</span>
                </div>
              ))}
            </div>
          </Section>

          {/* API endpoints (Level 3) */}
          {profile.api_endpoints && (
            <Section label="API Endpoints (Livello 3 — richiede credenziali)">
              <div className="text-[10px] font-mono space-y-1 bg-indigo-500/5 border border-indigo-500/20 rounded p-2">
                {Object.entries(profile.api_endpoints).map(([name, path]) => (
                  <div key={name} className="flex justify-between gap-2">
                    <span className="text-indigo-300">{name}</span>
                    <span className="text-white/50 truncate">{path}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          <Section label="Capabilities">
            <div className="flex flex-wrap gap-1.5">
              {(profile.capabilities || []).map(c => (
                <span key={c} className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/5 text-white/60">
                  {c.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          </Section>
        </div>

        {editing && (
          <div className="flex justify-end gap-2 p-4 border-t border-[var(--bg-border)] bg-[#0a0a0f]">
            <button onClick={() => setEditing(false)} className="px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-white/60 text-[12px] font-bold">Annulla</button>
            <button onClick={save} disabled={saving} className="px-4 py-2 rounded bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 text-indigo-300 text-[12px] font-bold disabled:opacity-50" data-testid="save-override-btn">
              {saving ? "Salvataggio..." : "Salva override"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ label, children, editable }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[9px] font-bold uppercase tracking-wider text-white/40">{label}</span>
        {editable && <span className="text-[8px] text-indigo-400">EDITABLE</span>}
      </div>
      {children}
    </div>
  );
}

function KeyValueGrid({ data }) {
  if (!data || Object.keys(data).length === 0) {
    return <div className="text-[11px] text-white/30 italic">—</div>;
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 text-[11px] font-mono">
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex justify-between gap-2 py-0.5 border-b border-white/5">
          <span className="text-white/50">{k}</span>
          <span className="text-white font-semibold truncate" title={typeof v === "string" ? v : JSON.stringify(v)}>
            {typeof v === "object" ? JSON.stringify(v) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

function JsonArea({ value, onChange, testId }) {
  return (
    <textarea
      value={value}
      onChange={e => onChange(e.target.value)}
      rows={Math.max(6, value.split("\n").length + 1)}
      className="w-full bg-black/40 border border-white/10 rounded p-2 font-mono text-[11px] text-white/90 focus:border-indigo-500 outline-none resize-y"
      spellCheck={false}
      data-testid={testId}
    />
  );
}

/* ---------------- FINGERPRINT TESTER ---------------- */

function FingerprintTesterModal({ onClose }) {
  const [sysoid, setSysoid] = useState("");
  const [sysdescr, setSysdescr] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const test = async () => {
    setLoading(true); setResult(null);
    try {
      const res = await axios.post(`${API}/device-profiles/fingerprint`, {
        sysobjectid: sysoid, sysdescr,
      });
      setResult(res.data);
    } catch (e) {
      toast.error("Errore: " + (e.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-[#0d0d12] border border-[var(--bg-border)] rounded-xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()} data-testid="fingerprint-tester-modal">
        <div className="flex items-start justify-between gap-3 p-5 border-b border-[var(--bg-border)]">
          <div>
            <h2 className="font-bold text-white text-lg flex items-center gap-2">
              <MagnifyingGlass size={18} className="text-indigo-400" />
              Tester Fingerprint
            </h2>
            <p className="text-[11px] text-white/50 mt-0.5">Incolla i valori SNMP di un device e scopri che profilo viene matchato.</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-white/5 text-white/50"><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-white/50 mb-1 block">sysObjectID (opzionale)</label>
            <input
              type="text" value={sysoid} onChange={e => setSysoid(e.target.value)}
              placeholder="1.3.6.1.4.1.6574.1"
              className="w-full bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-3 py-2 text-[12px] text-white font-mono focus:border-indigo-500 outline-none"
              data-testid="fp-sysoid-input"
            />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-white/50 mb-1 block">sysDescr</label>
            <textarea
              value={sysdescr} onChange={e => setSysdescr(e.target.value)}
              rows={3} placeholder="Linux DiskStation 4.4.302 #42962 Synology"
              className="w-full bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-3 py-2 text-[12px] text-white font-mono focus:border-indigo-500 outline-none resize-y"
              data-testid="fp-sysdescr-input"
            />
          </div>
          <button
            onClick={test}
            disabled={loading || (!sysoid && !sysdescr)}
            className="w-full px-4 py-2.5 rounded bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 text-indigo-200 text-[12px] font-bold disabled:opacity-50"
            data-testid="fp-test-btn"
          >
            {loading ? "Analisi..." : "Analizza → Match Profilo"}
          </button>

          {result && (
            <div className="mt-2 border rounded-lg p-4"
              style={{ borderColor: result.matched ? "rgba(16,185,129,0.3)" : "rgba(245,158,11,0.3)",
                       background: result.matched ? "rgba(16,185,129,0.05)" : "rgba(245,158,11,0.05)" }}
              data-testid="fp-result">
              <div className="flex items-center gap-2 mb-2">
                {result.matched
                  ? <CheckCircle size={18} weight="fill" className="text-emerald-400" />
                  : <WarningCircle size={18} weight="fill" className="text-amber-400" />}
                <h3 className="font-bold text-white text-sm">
                  {result.matched
                    ? `MATCH (${result.confidence} confidence): ${result.profile?.vendor} · ${result.profile?.label}`
                    : "Nessun profilo matcha — useremo 'generic_snmp' come fallback"}
                </h3>
              </div>
              {result.matched && (
                <div className="grid grid-cols-2 gap-2 text-[11px] font-mono text-white/70 mt-3">
                  <div>key: <span className="text-cyan-300">{result.profile.key}</span></div>
                  <div>family: <span className="text-cyan-300">{result.profile.family}</span></div>
                  <div>SNMP: {result.profile.snmp?.version}:{result.profile.snmp?.port}</div>
                  <div>Web: {result.profile.web_console?.scheme}:{result.profile.web_console?.port}</div>
                  <div>OID count: {Object.keys(result.profile.oids || {}).length}</div>
                  <div>Polling: {result.profile.polling_interval_seconds}s</div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
