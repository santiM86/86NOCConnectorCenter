import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

export default function ThresholdsPage() {
  const [clients, setClients] = useState([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [thresholds, setThresholds] = useState(null);
  const [modified, setModified] = useState(false);
  const token = localStorage.getItem("noc_token");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    axios.get(`${API}/api/clients`, { headers }).then(r => {
      const cl = Array.isArray(r.data) ? r.data : r.data.clients || [];
      setClients(cl);
      if (cl.length > 0) setSelectedClient(cl[0].id);
    }).catch(() => {});
  }, []);

  const fetchThresholds = useCallback(() => {
    if (!selectedClient) return;
    axios.get(`${API}/api/thresholds/${selectedClient}`, { headers })
      .then(r => { setThresholds(r.data); setModified(false); })
      .catch(() => toast.error("Errore caricamento soglie"));
  }, [selectedClient]);

  useEffect(() => { fetchThresholds(); }, [fetchThresholds]);

  const updateField = (field, value) => {
    setThresholds(t => ({ ...t, [field]: Number(value) }));
    setModified(true);
  };

  const save = () => {
    axios.post(`${API}/api/thresholds/${selectedClient}`, thresholds, { headers })
      .then(() => { toast.success("Soglie salvate!"); setModified(false); })
      .catch(() => toast.error("Errore nel salvataggio"));
  };

  const groups = [
    {
      title: "Connettivita",
      icon: "M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z",
      fields: [
        { key: "ping_max_ms", label: "Latenza Critica (ms)", desc: "Alert critico se il ping supera questo valore", unit: "ms" },
        { key: "ping_warning_ms", label: "Latenza Warning (ms)", desc: "Alert warning se il ping supera questo valore", unit: "ms" },
        { key: "packet_loss_max_pct", label: "Perdita Pacchetti Max (%)", desc: "Alert se la perdita pacchetti supera questa %", unit: "%" },
        { key: "offline_alert_after_min", label: "Tempo Offline (min)", desc: "Genera alert dopo N minuti di device offline", unit: "min" },
      ]
    },
    {
      title: "Risorse Hardware",
      icon: "M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25z",
      fields: [
        { key: "cpu_warning_pct", label: "CPU Warning (%)", desc: "Alert warning se CPU supera questa %", unit: "%" },
        { key: "cpu_critical_pct", label: "CPU Critico (%)", desc: "Alert critico se CPU supera questa %", unit: "%" },
        { key: "memory_warning_pct", label: "Memoria Warning (%)", desc: "Alert warning se RAM supera questa %", unit: "%" },
        { key: "memory_critical_pct", label: "Memoria Critico (%)", desc: "Alert critico se RAM supera questa %", unit: "%" },
      ]
    },
    {
      title: "Bandwidth",
      icon: "M3 7.5L7.5 3m0 0L12 7.5M7.5 3v13.5m13.5-4.5L16.5 16.5m0 0L12 12m4.5 4.5V3",
      fields: [
        { key: "bandwidth_warning_pct", label: "Utilizzo Warning (%)", desc: "Alert warning se utilizzo banda supera questa %", unit: "%" },
        { key: "bandwidth_critical_pct", label: "Utilizzo Critico (%)", desc: "Alert critico se utilizzo banda supera questa %", unit: "%" },
      ]
    },
    {
      title: "Stampanti",
      icon: "M6.72 13.829c-.24.03-.48.062-.72.096m.72-.096a42.415 42.415 0 0110.56 0m-10.56 0L6.34 18m10.94-4.171c.24.03.48.062.72.096m-.72-.096L17.66 18m0 0l.229 2.523a1.125 1.125 0 01-1.12 1.227H7.231c-.662 0-1.18-.568-1.12-1.227L6.34 18m11.318 0h1.091A2.25 2.25 0 0021 15.75V9.456c0-1.081-.768-2.015-1.837-2.175a48.055 48.055 0 00-1.913-.247M6.34 18H5.25A2.25 2.25 0 013 15.75V9.456c0-1.081.768-2.015 1.837-2.175a48.041 48.041 0 011.913-.247m10.5 0a48.536 48.536 0 00-10.5 0m10.5 0V3.375c0-.621-.504-1.125-1.125-1.125h-8.25c-.621 0-1.125.504-1.125 1.125v3.659M18 10.5h.008v.008H18V10.5zm-3 0h.008v.008H15V10.5z",
      fields: [
        { key: "toner_low_pct", label: "Toner Warning (%)", desc: "Alert warning quando il toner scende sotto questa %", unit: "%" },
        { key: "toner_critical_pct", label: "Toner Critico (%)", desc: "Alert critico quando il toner scende sotto questa %", unit: "%" },
      ]
    },
  ];

  return (
    <div className="space-y-6" data-testid="thresholds-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Soglie Alert</h1>
          <p className="text-sm text-[var(--text-secondary)]">Personalizza le soglie per la generazione degli alert</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={selectedClient} onChange={e => setSelectedClient(e.target.value)}
            className="h-8 px-3 text-xs rounded-md border border-[var(--bg-border)] bg-[var(--bg-card)] text-[var(--text-primary)]"
            data-testid="thresh-client-select">
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {modified && (
            <button onClick={save}
              className="h-8 px-4 text-xs font-semibold rounded-md bg-emerald-600 text-white hover:bg-emerald-700 animate-pulse"
              data-testid="thresh-save-btn">
              Salva Modifiche
            </button>
          )}
        </div>
      </div>

      {thresholds && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {groups.map((group) => (
            <div key={group.title} className="rounded-xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4" data-testid={`thresh-group-${group.title}`}>
              <div className="flex items-center gap-2 mb-4">
                <svg className="w-5 h-5 text-[var(--accent)]" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d={group.icon} />
                </svg>
                <h3 className="text-sm font-bold text-[var(--text-primary)]">{group.title}</h3>
              </div>
              <div className="space-y-3">
                {group.fields.map(f => (
                  <div key={f.key} className="flex items-center justify-between">
                    <div className="flex-1 mr-3">
                      <p className="text-xs font-medium text-[var(--text-primary)]">{f.label}</p>
                      <p className="text-[10px] text-[var(--text-secondary)]">{f.desc}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      <input type="number" value={thresholds[f.key] ?? ""} onChange={e => updateField(f.key, e.target.value)}
                        className="w-20 h-7 px-2 text-xs text-right rounded-md border border-[var(--bg-border)] bg-[var(--bg-surface)] text-[var(--text-primary)]"
                        data-testid={`thresh-${f.key}`} />
                      <span className="text-[10px] text-[var(--text-secondary)] w-6">{f.unit}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
