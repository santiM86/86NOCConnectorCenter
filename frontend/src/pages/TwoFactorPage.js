import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth, API } from "@/App";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ShieldWarning, Lock } from "@phosphor-icons/react";

export default function TwoFactorPage() {
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleVerify = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const response = await axios.post(`${API}/auth/verify-2fa`, { code });
      
      // Update token with the new one that doesn't require 2FA
      localStorage.setItem("noc_token", response.data.token);
      axios.defaults.headers.common["Authorization"] = `Bearer ${response.data.token}`;
      
      toast.success("Verifica completata");
      
      // Redirect to intended destination or dashboard
      const from = location.state?.from?.pathname || "/";
      navigate(from, { replace: true });
      window.location.reload();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Codice non valido");
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-[#050505] flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-3 mb-2">
            <ShieldWarning size={32} weight="fill" className="text-zinc-100" />
            <span className="font-heading text-2xl font-bold tracking-tight text-zinc-100">
              NOC // COMMAND
            </span>
          </div>
          <p className="text-zinc-500 text-sm font-mono">
            Verifica Autenticazione 2FA
          </p>
        </div>

        {/* Form */}
        <div className="noc-panel p-6">
          <div className="flex items-center gap-3 mb-6 pb-4 border-b border-zinc-800">
            <div className="w-10 h-10 rounded-sm bg-zinc-800 flex items-center justify-center">
              <Lock size={20} className="text-zinc-400" />
            </div>
            <div>
              <p className="text-zinc-200 font-medium">Autenticazione a Due Fattori</p>
              <p className="text-zinc-500 text-xs">Inserisci il codice dalla tua app</p>
            </div>
          </div>

          <form onSubmit={handleVerify} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="code" className="text-zinc-400 text-xs uppercase tracking-wider">
                Codice di Verifica
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
                data-testid="2fa-code-input"
                className="bg-zinc-900 border-zinc-800 text-zinc-100 placeholder:text-zinc-600 rounded-sm h-14 text-center text-3xl tracking-[0.5em] font-mono focus:border-zinc-600 focus:ring-1 focus:ring-zinc-600"
              />
              <p className="text-zinc-600 text-xs text-center">
                Apri Google Authenticator o Authy per ottenere il codice
              </p>
            </div>

            <Button
              type="submit"
              disabled={loading || code.length !== 6}
              data-testid="verify-2fa-btn"
              className="w-full h-11 rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white font-medium uppercase tracking-wider text-sm transition-fast"
            >
              {loading ? "Verifica..." : "Verifica Codice"}
            </Button>
          </form>

          <div className="mt-4 pt-4 border-t border-zinc-800">
            <button
              type="button"
              onClick={handleCancel}
              className="w-full text-zinc-500 hover:text-zinc-300 text-sm transition-fast"
            >
              Annulla e torna al login
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
