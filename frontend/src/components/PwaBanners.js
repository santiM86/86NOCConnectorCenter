import { useState, useEffect } from "react";
import { usePwa } from "@/components/PwaProvider";
import { DownloadSimple, Bell, WifiSlash, X, Check } from "@phosphor-icons/react";

export function PwaInstallBanner() {
  const pwa = usePwa();
  const [dismissed, setDismissed] = useState(false);

  if (!pwa?.installPrompt || pwa.isInstalled || dismissed) return null;

  return (
    <div
      className="fixed bottom-20 md:bottom-4 left-4 right-4 md:left-auto md:right-4 md:w-80 bg-[var(--bg-panel)] border border-indigo-500/30 rounded-xl p-3 shadow-2xl z-50 animate-in slide-in-from-bottom duration-300"
      data-testid="pwa-install-banner"
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-indigo-500/15 flex items-center justify-center flex-shrink-0">
          <DownloadSimple size={20} className="text-indigo-400" weight="bold" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-[var(--text-primary)]">Installa NOC Center</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
            Aggiungi alla Home per accesso rapido e notifiche push
          </p>
          <div className="flex gap-2 mt-2">
            <button
              onClick={async () => {
                const ok = await pwa.promptInstall();
                if (!ok) setDismissed(true);
              }}
              className="px-3 py-1 rounded-lg bg-indigo-600 text-white text-[10px] font-semibold hover:bg-indigo-500 transition-colors"
              data-testid="pwa-install-btn"
            >
              Installa
            </button>
            <button
              onClick={() => setDismissed(true)}
              className="px-3 py-1 rounded-lg text-[var(--text-muted)] text-[10px] hover:bg-[var(--bg-app)] transition-colors"
            >
              Non ora
            </button>
          </div>
        </div>
        <button onClick={() => setDismissed(true)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

export function NotificationPermissionBanner() {
  const pwa = usePwa();
  const [dismissed, setDismissed] = useState(false);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const d = localStorage.getItem("noc_notif_dismissed");
    if (d) setDismissed(true);
  }, []);

  if (!pwa || pwa.notificationPermission !== "default" || dismissed) return null;

  const handleEnable = async () => {
    const perm = await pwa.requestNotificationPermission();
    if (perm === "granted") {
      setEnabled(true);
      setTimeout(() => setDismissed(true), 2000);
    } else {
      setDismissed(true);
      localStorage.setItem("noc_notif_dismissed", "1");
    }
  };

  return (
    <div
      className="fixed bottom-20 md:bottom-4 left-4 right-4 md:left-auto md:right-4 md:w-80 bg-[var(--bg-panel)] border border-amber-500/30 rounded-xl p-3 shadow-2xl z-50 animate-in slide-in-from-bottom duration-300"
      data-testid="notification-permission-banner"
    >
      {enabled ? (
        <div className="flex items-center gap-2 text-emerald-400">
          <Check size={16} weight="bold" />
          <span className="text-xs font-medium">Notifiche attivate!</span>
        </div>
      ) : (
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/15 flex items-center justify-center flex-shrink-0">
            <Bell size={20} className="text-amber-400" weight="bold" />
          </div>
          <div className="flex-1">
            <p className="text-xs font-semibold text-[var(--text-primary)]">Attiva le Notifiche</p>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
              Ricevi alert critici anche quando l'app non e' in primo piano
            </p>
            <div className="flex gap-2 mt-2">
              <button
                onClick={handleEnable}
                className="px-3 py-1 rounded-lg bg-amber-600 text-white text-[10px] font-semibold hover:bg-amber-500 transition-colors"
                data-testid="enable-notifications-btn"
              >
                Attiva
              </button>
              <button
                onClick={() => { setDismissed(true); localStorage.setItem("noc_notif_dismissed", "1"); }}
                className="px-3 py-1 rounded-lg text-[var(--text-muted)] text-[10px] hover:bg-[var(--bg-app)] transition-colors"
              >
                Non ora
              </button>
            </div>
          </div>
          <button onClick={() => { setDismissed(true); localStorage.setItem("noc_notif_dismissed", "1"); }} className="text-[var(--text-muted)]">
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

export function OfflineIndicator() {
  const pwa = usePwa();
  if (!pwa || pwa.isOnline) return null;

  return (
    <div
      className="fixed top-0 left-0 right-0 bg-amber-600 text-white text-center py-1 text-xs font-medium z-[100] flex items-center justify-center gap-2"
      data-testid="offline-indicator"
    >
      <WifiSlash size={14} weight="bold" />
      Sei offline — i dati potrebbero non essere aggiornati
    </div>
  );
}
