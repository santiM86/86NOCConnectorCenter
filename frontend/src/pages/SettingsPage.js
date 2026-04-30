import { useState, useEffect } from "react";
import axios from "axios";
import { API, useAuth } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Gear, ShieldCheck, Bell, Key, BellRinging, BellSlash, Moon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { usePwa } from "@/components/PwaProvider";

export default function SettingsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const pwa = usePwa();
  const [pushStatus, setPushStatus] = useState({ configured: false, active_subscriptions: 0 });
  const [pushBusy, setPushBusy] = useState(false);
  const [prefs, setPrefs] = useState({
    quiet_hours_enabled: false,
    quiet_start: "22:00",
    quiet_end: "07:00",
    quiet_timezone: "Europe/Rome",
    quiet_exclude_critical: true,
  });
  const [prefsBusy, setPrefsBusy] = useState(false);

  useEffect(() => {
    axios.get(`${API}/push/status`).then(r => setPushStatus(r.data)).catch(() => {});
    axios.get(`${API}/push/preferences`).then(r => setPrefs(p => ({ ...p, ...r.data }))).catch(() => {});
  }, []);

  const refreshPush = async () => {
    try {
      const r = await axios.get(`${API}/push/status`);
      setPushStatus(r.data);
    } catch {}
  };

  const enablePush = async () => {
    setPushBusy(true);
    try {
      if (!pwa) { toast.error("PWA non inizializzata"); return; }
      const perm = await pwa.requestNotificationPermission();
      if (perm !== "granted") {
        toast.error("Permesso notifiche negato dal browser");
        return;
      }
      const sub = await pwa.subscribeToPush();
      if (sub) {
        toast.success("Notifiche push attivate");
        await refreshPush();
      } else {
        toast.error("Impossibile attivare le notifiche push");
      }
    } finally {
      setPushBusy(false);
    }
  };

  const disablePush = async () => {
    setPushBusy(true);
    try {
      const ok = await pwa.unsubscribeFromPush();
      if (ok) {
        toast.success("Notifiche push disattivate");
        await refreshPush();
      } else {
        toast.error("Errore durante la disattivazione");
      }
    } finally {
      setPushBusy(false);
    }
  };

  const testPush = async () => {
    setPushBusy(true);
    try {
      const res = await pwa.sendTestPush();
      if (res?.success && (res.sent ?? 0) > 0) {
        toast.success(`Notifica di test inviata (${res.sent})`);
      } else if (res?.reason === "vapid_not_configured") {
        toast.error("Web Push non configurato lato server");
      } else {
        toast.error("Nessuna sottoscrizione attiva - attiva prima le notifiche");
      }
    } finally {
      setPushBusy(false);
    }
  };

  const savePrefs = async (next) => {
    setPrefsBusy(true);
    try {
      const body = next || prefs;
      const r = await axios.put(`${API}/push/preferences`, body);
      if (r.data?.success) {
        setPrefs(body);
        toast.success("Preferenze salvate");
      } else {
        toast.error("Errore nel salvataggio");
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nel salvataggio");
    } finally {
      setPrefsBusy(false);
    }
  };

  const pushEnabled = pushStatus.active_subscriptions > 0 && pwa?.notificationPermission === "granted";

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="settings-page">
      <div className="mb-5">
        <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Impostazioni</h1>
        <p className="text-[var(--text-muted)] text-xs mt-0.5">Profilo, sicurezza e notifiche</p>
      </div>

      <div className="space-y-4 max-w-lg">
        <div className="noc-panel p-5">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <Gear size={13} /> Profilo
          </h3>
          <div className="space-y-2">
            <SettingRow label="Nome" value={user?.name} />
            <SettingRow label="Email" value={user?.email} mono />
            <SettingRow label="Ruolo" value={user?.role?.toUpperCase()} />
          </div>
        </div>

        <div className="noc-panel p-5">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <ShieldCheck size={13} /> Sicurezza
          </h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">Autenticazione 2FA</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  {user?.two_factor_enabled ? "Attiva - La verifica TOTP è abilitata" : "Non attiva - Si consiglia di abilitarla"}
                </p>
              </div>
              <Button size="sm" variant="outline"
                onClick={() => navigate("/2fa")}
                className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                data-testid="manage-2fa-btn">
                {user?.two_factor_enabled ? "Gestisci" : "Attiva"}
              </Button>
            </div>
            <div className="flex items-center justify-between pt-3 border-t border-[var(--bg-border)]">
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">IP Pubblici Autorizzati</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  Limita l'accesso al Center solo da IP/range autorizzati (military-grade allowlist).
                </p>
              </div>
              <Button size="sm" variant="outline"
                onClick={() => navigate("/settings/ip-allowlist")}
                className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                data-testid="manage-ip-allowlist-btn">
                Gestisci
              </Button>
            </div>
            <div className="flex items-center justify-between pt-3 border-t border-[var(--bg-border)]">
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">VPN WireGuard (Accesso Remoto)</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  Tunnel on-demand verso i dispositivi del cliente con crittografia ChaCha20-Poly1305.
                </p>
              </div>
              <Button size="sm" variant="outline"
                onClick={() => navigate("/settings/wireguard")}
                className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                data-testid="manage-wireguard-btn">
                Gestisci
              </Button>
            </div>
            <div className="flex items-center justify-between pt-3 border-t border-[var(--bg-border)]">
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">Hornetsecurity 365 Backup</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  Monitoraggio backup Microsoft 365 (Mailbox, OneDrive, SharePoint, Teams) per tutti i tenant.
                </p>
              </div>
              <Button size="sm" variant="outline"
                onClick={() => navigate("/settings/hornetsecurity")}
                className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                data-testid="manage-hornetsecurity-btn">
                Gestisci
              </Button>
            </div>
            <div className="flex items-center justify-between pt-3 border-t border-[var(--bg-border)]">
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">Cifratura &amp; Master Key</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  AES-256-GCM, salt random per deployment, 600k iter PBKDF2. Migrazione legacy + rotazione master key.
                </p>
              </div>
              <Button size="sm" variant="outline"
                onClick={() => navigate("/settings/encryption")}
                className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                data-testid="manage-encryption-btn">
                Gestisci
              </Button>
            </div>
            <div className="flex items-center justify-between pt-3 border-t border-[var(--bg-border)]">
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">Audit &amp; Security Events</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  Login falliti, IP bloccati per brute-force, eventi critici, top IP — visibilita` real-time.
                </p>
              </div>
              <Button size="sm" variant="outline"
                onClick={() => navigate("/settings/audit")}
                className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                data-testid="manage-audit-btn">
                Apri
              </Button>
            </div>
          </div>
        </div>

        <div className="noc-panel p-5" data-testid="push-notifications-card">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <Bell size={13} /> Notifiche Push
          </h3>
          {!pushStatus.configured ? (
            <p className="text-[var(--text-muted)] text-xs">
              Web Push non configurato. Contatta l'amministratore.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <p className="text-[var(--text-primary)] text-xs font-medium flex items-center gap-1.5">
                    {pushEnabled ? <BellRinging size={13} className="text-emerald-400" /> : <BellSlash size={13} className="text-[var(--text-muted)]" />}
                    {pushEnabled ? "Attive su questo dispositivo" : "Non attive"}
                  </p>
                  <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                    Ricevi alert (critical/high) sul browser e PWA anche se l'app è chiusa.
                  </p>
                  <p className="text-[var(--text-muted)] text-[10px] mt-1">
                    Dispositivi sottoscritti: <span className="font-mono text-[var(--text-primary)]">{pushStatus.active_subscriptions}</span>
                  </p>
                </div>
                {pushEnabled ? (
                  <Button size="sm" variant="outline" disabled={pushBusy}
                    onClick={disablePush}
                    className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                    data-testid="disable-push-btn">
                    Disattiva
                  </Button>
                ) : (
                  <Button size="sm" disabled={pushBusy}
                    onClick={enablePush}
                    className="rounded-md text-xs h-7 bg-indigo-600 hover:bg-indigo-700 text-white"
                    data-testid="enable-push-btn">
                    Attiva
                  </Button>
                )}
              </div>
              {pushEnabled && (
                <div className="pt-2 border-t border-[var(--bg-border)]">
                  <Button size="sm" variant="outline" disabled={pushBusy}
                    onClick={testPush}
                    className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)] gap-1.5"
                    data-testid="test-push-btn">
                    <Bell size={12} /> Invia notifica di test
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="noc-panel p-5" data-testid="quiet-hours-card">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <Moon size={13} /> Notte silenziosa (Quiet Hours)
          </h3>
          <p className="text-[var(--text-muted)] text-[10px] mb-3">
            Durante la finestra impostata non riceverai notifiche push (utile per evitare sveglie notturne). I CRITICAL possono bypassare la quiet window.
          </p>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor="qh-enabled" className="text-[var(--text-primary)] text-xs font-medium">Attiva Quiet Hours</Label>
              <Switch
                id="qh-enabled"
                checked={prefs.quiet_hours_enabled}
                disabled={prefsBusy}
                onCheckedChange={(v) => savePrefs({ ...prefs, quiet_hours_enabled: v })}
                data-testid="quiet-hours-toggle"
              />
            </div>
            <div className={`grid grid-cols-2 gap-3 ${prefs.quiet_hours_enabled ? "" : "opacity-50 pointer-events-none"}`}>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Dalle</Label>
                <Input type="time" value={prefs.quiet_start}
                  onChange={(e) => setPrefs(p => ({ ...p, quiet_start: e.target.value }))}
                  onBlur={() => savePrefs()}
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8"
                  data-testid="quiet-start-input" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Alle</Label>
                <Input type="time" value={prefs.quiet_end}
                  onChange={(e) => setPrefs(p => ({ ...p, quiet_end: e.target.value }))}
                  onBlur={() => savePrefs()}
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8"
                  data-testid="quiet-end-input" />
              </div>
            </div>
            <div className={`flex items-center justify-between ${prefs.quiet_hours_enabled ? "" : "opacity-50 pointer-events-none"}`}>
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">Bypass per CRITICAL</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  Ricevi comunque gli alert critici durante la notte silenziosa
                </p>
              </div>
              <Switch
                checked={prefs.quiet_exclude_critical}
                disabled={prefsBusy}
                onCheckedChange={(v) => savePrefs({ ...prefs, quiet_exclude_critical: v })}
                data-testid="quiet-exclude-critical-toggle"
              />
            </div>
            <p className="text-[var(--text-muted)] text-[9px] pt-1 border-t border-[var(--bg-border)]">
              Fuso orario: <span className="font-mono">{prefs.quiet_timezone}</span>
            </p>
          </div>
        </div>

        <div className="noc-panel p-5">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <Key size={13} /> API Keys
          </h3>
          <p className="text-[var(--text-muted)] text-xs">
            Usa le API keys dei clienti per inviare trap SNMP e syslog al sistema.
          </p>
        </div>
      </div>
    </div>
  );
}

function SettingRow({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--bg-border)] last:border-0">
      <span className="text-[var(--text-muted)] text-xs">{label}</span>
      <span className={`text-[var(--text-primary)] text-xs ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}
