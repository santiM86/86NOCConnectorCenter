import { useState } from "react";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";
import { PencilSimple, ShieldCheck, WifiHigh, Lightning, BellSlash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

/**
 * Modale di modifica rapida del dispositivo.
 * Riusa gli endpoint esistenti:
 *   - PUT /connector/{clientId}/managed-devices/{deviceId}/monitor-type
 *   - PUT /connector/{clientId}/managed-devices/{deviceId}/snmp
 * Nome e IP sono read-only (sono chiavi logiche: per cambiarli cancella e ri-aggiungi).
 */
export function DeviceEditModal({ clientId, device, open, onClose, onSaved }) {
  const [monitorType, setMonitorType] = useState(device?.monitor_type || "snmp");
  const [snmpVersion, setSnmpVersion] = useState(device?.snmp_version || "v2c");
  const [community, setCommunity] = useState(device?.snmp_community || device?.community || "public");
  const [v3, setV3] = useState({
    username: device?.snmpv3_username || "",
    auth_protocol: device?.snmpv3_auth_protocol || "SHA",
    auth_password: device?.snmpv3_auth_password || "",
    priv_protocol: device?.snmpv3_priv_protocol || "AES",
    priv_password: device?.snmpv3_priv_password || "",
    security_level: device?.snmpv3_security_level || "authPriv",
  });
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [alertsSilenced, setAlertsSilenced] = useState(!!device?.alerts_silenced);
  const [silenceReason, setSilenceReason] = useState(device?.alerts_silenced_reason || "");

  const save = async () => {
    if (!device?.id && !device?.device_id) {
      toast.error("ID dispositivo mancante");
      return;
    }
    const deviceId = device.id || device.device_id;
    setSaving(true);
    // Eseguo le 3 PUT in modo INDIPENDENTE: il fallimento di una non deve
    // impedire le altre. Il silence in particolare e` la modifica piu` semplice e
    // l'utente si aspetta che funzioni anche se monitor-type/snmp falliscono.
    const errors = [];
    let silencePersisted = false;

    // 1) Monitor type
    try {
      await axios.put(
        `${API}/connector/${clientId}/managed-devices/${deviceId}/monitor-type`,
        { monitor_type: monitorType }
      );
    } catch (e) {
      errors.push(`Metodo monitoraggio: ${e.response?.data?.detail || e.message}`);
    }

    // 2) SNMP config (solo se il tipo include SNMP)
    if (monitorType === "snmp" || monitorType === "snmp+http") {
      try {
        const payload = { snmp_version: snmpVersion };
        if (snmpVersion === "v3") {
          Object.assign(payload, {
            snmpv3_username: v3.username,
            snmpv3_auth_protocol: v3.auth_protocol,
            snmpv3_auth_password: v3.auth_password,
            snmpv3_priv_protocol: v3.priv_protocol,
            snmpv3_priv_password: v3.priv_password,
            snmpv3_security_level: v3.security_level,
          });
        } else {
          payload.community = community;
        }
        await axios.put(
          `${API}/connector/${clientId}/managed-devices/${deviceId}/snmp`,
          payload
        );
      } catch (e) {
        errors.push(`SNMP: ${e.response?.data?.detail || e.message}`);
      }
    }

    // 3) Silenziamento alert (sempre tentato, anche se 1/2 falliscono)
    const wasSilenced = !!device?.alerts_silenced;
    const wasReason = device?.alerts_silenced_reason || "";
    const silenceDirty = alertsSilenced !== wasSilenced || silenceReason !== wasReason;
    if (silenceDirty) {
      try {
        await axios.put(
          `${API}/connector/${clientId}/managed-devices/${deviceId}/silence`,
          { silenced: alertsSilenced, reason: silenceReason }
        );
        silencePersisted = true;
      } catch (e) {
        errors.push(`Silenzio alert: ${e.response?.data?.detail || e.message}`);
      }
    }

    setSaving(false);

    if (errors.length > 0) {
      toast.error(`Errori durante il salvataggio: ${errors.join(" | ")}`);
      return;
    }
    if (silencePersisted) {
      toast.success(alertsSilenced
        ? "Alert SILENZIATI per questo device. Eventuali alert già aperti restano e vanno risolti manualmente."
        : "Alert RIATTIVATI per questo device.");
    } else {
      toast.success("Dispositivo aggiornato. Clicca 'Applica ora' per forzare il connector a ri-leggere immediatamente.");
    }
    if (onSaved) onSaved();
  };

  const applyNow = async () => {
    setRefreshing(true);
    try {
      const res = await axios.post(`${API}/connector/${clientId}/request-refresh`);
      toast.success(res.data?.message || "Richiesta inviata al connector");
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nella richiesta refresh");
    } finally {
      setRefreshing(false);
    }
  };

  const isSnmp = monitorType === "snmp" || monitorType === "snmp+http";

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg max-w-md"
        data-testid="device-edit-modal"
      >
        <DialogHeader>
          <DialogTitle className="font-heading text-[var(--text-primary)] text-sm flex items-center gap-2">
            <PencilSimple size={16} className="text-indigo-400" />
            Modifica Dispositivo
          </DialogTitle>
        </DialogHeader>

        {/* Info read-only */}
        <div className="bg-[var(--bg-card)] border border-[var(--bg-border)] rounded px-3 py-2 space-y-1">
          <div className="flex justify-between text-[10px] uppercase tracking-wider">
            <span className="text-[var(--text-muted)]">Nome</span>
            <span className="text-[var(--text-primary)] font-semibold">{device?.name}</span>
          </div>
          <div className="flex justify-between text-[10px] uppercase tracking-wider">
            <span className="text-[var(--text-muted)]">IP</span>
            <span className="text-[var(--text-primary)] font-mono">{device?.ip_address || device?.ip}</span>
          </div>
          <p className="text-[9px] text-[var(--text-muted)] italic pt-1">
            Per modificare nome/IP, rimuovi il dispositivo e ri-aggiungilo.
          </p>
        </div>

        <div className="space-y-3 mt-2">
          {/* Monitor type */}
          <div className="space-y-1.5">
            <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest flex items-center gap-1">
              <WifiHigh size={11} /> Metodo di monitoraggio
            </Label>
            <Select value={monitorType} onValueChange={setMonitorType}>
              <SelectTrigger
                className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs"
                data-testid="edit-monitor-type"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                <SelectItem value="ping">Ping (reachability only)</SelectItem>
                <SelectItem value="snmp">SNMP</SelectItem>
                <SelectItem value="http">HTTP</SelectItem>
                <SelectItem value="snmp+http">SNMP + HTTP (ibrido)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {isSnmp && (
            <>
              <div className="space-y-1.5">
                <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest flex items-center gap-1">
                  <ShieldCheck size={11} /> Versione SNMP
                </Label>
                <Select value={snmpVersion} onValueChange={setSnmpVersion}>
                  <SelectTrigger
                    className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs"
                    data-testid="edit-snmp-version"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                    <SelectItem value="v1">v1</SelectItem>
                    <SelectItem value="v2c">v2c (Community String)</SelectItem>
                    <SelectItem value="v3">v3 (Auth + Priv)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {snmpVersion !== "v3" ? (
                <div className="space-y-1.5">
                  <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Community</Label>
                  <Input
                    value={community}
                    onChange={(e) => setCommunity(e.target.value)}
                    placeholder="public"
                    className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-8 text-xs font-mono"
                    data-testid="edit-snmp-community"
                  />
                  <p className="text-[9px] text-[var(--text-muted)] italic">
                    Case-sensitive. Deve corrispondere esattamente alla community configurata sul dispositivo.
                  </p>
                </div>
              ) : (
                <div className="space-y-2 border border-amber-500/30 bg-amber-500/5 rounded p-2">
                  <div className="space-y-1">
                    <Label className="text-[var(--text-muted)] text-[10px] uppercase">Username</Label>
                    <Input
                      value={v3.username}
                      onChange={(e) => setV3({ ...v3, username: e.target.value })}
                      className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-7 text-xs font-mono"
                      data-testid="edit-snmpv3-username"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-[var(--text-muted)] text-[10px] uppercase">Auth Protocol</Label>
                      <Select
                        value={v3.auth_protocol}
                        onValueChange={(v) => setV3({ ...v3, auth_protocol: v })}
                      >
                        <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] h-7 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                          <SelectItem value="MD5">MD5</SelectItem>
                          <SelectItem value="SHA">SHA</SelectItem>
                          <SelectItem value="SHA256">SHA256</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[var(--text-muted)] text-[10px] uppercase">Auth Password</Label>
                      <Input
                        type="password"
                        value={v3.auth_password}
                        onChange={(e) => setV3({ ...v3, auth_password: e.target.value })}
                        className="bg-[var(--bg-card)] border-[var(--bg-border)] h-7 text-xs font-mono"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-[var(--text-muted)] text-[10px] uppercase">Priv Protocol</Label>
                      <Select
                        value={v3.priv_protocol}
                        onValueChange={(v) => setV3({ ...v3, priv_protocol: v })}
                      >
                        <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] h-7 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                          <SelectItem value="DES">DES</SelectItem>
                          <SelectItem value="AES">AES</SelectItem>
                          <SelectItem value="AES256">AES256</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[var(--text-muted)] text-[10px] uppercase">Priv Password</Label>
                      <Input
                        type="password"
                        value={v3.priv_password}
                        onChange={(e) => setV3({ ...v3, priv_password: e.target.value })}
                        className="bg-[var(--bg-card)] border-[var(--bg-border)] h-7 text-xs font-mono"
                      />
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Silenziamento alert per device — utile per stampanti che vanno offline la sera */}
          <div className={`rounded p-2.5 border transition-colors ${alertsSilenced ? "bg-amber-500/10 border-amber-500/40" : "bg-[var(--bg-card)] border-[var(--bg-border)]"}`}>
            <label className="flex items-start gap-2 cursor-pointer" data-testid="silence-toggle-label">
              <input
                type="checkbox"
                checked={alertsSilenced}
                onChange={(e) => setAlertsSilenced(e.target.checked)}
                className="mt-0.5 cursor-pointer"
                data-testid="silence-toggle"
              />
              <span className="flex-1">
                <span className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-300">
                  <BellSlash size={13} weight="fill" />
                  Silenzia alert per questo dispositivo
                </span>
                <span className="block text-[9px] text-[var(--text-muted)] mt-0.5 leading-relaxed">
                  Il device viene comunque monitorato ed appare nelle dashboard, ma <strong>nessun nuovo alert</strong>{" "}
                  (offline, errori, soglia, syslog, SNMP trap, iLO) verra` generato.
                  Gli alert gia` aperti restano e vanno risolti manualmente.
                </span>
              </span>
            </label>
            {alertsSilenced && (
              <div className="mt-2 pl-5">
                <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-wider">Motivo (opzionale)</Label>
                <Input
                  value={silenceReason}
                  onChange={(e) => setSilenceReason(e.target.value)}
                  placeholder="Es. stampante ufficio — spenta dopo 19:00"
                  className="bg-[var(--bg-card)] border-amber-500/30 text-[var(--text-primary)] h-7 text-xs mt-0.5"
                  maxLength={200}
                  data-testid="silence-reason"
                />
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2 justify-end mt-4">
          <Button
            variant="ghost"
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] h-8 text-xs"
            data-testid="edit-cancel-btn"
          >
            Chiudi
          </Button>
          <Button
            onClick={applyNow}
            disabled={refreshing || saving}
            variant="outline"
            className="border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 h-8 text-xs"
            title="Forza il connector a ri-leggere subito la lista dispositivi con la nuova config (max 30s di attesa)"
            data-testid="edit-apply-now-btn"
          >
            <Lightning size={13} className="mr-1" />
            {refreshing ? "Invio..." : "Applica ora"}
          </Button>
          <Button
            onClick={save}
            disabled={saving || refreshing}
            className="bg-indigo-500 hover:bg-indigo-600 text-white h-8 text-xs"
            data-testid="edit-save-btn"
          >
            {saving ? "Salvataggio..." : "Salva"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
