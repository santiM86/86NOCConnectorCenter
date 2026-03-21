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

  if (user) {
    navigate(from, { replace: true });
    return null;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      if (isLogin) {
        const result = await login(email, password);
        if (result?.requires_2fa) {
          toast.info("Verifica 2FA richiesta");
          navigate("/2fa", { state: { from: location.state?.from } });
          return;
        }
        toast.success("Login effettuato");
      } else {
        await register(email, password, name);
        toast.success("Registrazione completata");
      }
      navigate(from, { replace: true });
    } catch (error) {
      toast.error(error.response?.data?.detail || "Errore di autenticazione");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      {/* Left side - Image */}
      <div 
        className="login-image"
        style={{
          backgroundImage: `url('https://images.unsplash.com/photo-1762163516269-3c143e04175c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA0MTJ8MHwxfHNlYXJjaHwxfHxzZXJ2ZXIlMjByYWNrJTIwZGFyayUyMGxpZ2h0c3xlbnwwfHx8fDE3NzQwODIxODJ8MA&ixlib=rb-4.1.0&q=85')`
        }}
      >
        <div className="absolute inset-0 flex items-end p-8 z-10">
          <div className="text-white/60 text-sm font-mono">
            <p>SYSTEM // OPERATIONAL</p>
            <p>NODES // MONITORING</p>
          </div>
        </div>
      </div>

      {/* Right side - Form */}
      <div className="login-form-container">
        <div className="w-full max-w-sm">
          {/* Logo/Title */}
          <div className="mb-10">
            <div className="flex items-center gap-3 mb-2">
              <ShieldWarning size={32} weight="fill" className="text-zinc-100" />
              <span className="font-heading text-2xl font-bold tracking-tight text-zinc-100">
                NOC // COMMAND
              </span>
            </div>
            <p className="text-zinc-500 text-sm font-mono">
              Alert Management System v1.0
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {!isLogin && (
              <div className="space-y-2">
                <Label htmlFor="name" className="text-zinc-400 text-xs uppercase tracking-wider">
                  Nome
                </Label>
                <Input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Mario Rossi"
                  required={!isLogin}
                  data-testid="register-name-input"
                  className="bg-zinc-900 border-zinc-800 text-zinc-100 placeholder:text-zinc-600 rounded-sm h-11 focus:border-zinc-600 focus:ring-1 focus:ring-zinc-600"
                />
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="email" className="text-zinc-400 text-xs uppercase tracking-wider">
                Email
              </Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operatore@azienda.it"
                required
                data-testid="login-email-input"
                className="bg-zinc-900 border-zinc-800 text-zinc-100 placeholder:text-zinc-600 rounded-sm h-11 focus:border-zinc-600 focus:ring-1 focus:ring-zinc-600"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password" className="text-zinc-400 text-xs uppercase tracking-wider">
                Password
              </Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  data-testid="login-password-input"
                  className="bg-zinc-900 border-zinc-800 text-zinc-100 placeholder:text-zinc-600 rounded-sm h-11 pr-10 focus:border-zinc-600 focus:ring-1 focus:ring-zinc-600"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-fast"
                  data-testid="toggle-password-btn"
                >
                  {showPassword ? <EyeSlash size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <Button
              type="submit"
              disabled={loading}
              data-testid="login-submit-btn"
              className="w-full h-11 rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white font-medium uppercase tracking-wider text-sm transition-fast"
            >
              {loading ? "..." : isLogin ? "Accedi" : "Registrati"}
            </Button>
          </form>

          {/* Toggle */}
          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={() => setIsLogin(!isLogin)}
              data-testid="toggle-auth-mode-btn"
              className="text-zinc-500 hover:text-zinc-300 text-sm transition-fast"
            >
              {isLogin ? "Non hai un account? Registrati" : "Hai già un account? Accedi"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
