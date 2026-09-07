import { useState, useEffect } from "react";
import { useAuth } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Fingerprint, Trash, ShieldWarning, Plus } from "@phosphor-icons/react";
import {
  passkeySupported, registerPasskey, listPasskeys, deletePasskey,
  adminListPasskeyUsers, adminResetPasskeys,
} from "@/lib/webauthn";

export default function PasskeysPage() {
  const { user } = useAuth();
  const [creds, setCreds] = useState([]);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [adminUsers, setAdminUsers] = useState([]);
  const isAdmin = user?.role === "admin";

  const refresh = async () => {
    try { setCreds(await listPasskeys()); } catch { /* noop */ }
    if (isAdmin) { try { setAdminUsers(await adminListPasskeyUsers()); } catch { /* noop */ } }
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, []);

  const add = async () => {
    setBusy(true);
    try {
      await registerPasskey(label || "Passkey");
      toast.success("Passkey registrata");
      setLabel(""); refresh();
    } catch (e) {
      if (e?.name === "NotAllowedError") toast.error("Registrazione annullata");
      else toast.error(e.response?.data?.detail || "Errore registrazione passkey");
    } finally { setBusy(false); }
  };
  const remove = async (id) => {
    try { await deletePasskey(id); toast.success("Passkey rimossa"); refresh(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore"); }
  };
  const reset = async (uid, email) => {
    if (!window.confirm(`Azzerare TUTTE le passkey di ${email}? L'utente rientrerà con password + TOTP.`)) return;
    try { const r = await adminResetPasskeys(uid); toast.success(`Reset: ${r.data.deleted} passkey rimosse`); refresh(); }
    catch (e) { toast.error(e.response?.data?.detail || "Errore reset"); }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-8" data-testid="passkeys-page">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)] flex items-center gap-2">
          <Fingerprint size={26} weight="bold" /> Passkey (WebAuthn/FIDO2)
        </h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">Accesso passwordless con chiavi FIDO2. Il 2FA TOTP resta come fallback.</p>
      </div>

      {!passkeySupported() && (
        <div className="text-sm text-amber-400">Questo browser non supporta le passkey.</div>
      )}

      <section className="space-y-3">
        <h2 className="text-base font-semibold text-[var(--text-secondary)]">Le mie passkey</h2>
        <div className="flex gap-2">
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Nome (es. YubiKey ufficio)"
            data-testid="passkey-label-input" className="max-w-xs" />
          <Button onClick={add} disabled={busy || !passkeySupported()} data-testid="passkey-add-btn"
            className="bg-indigo-600 hover:bg-indigo-700 text-white gap-1">
            <Plus size={16} weight="bold" /> Registra passkey
          </Button>
        </div>
        <div className="space-y-2">
          {creds.length === 0 && <p className="text-sm text-[var(--text-muted)]">Nessuna passkey registrata.</p>}
          {creds.map((c) => (
            <div key={c.credential_id} data-testid={`passkey-row-${c.credential_id}`}
              className="flex items-center justify-between rounded-lg border border-[var(--bg-border)] px-3 py-2">
              <div className="text-sm text-[var(--text-primary)]">
                {c.label || "Passkey"} <span className="text-[var(--text-muted)] text-xs">· {c.rp_id} · {c.created_at?.slice(0,10)}</span>
              </div>
              <Button size="sm" variant="ghost" onClick={() => remove(c.credential_id)}
                data-testid={`passkey-del-${c.credential_id}`} className="text-rose-400 hover:bg-rose-500/10">
                <Trash size={16} />
              </Button>
            </div>
          ))}
        </div>
      </section>

      {isAdmin && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-amber-400 flex items-center gap-2">
            <ShieldWarning size={18} weight="bold" /> Zona Admin — reset passkey utenti
          </h2>
          <p className="text-xs text-[var(--text-muted)]">Usa in caso di chiave persa/rubata: azzera le passkey dell'utente, che rientrerà con password + TOTP.</p>
          <div className="space-y-2">
            {adminUsers.map((u) => (
              <div key={u.id} data-testid={`admin-passkey-user-${u.id}`}
                className="flex items-center justify-between rounded-lg border border-[var(--bg-border)] px-3 py-2">
                <div className="text-sm text-[var(--text-primary)]">
                  {u.email} <span className="text-[var(--text-muted)] text-xs">· {u.role} · {u.passkey_count} passkey</span>
                </div>
                <Button size="sm" variant="outline" disabled={!u.passkey_count}
                  onClick={() => reset(u.id, u.email)} data-testid={`admin-passkey-reset-${u.id}`}
                  className="border-rose-500/40 text-rose-300 hover:bg-rose-500/10">
                  Reset passkey
                </Button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
