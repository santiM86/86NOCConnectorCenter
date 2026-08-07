import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth, API } from "@/App";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ShieldCheck, Lock, Copy } from "@phosphor-icons/react";

const authHeader = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem("noc_token")}` } });

export default function TwoFactorSetupPage() {
  const [qr, setQr] = useState("");
  const [secret, setSecret] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const { logout } = useAuth();
  const navigate = useNavigate();
  const initDone = useRef(false);

  useEffect(() => {
    if (initDone.current) return;
    initDone.current = true;
    const init = async () => {
      try {
        const res = await axios.post(`${API}/auth/setup-2fa`, {}, authHeader());
        setQr(res.data.qr_code);
        setSecret(res.data.secret);
      } catch (error) {
        toast.error(error.response?.data?.detail || "Impossibile avviare la configurazione 2FA");
        logout();
        navigate("/login");
      } finally {
        setInitializing(false);
      }
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConfirm = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await axios.post(`${API}/auth/confirm-2fa`, { code }, authHeader());
      if (res.data.token) {
        localStorage.setItem("noc_token", res.data.token);
        if (res.data.refresh_token) localStorage.setItem("noc_refresh_token", res.data.refresh_token);
        axios.defaults.headers.common["Authorization"] = `Bearer ${res.data.token}`;
      }
      toast.success("2FA attivato con successo");
      navigate("/", { replace: true });
      window.location.reload();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Codice non valido");
    } finally {
      setLoading(false);
    }
  };

  const copySecret = () => {
    navigator.clipboard?.writeText(secret);
    toast.success("Chiave copiata");
  };

  return (
    <div className="min-h-screen bg-[#050505] flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-3 mb-2">
            <ShieldCheck size={32} weight="fill" className="text-emerald-400" />
            <span className="font-heading text-2xl font-bold tracking-tight text-zinc-100">
              NOC // COMMAND
            </span>
          </div>
          <p className="text-zinc-500 text-sm font-mono">
            Configurazione 2FA obbligatoria
          </p>
        </div>

        <div className="noc-panel p-6">
          <div className="flex items-center gap-3 mb-6 pb-4 border-b border-zinc-800">
            <div className="w-10 h-10 rounded-sm bg-zinc-800 flex items-center justify-center">
              <Lock size={20} className="text-zinc-400" />
            </div>
            <div>
              <p className="text-zinc-200 font-medium">Proteggi l'account admin</p>
              <p className="text-zinc-500 text-xs">Scansiona con Microsoft Authenticator</p>
            </div>
          </div>

          {initializing ? (
            <p className="text-zinc-500 text-sm text-center py-8">Generazione codice QR...</p>
          ) : (
            <>
              {qr && (
                <div className="flex flex-col items-center gap-3 mb-5">
                  <div className="bg-white p-3 rounded-md" data-testid="2fa-qr">
                    <img src={`data:image/png;base64,${qr}`} alt="QR 2FA" width={180} height={180} />
                  </div>
                  <p className="text-zinc-500 text-xs text-center">
                    Apri <span className="text-zinc-300 font-medium">Microsoft Authenticator</span> →
                    Aggiungi account → Scansiona il QR
                  </p>
                  {secret && (
                    <button
                      type="button"
                      onClick={copySecret}
                      className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300 font-mono"
                      data-testid="2fa-copy-secret"
                    >
                      <Copy size={12} /> {secret}
                    </button>
                  )}
                </div>
              )}

              <form onSubmit={handleConfirm} className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="code" className="text-zinc-400 text-xs uppercase tracking-wider">
                    Codice a 6 cifre
                  </Label>
                  <Input
                    id="code"
                    type="text"
                    inputMode="numeric"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="000000"
                    maxLength={6}
                    required
                    autoFocus
                    data-testid="2fa-setup-code-input"
                    className="bg-zinc-900 border-zinc-800 text-zinc-100 placeholder:text-zinc-600 rounded-sm h-14 text-center text-3xl tracking-[0.5em] font-mono focus:border-zinc-600 focus:ring-1 focus:ring-zinc-600"
                  />
                </div>

                <Button
                  type="submit"
                  disabled={loading || code.length !== 6}
                  data-testid="confirm-2fa-setup-btn"
                  className="w-full h-11 rounded-sm bg-emerald-500 text-zinc-950 hover:bg-emerald-400 font-medium uppercase tracking-wider text-sm transition-fast"
                >
                  {loading ? "Attivazione..." : "Attiva 2FA"}
                </Button>
              </form>
            </>
          )}

          <div className="mt-4 pt-4 border-t border-zinc-800">
            <button
              type="button"
              onClick={() => { logout(); navigate("/login"); }}
              className="w-full text-zinc-500 hover:text-zinc-300 text-sm transition-fast"
              data-testid="2fa-setup-cancel"
            >
              Annulla e torna al login
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
