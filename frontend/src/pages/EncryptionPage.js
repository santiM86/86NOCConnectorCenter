import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { Lock, ShieldCheck, ArrowsClockwise, Warning, Key } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function EncryptionPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [showRotate, setShowRotate] = useState(false);
  const [totp, setTotp] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/admin/security/encryption-status`);
      setStatus(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore caricamento");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const migrateNow = async () => {
    if (!window.confirm("Migrare tutti i ciphertext legacy a schema v2 (salt random + 600k iter)? Operazione idempotente, sicura.")) return;
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/admin/security/migrate-to-v2`);
      toast.success(`Migrazione completata: ${data.migrated} migrati, ${data.skipped_v2} gia v2, ${data.failed} falliti`);
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore migrazione");
    } finally {
      setBusy(false);
    }
  };

  const rotateNow = async () => {
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/admin/security/rotate-master-key`, {
        confirm: true,
        totp_code: totp || null,
      });
      toast.success(`Rotation OK: ${data.rewritten} blob ricifrati. Nuova key: ${data.new_key_preview}`);
      if (data.warning) toast.warning(data.warning, { duration: 12000 });
      setShowRotate(false);
      setTotp("");
      await reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Errore rotation");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="p-6 text-[var(--text-muted)] text-sm">Caricamento…</div>;
  if (!status) return <div className="p-6 text-red-400">Impossibile caricare lo stato</div>;

  const pct = status.v2_percentage || 0;
  const pctColor = pct >= 100 ? "#34C759" : pct >= 50 ? "#FFB400" : "#FF3B30";

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4" data-testid="encryption-page">
      <div className="flex items-center gap-3 mb-2">
        <button onClick={() => navigate(-1)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm">←</button>
        <Lock size={20} className="text-cyan-400" />
        <h1 className="text-xl font-bold">Cifratura &amp; Master Key</h1>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        AES-256-GCM con PBKDF2-HMAC-SHA256 600k iterazioni e salt random per deployment (NIST SP 800-132 rev. 2024).
        Argon2id per password admin. Master key rotabile in-process senza downtime.
      </p>

      {/* Encryption health card */}
      <div className="noc-panel p-4 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} style={{ color: pctColor }} />
            <span className="text-sm font-bold">Stato cifratura</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: `${pctColor}20`, color: pctColor }}>
              {pct === 100 ? "v2 100%" : `v2 ${pct}% — ${status.v1_legacy_count} legacy`}
            </span>
          </div>
          <Button size="sm" onClick={reload} variant="outline" className="h-7 text-[11px] gap-1">
            <ArrowsClockwise size={11} /> Aggiorna
          </Button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
          <Stat label="Ciphertext totali" value={status.total_ciphertexts} />
          <Stat label="Schema v2" value={status.v2_count} color="#34C759" />
          <Stat label="Legacy v1" value={status.v1_legacy_count} color={status.v1_legacy_count > 0 ? "#FFB400" : "#34C759"} />
          <Stat label="Invalid" value={status.invalid_count} color={status.invalid_count > 0 ? "#FF3B30" : "#34C759"} />
        </div>

        {status.needs_migration && (
          <div className="rounded bg-amber-500/10 border border-amber-500/40 p-3 flex items-center gap-3">
            <Warning size={16} className="text-amber-400 shrink-0" />
            <div className="flex-1">
              <p className="text-[11px] text-amber-300 font-semibold">Migrazione raccomandata</p>
              <p className="text-[10px] text-[var(--text-muted)]">
                {status.v1_legacy_count} ciphertext usano ancora il salt fisso legacy (100k iter). Esegui la migrazione per allinearli a salt random + 600k iter.
              </p>
            </div>
            <Button size="sm" onClick={migrateNow} disabled={busy} className="bg-amber-600 hover:bg-amber-700 h-7 text-[11px]" data-testid="migrate-btn">
              Migra ora
            </Button>
          </div>
        )}

        {!status.needs_migration && status.total_ciphertexts > 0 && (
          <div className="rounded bg-emerald-500/10 border border-emerald-500/40 p-3 flex items-center gap-2">
            <ShieldCheck size={16} className="text-emerald-400" />
            <p className="text-[11px] text-emerald-300">
              Tutti i ciphertext usano lo schema v2 (salt random + 600k iter). Allineamento NIST 2024 ✓
            </p>
          </div>
        )}

        {/* Breakdown */}
        {Object.keys(status.breakdown || {}).length > 0 && (
          <details className="text-[11px]">
            <summary className="cursor-pointer text-[var(--text-muted)] hover:text-[var(--text-primary)]">Dettaglio per collection</summary>
            <table className="noc-table w-full text-[10px] mt-2">
              <thead><tr><th>Collection.field</th><th>Totale</th><th>v2</th><th>v1</th><th>Invalid</th></tr></thead>
              <tbody>
                {Object.entries(status.breakdown).map(([k, v]) => (
                  <tr key={k}><td className="font-mono">{k}</td><td>{v.total}</td><td className="text-emerald-400">{v.v2}</td><td className="text-amber-400">{v.v1_legacy}</td><td className="text-red-400">{v.invalid}</td></tr>
                ))}
              </tbody>
            </table>
          </details>
        )}

        <div className="text-[10px] text-[var(--text-muted)]">
          Salt v2: <code>{status.salt_v2_path}</code> {status.salt_v2_exists ? "✓" : "❌"}
        </div>
      </div>

      {/* Rotation card */}
      <div className="noc-panel p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Key size={16} className="text-violet-400" />
          <span className="text-sm font-bold">Rotazione master key</span>
        </div>
        <p className="text-[11px] text-[var(--text-muted)]">
          Genera una nuova master key e ricifra tutti i blob in modo atomico. Operazione zero-downtime.
          Esegui se sospetti compromissione, dopo offboarding admin con accesso al server, o ogni 90 giorni come best practice.
        </p>
        <p className="text-[10px] text-amber-400">
          ⚠️ La nuova key viene scritta in <code>backend/.env</code>. Fai un backup prima.
        </p>
        <div>
          <Button onClick={() => setShowRotate(true)} disabled={busy} className="bg-violet-600 hover:bg-violet-700 h-8 text-xs gap-1" data-testid="rotate-btn">
            <Key size={12} /> Ruota master key
          </Button>
        </div>
      </div>

      {/* Rotate dialog */}
      {showRotate && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowRotate(false)}>
          <div className="bg-[var(--bg-panel)] border border-violet-500/30 rounded-lg p-5 max-w-md w-full space-y-3" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold flex items-center gap-2"><Key size={14} className="text-violet-400" /> Ruota master key</h3>
            <p className="text-[11px] text-[var(--text-muted)]">
              Verra` generata una nuova ENCRYPTION_KEY 256-bit, tutti i blob ricifrati e <code>backend/.env</code> aggiornato.
              {status.total_ciphertexts > 0 && ` (${status.total_ciphertexts} blob da ricifrare)`}
            </p>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Codice 2FA (se attivo)</label>
              <Input value={totp} onChange={e => setTotp(e.target.value)} placeholder="123456" className="bg-[var(--bg-card)] h-8 text-xs font-mono" data-testid="rotate-totp" />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => { setShowRotate(false); setTotp(""); }} disabled={busy}>Annulla</Button>
              <Button onClick={rotateNow} disabled={busy} className="bg-violet-600 hover:bg-violet-700" data-testid="rotate-confirm">
                {busy ? "Rotazione..." : "Conferma e ruota"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div className="rounded bg-[var(--bg-card)] border border-[var(--bg-border)] px-2 py-1.5">
      <p className="text-[8px] uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
      <p className="text-base font-bold font-mono leading-none mt-0.5" style={{ color: color || "var(--text-primary)" }}>{value}</p>
    </div>
  );
}
