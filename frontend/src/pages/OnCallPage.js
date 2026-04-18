import { useState, useEffect } from "react";
import axios from "axios";
import { API, useAuth } from "@/App";
import { toast } from "sonner";
import { Clock, Plus, Trash, UserCircle, ArrowClockwise, CalendarBlank, ArrowUp } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const DAYS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"];

function uuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0; const v = c === "x" ? r : (r & 0x3 | 0x8); return v.toString(16);
  });
}

export default function OnCallPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [cfg, setCfg] = useState({ rotation_enabled: false, timezone: "Europe/Rome", slots: [] });
  const [users, setUsers] = useState([]);
  const [current, setCurrent] = useState({ rotation_enabled: false, active_slots: [], now: "" });
  const [escCfg, setEscCfg] = useState({ enabled: false, wait_minutes: 5, severities: ["critical"], escalate_to_roles: ["admin"] });
  const [escBusy, setEscBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [s, u, c, e] = await Promise.all([
        axios.get(`${API}/oncall/schedule`),
        axios.get(`${API}/oncall/users`),
        axios.get(`${API}/oncall/current`),
        axios.get(`${API}/escalation/config`),
      ]);
      setCfg(s.data);
      setUsers(u.data);
      setCurrent(c.data);
      setEscCfg(e.data);
    } catch (e) {
      toast.error("Errore caricamento rotazione on-call");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, []);

  const saveEsc = async (next) => {
    if (!isAdmin) return;
    setEscBusy(true);
    try {
      const body = next || escCfg;
      const r = await axios.put(`${API}/escalation/config`, body);
      if (r.data?.success) {
        setEscCfg(r.data.config);
        toast.success("Escalation aggiornata");
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally {
      setEscBusy(false);
    }
  };

  const triggerEscalation = async () => {
    setEscBusy(true);
    try {
      const r = await axios.post(`${API}/escalation/run-now`);
      if (r.data?.success) {
        toast.success(`Escalation eseguita: ${r.data.escalated} alert`);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore esecuzione");
    } finally {
      setEscBusy(false);
    }
  };

  const save = async (nextCfg) => {
    if (!isAdmin) return;
    setSaving(true);
    try {
      const body = nextCfg || cfg;
      const r = await axios.put(`${API}/oncall/schedule`, body);
      if (r.data?.success) {
        setCfg(r.data.config);
        toast.success("Rotazione salvata");
        // Refresh current on-call
        const c = await axios.get(`${API}/oncall/current`);
        setCurrent(c.data);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const addSlot = () => {
    if (!isAdmin) return;
    const newSlot = {
      id: uuid(), day_of_week: 0, start: "08:00", end: "18:00",
      user_id: users[0]?.id || "", user_email: users[0]?.email || "", label: "",
    };
    save({ ...cfg, slots: [...cfg.slots, newSlot] });
  };

  const updateSlot = (id, patch) => {
    const nextSlots = cfg.slots.map(s => s.id === id ? { ...s, ...patch } : s);
    setCfg({ ...cfg, slots: nextSlots });
  };

  const commitSlot = (id) => {
    // Fire-and-forget save when blurring a slot
    save();
  };

  const removeSlot = (id) => {
    if (!isAdmin) return;
    save({ ...cfg, slots: cfg.slots.filter(s => s.id !== id) });
  };

  const userLabel = (uid) => {
    const u = users.find(u => u.id === uid);
    return u ? `${u.name} (${u.email})` : uid;
  };

  if (loading) {
    return <div className="p-6 text-center text-[var(--text-muted)] text-xs">Caricamento...</div>;
  }

  return (
    <div className="p-4 md:p-5 animate-fade-in max-w-3xl" data-testid="oncall-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Reperibilità (On-Call)</h1>
          <p className="text-[var(--text-muted)] text-xs mt-0.5">
            Instrada le notifiche push all'operatore di turno
          </p>
        </div>
        <button onClick={fetchAll} className="p-1.5 rounded-md hover:bg-[var(--bg-hover)] text-[var(--text-muted)]" title="Aggiorna">
          <ArrowClockwise size={16} />
        </button>
      </div>

      {/* Chi è reperibile ora */}
      <div className="noc-panel p-4 mb-4" data-testid="current-oncall-banner">
        <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-2 flex items-center gap-1.5">
          <Clock size={13} /> Reperibile ora · <span className="font-mono normal-case tracking-normal">{current.now}</span>
        </h3>
        {!current.rotation_enabled ? (
          <p className="text-[var(--text-muted)] text-xs">
            Rotazione <b>disabilitata</b>. Le notifiche vengono inviate a tutti gli admin + operator.
          </p>
        ) : current.active_slots.length === 0 ? (
          <p className="text-amber-400 text-xs">
            Nessuno reperibile in questa fascia oraria. Le notifiche vengono inviate a tutti gli admin + operator.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {current.active_slots.map(s => (
              <div key={s.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs">
                <UserCircle size={14} weight="bold" />
                <span className="font-mono">{s.user_email || userLabel(s.user_id)}</span>
                <span className="text-[10px] opacity-75">({DAYS[s.day_of_week]} {s.start}-{s.end})</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Rotation master toggle */}
      <div className="noc-panel p-4 mb-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[var(--text-primary)] text-xs font-medium">Abilita rotazione On-Call</p>
            <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
              Quando attiva, le notifiche vengono inviate SOLO agli operatori di turno (fallback a tutti se nessuno è di turno)
            </p>
          </div>
          <Switch
            checked={cfg.rotation_enabled}
            disabled={saving || !isAdmin}
            onCheckedChange={(v) => save({ ...cfg, rotation_enabled: v })}
            data-testid="rotation-toggle"
          />
        </div>
        {!isAdmin && (
          <p className="text-[10px] text-[var(--text-muted)] mt-2">Solo gli admin possono modificare la rotazione.</p>
        )}
      </div>

      {/* Slots */}
      <div className="noc-panel p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest flex items-center gap-1.5">
            <CalendarBlank size={13} /> Turni settimanali ({cfg.slots.length})
          </h3>
          {isAdmin && (
            <Button size="sm" onClick={addSlot} disabled={saving || users.length === 0}
              className="rounded-md bg-indigo-600 hover:bg-indigo-700 text-white text-xs h-7 gap-1"
              data-testid="add-slot-btn">
              <Plus size={12} weight="bold" /> Aggiungi turno
            </Button>
          )}
        </div>

        {cfg.slots.length === 0 ? (
          <p className="text-[var(--text-muted)] text-xs text-center py-6">
            Nessun turno configurato. Clicca "Aggiungi turno" per iniziare.
          </p>
        ) : (
          <div className="space-y-2">
            {cfg.slots.map((slot) => (
              <div key={slot.id} className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto_auto_auto] gap-2 items-center p-2 rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)]"
                data-testid={`slot-${slot.id}`}>
                <div>
                  <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Giorno</Label>
                  <Select value={String(slot.day_of_week)}
                    onValueChange={(v) => { updateSlot(slot.id, { day_of_week: parseInt(v, 10) }); save({ ...cfg, slots: cfg.slots.map(s => s.id === slot.id ? { ...s, day_of_week: parseInt(v, 10) } : s) }); }}
                    disabled={!isAdmin}>
                    <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                      {DAYS.map((d, i) => <SelectItem key={i} value={String(i)} className="text-xs">{d}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Operatore</Label>
                  <Select value={slot.user_id}
                    onValueChange={(v) => { const u = users.find(x => x.id === v); save({ ...cfg, slots: cfg.slots.map(s => s.id === slot.id ? { ...s, user_id: v, user_email: u?.email || "" } : s) }); }}
                    disabled={!isAdmin}>
                    <SelectTrigger className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                      {users.map(u => <SelectItem key={u.id} value={u.id} className="text-xs">{u.name} · {u.role}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Dalle</Label>
                  <Input type="time" value={slot.start}
                    disabled={!isAdmin}
                    onChange={(e) => updateSlot(slot.id, { start: e.target.value })}
                    onBlur={() => commitSlot(slot.id)}
                    className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-8 w-24"
                    data-testid={`slot-start-${slot.id}`} />
                </div>
                <div>
                  <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Alle</Label>
                  <Input type="time" value={slot.end}
                    disabled={!isAdmin}
                    onChange={(e) => updateSlot(slot.id, { end: e.target.value })}
                    onBlur={() => commitSlot(slot.id)}
                    className="bg-[var(--bg-panel)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-8 w-24"
                    data-testid={`slot-end-${slot.id}`} />
                </div>
                {isAdmin && (
                  <button onClick={() => removeSlot(slot.id)} disabled={saving}
                    className="p-1.5 rounded-md hover:bg-[var(--critical-bg)] text-[var(--critical)] transition-colors self-end"
                    title="Rimuovi turno" data-testid={`remove-slot-${slot.id}`}>
                    <Trash size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <p className="text-[9px] text-[var(--text-muted)] mt-3 pt-3 border-t border-[var(--bg-border)]">
          Fuso orario: <span className="font-mono">{cfg.timezone}</span> · Turni overnight (es. 22:00→07:00) supportati automaticamente.
        </p>
      </div>

      {/* Escalation automatica */}
      <div className="noc-panel p-4 mt-4" data-testid="escalation-card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest flex items-center gap-1.5">
            <ArrowUp size={13} weight="bold" /> Escalation automatica
          </h3>
          {isAdmin && escCfg.enabled && (
            <Button size="sm" variant="outline" disabled={escBusy}
              onClick={triggerEscalation}
              className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)] gap-1"
              data-testid="trigger-escalation-btn">
              <ArrowClockwise size={12} /> Esegui ora
            </Button>
          )}
        </div>
        <p className="text-[var(--text-muted)] text-[10px] mb-3">
          Se un alert <b>critical</b> non viene preso in carico (ACK) entro la finestra, viene inviata una nuova push ai ruoli indicati con tag "ESCALATION".
        </p>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Label className="text-[var(--text-primary)] text-xs font-medium">Abilita escalation</Label>
            <Switch
              checked={escCfg.enabled}
              disabled={escBusy || !isAdmin}
              onCheckedChange={(v) => saveEsc({ ...escCfg, enabled: v })}
              data-testid="escalation-toggle"
            />
          </div>
          <div className={`grid grid-cols-2 gap-3 ${escCfg.enabled ? "" : "opacity-50 pointer-events-none"}`}>
            <div className="space-y-1.5">
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Attesa (minuti)</Label>
              <Input type="number" min={1} max={1440} value={escCfg.wait_minutes}
                disabled={!isAdmin}
                onChange={(e) => setEscCfg(c => ({ ...c, wait_minutes: parseInt(e.target.value || "5", 10) }))}
                onBlur={() => saveEsc()}
                className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8"
                data-testid="escalation-wait-input" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Escala a ruolo</Label>
              <Select value={escCfg.escalate_to_roles?.[0] || "admin"}
                onValueChange={(v) => saveEsc({ ...escCfg, escalate_to_roles: [v] })}
                disabled={!isAdmin}>
                <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] text-xs h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                  <SelectItem value="admin" className="text-xs">Admin</SelectItem>
                  <SelectItem value="operator" className="text-xs">Operator</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <p className="text-[9px] text-[var(--text-muted)] pt-1 border-t border-[var(--bg-border)]">
            Severity monitorate: <span className="font-mono">{escCfg.severities?.join(", ") || "critical"}</span>
          </p>
        </div>
      </div>
    </div>
  );
}
