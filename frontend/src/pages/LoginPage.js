import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ShieldWarning, Eye, EyeSlash } from "@phosphor-icons/react";

export default function LoginPage() {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const { login, register, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/";

  if (user) { navigate(from, { replace: true }); return null; }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (isLogin) {
        const result = await login(email, password);
        if (result?.requires_2fa) { toast.info("Verifica 2FA richiesta"); navigate("/2fa", { state: { from: location.state?.from } }); return; }
        toast.success("Login effettuato");
      } else {
        await register(email, password, name);
        toast.success("Registrazione completata");
      }
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
                NOC Center
              </span>
            </div>
            <p className="text-[var(--text-muted)] text-xs font-mono">
              Alert Management System
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div className="space-y-1.5">
                <Label htmlFor="name" className="text-[var(--text-muted)] text-[10px] uppercase tracking-widest">Nome</Label>
                <Input id="name" type="text" value={name} onChange={e => setName(e.target.value)} placeholder="Mario Rossi" required={!isLogin}
                  data-testid="register-name-input"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] rounded-lg h-10 focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30" />
              </div>
            )}
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
              {loading ? "..." : isLogin ? "Accedi" : "Registrati"}
            </Button>
          </form>

          <div className="mt-5 text-center">
            <button type="button" onClick={() => setIsLogin(!isLogin)} data-testid="toggle-auth-mode-btn"
              className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] text-xs transition-colors">
              {isLogin ? "Non hai un account? Registrati" : "Hai gia un account? Accedi"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
