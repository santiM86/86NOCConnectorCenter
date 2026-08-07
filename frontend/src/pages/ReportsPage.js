import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import {
  FileText, Download, Calendar, Buildings, HardDrives,
  ArrowRight, Spinner, FilePdf, CheckCircle, Palette, UploadSimple, Trash
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function ReportsPage() {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [period, setPeriod] = useState("30");
  const [generating, setGenerating] = useState(false);

  // Branding white-label state
  const [branding, setBranding] = useState(null);
  const [brandName, setBrandName] = useState("");
  const [savingBrand, setSavingBrand] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);

  useEffect(() => {
    axios.get(`${API}/reports/list`).then(r => setClients(r.data)).catch(() => {});
  }, []);

  const loadBranding = async (cid) => {
    if (!cid) { setBranding(null); setBrandName(""); return; }
    try {
      const r = await axios.get(`${API}/reports/branding/${cid}`);
      setBranding(r.data);
      setBrandName(r.data.brand_name || "");
    } catch {
      setBranding(null); setBrandName("");
    }
  };

  useEffect(() => { loadBranding(selectedClient); /* eslint-disable-next-line */ }, [selectedClient]);

  const saveBrandName = async () => {
    if (!selectedClient) { toast.error("Seleziona un cliente"); return; }
    setSavingBrand(true);
    try {
      await axios.put(`${API}/reports/branding/${selectedClient}`, { brand_name: brandName });
      toast.success("Nome brand salvato");
      loadBranding(selectedClient);
    } catch {
      toast.error("Errore nel salvataggio del nome brand");
    } finally {
      setSavingBrand(false);
    }
  };

  const uploadLogo = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f || !selectedClient) { if (!selectedClient) toast.error("Seleziona un cliente"); return; }
    if (f.size > 1024 * 1024) { toast.error("Logo troppo grande (max 1 MB)"); return; }
    setUploadingLogo(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      await axios.post(`${API}/reports/branding/${selectedClient}/logo`, fd);
      toast.success("Logo caricato");
      loadBranding(selectedClient);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Errore nel caricamento del logo");
    } finally {
      setUploadingLogo(false);
    }
  };

  const removeLogo = async () => {
    if (!selectedClient) return;
    try {
      await axios.delete(`${API}/reports/branding/${selectedClient}/logo`);
      toast.success("Logo rimosso");
      loadBranding(selectedClient);
    } catch {
      toast.error("Errore nella rimozione del logo");
    }
  };

  const generateReport = async () => {
    if (!selectedClient) { toast.error("Seleziona un cliente"); return; }
    setGenerating(true);
    try {
      const response = await axios.get(
        `${API}/reports/generate/${selectedClient}?days=${period}`,
        { responseType: "blob" }
      );
      const url = window.URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
      const link = document.createElement("a");
      link.href = url;
      const clientName = clients.find(c => c.client_id === selectedClient)?.client_name || "report";
      link.download = `Report_${clientName}_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Report PDF generato con successo");
    } catch {
      toast.error("Errore nella generazione del report");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="p-4 md:p-5 space-y-4 animate-fade-in" data-testid="reports-page">
      <div>
        <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">
          Report PDF
        </h1>
        <p className="text-[var(--text-muted)] text-xs mt-0.5">
          Genera report professionali per i tuoi clienti
        </p>
      </div>

      <div className="noc-panel p-5 space-y-5">
        <div className="flex items-center gap-2 mb-2">
          <FilePdf size={20} className="text-red-400" weight="fill" />
          <h2 className="text-sm font-bold text-[var(--text-primary)]">Genera Nuovo Report</h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium">Cliente</label>
            <Select value={selectedClient} onValueChange={setSelectedClient}>
              <SelectTrigger className="bg-[var(--bg-deep)] border-[var(--border-subtle)] text-[var(--text-primary)] h-9" data-testid="report-client-select">
                <SelectValue placeholder="Seleziona cliente..." />
              </SelectTrigger>
              <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                {clients.map(c => (
                  <SelectItem key={c.client_id} value={c.client_id} className="text-[var(--text-primary)]">
                    <div className="flex items-center gap-2">
                      <Buildings size={14} className="text-[var(--text-muted)]" />
                      <span>{c.client_name}</span>
                      <span className="text-[10px] text-[var(--text-muted)]">({c.device_count} dispositivi)</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium">Periodo</label>
            <Select value={period} onValueChange={setPeriod}>
              <SelectTrigger className="bg-[var(--bg-deep)] border-[var(--border-subtle)] text-[var(--text-primary)] h-9" data-testid="report-period-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[var(--bg-panel)] border-[var(--border-subtle)]">
                <SelectItem value="7" className="text-[var(--text-primary)]">Ultimi 7 giorni</SelectItem>
                <SelectItem value="30" className="text-[var(--text-primary)]">Ultimi 30 giorni</SelectItem>
                <SelectItem value="90" className="text-[var(--text-primary)]">Ultimi 90 giorni</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium">&nbsp;</label>
            <Button
              onClick={generateReport}
              disabled={generating || !selectedClient}
              className="w-full h-9 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium"
              data-testid="generate-report-btn"
            >
              {generating ? (
                <><Spinner size={14} className="animate-spin mr-2" /> Generazione...</>
              ) : (
                <><Download size={14} className="mr-2" /> Genera PDF</>
              )}
            </Button>
          </div>
        </div>

        <div className="border border-dashed border-[var(--border-subtle)] rounded-lg p-4 mt-2">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-2">Il report include:</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {["Copertina Cliente", "Riepilogo Esecutivo", "Inventario per Tipo", "Porte Switch + PoE",
              "Adiacenze LLDP", "SLA per Dispositivo", "Ultimi Alert", "Modifiche Rete"
            ].map(item => (
              <div key={item} className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                <CheckCircle size={12} className="text-emerald-400" weight="fill" />
                {item}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Personalizzazione brand white-label */}
      <div className="noc-panel p-5 space-y-4" data-testid="branding-panel">
        <div className="flex items-center gap-2">
          <Palette size={20} className="text-indigo-400" weight="fill" />
          <h2 className="text-sm font-bold text-[var(--text-primary)]">Personalizzazione Brand (White-label)</h2>
        </div>
        <p className="text-[var(--text-muted)] text-xs -mt-1">
          {selectedClient
            ? "Il logo e il nome brand appariranno nella copertina e nel footer del report PDF di questo cliente."
            : "Seleziona un cliente qui sopra per personalizzarne logo e nome brand."}
        </p>

        {selectedClient ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Nome brand */}
            <div className="space-y-1.5">
              <label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium">Nome brand</label>
              <div className="flex gap-2">
                <Input
                  value={brandName}
                  onChange={(e) => setBrandName(e.target.value)}
                  placeholder={branding?.default_brand || "ArgusCenter"}
                  maxLength={80}
                  className="bg-[var(--bg-deep)] border-[var(--border-subtle)] text-[var(--text-primary)] h-9 text-sm"
                  data-testid="brand-name-input"
                />
                <Button
                  onClick={saveBrandName}
                  disabled={savingBrand}
                  className="h-9 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium shrink-0"
                  data-testid="save-brand-name-btn"
                >
                  {savingBrand ? <Spinner size={14} className="animate-spin" /> : "Salva"}
                </Button>
              </div>
              <p className="text-[10px] text-[var(--text-muted)]">
                Lascia vuoto per usare il brand di default ({branding?.default_brand || "86BIT NOC"}).
              </p>
            </div>

            {/* Logo */}
            <div className="space-y-1.5">
              <label className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium">Logo (PNG/JPG/WEBP, max 1MB)</label>
              <div className="flex items-center gap-3">
                <div className="w-24 h-14 rounded-md border border-[var(--border-subtle)] bg-white/5 flex items-center justify-center overflow-hidden shrink-0">
                  {branding?.logo_data_url ? (
                    <img src={branding.logo_data_url} alt="logo" className="max-w-full max-h-full object-contain" data-testid="brand-logo-preview" />
                  ) : (
                    <span className="text-[9px] text-[var(--text-muted)]">Nessun logo</span>
                  )}
                </div>
                <div className="flex flex-col gap-2">
                  <label className="cursor-pointer">
                    <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={uploadLogo} data-testid="brand-logo-input" />
                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 text-xs font-medium transition-colors">
                      {uploadingLogo ? <Spinner size={14} className="animate-spin" /> : <UploadSimple size={14} />}
                      {branding?.has_logo ? "Sostituisci logo" : "Carica logo"}
                    </span>
                  </label>
                  {branding?.has_logo && (
                    <button
                      onClick={removeLogo}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-red-500/40 bg-red-500/10 hover:bg-red-500/20 text-red-300 text-xs font-medium transition-colors"
                      data-testid="remove-brand-logo-btn"
                    >
                      <Trash size={14} /> Rimuovi
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {clients.length > 0 && (
        <div className="noc-panel p-4">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3">
            Clienti Disponibili
          </h3>
          <div className="space-y-1.5">
            {clients.map(c => (
              <div key={c.client_id}
                className="flex items-center justify-between p-2.5 rounded-md bg-[var(--bg-card)] border border-[var(--bg-border)] hover:border-indigo-500/30 transition-colors cursor-pointer"
                onClick={() => { setSelectedClient(c.client_id); }}
                data-testid={`client-card-${c.client_id}`}
              >
                <div className="flex items-center gap-3">
                  <Buildings size={16} className="text-indigo-400" />
                  <div>
                    <p className="text-xs font-medium text-[var(--text-primary)]">{c.client_name}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">{c.device_count} dispositivi monitorati</p>
                  </div>
                </div>
                <ArrowRight size={14} className="text-[var(--text-muted)]" />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
