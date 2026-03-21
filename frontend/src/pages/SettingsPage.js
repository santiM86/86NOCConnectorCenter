import { useState, useEffect } from "react";
import axios from "axios";
import { API, useAuth } from "@/App";
import { toast } from "sonner";
import { 
  Shield, 
  Key, 
  Bell, 
  Globe, 
  Clock,
  QrCode,
  Copy,
  Check
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export default function SettingsPage() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  
  // 2FA State
  const [twoFADialogOpen, setTwoFADialogOpen] = useState(false);
  const [twoFASetup, setTwoFASetup] = useState(null);
  const [verificationCode, setVerificationCode] = useState("");
  const [password, setPassword] = useState("");
  
  // Notification Settings
  const [notifSettings, setNotifSettings] = useState({
    email_enabled: true,
    push_enabled: true,
    webhook_teams: "",
    webhook_slack: "",
    webhook_telegram: "",
    webhook_generic: ""
  });
  
  // Redfish Settings
  const [redfishSettings, setRedfishSettings] = useState({
    poll_interval_minutes: 5
  });

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      const [notifRes, redfishRes] = await Promise.all([
        axios.get(`${API}/settings/notifications`),
        axios.get(`${API}/settings/redfish`)
      ]);
      
      setNotifSettings(prev => ({
        ...prev,
        ...notifRes.data
      }));
      
      setRedfishSettings(redfishRes.data);
    } catch (error) {
      console.error("Error fetching settings:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveNotifications = async () => {
    setSaving(true);
    try {
      await axios.post(`${API}/settings/notifications`, notifSettings);
      toast.success("Impostazioni notifiche salvate");
    } catch (error) {
      toast.error("Errore nel salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveRedfish = async () => {
    setSaving(true);
    try {
      await axios.post(`${API}/settings/redfish?poll_interval=${redfishSettings.poll_interval_minutes}`);
      toast.success("Impostazioni Redfish salvate");
    } catch (error) {
      toast.error("Errore nel salvataggio");
    } finally {
      setSaving(false);
    }
  };

  const handleSetup2FA = async () => {
    try {
      const response = await axios.post(`${API}/auth/setup-2fa`, { password });
      setTwoFASetup(response.data);
      setPassword("");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Errore");
    }
  };

  const handleConfirm2FA = async () => {
    try {
      await axios.post(`${API}/auth/confirm-2fa`, { code: verificationCode });
      toast.success("2FA attivato con successo!");
      setTwoFADialogOpen(false);
      setTwoFASetup(null);
      setVerificationCode("");
      window.location.reload();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Codice non valido");
    }
  };

  const handleDisable2FA = async () => {
    try {
      await axios.post(`${API}/auth/disable-2fa`, { password });
      toast.success("2FA disattivato");
      setPassword("");
      window.location.reload();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Errore");
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copiato!");
  };

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto" data-testid="settings-page">
      {/* Header */}
      <div className="mb-6">
        <h1 className="font-heading text-2xl font-bold text-zinc-100 tracking-tight">
          Impostazioni
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          Configura sicurezza, notifiche e polling
        </p>
      </div>

      <Tabs defaultValue="security" className="space-y-6">
        <TabsList className="bg-zinc-900 border border-zinc-800 rounded-sm p-1">
          <TabsTrigger 
            value="security" 
            className="rounded-sm data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100"
          >
            <Shield size={16} className="mr-2" />
            Sicurezza
          </TabsTrigger>
          <TabsTrigger 
            value="notifications"
            className="rounded-sm data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100"
          >
            <Bell size={16} className="mr-2" />
            Notifiche
          </TabsTrigger>
          <TabsTrigger 
            value="redfish"
            className="rounded-sm data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100"
          >
            <Clock size={16} className="mr-2" />
            Redfish Polling
          </TabsTrigger>
        </TabsList>

        {/* Security Tab */}
        <TabsContent value="security">
          <div className="noc-panel p-6 space-y-6">
            <div>
              <h2 className="font-heading text-lg font-semibold text-zinc-100 mb-4 flex items-center gap-2">
                <Key size={20} />
                Autenticazione a Due Fattori (2FA)
              </h2>
              
              <div className="p-4 bg-zinc-800/50 rounded-sm border border-zinc-700 mb-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-zinc-200 font-medium">
                      {user?.two_factor_enabled ? "2FA Attivo" : "2FA Non Attivo"}
                    </p>
                    <p className="text-zinc-500 text-sm mt-1">
                      {user?.two_factor_enabled 
                        ? "Il tuo account è protetto con autenticazione a due fattori"
                        : "Aggiungi un ulteriore livello di sicurezza al tuo account"
                      }
                    </p>
                  </div>
                  <div className={`w-3 h-3 rounded-full ${user?.two_factor_enabled ? "bg-green-400" : "bg-zinc-600"}`} />
                </div>
              </div>

              {!user?.two_factor_enabled ? (
                <Button
                  onClick={() => setTwoFADialogOpen(true)}
                  className="rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white"
                >
                  <Shield size={16} className="mr-2" />
                  Attiva 2FA
                </Button>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                      Password per disattivare
                    </Label>
                    <Input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm max-w-xs"
                    />
                  </div>
                  <Button
                    onClick={handleDisable2FA}
                    variant="outline"
                    className="rounded-sm border-red-800 text-red-400 hover:bg-red-900/20"
                  >
                    Disattiva 2FA
                  </Button>
                </div>
              )}
            </div>

            {/* Security Info */}
            <div className="border-t border-zinc-800 pt-6">
              <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4">
                Sicurezza Enterprise
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="p-3 bg-zinc-800/30 rounded-sm border border-zinc-800">
                  <p className="text-green-400 text-sm font-medium">AES-256-GCM</p>
                  <p className="text-zinc-500 text-xs mt-1">Crittografia credenziali</p>
                </div>
                <div className="p-3 bg-zinc-800/30 rounded-sm border border-zinc-800">
                  <p className="text-green-400 text-sm font-medium">Argon2id</p>
                  <p className="text-zinc-500 text-xs mt-1">Hash password</p>
                </div>
                <div className="p-3 bg-zinc-800/30 rounded-sm border border-zinc-800">
                  <p className="text-green-400 text-sm font-medium">Rate Limiting</p>
                  <p className="text-zinc-500 text-xs mt-1">Protezione brute force</p>
                </div>
                <div className="p-3 bg-zinc-800/30 rounded-sm border border-zinc-800">
                  <p className="text-green-400 text-sm font-medium">Audit Log</p>
                  <p className="text-zinc-500 text-xs mt-1">Tracciamento completo</p>
                </div>
              </div>
            </div>
          </div>
        </TabsContent>

        {/* Notifications Tab */}
        <TabsContent value="notifications">
          <div className="noc-panel p-6 space-y-6">
            <h2 className="font-heading text-lg font-semibold text-zinc-100 mb-4 flex items-center gap-2">
              <Bell size={20} />
              Canali di Notifica
            </h2>

            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-zinc-800/50 rounded-sm border border-zinc-700">
                <div>
                  <p className="text-zinc-200 font-medium">Email</p>
                  <p className="text-zinc-500 text-sm">Notifiche via email per alert critici</p>
                </div>
                <Switch
                  checked={notifSettings.email_enabled}
                  onCheckedChange={(checked) => setNotifSettings(s => ({ ...s, email_enabled: checked }))}
                />
              </div>

              <div className="flex items-center justify-between p-4 bg-zinc-800/50 rounded-sm border border-zinc-700">
                <div>
                  <p className="text-zinc-200 font-medium">Push Notifications</p>
                  <p className="text-zinc-500 text-sm">Notifiche push su mobile e browser</p>
                </div>
                <Switch
                  checked={notifSettings.push_enabled}
                  onCheckedChange={(checked) => setNotifSettings(s => ({ ...s, push_enabled: checked }))}
                />
              </div>
            </div>

            <div className="border-t border-zinc-800 pt-6">
              <h3 className="font-heading text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4 flex items-center gap-2">
                <Globe size={16} />
                Webhook Integrations
              </h3>
              
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                    Microsoft Teams Webhook
                  </Label>
                  <Input
                    value={notifSettings.webhook_teams || ""}
                    onChange={(e) => setNotifSettings(s => ({ ...s, webhook_teams: e.target.value }))}
                    placeholder="https://outlook.office.com/webhook/..."
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono text-sm"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                    Slack Webhook
                  </Label>
                  <Input
                    value={notifSettings.webhook_slack || ""}
                    onChange={(e) => setNotifSettings(s => ({ ...s, webhook_slack: e.target.value }))}
                    placeholder="https://hooks.slack.com/services/..."
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono text-sm"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                    Telegram Chat ID
                  </Label>
                  <Input
                    value={notifSettings.webhook_telegram || ""}
                    onChange={(e) => setNotifSettings(s => ({ ...s, webhook_telegram: e.target.value }))}
                    placeholder="-1001234567890"
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono text-sm"
                  />
                </div>

                <div className="space-y-2">
                  <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                    Webhook Generico
                  </Label>
                  <Input
                    value={notifSettings.webhook_generic || ""}
                    onChange={(e) => setNotifSettings(s => ({ ...s, webhook_generic: e.target.value }))}
                    placeholder="https://your-endpoint.com/webhook"
                    className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono text-sm"
                  />
                </div>
              </div>
            </div>

            <Button
              onClick={handleSaveNotifications}
              disabled={saving}
              className="rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white"
            >
              {saving ? "Salvataggio..." : "Salva Impostazioni Notifiche"}
            </Button>
          </div>
        </TabsContent>

        {/* Redfish Tab */}
        <TabsContent value="redfish">
          <div className="noc-panel p-6 space-y-6">
            <h2 className="font-heading text-lg font-semibold text-zinc-100 mb-4 flex items-center gap-2">
              <Clock size={20} />
              Redfish API Polling
            </h2>

            <div className="p-4 bg-blue-900/20 border border-blue-800/50 rounded-sm mb-4">
              <p className="text-blue-400 text-sm">
                Il sistema interroga automaticamente tutti i dispositivi iLO/iDRAC configurati 
                con Redfish abilitato per ottenere stato hardware, temperature e eventi.
              </p>
            </div>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Intervallo Polling (minuti)
                </Label>
                <Input
                  type="number"
                  min={1}
                  max={60}
                  value={redfishSettings.poll_interval_minutes}
                  onChange={(e) => setRedfishSettings(s => ({ ...s, poll_interval_minutes: parseInt(e.target.value) || 5 }))}
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm max-w-xs"
                />
                <p className="text-zinc-500 text-xs">
                  Valori consigliati: 5-15 minuti per monitoraggio attivo
                </p>
              </div>
            </div>

            <Button
              onClick={handleSaveRedfish}
              disabled={saving}
              className="rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white"
            >
              {saving ? "Salvataggio..." : "Salva Impostazioni Redfish"}
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      {/* 2FA Setup Dialog */}
      <Dialog open={twoFADialogOpen} onOpenChange={setTwoFADialogOpen}>
        <DialogContent className="bg-zinc-900 border-zinc-800 rounded-sm max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading text-zinc-100 flex items-center gap-2">
              <Shield size={20} />
              Configura Autenticazione 2FA
            </DialogTitle>
          </DialogHeader>
          
          {!twoFASetup ? (
            <div className="space-y-4 mt-4">
              <p className="text-zinc-400 text-sm">
                Inserisci la tua password per generare il codice QR per l'app di autenticazione.
              </p>
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Password *
                </Label>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm"
                />
              </div>
              <Button
                onClick={handleSetup2FA}
                className="w-full rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white"
              >
                Genera QR Code
              </Button>
            </div>
          ) : (
            <div className="space-y-4 mt-4">
              <p className="text-zinc-400 text-sm">
                Scansiona il QR code con Google Authenticator, Authy o un'altra app 2FA.
              </p>
              
              {/* QR Code */}
              <div className="flex justify-center p-4 bg-white rounded-sm">
                <img 
                  src={`data:image/png;base64,${twoFASetup.qr_code}`} 
                  alt="QR Code 2FA"
                  className="w-48 h-48"
                />
              </div>
              
              {/* Manual Entry */}
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Oppure inserisci manualmente:
                </Label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 p-2 bg-zinc-800 border border-zinc-700 rounded-sm text-zinc-300 text-xs font-mono">
                    {twoFASetup.secret}
                  </code>
                  <Button
                    size="icon"
                    variant="outline"
                    onClick={() => copyToClipboard(twoFASetup.secret)}
                    className="rounded-sm border-zinc-700 h-9 w-9"
                  >
                    <Copy size={14} />
                  </Button>
                </div>
              </div>
              
              {/* Verification */}
              <div className="space-y-2">
                <Label className="text-zinc-400 text-xs uppercase tracking-wider">
                  Codice di Verifica *
                </Label>
                <Input
                  value={verificationCode}
                  onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="000000"
                  maxLength={6}
                  className="bg-zinc-800 border-zinc-700 text-zinc-100 rounded-sm font-mono text-center text-2xl tracking-widest"
                />
              </div>
              
              <Button
                onClick={handleConfirm2FA}
                disabled={verificationCode.length !== 6}
                className="w-full rounded-sm bg-zinc-100 text-zinc-900 hover:bg-white"
              >
                <Check size={16} className="mr-2" />
                Conferma e Attiva 2FA
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
