import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Check, Copy, ArrowRight, SkipForward } from "@phosphor-icons/react";

const STEPS = ["Cliente", "Datto RMM", "Backup", "Monitor WAN", "Agent"];

export const NewClientWizard = ({ open, onClose, onCreated }) => {
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  // Step 1
  const [form, setForm] = useState({ name: "", description: "", contact_email: "" });
  const [client, setClient] = useState(null); // {id, api_key, name}
  // Step 2 Datto
  const [sites, setSites] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [seedDevices, setSeedDevices] = useState(true);
  // Step 3 Hornet
  const [tenants, setTenants] = useState([]);
  const [selTenants, setSelTenants] = useState(new Set());
  // Step 4 WAN
  const [wan, setWan] = useState({ label: "Firewall", device_type: "firewall", public_ip: "" });

  useEffect(() => {
    if (open) {
      setStep(1); setSaving(false);
      setForm({ name: "", description: "", contact_email: "" });
      setClient(null);
      setSites([]); setSiteId(""); setSeedDevices(true);
      setTenants([]); setSelTenants(new Set());
      setWan({ label: "Firewall", device_type: "firewall", public_ip: "" });
    }
  }, [open]);

  // Carica dati lazy al cambio step
  useEffect(() => {
    if (!client) return;
    if (step === 2 && sites.length === 0) {
      axios.get(`${API}/datto/sites`).then(r => setSites(r.data?.items || [])).catch(() => {});
    }
    if (step === 3 && tenants.length === 0) {
      axios.get(`${API}/admin/hornetsecurity/tenants`).then(r => setTenants(r.data?.tenants || r.data || [])).catch(() => {});
    }
    if (step === 4 && !wan.public_ip) {
      axios.get(`${API}/external-monitor/detected-public-ip/${client.id}`)
        .then(r => { if (r.data?.public_ip) setWan(w => ({ ...w, public_ip: r.data.public_ip })); })
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, client]);

  const createClient = async () => {
    if (!form.name.trim()) { toast.error("Il nome è obbligatorio"); return; }
    setSaving(true);
    try {
      const { data } = await axios.post(`${API}/clients`, form);
      setClient({ id: data.id, api_key: data.api_key, name: data.name });
      onCreated?.();
      toast.success(`Cliente "${data.name}" creato`);
      setStep(2);
    } catch (e) {
      toast.error(`Creazione fallita: ${e.response?.data?.detail || e.message}`);
    } finally { setSaving(false); }
  };

  const linkDatto = async () => {
    if (!siteId) { setStep(3); return; }
    setSaving(true);
    try {
      await axios.put(`${API}/clients/${client.id}/datto/link`, { site_id: siteId });
      if (seedDevices) {
        try { await axios.post(`${API}/clients/${client.id}/datto/seed-managed`, {}); } catch { /* opzionale */ }
      }
      toast.success("Sito Datto collegato");
      setStep(3);
    } catch (e) {
      toast.error(`Link Datto fallito: ${e.response?.data?.detail || e.message}`);
    } finally { setSaving(false); }
  };

  const saveHornet = async () => {
    if (selTenants.size === 0) { setStep(4); return; }
    setSaving(true);
    try {
      await axios.put(`${API}/clients/${client.id}/backup/hornetsecurity/mapping`, { tenants: Array.from(selTenants) });
      toast.success("Backup mappato al cliente");
      setStep(4);
    } catch (e) {
      toast.error(`Mapping backup fallito: ${e.response?.data?.detail || e.message}`);
    } finally { setSaving(false); }
  };

  const addWan = async () => {
    if (!wan.public_ip.trim()) { setStep(5); return; }
    setSaving(true);
    try {
      await axios.post(`${API}/external-monitor/targets`, {
        client_id: client.id, label: wan.label || "Firewall",
        device_type: wan.device_type, public_ip: wan.public_ip.trim(),
        check_ports: [443],
      });
      toast.success("Target WAN aggiunto");
      setStep(5);
    } catch (e) {
      toast.error(`Aggiunta WAN fallita: ${e.response?.data?.detail || e.message}`);
    } finally { setSaving(false); }
  };

  const installCmd = client ? (() => {
    const wsBase = (window.location.origin || "https://argus.86bit.it").replace(/^http/, "ws");
    const raw = "https://raw.githubusercontent.com/santiM86/86NOCConnectorCenter/main/noc-agent/build/install-noc-agent.ps1";
    return `powershell -ExecutionPolicy Bypass -Command "iwr -useb ${raw} -OutFile $env:TEMP\\i.ps1; & $env:TEMP\\i.ps1 -Token '${client.api_key}' -ClientId '${client.id}' -BackendUrl '${wsBase}/api/agent/ws' -Role master"`;
  })() : "";

  const copy = (txt, label) => { navigator.clipboard.writeText(txt); toast.success(`${label} copiato`); };

  const toggleTenant = (t) => {
    setSelTenants(prev => { const n = new Set(prev); n.has(t) ? n.delete(t) : n.add(t); return n; });
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] rounded-lg max-w-lg" data-testid="new-client-wizard">
        <DialogHeader>
          <DialogTitle className="font-heading text-[var(--text-primary)] text-sm">
            Nuovo Cliente {client ? `· ${client.name}` : ""}
          </DialogTitle>
          <DialogDescription className="text-[11px] text-[var(--text-muted)]">
            Configura tutto in un unico flusso. Ogni passo è saltabile: potrai completarlo dopo.
          </DialogDescription>
        </DialogHeader>

        {/* Stepper */}
        <div className="flex items-center gap-1 text-[10px] mb-1">
          {STEPS.map((s, i) => (
            <div key={s} className="flex items-center gap-1">
              <span className={`px-2 py-0.5 rounded-full border ${step === i + 1 ? "bg-indigo-600 text-white border-indigo-500" : step > i + 1 ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : "text-[var(--text-muted)] border-[var(--bg-border)]"}`}>
                {step > i + 1 ? <Check size={9} className="inline" /> : i + 1} {s}
              </span>
              {i < STEPS.length - 1 && <span className="text-[var(--text-muted)]">›</span>}
            </div>
          ))}
        </div>

        <div className="mt-1 space-y-3 min-h-[200px]">
          {step === 1 && (
            <div className="space-y-3" data-testid="wizard-step-client">
              <Field label="Nome *"><Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Acme Corp" className={inputCls} data-testid="client-name-input" /></Field>
              <Field label="Descrizione"><Input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="Cliente enterprise" className={inputCls} data-testid="client-description-input" /></Field>
              <Field label="Email"><Input type="email" value={form.contact_email} onChange={e => setForm(f => ({ ...f, contact_email: e.target.value }))} placeholder="it@acme.com" className={inputCls} data-testid="client-email-input" /></Field>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3" data-testid="wizard-step-datto">
              <Field label="Sito Datto RMM da collegare">
                <Select value={siteId} onValueChange={setSiteId}>
                  <SelectTrigger className={inputCls} data-testid="wizard-datto-site"><SelectValue placeholder={sites.length ? "Seleziona sito..." : "Nessun sito (Datto non configurato)"} /></SelectTrigger>
                  <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)] max-h-64">
                    {sites.map(s => <SelectItem key={s.site_id} value={s.site_id} className="text-xs">{s.site_name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </Field>
              <label className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)] cursor-pointer">
                <input type="checkbox" checked={seedDevices} onChange={e => setSeedDevices(e.target.checked)} data-testid="wizard-datto-seed" />
                Importa subito i dispositivi dal sito Datto
              </label>
              <p className="text-[10px] text-[var(--text-muted)]">Datto è configurato una sola volta a livello globale; qui colleghi il sito a questo cliente.</p>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-2" data-testid="wizard-step-hornet">
              <Label className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Tenant backup (Hornetsecurity / Altaro)</Label>
              <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
                {tenants.length === 0 && <span className="text-[11px] text-[var(--text-muted)]">Nessun tenant rilevato (backup globale non ancora popolato).</span>}
                {tenants.map(t => {
                  const name = t._id || t.tenant || t;
                  const active = selTenants.has(name);
                  return (
                    <button key={name} type="button" onClick={() => toggleTenant(name)} data-testid={`wizard-tenant-${name}`}
                      className={`px-2 py-1 rounded text-[11px] border ${active ? "bg-indigo-600 text-white border-indigo-500" : "bg-[var(--bg-card)] text-[var(--text-secondary)] border-[var(--bg-border)]"}`}>
                      {active && <Check size={10} className="inline mr-1" />}{name}
                    </button>
                  );
                })}
              </div>
              <p className="text-[10px] text-[var(--text-muted)]">Mappa il cliente a uno o più tenant già presenti sul vostro account Hornetsecurity.</p>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-3" data-testid="wizard-step-wan">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Etichetta"><Input value={wan.label} onChange={e => setWan(w => ({ ...w, label: e.target.value }))} placeholder="Firewall Zyxel" className={inputCls} data-testid="wizard-wan-label" /></Field>
                <Field label="Tipo">
                  <Select value={wan.device_type} onValueChange={v => setWan(w => ({ ...w, device_type: v }))}>
                    <SelectTrigger className={inputCls}><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-[var(--bg-panel)] border-[var(--bg-border)]">
                      <SelectItem value="firewall" className="text-xs">Firewall</SelectItem>
                      <SelectItem value="router" className="text-xs">Router</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              </div>
              <Field label="IP pubblico WAN"><Input value={wan.public_ip} onChange={e => setWan(w => ({ ...w, public_ip: e.target.value }))} placeholder="85.42.xxx.xxx" className={inputCls} data-testid="wizard-wan-ip" /></Field>
              <p className="text-[10px] text-[var(--text-muted)]">Se un agent è già online, l'IP viene rilevato in automatico.</p>
            </div>
          )}

          {step === 5 && client && (
            <div className="space-y-3" data-testid="wizard-step-agent">
              <Field label="API Key cliente">
                <div className="flex items-center gap-2">
                  <Input readOnly value={client.api_key} className={`${inputCls} font-mono`} data-testid="wizard-agent-key" />
                  <Button type="button" variant="outline" className="h-8 px-2" onClick={() => copy(client.api_key, "API Key")}><Copy size={13} /></Button>
                </div>
              </Field>
              <Field label="Comando di installazione agent (PowerShell admin)">
                <div className="flex items-start gap-2">
                  <textarea readOnly value={installCmd} className="w-full h-24 bg-[var(--bg-card)] border border-[var(--bg-border)] rounded-md text-[10px] font-mono p-2 text-[var(--text-secondary)]" data-testid="wizard-agent-cmd" />
                  <Button type="button" variant="outline" className="h-8 px-2" onClick={() => copy(installCmd, "Comando")}><Copy size={13} /></Button>
                </div>
              </Field>
              <p className="text-[10px] text-[var(--text-muted)]">Esegui sul server del cliente come amministratore per installare l'agent.</p>
            </div>
          )}
        </div>

        {/* Footer navigazione */}
        <div className="flex justify-between items-center pt-2 border-t border-[var(--bg-border)]">
          <Button type="button" variant="ghost" size="sm" className="text-xs text-[var(--text-muted)]" onClick={onClose} data-testid="wizard-close">
            {step === 5 ? "Fine" : "Chiudi"}
          </Button>
          <div className="flex gap-2">
            {step === 1 && (
              <Button size="sm" disabled={saving} onClick={createClient} className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs gap-1" data-testid="wizard-create-client">
                {saving ? "..." : <>Crea e continua <ArrowRight size={12} /></>}
              </Button>
            )}
            {step === 2 && client && (
              <>
                <Button size="sm" variant="ghost" className="text-xs gap-1" onClick={() => setStep(3)} data-testid="wizard-skip-datto"><SkipForward size={12} /> Salta</Button>
                <Button size="sm" disabled={saving} onClick={linkDatto} className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="wizard-next-datto">{siteId ? "Collega e continua" : "Continua"}</Button>
              </>
            )}
            {step === 3 && (
              <>
                <Button size="sm" variant="ghost" className="text-xs gap-1" onClick={() => setStep(4)} data-testid="wizard-skip-hornet"><SkipForward size={12} /> Salta</Button>
                <Button size="sm" disabled={saving} onClick={saveHornet} className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="wizard-next-hornet">{selTenants.size ? "Salva e continua" : "Continua"}</Button>
              </>
            )}
            {step === 4 && (
              <>
                <Button size="sm" variant="ghost" className="text-xs gap-1" onClick={() => setStep(5)} data-testid="wizard-skip-wan"><SkipForward size={12} /> Salta</Button>
                <Button size="sm" disabled={saving} onClick={addWan} className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs" data-testid="wizard-next-wan">{wan.public_ip ? "Aggiungi e continua" : "Continua"}</Button>
              </>
            )}
            {step === 5 && (
              <Button size="sm" onClick={onClose} className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs gap-1" data-testid="wizard-finish"><Check size={12} /> Completa</Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

const inputCls = "bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] rounded-md text-xs h-8";
const Field = ({ label, children }) => (
  <div className="space-y-1.5">
    <Label className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">{label}</Label>
    {children}
  </div>
);
