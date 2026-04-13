import { useState } from "react";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";
import { Lock, ShieldCheck } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export function SnmpConfigPanel({ clientId, deviceId, device, onUpdated }) {
  const [snmpVersion, setSnmpVersion] = useState(device?.snmp_version || "v2c");
  const [community, setCommunity] = useState(device?.community || "public");
  const [v3, setV3] = useState({
    username: device?.snmpv3_username || "",
    auth_protocol: device?.snmpv3_auth_protocol || "SHA",
    auth_password: device?.snmpv3_auth_password || "",
    priv_protocol: device?.snmpv3_priv_protocol || "AES",
    priv_password: device?.snmpv3_priv_password || "",
    security_level: device?.snmpv3_security_level || "authPriv",
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
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
      await axios.put(`${API}/connector/${clientId}/managed-devices/${deviceId}/snmp`, payload);
      toast.success("Configurazione SNMP aggiornata");
      if (onUpdated) onUpdated();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore nel salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const secLevelLabels = {
    noAuthNoPriv: "No Auth, No Privacy",
    authNoPriv: "Auth, No Privacy",
    authPriv: "Auth + Privacy (Consigliato)",
  };

  return (
    <div className="space-y-3" data-testid="snmp-config-panel">
      <div className="flex items-center gap-2 mb-2">
        <Lock size={14} className="text-indigo-400" />
        <span className="text-xs font-semibold text-[var(--text-primary)]">Configurazione SNMP</span>
        {snmpVersion === "v3" && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-semibold">
            <ShieldCheck size={10} weight="fill" className="inline mr-0.5" />v3 SICURO
          </span>
        )}
      </div>

      {/* SNMP Version */}
      <div className="space-y-1">
        <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Versione SNMP</Label>
        <Select value={snmpVersion} onValueChange={setSnmpVersion}>
          <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7" data-testid="snmp-version-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
            <SelectItem value="v1" className="text-xs">v1 (Legacy)</SelectItem>
            <SelectItem value="v2c" className="text-xs">v2c (Community String)</SelectItem>
            <SelectItem value="v3" className="text-xs">v3 (USM - Auth + Privacy)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* v1/v2c: Community */}
      {snmpVersion !== "v3" && (
        <div className="space-y-1">
          <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Community String</Label>
          <Input
            value={community} onChange={e => setCommunity(e.target.value)}
            placeholder="public"
            className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7"
            data-testid="snmp-community-input"
          />
        </div>
      )}

      {/* v3: USM Fields */}
      {snmpVersion === "v3" && (
        <div className="space-y-2 bg-[var(--bg-app)] rounded-lg p-3 border border-[var(--bg-border)]">
          <div className="space-y-1">
            <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Security Level</Label>
            <Select value={v3.security_level} onValueChange={v => setV3(p => ({ ...p, security_level: v }))}>
              <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7" data-testid="snmpv3-security-level">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                <SelectItem value="noAuthNoPriv" className="text-xs">noAuthNoPriv</SelectItem>
                <SelectItem value="authNoPriv" className="text-xs">authNoPriv</SelectItem>
                <SelectItem value="authPriv" className="text-xs">authPriv (Consigliato)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[9px] text-[var(--text-muted)]">{secLevelLabels[v3.security_level]}</p>
          </div>

          <div className="space-y-1">
            <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Username USM *</Label>
            <Input
              value={v3.username} onChange={e => setV3(p => ({ ...p, username: e.target.value }))}
              placeholder="snmpv3user" required
              className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7"
              data-testid="snmpv3-username-input"
            />
          </div>

          {v3.security_level !== "noAuthNoPriv" && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Auth Protocol</Label>
                  <Select value={v3.auth_protocol} onValueChange={v => setV3(p => ({ ...p, auth_protocol: v }))}>
                    <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7" data-testid="snmpv3-auth-proto">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                      <SelectItem value="MD5" className="text-xs">MD5</SelectItem>
                      <SelectItem value="SHA" className="text-xs">SHA</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Auth Password</Label>
                  <Input
                    type="password"
                    value={v3.auth_password} onChange={e => setV3(p => ({ ...p, auth_password: e.target.value }))}
                    placeholder="min 8 caratteri"
                    className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7"
                    data-testid="snmpv3-auth-password"
                  />
                </div>
              </div>

              {v3.security_level === "authPriv" && (
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Privacy Protocol</Label>
                    <Select value={v3.priv_protocol} onValueChange={v => setV3(p => ({ ...p, priv_protocol: v }))}>
                      <SelectTrigger className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7" data-testid="snmpv3-priv-proto">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg">
                        <SelectItem value="DES" className="text-xs">DES</SelectItem>
                        <SelectItem value="AES" className="text-xs">AES-128</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[var(--text-muted)] text-[9px] uppercase tracking-widest">Privacy Password</Label>
                    <Input
                      type="password"
                      value={v3.priv_password} onChange={e => setV3(p => ({ ...p, priv_password: e.target.value }))}
                      placeholder="min 8 caratteri"
                      className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-7"
                      data-testid="snmpv3-priv-password"
                    />
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <Button size="sm" className="w-full h-7 text-xs rounded-md bg-indigo-600 hover:bg-indigo-700 text-white" onClick={handleSave} disabled={saving} data-testid="snmp-save-btn">
        {saving ? "Salvataggio..." : "Salva Configurazione SNMP"}
      </Button>
    </div>
  );
}
