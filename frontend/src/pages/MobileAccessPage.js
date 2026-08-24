import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DeviceMobile, QrCode, Trash, ArrowLeft, Copy, ShieldCheck, WarningCircle } from "@phosphor-icons/react";

export default function MobileAccessPage() {
  const navigate = useNavigate();
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState("");
  const [generating, setGenerating] = useState(false);
  const [fresh, setFresh] = useState(null); // { token, pairUrl, id, device_label }

  const pairUrlFor = (tk) => `${window.location.origin}/m#t=${tk}`;

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/mobile/pairing`);
      setDevices(data.devices || []);
    } catch {
      toast.error("Errore nel caricamento dei telefoni agganciati");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setGenerating(true);
    try {
      const { data } = await axios.post(`${API}/mobile/pairing`, { device_label: label });
      setFresh({ ...data, pairUrl: pairUrlFor(data.token) });
      setLabel("");
      load();
    } catch {
      toast.error("Impossibile generare il QR di accesso");
    } finally {
      setGenerating(false);
    }
  };

  const revoke = async (id) => {
    try {
      await axios.delete(`${API}/mobile/pairing/${id}`);
      toast.success("Telefono scollegato. Non potrà più accedere.");
      if (fresh?.id === id) setFresh(null);
      load();
    } catch {
      toast.error("Errore nella revoca");
    }
  };

  const copy = (txt) => {
    navigator.clipboard?.writeText(txt).then(() => toast.success("Link copiato")).catch(() => {});
  };

  const fmt = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }
    catch { return iso; }
  };

  return (
    <div className="max-w-3xl mx-auto p-5 space-y-5" data-testid="mobile-access-page">
      <button onClick={() => navigate("/settings")} className="flex items-center gap-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] text-xs" data-testid="back-to-settings">
        <ArrowLeft size={14} /> Impostazioni
      </button>

      <div>
        <h1 className="text-[var(--text-primary)] text-xl font-bold flex items-center gap-2">
          <DeviceMobile size={22} className="text-teal-400" /> Accesso Mobile (QR)
        </h1>
        <p className="text-[var(--text-muted)] text-xs mt-1 max-w-xl">
          Aggancia il tuo telefono una volta sola inquadrando il QR: da quel momento potrai monitorare in tempo reale
          <b> tutte le aziende</b> in sola lettura, <b>senza reinserire la password</b>. Il collegamento resta valido finché
          non lo revochi da qui.
        </p>
      </div>

      {/* Generate */}
      <div className="noc-panel p-5 space-y-3">
        <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest flex items-center gap-1.5">
          <QrCode size={13} /> Genera un nuovo aggancio
        </h3>
        <div className="flex gap-2 items-end flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <label className="text-[var(--text-muted)] text-[10px] uppercase tracking-wider">Nome del telefono (opzionale)</label>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="es. iPhone 17 Pro di Marco"
              className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] h-9 text-sm mt-1" maxLength={60}
              data-testid="mobile-label-input" />
          </div>
          <Button onClick={generate} disabled={generating}
            className="bg-teal-500 hover:bg-teal-600 text-white h-9 text-sm" data-testid="generate-qr-btn">
            <QrCode size={15} className="mr-1.5" /> {generating ? "Genero…" : "Genera QR"}
          </Button>
        </div>

        {fresh && (
          <div className="mt-3 rounded-lg border border-teal-500/30 bg-teal-500/5 p-4 flex flex-col sm:flex-row gap-5 items-center" data-testid="fresh-qr-block">
            <div className="bg-white p-3 rounded-xl shrink-0">
              <QRCodeSVG value={fresh.pairUrl} size={188} level="M" includeMargin={false} data-testid="mobile-qr-svg" />
            </div>
            <div className="flex-1 space-y-2 w-full">
              <p className="text-[var(--text-primary)] text-sm font-semibold flex items-center gap-1.5">
                <ShieldCheck size={15} className="text-teal-400" /> Inquadra questo QR col telefono
              </p>
              <p className="text-[var(--text-muted)] text-[11px] leading-relaxed">
                Apri la fotocamera dell'iPhone, inquadra il codice e tocca la notifica. Il telefono resterà agganciato.
              </p>
              <div className="flex gap-2 items-center">
                <Input readOnly value={fresh.pairUrl} className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-muted)] h-8 text-[11px] font-mono" data-testid="mobile-pair-url" />
                <Button size="sm" variant="outline" onClick={() => copy(fresh.pairUrl)} className="h-8 text-xs border-[var(--bg-border)]" data-testid="copy-pair-url"><Copy size={13} /></Button>
              </div>
              <p className="text-amber-300/90 text-[10px] flex items-start gap-1.5 pt-1">
                <WarningCircle size={13} className="mt-px shrink-0" />
                Mostra il QR solo a te: chiunque lo inquadri potrà vedere il monitoraggio. Il link con il token è visibile solo ora.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Paired devices */}
      <div className="noc-panel p-5">
        <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
          <DeviceMobile size={13} /> Telefoni agganciati ({devices.length})
        </h3>
        {loading ? (
          <p className="text-[var(--text-muted)] text-xs">Caricamento…</p>
        ) : devices.length === 0 ? (
          <p className="text-[var(--text-muted)] text-xs">Nessun telefono agganciato. Genera un QR qui sopra.</p>
        ) : (
          <div className="space-y-2" data-testid="paired-devices-list">
            {devices.map((d) => (
              <div key={d.id} className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--bg-border)] rounded-lg px-3 py-2.5" data-testid="paired-device-row">
                <DeviceMobile size={18} className="text-teal-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-[var(--text-primary)] text-sm font-medium truncate">{d.device_label || "Telefono"}</p>
                  <p className="text-[var(--text-muted)] text-[10px]">
                    Creato {fmt(d.created_at)} · Ultimo accesso {d.last_used_at ? fmt(d.last_used_at) : "mai"}
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={() => revoke(d.id)}
                  className="h-7 text-xs border-rose-500/40 text-rose-300 hover:bg-rose-500/10" data-testid="revoke-device-btn">
                  <Trash size={13} className="mr-1" /> Scollega
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
