import { useState, useEffect } from "react";
import axios from "axios";
import { API, useAuth } from "@/App";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Gear, ShieldCheck, Bell, Key } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export default function SettingsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="p-4 md:p-5 animate-fade-in" data-testid="settings-page">
      <div className="mb-5">
        <h1 className="font-heading text-xl font-bold text-[var(--text-primary)] tracking-tight">Impostazioni</h1>
        <p className="text-[var(--text-muted)] text-xs mt-0.5">Profilo e sicurezza</p>
      </div>

      <div className="space-y-4 max-w-lg">
        <div className="noc-panel p-5">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <Gear size={13} /> Profilo
          </h3>
          <div className="space-y-2">
            <SettingRow label="Nome" value={user?.name} />
            <SettingRow label="Email" value={user?.email} mono />
            <SettingRow label="Ruolo" value={user?.role?.toUpperCase()} />
          </div>
        </div>

        <div className="noc-panel p-5">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <ShieldCheck size={13} /> Sicurezza
          </h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[var(--text-primary)] text-xs font-medium">Autenticazione 2FA</p>
                <p className="text-[var(--text-muted)] text-[10px] mt-0.5">
                  {user?.two_factor_enabled ? "Attiva - La verifica TOTP è abilitata" : "Non attiva - Si consiglia di abilitarla"}
                </p>
              </div>
              <Button size="sm" variant="outline"
                onClick={() => navigate("/2fa")}
                className="rounded-md text-xs h-7 border-[var(--bg-border)] hover:bg-[var(--bg-hover)]"
                data-testid="manage-2fa-btn">
                {user?.two_factor_enabled ? "Gestisci" : "Attiva"}
              </Button>
            </div>
          </div>
        </div>

        <div className="noc-panel p-5">
          <h3 className="text-[var(--text-muted)] text-[10px] font-medium uppercase tracking-widest mb-3 flex items-center gap-1.5">
            <Key size={13} /> API Keys
          </h3>
          <p className="text-[var(--text-muted)] text-xs">
            Usa le API keys dei clienti per inviare trap SNMP e syslog al sistema.
          </p>
        </div>
      </div>
    </div>
  );
}

function SettingRow({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--bg-border)] last:border-0">
      <span className="text-[var(--text-muted)] text-xs">{label}</span>
      <span className={`text-[var(--text-primary)] text-xs ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}
