import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ShieldWarning, Eye, EyeSlash } from "@phosphor-icons/react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/";

  if (user) { navigate(from, { replace: true }); return null; }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await login(email, password);
      if (result?.requires_2fa) { toast.info("Verifica 2FA richiesta"); navigate("/2fa", { state: { from: location.state?.from } }); return; }
      toast.success("Login effettuato");
      navigate(from, { replace: true });
    } catch (error) {
      toast.error(error.response?.data?.detail || "Errore di autenticazione");
    } finally { setLoading(false); }
  };

  return (
    <div className="login-container">
      <div className="login-image"
        style={{ backgroundImage: `url('https://images.unsplash.com/photo-1762163516269-3c143e04175c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA0MTJ8MHwxfHNlYXJjaHwxfHxzZXJ2ZXIlMjByYWNrJTIwZGFyayUyMGxpZ2h0c3xlbnwwfHx8fDE3NzQwODIxODJ8MA&ixlib=rb-4.1.0&q=85')` }}>
        <div className="absolute inset-0 flex items-end p-8 z-10">
          <div className="text-white/40 text-xs font-mono">
            <p>SYSTEM // OPERATIONAL</p>
            <p>NODES // MONITORING</p>
          </div>
        </div>
      </div>

      <div className="login-form-container">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <div className="flex items-center gap-2.5 mb-2">
              <div className="w-9 h-9 rounded-lg bg-indigo-600/20 flex items-center justify-center">
                <ShieldWarning size={22} weight="fill" className="text-indigo-400" />
              </div>
              <span className="font-heading text-xl font-bold tracking-tight text-[var(--text-primary)]">
                Argus
              </span>
            </div>
            <p className="text-[var(--text-muted)] text-xs font-mono">
              Vediamo tutto. Sempre!
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Email</Label>
              <Input id="email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="operatore@azienda.it" required
                data-testid="login-email-input"
                className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] rounded-lg h-10 focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Password</Label>
              <div className="relative">
                <Input id="password" type={showPassword ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)} placeholder="........" required
                  data-testid="login-password-input"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] rounded-lg h-10 pr-10 focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30" />
                <button type="button" onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
                  data-testid="toggle-password-btn">
                  {showPassword ? <EyeSlash size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            <Button type="submit" disabled={loading} data-testid="login-submit-btn"
              className="w-full h-10 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm transition-colors">
              {loading ? "..." : "Accedi"}
            </Button>
          </form>

          {/* Footer societario */}
          <div className="mt-8 pt-4 border-t border-[var(--bg-border)]">
            <p className="text-[8px] text-[var(--text-muted)]/50 leading-relaxed text-center">
              &copy; Copyright 2026 | 86BIT srl Unipersonale &mdash; Codice Fiscale e P.Iva 04353030168 &mdash; Capitale sociale &euro; 50.000,00 i.v. &mdash; Reg. Imprese di Bergamo 04353030168
              <br />
              REA n. BG456578 &mdash; Sede Operativa: Piazza Papa Giovanni XXIII &mdash; 24020 Scanzorosciate (BG) &mdash; Tel. +39 035 310 900 &mdash; info@86bit.it
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
