import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ShieldWarning, MagnifyingGlass, ArrowsClockwise, Bug, Globe, Warning,
  Key, Trash, Database, Pulse, Virus,
} from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

const FEED_LABELS = {
  feodo: "abuse.ch Feodo (C2)",
  threatfox: "abuse.ch ThreatFox",
  spamhaus_drop: "Spamhaus DROP",
  firehol_level1: "FireHOL Level 1",
  cisa_kev: "CISA KEV",
};

const KEY_PROVIDERS = [
  { id: "abusech", label: "abuse.ch (Auth-Key)", url: "https://auth.abuse.ch/", note: "Attiva ThreatFox e URLhaus" },
  { id: "abuseipdb", label: "AbuseIPDB", url: "https://www.abuseipdb.com/account/api", note: "Reputazione IP — 1.000 check/giorno free" },
  { id: "greynoise", label: "GreyNoise Community", url: "https://www.greynoise.io/", note: "Scanner/noise — riduce falsi positivi" },
  { id: "nvd", label: "NVD (NIST)", url: "https://nvd.nist.gov/developers/request-an-api-key", note: "Opzionale: dettagli CVE, rate limit più alto" },
];

function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("it-IT"); } catch { return iso; }
}

export default function OsintPage() {
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [keyInputs, setKeyInputs] = useState({});
  const [savingKey, setSavingKey] = useState(null);

  const [lookupIp, setLookupIp] = useState("");
  const [lookupResult, setLookupResult] = useState(null);
  const [lookingUp, setLookingUp] = useState(false);

  const [exposure, setExposure] = useState([]);
  const [c2, setC2] = useState([]);
  const [scanningC2, setScanningC2] = useState(false);
  const [kev, setKev] = useState([]);
  const [kevQuery, setKevQuery] = useState("");
  const [kevAssets, setKevAssets] = useState(null);

  const reloadStatus = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/osint/status`, { headers });
      setStatus(r.data);
    } catch {
      toast.error("Errore caricamento stato OSINT");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reloadExposure = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/osint/exposure`, { headers });
      setExposure(r.data.items || []);
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reloadKev = useCallback(async (q = "") => {
    try {
      const r = await axios.get(`${API}/api/osint/kev`, { headers, params: { q, limit: 50 } });
      setKev(r.data.items || []);
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reloadC2 = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/osint/c2-matches`, { headers, params: { status_filter: "all", limit: 100 } });
      setC2(r.data.items || []);
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reloadKevAssets = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/osint/kev/asset-exposure`, { headers });
      setKevAssets(r.data);
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { reloadStatus(); reloadExposure(); reloadKev(); reloadC2(); reloadKevAssets(); },
    [reloadStatus, reloadExposure, reloadKev, reloadC2, reloadKevAssets]);

  const refreshFeeds = async () => {
    setRefreshing(true);
    try {
      await axios.post(`${API}/api/osint/refresh`, {}, { headers });
      toast.success("Feed OSINT aggiornati");
      await reloadStatus();
      await reloadKev(kevQuery);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore refresh feed");
    } finally {
      setRefreshing(false);
    }
  };

  const saveKey = async (provider) => {
    const val = (keyInputs[provider] || "").trim();
    if (val.length < 6) { toast.error("API key troppo corta"); return; }
    setSavingKey(provider);
    try {
      await axios.put(`${API}/api/osint/keys/${provider}`, { api_key: val }, { headers });
      toast.success(`Chiave ${provider} salvata (cifrata)`);
      setKeyInputs((s) => ({ ...s, [provider]: "" }));
      await reloadStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSavingKey(null);
    }
  };

  const deleteKey = async (provider) => {
    if (!window.confirm(`Rimuovere la chiave ${provider}?`)) return;
    try {
      await axios.delete(`${API}/api/osint/keys/${provider}`, { headers });
      toast.success("Chiave rimossa");
      await reloadStatus();
    } catch { toast.error("Errore"); }
  };

  const scanC2 = async () => {
    setScanningC2(true);
    try {
      const r = await axios.post(`${API}/api/osint/c2-scan`, {}, { headers });
      const s = r.data.summary || {};
      toast.success(`Scansione C2: ${s.scanned ?? 0} eventi, ${s.matches ?? 0} match, ${s.alerts ?? 0} nuovi alert`);
      await reloadC2();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore scansione C2");
    } finally {
      setScanningC2(false);
    }
  };

  const doLookup = async () => {
    const ip = lookupIp.trim();
    if (!ip) return;
    setLookingUp(true);
    setLookupResult(null);
    try {
      const r = await axios.get(`${API}/api/osint/lookup/${encodeURIComponent(ip)}`, { headers });
      setLookupResult(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore lookup");
    } finally {
      setLookingUp(false);
    }
  };

  const feeds = status?.feeds || {};

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto" data-testid="osint-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <ShieldWarning size={26} className="text-amber-400" weight="duotone" />
          <div>
            <h1 className="text-lg font-bold">OSINT Threat Intelligence</h1>
            <p className="text-[11px] text-[var(--text-muted)]">
              Feed globali di intelligence integrati nel motore di alert e monitoraggio.
              Match e alert restano isolati per cliente.
            </p>
          </div>
        </div>
        <Button onClick={refreshFeeds} disabled={refreshing} size="sm"
          className="gap-1 bg-amber-600 hover:bg-amber-700" data-testid="osint-refresh-btn">
          <ArrowsClockwise size={14} className={refreshing ? "animate-spin" : ""} />
          {refreshing ? "Aggiornamento…" : "Aggiorna feed ora"}
        </Button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <KpiCard icon={Bug} color="text-red-400" label="IOC totali" value={status?.ioc_total} testid="osint-kpi-ioc" />
        <KpiCard icon={Virus} color="text-fuchsia-400" label="CVE KEV" value={status?.kev_total} testid="osint-kpi-kev" />
        <KpiCard icon={Globe} color="text-cyan-400" label="IP pubblici scansionati" value={status?.exposure_total} testid="osint-kpi-exposure" />
        <KpiCard icon={Warning} color="text-amber-400" label="Esposizioni KEV" value={status?.exposure_with_kev} testid="osint-kpi-exposure-kev" />
        <KpiCard icon={Bug} color="text-red-400" label="Alert C2 attivi" value={c2.filter((a) => a.status === "active").length} testid="osint-kpi-c2" />
      </div>

      {/* Feed status */}
      <Section title="Stato feed" icon={Pulse}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2" data-testid="osint-feeds-grid">
          {Object.keys(FEED_LABELS).map((k) => {
            const f = feeds[k];
            const ok = f?.status === "success";
            return (
              <div key={k} className="flex items-center justify-between rounded border border-[var(--bg-border)] bg-[var(--bg-card)] px-3 py-2"
                data-testid={`osint-feed-${k}`}>
                <div>
                  <p className="text-xs font-semibold">{FEED_LABELS[k]}</p>
                  <p className="text-[10px] text-[var(--text-muted)]">
                    {f ? `${f.count ?? 0} record · ${fmtTime(f.finished_at)}` : "Mai eseguito"}
                  </p>
                  {f?.error && <p className="text-[10px] text-red-400 truncate max-w-[280px]">{f.error}</p>}
                </div>
                <span className={`text-[10px] px-2 py-0.5 rounded font-mono ${
                  !f ? "bg-slate-500/15 text-slate-300"
                    : ok ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"}`}>
                  {!f ? "IDLE" : ok ? "OK" : "FAIL"}
                </span>
              </div>
            );
          })}
        </div>
      </Section>

      {/* IP Lookup */}
      <Section title="Lookup IP pubblico" icon={MagnifyingGlass}>
        <div className="flex gap-2 mb-3">
          <Input value={lookupIp} onChange={(e) => setLookupIp(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doLookup()}
            placeholder="es. 45.155.205.233"
            className="flex-1 bg-[var(--bg-input)] text-xs font-mono" data-testid="osint-lookup-input" />
          <Button onClick={doLookup} disabled={lookingUp || !lookupIp} size="sm"
            className="gap-1 bg-cyan-600 hover:bg-cyan-700" data-testid="osint-lookup-btn">
            <MagnifyingGlass size={14} /> {lookingUp ? "Ricerca…" : "Analizza"}
          </Button>
        </div>
        {lookupResult && (
          <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3 space-y-3 text-xs"
            data-testid="osint-lookup-result">
            <div className="flex items-center gap-2">
              <span className="font-mono font-semibold">{lookupResult.ip}</span>
              <span className={`text-[10px] px-2 py-0.5 rounded font-mono ${
                lookupResult.malicious ? "bg-red-500/15 text-red-300" : "bg-emerald-500/15 text-emerald-300"}`}
                data-testid="osint-lookup-verdict">
                {lookupResult.malicious ? "⚠ IOC MATCH" : "Nessun match locale"}
              </span>
            </div>
            {lookupResult.local_matches?.length > 0 && (
              <div>
                <p className="text-[10px] text-[var(--text-muted)] mb-1">Match nei feed locali:</p>
                <div className="flex flex-wrap gap-1">
                  {lookupResult.local_matches.map((m, i) => (
                    <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-red-500/10 text-red-300 font-mono">
                      {m.source} ({m.threat || m.kind})
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <LookupCard title="AbuseIPDB" data={lookupResult.abuseipdb} />
              <LookupCard title="GreyNoise" data={lookupResult.greynoise} />
              <LookupCard title="Shodan InternetDB" data={lookupResult.internetdb} />
            </div>
            {lookupResult.kev_hits?.length > 0 && (
              <div className="rounded bg-fuchsia-500/10 border border-fuchsia-500/30 p-2">
                <p className="text-[11px] font-semibold text-fuchsia-300 mb-1">
                  <Virus size={12} className="inline mr-1" />CVE attivamente sfruttate (CISA KEV)
                </p>
                <div className="flex flex-wrap gap-1">
                  {lookupResult.kev_hits.map((k, i) => (
                    <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-fuchsia-500/20 text-fuchsia-200 font-mono">
                      {k.cve_id}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Section>

      {/* Exposure findings */}
      <Section title="Esposizione IP pubblici (Shodan InternetDB)" icon={Globe}>
        {exposure.length === 0 ? (
          <p className="text-[11px] text-[var(--text-muted)]">
            Nessuna scansione ancora disponibile. Vengono analizzati automaticamente gli IP pubblici
            configurati in Monitor WAN (target). Prima scansione entro pochi minuti.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--bg-border)]">
            <table className="w-full text-xs" data-testid="osint-exposure-table">
              <thead className="bg-[var(--bg-card)] text-[var(--text-muted)]">
                <tr>
                  <th className="text-left px-3 py-2">Cliente</th>
                  <th className="text-left px-3 py-2">IP pubblico</th>
                  <th className="text-left px-3 py-2">Porte</th>
                  <th className="text-left px-3 py-2">CVE</th>
                  <th className="text-left px-3 py-2">KEV</th>
                  <th className="text-left px-3 py-2">Scan</th>
                </tr>
              </thead>
              <tbody>
                {exposure.map((e) => (
                  <tr key={e.target_id} className="border-t border-[var(--bg-border)]"
                    data-testid={`osint-exposure-row-${e.public_ip}`}>
                    <td className="px-3 py-2">{e.client_name || "—"}</td>
                    <td className="px-3 py-2 font-mono">{e.public_ip}</td>
                    <td className="px-3 py-2 font-mono text-[10px]">{(e.ports || []).slice(0, 8).join(", ") || "—"}</td>
                    <td className="px-3 py-2">{(e.vulns || []).length}</td>
                    <td className="px-3 py-2">
                      {e.kev_count > 0 ? (
                        <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/15 text-red-300 font-mono">
                          {e.kev_count} sfruttate
                        </span>
                      ) : <span className="text-emerald-400">0</span>}
                    </td>
                    <td className="px-3 py-2 text-[10px] text-[var(--text-muted)]">{fmtTime(e.last_scan)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* C2 correlation */}
      <Section title="Correlazione C2 (Syslog / Firewall)" icon={Bug}>
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <p className="text-[11px] text-[var(--text-muted)] max-w-2xl">
            Confronta automaticamente gli IP presenti nei log firewall/syslog dei clienti con gli IOC
            (Feodo, Spamhaus, FireHOL, ThreatFox). Se un dispositivo comunica con un IP malevolo noto
            viene generato un alert <span className="text-red-300 font-semibold">critico</span> per quel
            cliente. Scansione automatica ogni 2 minuti.
          </p>
          <Button onClick={scanC2} disabled={scanningC2} size="sm"
            className="gap-1 bg-red-600 hover:bg-red-700" data-testid="osint-c2-scan-btn">
            <ArrowsClockwise size={14} className={scanningC2 ? "animate-spin" : ""} />
            {scanningC2 ? "Scansione…" : "Scansiona ora"}
          </Button>
        </div>
        {c2.length === 0 ? (
          <p className="text-[11px] text-[var(--text-muted)]" data-testid="osint-c2-empty">
            Nessuna comunicazione con IP malevoli rilevata. Verranno mostrate qui le corrispondenze
            trovate nei syslog dei firewall dei clienti.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--bg-border)]">
            <table className="w-full text-xs" data-testid="osint-c2-table">
              <thead className="bg-[var(--bg-card)] text-[var(--text-muted)]">
                <tr>
                  <th className="text-left px-3 py-2">Stato</th>
                  <th className="text-left px-3 py-2">Cliente</th>
                  <th className="text-left px-3 py-2">IP malevolo</th>
                  <th className="text-left px-3 py-2">Dettaglio</th>
                  <th className="text-left px-3 py-2">Rilevato</th>
                </tr>
              </thead>
              <tbody>
                {c2.map((a) => (
                  <tr key={a.id} className="border-t border-[var(--bg-border)]"
                    data-testid={`osint-c2-row-${a.raw_data}`}>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] px-2 py-0.5 rounded font-mono ${
                        a.status === "active" ? "bg-red-500/15 text-red-300" : "bg-slate-500/15 text-slate-300"}`}>
                        {a.status === "active" ? "ATTIVO" : (a.status || "").toUpperCase()}
                      </span>
                    </td>
                    <td className="px-3 py-2">{a.client_name || "—"}</td>
                    <td className="px-3 py-2 font-mono text-red-300">{a.raw_data}</td>
                    <td className="px-3 py-2 text-[10px] max-w-[420px] truncate">{a.message}</td>
                    <td className="px-3 py-2 text-[10px] text-[var(--text-muted)]">{fmtTime(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Asset esposti a KEV: incrocio catalogo KEV ↔ vendor/modelli CMDB */}
      {kevAssets && kevAssets.total > 0 && (
        <Section title={`I miei asset esposti a KEV — ${kevAssets.total} dispositivi`} icon={Virus}>
          <p className="text-[11px] text-[var(--text-muted)] mb-3">
            Incrocio automatico tra il catalogo CISA KEV (CVE attivamente sfruttate) e i vendor/modelli
            reali dei tuoi asset (firewall Zyxel Nebula + dispositivi gestiti). {kevAssets.assets_scanned} asset con modello analizzati.
          </p>
          <div className="overflow-x-auto rounded-lg border border-red-500/25">
            <table className="w-full text-xs" data-testid="osint-kev-assets-table">
              <thead className="bg-[var(--bg-card)] text-[var(--text-muted)]">
                <tr>
                  <th className="text-left px-3 py-2">Cliente</th>
                  <th className="text-left px-3 py-2">Dispositivo</th>
                  <th className="text-left px-3 py-2">Vendor / Modello</th>
                  <th className="text-left px-3 py-2">CVE KEV</th>
                  <th className="text-left px-3 py-2">Prima scadenza</th>
                </tr>
              </thead>
              <tbody>
                {kevAssets.items.map((a) => {
                  const first = a.matches[0];
                  const overdue = first?.due_date && new Date(first.due_date) < new Date();
                  const ransom = a.matches.some((m) => String(m.ransomware).toLowerCase() === "known");
                  return (
                    <tr key={`${a.client_id}-${a.name}`} className="border-t border-[var(--bg-border)] align-top"
                        data-testid={`osint-kev-asset-${a.client_id}`}>
                      <td className="px-3 py-2 whitespace-nowrap">{a.client_name}</td>
                      <td className="px-3 py-2">
                        {a.name}
                        <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-[var(--bg-card)] text-[var(--text-muted)] uppercase">{a.device_type || a.source}</span>
                      </td>
                      <td className="px-3 py-2 text-[10px]">{a.vendor} / {a.model}</td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap items-center gap-1">
                          <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/15 text-red-300 font-bold">{a.match_count} CVE</span>
                          {ransom && <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-600/25 text-red-200 font-bold uppercase">Ransomware</span>}
                          {a.matches.slice(0, 4).map((m) => (
                            <span key={m.cve_id} className="text-[9px] font-mono text-cyan-300/90 border border-cyan-500/25 rounded px-1"
                                  title={`${m.product} — ${m.short_description || ""}${m.match_type === "vendor_category" ? " (match per categoria vendor)" : ""}`}>
                              {m.cve_id}
                            </span>
                          ))}
                          {a.match_count > 4 && <span className="text-[9px] text-[var(--text-muted)]">+{a.match_count - 4}</span>}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-[10px] whitespace-nowrap">
                        <span className={overdue ? "text-red-400 font-bold" : "text-[var(--text-muted)]"}>{first?.due_date || "—"}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {/* KEV browser */}
      <Section title="Catalogo CISA KEV (CVE attivamente sfruttate)" icon={Virus}>
        <div className="flex gap-2 mb-3">
          <Input value={kevQuery} onChange={(e) => setKevQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && reloadKev(kevQuery)}
            placeholder="Cerca CVE, vendor o prodotto…"
            className="flex-1 bg-[var(--bg-input)] text-xs" data-testid="osint-kev-search" />
          <Button onClick={() => reloadKev(kevQuery)} size="sm" variant="outline" className="gap-1" data-testid="osint-kev-search-btn">
            <MagnifyingGlass size={14} /> Cerca
          </Button>
        </div>
        <div className="overflow-x-auto rounded-lg border border-[var(--bg-border)] max-h-96 overflow-y-auto">
          <table className="w-full text-xs" data-testid="osint-kev-table">
            <thead className="bg-[var(--bg-card)] text-[var(--text-muted)] sticky top-0">
              <tr>
                <th className="text-left px-3 py-2">CVE</th>
                <th className="text-left px-3 py-2">Vendor / Prodotto</th>
                <th className="text-left px-3 py-2">Vulnerabilità</th>
                <th className="text-left px-3 py-2">Azione richiesta</th>
                <th className="text-left px-3 py-2">Aggiunta</th>
                <th className="text-left px-3 py-2">Scadenza</th>
                <th className="text-left px-3 py-2">Ransomware</th>
              </tr>
            </thead>
            <tbody>
              {kev.map((k) => {
                const overdue = k.due_date && new Date(k.due_date) < new Date();
                return (
                <tr key={k.cve_id} className="border-t border-[var(--bg-border)] align-top" data-testid={`osint-kev-row-${k.cve_id}`}>
                  <td className="px-3 py-2 font-mono text-cyan-300 whitespace-nowrap">{k.cve_id}</td>
                  <td className="px-3 py-2">{k.vendor} / {k.product}</td>
                  <td className="px-3 py-2 text-[10px] max-w-[240px] truncate" title={k.short_description || k.name}>{k.name}</td>
                  <td className="px-3 py-2 text-[10px] text-[var(--text-secondary)] max-w-[220px] truncate" title={k.required_action || ""}>{k.required_action || "—"}</td>
                  <td className="px-3 py-2 text-[10px] text-[var(--text-muted)] whitespace-nowrap">{k.date_added}</td>
                  <td className="px-3 py-2 text-[10px] whitespace-nowrap" title={overdue ? "Scadenza remediation superata" : ""}>
                    <span className={overdue ? "text-red-400 font-bold" : "text-[var(--text-muted)]"}>{k.due_date || "—"}</span>
                  </td>
                  <td className="px-3 py-2">
                    {String(k.ransomware).toLowerCase() === "known"
                      ? <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/15 text-red-300">SÌ</span>
                      : <span className="text-[10px] text-[var(--text-muted)]">—</span>}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      {/* API keys */}
      <Section title="Chiavi API provider (opzionali)" icon={Key}>
        <p className="text-[11px] text-[var(--text-muted)] mb-3">
          Feed keyless (Feodo, Spamhaus, FireHOL, CISA KEV, Shodan InternetDB) sono già attivi.
          Aggiungi le chiavi gratuite qui sotto per abilitare i provider extra. Cifrate AES-256-GCM.
        </p>
        <div className="space-y-2">
          {KEY_PROVIDERS.map((p) => {
            const st = status?.keys?.[p.id];
            return (
              <div key={p.id} className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3"
                data-testid={`osint-key-row-${p.id}`}>
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <p className="text-xs font-semibold flex items-center gap-2">
                      {p.label}
                      <span className={`text-[10px] px-2 py-0.5 rounded font-mono ${
                        st?.configured ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-500/15 text-slate-300"}`}
                        data-testid={`osint-key-status-${p.id}`}>
                        {st?.configured ? `ATTIVA ${st.masked_key || ""}` : "NON CONFIGURATA"}
                      </span>
                    </p>
                    <p className="text-[10px] text-[var(--text-muted)]">
                      {p.note} · <a href={p.url} target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline">ottieni chiave</a>
                    </p>
                  </div>
                  {st?.configured && (
                    <Button onClick={() => deleteKey(p.id)} size="sm" variant="outline"
                      className="gap-1 border-red-500/40 text-red-300 hover:bg-red-500/10"
                      data-testid={`osint-key-delete-${p.id}`}>
                      <Trash size={12} />
                    </Button>
                  )}
                </div>
                <div className="flex gap-2">
                  <Input type="password" autoComplete="off" placeholder="Incolla la API key…"
                    value={keyInputs[p.id] || ""}
                    onChange={(e) => setKeyInputs((s) => ({ ...s, [p.id]: e.target.value }))}
                    className="flex-1 bg-[var(--bg-input)] text-xs font-mono"
                    data-testid={`osint-key-input-${p.id}`} />
                  <Button onClick={() => saveKey(p.id)} disabled={savingKey === p.id || !(keyInputs[p.id])}
                    size="sm" className="gap-1" data-testid={`osint-key-save-${p.id}`}>
                    {savingKey === p.id ? "…" : "Salva"}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

function KpiCard({ icon: Icon, color, label, value, testid }) {
  return (
    <div className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-card)] p-3" data-testid={testid}>
      <Icon size={18} className={color} weight="duotone" />
      <p className="text-2xl font-bold mt-1">{value ?? "—"}</p>
      <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
    </div>
  );
}

function Section({ title, icon: Icon, children }) {
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={14} className="text-[var(--text-secondary)]" />
        <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function LookupCard({ title, data }) {
  return (
    <div className="rounded border border-[var(--bg-border)] bg-[var(--bg-input)] p-2">
      <p className="text-[10px] font-semibold text-[var(--text-secondary)] mb-1">{title}</p>
      {!data ? (
        <p className="text-[10px] text-[var(--text-muted)]">Non configurato</p>
      ) : data.error ? (
        <p className="text-[10px] text-red-400">{data.error}</p>
      ) : (
        <pre className="text-[10px] font-mono whitespace-pre-wrap max-h-40 overflow-auto text-[var(--text-secondary)]">
          {JSON.stringify(data, null, 1)}
        </pre>
      )}
    </div>
  );
}
