import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  ArrowLeft, BellRinging, Pulse, Cloud, PaperPlaneTilt, ArrowsClockwise,
  Warning, CheckCircle, Broadcast, ShieldCheck, Lightning,
} from "@phosphor-icons/react";

const API = process.env.REACT_APP_BACKEND_URL;

const NumField = ({ label, hint, value, onChange, testid }) => (
  <div>
    <Label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{label}</Label>
    <Input
      type="number" min={0} value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
      className="h-9 text-sm font-mono bg-[var(--bg-panel)] border-[var(--bg-border)] mt-1"
      data-testid={testid}
    />
    {hint && <p className="text-[9px] text-[var(--text-muted)] mt-1">{hint}</p>}
  </div>
);

const Section = ({ icon: Icon, color, title, desc, children }) => (
  <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 space-y-4">
    <div className="flex items-center gap-2">
      <Icon size={16} weight="bold" style={{ color }} />
      <div>
        <h3 className="text-xs font-bold text-[var(--text-primary)]">{title}</h3>
        {desc && <p className="text-[10px] text-[var(--text-muted)]">{desc}</p>}
      </div>
    </div>
    {children}
  </div>
);

export default function AlertEngineSettingsPage() {
  const navigate = useNavigate();
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null);
  const [tgToken, setTgToken] = useState("");
  const [detected, setDetected] = useState(null);
  const [busy, setBusy] = useState("");

  const reload = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        axios.get(`${API}/api/alert-engine/config`, { headers }),
        axios.get(`${API}/api/alert-engine/status`, { headers }),
      ]);
      setCfg(c.data);
      setStatus(s.data);
    } catch {
      toast.error("Errore caricamento configurazione Alert Engine");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const set = (k, v) => setCfg((p) => ({ ...p, [k]: v }));
  const toggleChannel = (ch) => {
    const cur = new Set(cfg.channels || []);
    if (cur.has(ch)) cur.delete(ch); else cur.add(ch);
    set("channels", Array.from(cur));
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...cfg };
      delete payload.telegram_bot_token_set;
      if (tgToken.trim()) payload.telegram_bot_token = tgToken.trim();
      else delete payload.telegram_bot_token;
      const r = await axios.put(`${API}/api/alert-engine/config`, payload, { headers });
      setCfg(r.data);
      setTgToken("");
      toast.success("Configurazione salvata");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally { setSaving(false); }
  };

  const runNow = async () => {
    setBusy("run");
    try {
      const r = await axios.post(`${API}/api/alert-engine/run-now`, {}, { headers });
      toast.success(`Scansione eseguita: ${r.data.result.vital_actions} vitali, ${r.data.result.datto_actions} Datto`);
      reload();
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(""); }
  };

  const testTelegram = async () => {
    setBusy("test");
    try {
      await axios.post(`${API}/api/alert-engine/telegram/test`,
        { token: tgToken.trim() || undefined, chat_id: cfg.telegram_chat_id || undefined }, { headers });
      toast.success("Messaggio di test inviato su Telegram!");
    } catch (e) { toast.error(e.response?.data?.detail || "Invio fallito — verifica token e chat_id"); }
    finally { setBusy(""); }
  };

  const detectChats = async () => {
    setBusy("detect");
    try {
      const r = await axios.get(`${API}/api/alert-engine/telegram/detect-chats`, { headers });
      setDetected(r.data.chats || []);
      if (!(r.data.chats || []).length) toast.info("Nessuna chat trovata. Invia prima /start al bot da Telegram.");
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(""); }
  };

  const resolveSwitchLinks = async () => {
    setBusy("switch");
    try {
      const r = await axios.post(`${API}/api/topology/resolve-switch-links`, {}, { headers });
      toast.success(`Link switch ricalcolati dalla FDB: ${r.data.devices_mapped} device mappati.`);
    } catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
    finally { setBusy(""); }
  };

  if (loading || !cfg) {
    return <div className="p-8 text-sm text-[var(--text-muted)]">Caricamento…</div>;
  }

  const channels = cfg.channels || [];

  return (
    <div className="max-w-4xl mx-auto p-5 space-y-4" data-testid="alert-engine-settings">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="h-8 gap-1" data-testid="back-btn">
            <ArrowLeft size={14} /> Indietro
          </Button>
          <div>
            <h1 className="text-lg font-bold text-[var(--text-primary)] flex items-center gap-2">
              <BellRinging size={20} weight="bold" className="text-amber-400" /> Alert Engine proattivo
            </h1>
            <p className="text-[11px] text-[var(--text-muted)]">Avvisi automatici per dispositivi vitali offline e disconnessioni Datto RMM.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={runNow} disabled={busy === "run"} className="h-8 gap-1 border-cyan-500/30 text-cyan-300" data-testid="run-now-btn">
            <Lightning size={13} weight="bold" /> {busy === "run" ? "Scansione…" : "Esegui scansione ora"}
          </Button>
          <Button size="sm" onClick={save} disabled={saving} className="h-8 bg-amber-600 hover:bg-amber-700 text-white" data-testid="save-btn">
            {saving ? "Salvataggio…" : "Salva"}
          </Button>
        </div>
      </div>

      {/* Master toggle + status */}
      <div className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-4 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Switch checked={!!cfg.enabled} onCheckedChange={(v) => set("enabled", v)} data-testid="enabled-switch" />
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">Motore {cfg.enabled ? "attivo" : "disattivato"}</p>
            <p className="text-[10px] text-[var(--text-muted)]">Scansione automatica ogni 60 secondi.</p>
          </div>
        </div>
        {status?.last_run?.at && (
          <div className="text-[10px] text-[var(--text-muted)] text-right">
            <div>Ultima scansione: {new Date(status.last_run.at).toLocaleTimeString("it-IT")}</div>
            <div>{status.vital_offline_tracked} vitali monitorati · {status.datto_offline_tracked} server Datto</div>
          </div>
        )}
      </div>

      {/* Vital devices */}
      <Section icon={Pulse} color="#F59E0B" title="Dispositivi vitali offline"
        desc="Soglie di escalation per i device marcati come vitali (non silenziabili).">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <NumField label="Warning dopo (minuti)" hint="Alert ALTO dopo N minuti di offline continuo." value={cfg.vital_warn_minutes} onChange={(v) => set("vital_warn_minutes", v)} testid="vital-warn" />
          <NumField label="Critico dopo (minuti)" hint="Escalation a CRITICO dopo N minuti." value={cfg.vital_crit_minutes} onChange={(v) => set("vital_crit_minutes", v)} testid="vital-crit" />
        </div>
      </Section>

      {/* Datto */}
      <Section icon={Cloud} color="#10B981" title="Datto RMM"
        desc="Allerta quando un server perde la connessione al cloud o il sync si ferma.">
        <div className="flex items-center gap-3 mb-1">
          <Switch checked={!!cfg.datto_enabled} onCheckedChange={(v) => set("datto_enabled", v)} data-testid="datto-enabled-switch" />
          <span className="text-xs text-[var(--text-primary)]">Watchdog Datto attivo</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <NumField label="Server offline (ore)" hint="Alert ALTO se un server Datto è offline oltre N ore." value={cfg.datto_server_offline_hours} onChange={(v) => set("datto_server_offline_hours", v)} testid="datto-warn-h" />
          <NumField label="Critico (ore)" hint="Escalation a CRITICO oltre N ore." value={cfg.datto_server_crit_hours} onChange={(v) => set("datto_server_crit_hours", v)} testid="datto-crit-h" />
          <NumField label="Sync fermo (minuti)" hint="Alert se il sync Datto non si aggiorna da N minuti." value={cfg.datto_sync_stale_minutes} onChange={(v) => set("datto_sync_stale_minutes", v)} testid="datto-sync-stale" />
        </div>
      </Section>

      {/* Channels */}
      <Section icon={Broadcast} color="#6366F1" title="Canali di notifica" desc="Come vuoi ricevere gli avvisi.">
        <div className="flex items-center gap-3 flex-wrap">
          {[
            { id: "push", label: "Push browser" },
            { id: "telegram", label: "Telegram" },
          ].map((ch) => (
            <button key={ch.id} onClick={() => toggleChannel(ch.id)}
              className={`px-3 h-8 rounded-lg border text-xs font-medium transition-colors ${channels.includes(ch.id) ? "bg-indigo-500/15 border-indigo-500/50 text-indigo-300" : "border-[var(--bg-border)] text-[var(--text-muted)]"}`}
              data-testid={`channel-${ch.id}`}>
              {channels.includes(ch.id) ? "✓ " : ""}{ch.label}
            </button>
          ))}
          <div className="flex items-center gap-2 ml-2">
            <Switch checked={!!cfg.auto_recovery} onCheckedChange={(v) => set("auto_recovery", v)} data-testid="auto-recovery-switch" />
            <span className="text-xs text-[var(--text-primary)]">Avviso "tornato ONLINE"</span>
          </div>
        </div>
      </Section>

      {/* Telegram config */}
      {channels.includes("telegram") && (
        <Section icon={PaperPlaneTilt} color="#22B8EB" title="Configurazione Telegram"
          desc="Crea un bot con @BotFather, incolla il token, poi rileva la chat.">
          <div className="flex items-center gap-2 mb-2">
            {cfg.telegram_bot_token_set
              ? <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 flex items-center gap-1"><CheckCircle size={11} weight="bold" /> Token configurato</span>
              : <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 flex items-center gap-1"><Warning size={11} weight="bold" /> Token mancante</span>}
            <Switch checked={!!cfg.telegram_enabled} onCheckedChange={(v) => set("telegram_enabled", v)} data-testid="telegram-enabled-switch" />
            <span className="text-[10px] text-[var(--text-muted)]">Abilitato</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Bot Token</Label>
              <Input type="password" value={tgToken} onChange={(e) => setTgToken(e.target.value)}
                placeholder={cfg.telegram_bot_token_set ? "•••••• (lascia vuoto per non cambiare)" : "123456:ABC-DEF…"}
                className="h-9 text-sm font-mono bg-[var(--bg-panel)] border-[var(--bg-border)] mt-1" data-testid="tg-token" />
            </div>
            <div>
              <Label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Chat ID</Label>
              <Input value={cfg.telegram_chat_id || ""} onChange={(e) => set("telegram_chat_id", e.target.value)}
                placeholder="-1001234567890" className="h-9 text-sm font-mono bg-[var(--bg-panel)] border-[var(--bg-border)] mt-1" data-testid="tg-chat" />
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Button variant="outline" size="sm" onClick={detectChats} disabled={busy === "detect"} className="h-8 gap-1 text-xs" data-testid="detect-chats-btn">
              <ArrowsClockwise size={12} /> {busy === "detect" ? "Rilevo…" : "Rileva chat"}
            </Button>
            <Button variant="outline" size="sm" onClick={testTelegram} disabled={busy === "test"} className="h-8 gap-1 text-xs border-cyan-500/30 text-cyan-300" data-testid="tg-test-btn">
              <PaperPlaneTilt size={12} weight="bold" /> {busy === "test" ? "Invio…" : "Invia test"}
            </Button>
            <span className="text-[9px] text-[var(--text-muted)]">Suggerimento: salva il token prima di rilevare la chat.</span>
          </div>
          {detected && detected.length > 0 && (
            <div className="space-y-1 pt-1">
              {detected.map((c) => (
                <button key={c.chat_id} onClick={() => set("telegram_chat_id", c.chat_id)}
                  className="w-full text-left flex items-center justify-between px-2 py-1.5 rounded border border-[var(--bg-border)] hover:border-cyan-500/40 text-xs" data-testid={`chat-opt-${c.chat_id}`}>
                  <span className="text-[var(--text-primary)]">{c.title} <span className="text-[9px] text-[var(--text-muted)]">({c.type})</span></span>
                  <span className="font-mono text-[10px] text-cyan-300">{c.chat_id}</span>
                </button>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* Come funziona la correlazione */}
      <Section icon={ShieldCheck} color="#10B981" title="Correlazione multi-sorgente (anti falsi-positivi)"
        desc="Argus incrocia più segnali prima di allertare: ping, Datto, evidenza L2 (switch/ARP), WAN e iLO.">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px]">
          {[
            ["Ping FAIL + Datto OFFLINE + iLO Off", "SERVER SPENTO · 100%", "#EF4444"],
            ["Ping FAIL + Datto OFFLINE + iLO On", "OS BLOCCATO · 92%", "#EF4444"],
            ["Ping FAIL + Datto OFFLINE (no L2)", "SERVER DOWN · 95%", "#EF4444"],
            ["Ping OK + Datto OFFLINE", "AGENT DATTO KO (server su) · 85%", "#3B82F6"],
            ["Ping FAIL + Datto ONLINE", "Monitoraggio cieco · 50%", "#F59E0B"],
            ["Firewall down + sito giù", "SITO ISOLATO (1 alert) · 97%", "#EF4444"],
            ["Firewall su + Internet giù", "LINEA ISP DOWN · 95%", "#EF4444"],
            ["Switch down + figli giù", "SWITCH DOWN (figli soppressi) · 95%", "#EF4444"],
          ].map(([cond, verdict, col]) => (
            <div key={cond} className="flex items-center justify-between gap-2 px-2 py-1.5 rounded border border-[var(--bg-border)]">
              <span className="text-[var(--text-muted)] font-mono">{cond}</span>
              <span className="font-semibold shrink-0" style={{ color: col }}>{verdict}</span>
            </div>
          ))}
        </div>
        <p className="text-[9px] text-[var(--text-muted)]">Ogni alert riporta il ragionamento e la % di confidenza. La correlazione è sempre attiva quando il motore è acceso.</p>
        <div className="flex items-center gap-2 flex-wrap pt-1">
          <Button variant="outline" size="sm" onClick={resolveSwitchLinks} disabled={busy === "switch"}
            className="h-8 gap-1 text-xs border-emerald-500/30 text-emerald-300" data-testid="resolve-switch-btn">
            <ArrowsClockwise size={12} /> {busy === "switch" ? "Ricalcolo…" : "Ricalcola link switch (FDB)"}
          </Button>
          <span className="text-[9px] text-[var(--text-muted)]">Popola switch_ip dai dati SNMP FDB → abilita la soppressione switch-level (auto ogni 10 min).</span>
        </div>
      </Section>

      <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)] px-1">
        <ShieldCheck size={12} className="text-emerald-400" />
        I dispositivi vitali non possono essere silenziati: generano sempre alert. Le soglie possono essere sovrascritte per singolo cliente.
      </div>
    </div>
  );
}
