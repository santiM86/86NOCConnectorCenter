import { useState, useEffect } from "react";
import { API } from "@/App";
import axios from "axios";
import { toast } from "sonner";
import { PencilSimple, ShieldCheck, WifiHigh, Lightning, BellSlash, Power, Cpu, CheckCircle } from "@phosphor-icons/react";
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
  const [savedOk, setSavedOk] = useState(false);
  const [alertsSilenced, setAlertsSilenced] = useState(!!device?.alerts_silenced);
  const [silenceReason, setSilenceReason] = useState(device?.alerts_silenced_reason || "");
  // Alert opzionale "VM spenta inaspettatamente" (solo VM Hyper-V)
  const [vmAlertOnOff, setVmAlertOnOff] = useState(!!device?.hyperv_alert_on_off);
  // Tipo macchina (fisico / VM) — impostabile dall'admin
  const [virtualization, setVirtualization] = useState(device?.virtualization || "");
  const [hypervVmName, setHypervVmName] = useState(device?.hyperv_vm_name || "");
  const [hypervHostHint, setHypervHostHint] = useState(device?.hyperv_host_hint || "");
  const isVM = ["hyperv", "vmware", "vm_generic"].includes(virtualization);
  // Toggle "allerta VM spenta" utile se è una VM Hyper-V (snapshot già presente
  // OPPURE marcata manualmente come Hyper-V dall'admin)
  const isHyperVvm = !!device?.hyperv_state || virtualization === "hyperv";

  // Re-seed dello stato locale quando la prop `device` cambia.
  // Necessario perche` ClientOverviewPage refetch /api/devices dopo un Salva e
  // riapre il modal sullo STESSO componente con prop aggiornata: se non
  // re-seedo, il toggle resta sullo stato precedente. Stesso discorso quando
  // l'utente apre il modal su un altro device senza unmount.
  useEffect(() => {
    setMonitorType(device?.monitor_type || "snmp");
    setSnmpVersion(device?.snmp_version || "v2c");
    setCommunity(device?.snmp_community || device?.community || "public");
    setAlertsSilenced(!!device?.alerts_silenced);
    setSilenceReason(device?.alerts_silenced_reason || "");
    setVmAlertOnOff(!!device?.hyperv_alert_on_off);
    // AUTOFILL "tipo macchina": se il device NON ha ancora una classificazione
    // manuale ma l'agent l'ha gia' riconosciuto come VM Hyper-V (hyperv_state
    // presente dallo snapshot dell'host), precompiliamo i campi cosi' l'utente
    // non deve riscrivere tutto a mano. Restano modificabili.
    const persistedVirt = device?.virtualization || "";
    const detectedHV = !!device?.hyperv_state;
    const effVirt = persistedVirt || (detectedHV ? "hyperv" : "");
    setVirtualization(effVirt);
    setHypervVmName(
      device?.hyperv_vm_name || (effVirt === "hyperv" ? (device?.name || "") : "")
    );
    setHypervHostHint(
      device?.hyperv_host_hint || (effVirt === "hyperv" ? (device?.hyperv_host || "") : "")
    );
  }, [device?.id, device?.alerts_silenced, device?.alerts_silenced_reason, device?.monitor_type, device?.snmp_version, device?.snmp_community, device?.hyperv_alert_on_off, device?.virtualization, device?.hyperv_vm_name, device?.hyperv_host_hint, device?.hyperv_state, device?.hyperv_host, device?.name]);

  // Cambio "tipo macchina" con AUTOFILL: scegliendo Hyper-V precompila il nome
  // VM (col nome device) e l'host (se rilevato) quando i campi sono vuoti.
  const handleVirtChange = (v) => {
    setVirtualization(v);
    if (v === "hyperv") {
      setHypervVmName((prev) => prev || device?.name || "");
      setHypervHostHint((prev) => prev || device?.hyperv_host || "");
    }
  };

  // Reset conferma "salvato" quando cambia device o si riapre il modal.
  useEffect(() => { setSavedOk(false); }, [device?.id, open]);

  // Ricarica il device dal backend DOPO il salvataggio per confermare che le
  // modifiche siano state persistite (verifica reale, non ottimistica).
  const reloadSavedDevice = async () => {
    try {
      const ip = device?.ip_address || device?.ip;
      const { data } = await axios.get(`${API}/devices`, { params: { client_id: clientId } });
      const list = Array.isArray(data) ? data : (data?.devices || []);
      return list.find((d) => (d.ip_address || d.ip) === ip) || null;
    } catch {
      return null;
    }
  };

  // AUTOFILL SNMP: quando il device non ha ancora una community/versione
  // configurata (o usa il default generico), proponiamo i valori PIU' USATI
  // tra i dispositivi gia' configurati dello STESSO cliente. Resta modificabile.
  const [snmpSuggest, setSnmpSuggest] = useState(null);
  useEffect(() => {
    if (!open || !clientId) return;
    let cancelled = false;
    axios.get(`${API}/clients/${clientId}/snmp-defaults`).then(({ data }) => {
      if (cancelled || !data) return;
      setSnmpSuggest(data);
      const neverConfiguredComm = !device?.snmp_community && !device?.community;
      const communityIsDefault = (device?.snmp_community || device?.community || "public").toLowerCase() === "public";
      if (data.community && (neverConfiguredComm || communityIsDefault)) {
        setCommunity((prev) => (!prev || prev.toLowerCase() === "public" ? data.community : prev));
      }
      if (data.snmp_version && !device?.snmp_version) {
        setSnmpVersion((prev) => prev || data.snmp_version);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [open, clientId, device?.id, device?.snmp_community, device?.community, device?.snmp_version]);

  const buildOptimistic = () => ({
    ...device,
    alerts_silenced: alertsSilenced,
    alerts_silenced_reason: silenceReason,
    hyperv_alert_on_off: isHyperVvm ? vmAlertOnOff : device?.hyperv_alert_on_off,
    virtualization,
    hyperv_vm_name: virtualization === "hyperv" ? hypervVmName : "",
    hyperv_host_hint: virtualization === "hyperv" ? hypervHostHint : "",
    monitor_type: monitorType,
    snmp_version: snmpVersion,
    snmp_community: snmpVersion !== "v3" ? community : device?.snmp_community,
  });

  // Esegue TUTTE le PUT/POST di persistenza (senza toast/onSaved). Ritorna gli
  // errori raccolti + se il silence e' stato scritto. Usata sia da "Salva" sia
  // da "Applica ora" (che PRIMA salva, POI forza il refresh del connector).
  const persistChanges = async () => {
    const deviceId = device.id || device.device_id;
    // Eseguo le PUT in modo INDIPENDENTE: il fallimento di una non deve
    // impedire le altre. Il silence in particolare e` la modifica piu` semplice e
    // l'utente si aspetta che funzioni anche se monitor-type/snmp falliscono.
    const errors = [];
    let silencePersisted = false;

    // Calcolo dirty-state per evitare PUT inutili (riducono chiamate + non
    // generano toast errore quando il device e` solo in db.devices/poll_status
    // — gli endpoint /monitor-type e /snmp non hanno ancora il fallback
    // multi-source che invece /silence ha).
    const monitorDirty = monitorType !== (device?.monitor_type || "snmp");
    const snmpFieldsDirty = (
      snmpVersion !== (device?.snmp_version || "v2c") ||
      (snmpVersion !== "v3" && community !== (device?.snmp_community || device?.community || "public")) ||
      (snmpVersion === "v3" && (
        v3.username !== (device?.snmpv3_username || "") ||
        v3.auth_protocol !== (device?.snmpv3_auth_protocol || "SHA") ||
        v3.auth_password !== (device?.snmpv3_auth_password || "") ||
        v3.priv_protocol !== (device?.snmpv3_priv_protocol || "AES") ||
        v3.priv_password !== (device?.snmpv3_priv_password || "") ||
        v3.security_level !== (device?.snmpv3_security_level || "authPriv")
      ))
    );

    // 1) Monitor type — solo se cambiato
    if (monitorDirty) {
      try {
        await axios.put(
          `${API}/connector/${clientId}/managed-devices/${deviceId}/monitor-type`,
          { monitor_type: monitorType }
        );
      } catch (e) {
        errors.push(`Metodo monitoraggio: ${e.response?.data?.detail || e.message}`);
      }
    }

    // 2) SNMP config — solo se SNMP attivo E i field sono cambiati
    if ((monitorType === "snmp" || monitorType === "snmp+http") && snmpFieldsDirty) {
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

    // 4) Alert "VM spenta inaspettatamente" (solo VM Hyper-V, sempre tentato)
    const wasVmAlert = !!device?.hyperv_alert_on_off;
    if (isHyperVvm && vmAlertOnOff !== wasVmAlert) {
      try {
        await axios.post(
          `${API}/devices/by-ip/${encodeURIComponent(device?.ip_address || device?.ip)}/vm-alert`,
          { enabled: vmAlertOnOff, client_id: clientId }
        );
      } catch (e) {
        errors.push(`Alert VM spenta: ${e.response?.data?.detail || e.message}`);
      }
    }

    // 5) Tipo macchina (virtualization) — persistito se cambiato
    const virtDirty = virtualization !== (device?.virtualization || "")
      || hypervVmName !== (device?.hyperv_vm_name || "")
      || hypervHostHint !== (device?.hyperv_host_hint || "");
    if (virtDirty) {
      try {
        await axios.post(
          `${API}/devices/by-ip/${encodeURIComponent(device?.ip_address || device?.ip)}/virtualization`,
          {
            virtualization,
            hyperv_vm_name: virtualization === "hyperv" ? hypervVmName : "",
            hyperv_host_hint: virtualization === "hyperv" ? hypervHostHint : "",
            client_id: clientId,
          }
        );
      } catch (e) {
        errors.push(`Tipo macchina: ${e.response?.data?.detail || e.message}`);
      }
    }

    return { errors, silencePersisted };
  };

  const save = async () => {
    if (!device?.id && !device?.device_id) {
      toast.error("ID dispositivo mancante");
      return;
    }
    setSaving(true);
    const { errors, silencePersisted } = await persistChanges();

    if (errors.length > 0) {
      setSaving(false);
      toast.error(`Errori durante il salvataggio: ${errors.join(" | ")}`);
      return;
    }
    // Ricarica dal backend per CONFERMARE la persistenza (verifica reale).
    const confirmed = await reloadSavedDevice();
    setSaving(false);
    setSavedOk(true);
    if (silencePersisted) {
      toast.success(alertsSilenced
        ? "Alert SILENZIATI per questo device. Eventuali alert già aperti restano e vanno risolti manualmente."
        : "Alert RIATTIVATI per questo device.");
    } else {
      toast.success("Impostazioni salvate ✓");
    }
    // Mostra la conferma visiva ~1.4s, poi push update + chiudi/refresh parent.
    setTimeout(() => {
      if (onSaved) onSaved(confirmed || buildOptimistic());
    }, 1400);
  };

  const applyNow = async () => {
    if (!device?.id && !device?.device_id) {
      toast.error("ID dispositivo mancante");
      return;
    }
    setRefreshing(true);
    try {
      // FIX: prima "Applica ora" NON salvava (chiamava solo request-refresh) e
      // i parametri VM/SNMP/silence appena impostati andavano PERSI. Ora salva
      // PRIMA le modifiche pendenti, POI forza il refresh del connector.
      const { errors } = await persistChanges();
      if (errors.length > 0) {
        toast.error(`Errori durante il salvataggio: ${errors.join(" | ")}`);
        setRefreshing(false);
        return;
      }
      const res = await axios.post(`${API}/connector/${clientId}/request-refresh`);
      const confirmed = await reloadSavedDevice();
      setRefreshing(false);
      setSavedOk(true);
      toast.success(res.data?.message || "Impostazioni salvate ✓ — richiesta di refresh inviata al connector");
      setTimeout(() => {
        if (onSaved) onSaved(confirmed || buildOptimistic()); else onClose();
      }, 1400);
    } catch (e) {
      setRefreshing(false);
      toast.error(e.response?.data?.detail || "Errore nella richiesta refresh");
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
                  {snmpSuggest && snmpSuggest.community && snmpSuggest.community === community && (
                    <p className="text-[9px] text-cyan-400 flex items-center gap-1" data-testid="snmp-autofill-hint">
                      <Lightning size={9} weight="fill" />
                      Precompilato: {snmpSuggest.community_count} dispositivi di questo cliente usano «{snmpSuggest.community}»
                    </p>
                  )}
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

          {/* Tipo macchina (fisico / VM) — impostabile dall'admin */}
          <div className="rounded p-2.5 border bg-[var(--bg-card)] border-[var(--bg-border)] space-y-2" data-testid="virtualization-block">
            <label className="flex items-center gap-1.5 text-[11px] font-semibold text-cyan-300">
              <Cpu size={13} weight="bold" />
              Tipo macchina
              {device?.virtualization_auto_matched && (
                <span
                  className="ml-auto text-[9px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                  title="Rilevato automaticamente: l'host Hyper-V riporta questa VM. Cambia il valore per bloccare la scelta manuale."
                  data-testid="virtualization-auto-badge"
                >
                  ⚡ auto-rilevato
                </span>
              )}
            </label>
            <select
              value={virtualization}
              onChange={(e) => handleVirtChange(e.target.value)}
              className="w-full bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2 py-1.5 text-[12px] text-white focus:border-cyan-500 outline-none"
              data-testid="virtualization-select"
            >
              <option value="">— non impostato (fisico) —</option>
              <option value="physical">Server fisico</option>
              <option value="hyperv">VM Hyper-V</option>
              <option value="vmware">VM VMware</option>
              <option value="vm_generic">VM (generica)</option>
            </select>
            <span className="block text-[9px] text-[var(--text-muted)] leading-relaxed">
              Le VM sono <strong>escluse dalla lista "server senza credenziali iLO"</strong> (niente richiesta iLO inutile).
            </span>
            {virtualization === "hyperv" && (
              <div className="space-y-2 pt-1 border-t border-white/5">
                <div>
                  <label className="block text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-1">Nome VM su Hyper-V (Get-VM)</label>
                  <input
                    type="text"
                    value={hypervVmName}
                    onChange={(e) => setHypervVmName(e.target.value)}
                    placeholder={device?.name || "es. SRVDC"}
                    className="w-full bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2 py-1.5 text-[12px] text-white focus:border-cyan-500 outline-none"
                    data-testid="hyperv-vm-name-input"
                  />
                  <span className="block text-[9px] text-[var(--text-muted)] mt-0.5">
                    Compila solo se il nome VM sull'host <strong>NON coincide</strong> col nome del device. Serve per agganciare lo stato power-state.
                  </span>
                </div>
                <div>
                  <label className="block text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-1">Host Hyper-V (opzionale)</label>
                  <input
                    type="text"
                    value={hypervHostHint}
                    onChange={(e) => setHypervHostHint(e.target.value)}
                    placeholder="es. GALVANSRV"
                    className="w-full bg-[var(--bg-panel)] border border-[var(--bg-border)] rounded px-2 py-1.5 text-[12px] text-white focus:border-cyan-500 outline-none"
                    data-testid="hyperv-host-hint-input"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Alert opzionale "VM spenta inaspettatamente" — solo VM Hyper-V */}
          {isHyperVvm && (
            <div className={`rounded p-2.5 border transition-colors ${vmAlertOnOff ? "bg-rose-500/10 border-rose-500/40" : "bg-[var(--bg-card)] border-[var(--bg-border)]"}`}>
              <label className="flex items-start gap-2 cursor-pointer" data-testid="vm-alert-toggle-label">
                <input
                  type="checkbox"
                  checked={vmAlertOnOff}
                  onChange={(e) => setVmAlertOnOff(e.target.checked)}
                  className="mt-0.5 cursor-pointer"
                  data-testid="vm-alert-toggle"
                />
                <span className="flex-1">
                  <span className="flex items-center gap-1.5 text-[11px] font-semibold text-rose-300">
                    <Power size={13} weight="fill" />
                    Allerta se questa VM si spegne (deve restare sempre accesa)
                  </span>
                  <span className="block text-[9px] text-[var(--text-muted)] mt-0.5 leading-relaxed">
                    Stato Hyper-V attuale: <strong className="text-[var(--text-primary)]">{device?.hyperv_state || "n/d"}</strong>.
                    Se attivo e la VM risulta <strong>Off / Saved / Paused</strong> sull'host (spegnimento inatteso),
                    verra` generato un alert <strong>CRITICO</strong>. Se disattivo, una VM spenta e` considerata
                    spegnimento pianificato (nessun alert).
                  </span>
                </span>
              </label>
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-2 justify-end items-center mt-4">
          {savedOk && (
            <span
              className="mr-auto inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 animate-in fade-in duration-200"
              data-testid="device-saved-indicator"
            >
              <CheckCircle size={14} weight="fill" />
              Impostazioni salvate
            </span>
          )}
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
            disabled={refreshing || saving || savedOk}
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
            disabled={saving || refreshing || savedOk}
            className="bg-indigo-500 hover:bg-indigo-600 text-white h-8 text-xs"
            data-testid="edit-save-btn"
          >
            {savedOk ? "Salvato ✓" : saving ? "Salvataggio..." : "Salva"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
