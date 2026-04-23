import { useState } from "react";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";
import { PencilSimple, ShieldCheck, WifiHigh } from "@phosphor-icons/react";
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

  const save = async () => {
    if (!device?.id && !device?.device_id) {
      toast.error("ID dispositivo mancante");
      return;
    }
    const deviceId = device.id || device.device_id;
    setSaving(true);
    try {
      // 1) Monitor type
      await axios.put(
        `${API}/connector/${clientId}/managed-devices/${deviceId}/monitor-type`,
        { monitor_type: monitorType }
      );
      // 2) SNMP config (solo se il tipo include SNMP)
      if (monitorType === "snmp" || monitorType === "snmp+http") {
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
      }
      toast.success("Dispositivo aggiornato — il connector applichera' le modifiche al prossimo fetch (max 10 min)");
      if (onSaved) onSaved();
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore nel salvataggio");
    } finally {
      setSaving(false);
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
        </div>

        <div className="flex gap-2 justify-end mt-4">
          <Button
            variant="ghost"
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] h-8 text-xs"
            data-testid="edit-cancel-btn"
          >
            Annulla
          </Button>
          <Button
            onClick={save}
            disabled={saving}
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
