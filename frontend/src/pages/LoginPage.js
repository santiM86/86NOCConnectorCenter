import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Eye, EyeSlash, Info } from "@phosphor-icons/react";
import { useAppVersion } from "@/components/AppVersion";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showEaster, setShowEaster] = useState(false);
  const { login, user } = useAuth();
  const { version } = useAppVersion();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/";

  useEffect(() => {
    if (user) {
      navigate(from, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

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
        <div className="absolute inset-0" />
      </div>

      <div className="login-form-container">
        <div className="w-full flex flex-col h-full">
          {/* Spacer top */}
          <div className="flex-1 min-h-0" />

          {/* Logo + Title */}
          <div className="text-center mb-2 max-w-sm mx-auto w-full px-4">
            <div className="flex items-center justify-center gap-3 mb-1">
              <img src="/icon-192.png" alt="ARGUS" className="w-10 h-10 rounded-lg" data-testid="login-argus-icon" />
              <div>
                <span className="text-2xl tracking-tight text-[var(--text-primary)]">
                  <b className="font-black">ARGUS</b> <span className="font-light">Center</span>
                </span>
                <p className="text-indigo-400/70 text-sm tracking-wide text-left">
                  Alert Management System
                </p>
              </div>
            </div>
          </div>

          {/* Login Card */}
          <div className="mt-6 rounded-xl border border-[var(--bg-border)] bg-[var(--bg-panel)] p-5 max-w-sm mx-auto w-full">
            <h2 className="text-lg font-bold text-[var(--text-primary)] mb-1">Accedi</h2>
            <p className="text-xs text-[var(--text-muted)] mb-4">Inserisci le tue credenziali</p>

            <form onSubmit={handleSubmit} className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="email" className="text-[var(--text-secondary)] text-xs font-medium">Email</Label>
                <Input id="email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="info@86bit.it" required
                  data-testid="login-email-input"
                  className="bg-[var(--bg-card)] border-[var(--bg-border)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] rounded-lg h-10 focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="password" className="text-[var(--text-secondary)] text-xs font-medium">Password</Label>
                <div className="relative">
                  <Input id="password" type={showPassword ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)} placeholder="............" required
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
                className="w-full h-10 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-sm transition-colors">
                {loading ? "..." : "Accedi"}
              </Button>
            </form>
          </div>

          {/* Spacer bottom */}
          <div className="flex-1 min-h-0" />

          {/* Footer societario - full width, font Verdana */}
          <div className="w-full border-t border-[var(--bg-border)] pt-3 pb-3 px-6 relative flex-shrink-0" data-testid="login-footer">
            <div className="text-center" style={{ fontFamily: "'Verdana', Geneva, sans-serif" }}>
              {/* Desktop: dati completi */}
              <div className="hidden md:block">
                <p className="text-[11px] text-[var(--text-muted)] opacity-70 leading-[1.9]">
                  &copy; Copyright 2026 &nbsp;|&nbsp; <b>86BIT</b> srl Unipersonale &nbsp;&mdash;&nbsp; Codice Fiscale e P.Iva <span className="text-indigo-400/70">04353030168</span> &nbsp;&mdash;&nbsp; Capitale sociale &euro; 50.000,00 i.v. &nbsp;&mdash;&nbsp; Reg. Imprese di Bergamo <span className="text-indigo-400/70">04353030168</span>
                </p>
                <p className="text-[11px] text-[var(--text-muted)] opacity-70 leading-[1.9] mt-0.5">
                  REA n. BG456578 &nbsp;&mdash;&nbsp; Sede Operativa: Piazza Papa Giovanni XXIII &nbsp;&mdash;&nbsp; 24020 Scanzorosciate (BG) &nbsp;&mdash;&nbsp; Tel. <span className="text-indigo-400/70">+39 035 310 900</span> &nbsp;&mdash;&nbsp; <span className="text-indigo-400/70">info@86bit.it</span>
                </p>
              </div>
              {/* Mobile: solo essenziale */}
              <p className="md:hidden text-[10px] text-[var(--text-muted)] opacity-60 leading-relaxed">
                &copy; 2026 <b>86BIT</b> srl &mdash; P.Iva <span className="text-indigo-400/60">04353030168</span><br />
                Tel. <span className="text-indigo-400/60">+39 035 310 900</span> &mdash; <span className="text-indigo-400/60">info@86bit.it</span>
              </p>
            </div>

            {/* Versione in basso a sinistra */}
            {version && (
              <div className="absolute bottom-3 left-3" data-testid="login-version-badge">
                <span className="text-[9px] font-mono text-[var(--text-muted)] opacity-40 select-none">V.{version}</span>
              </div>
            )}

            {/* Easter egg ! */}
            <div className="absolute bottom-3 right-3"
              onMouseEnter={() => setShowEaster(true)}
              onMouseLeave={() => setShowEaster(false)}
              onClick={() => setShowEaster(!showEaster)}
            >
              <div className="w-7 h-7 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center cursor-pointer hover:bg-indigo-500/20 hover:border-indigo-500/40 transition-all hover:scale-110"
                data-testid="easter-egg-btn">
                <span className="text-indigo-400 text-sm font-bold select-none" style={{ fontFamily: "'Verdana', Geneva, sans-serif", fontVariant: "small-caps" }}>!</span>
              </div>

              {/* Tooltip */}
              {showEaster && (
                <div className="absolute bottom-10 right-0 w-72 p-3 rounded-lg bg-[var(--bg-panel)] border border-indigo-500/30 shadow-2xl shadow-indigo-500/10 z-50"
                  style={{ animation: "fadeInUp 0.25s ease-out" }}
                  data-testid="easter-egg-tooltip">
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed"
                    style={{ fontFamily: "'Playfair Display', 'Georgia', serif", fontStyle: "italic" }}>
                    Argo Panoptes nella mitologia greca era il guardiano con 100 occhi che non dormiva mai — esattamente quello che fa il vostro NOC!
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
