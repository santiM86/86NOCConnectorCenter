import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { API } from "@/App";
import axios from "axios";

const PwaContext = createContext(null);
export const usePwa = () => useContext(PwaContext);

// VAPID public key placeholder - will use Web Push API when available
const urlBase64ToUint8Array = (base64String) => {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
};

export function PwaProvider({ children }) {
  const [installPrompt, setInstallPrompt] = useState(null);
  const [isInstalled, setIsInstalled] = useState(false);
  const [notificationPermission, setNotificationPermission] = useState(
    typeof Notification !== "undefined" ? Notification.permission : "default"
  );
  const [swRegistration, setSwRegistration] = useState(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  // Detect if already installed
  useEffect(() => {
    const mq = window.matchMedia("(display-mode: standalone)");
    setIsInstalled(mq.matches || window.navigator.standalone === true);
    const handler = (e) => setIsInstalled(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Capture beforeinstallprompt
  useEffect(() => {
    const handler = (e) => {
      e.preventDefault();
      setInstallPrompt(e);
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  // Online/Offline detection
  useEffect(() => {
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  // Service Worker registration
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.getRegistration().then((reg) => {
        if (reg) setSwRegistration(reg);
      });
    }
  }, []);

  const promptInstall = useCallback(async () => {
    if (!installPrompt) return false;
    installPrompt.prompt();
    const result = await installPrompt.userChoice;
    setInstallPrompt(null);
    if (result.outcome === "accepted") {
      setIsInstalled(true);
      return true;
    }
    return false;
  }, [installPrompt]);

  const requestNotificationPermission = useCallback(async () => {
    if (!("Notification" in window)) return "unsupported";
    const permission = await Notification.requestPermission();
    setNotificationPermission(permission);
    return permission;
  }, []);

  const subscribeToPush = useCallback(async () => {
    if (!swRegistration) return null;
    try {
      const sub = await swRegistration.pushManager.getSubscription();
      if (sub) return sub;
      // Note: Without a real VAPID key, we can still use the Notification API directly
      return null;
    } catch {
      return null;
    }
  }, [swRegistration]);

  const showLocalNotification = useCallback((title, options = {}) => {
    if (notificationPermission !== "granted") return;
    if (swRegistration) {
      swRegistration.showNotification(title, {
        icon: "/icon-192.png",
        badge: "/icon-192.png",
        vibrate: [200, 100, 200],
        ...options,
      });
    } else if ("Notification" in window) {
      new Notification(title, {
        icon: "/icon-192.png",
        ...options,
      });
    }
  }, [notificationPermission, swRegistration]);

  return (
    <PwaContext.Provider value={{
      installPrompt: !!installPrompt,
      isInstalled,
      isOnline,
      notificationPermission,
      promptInstall,
      requestNotificationPermission,
      subscribeToPush,
      showLocalNotification,
      swRegistration,
    }}>
      {children}
    </PwaContext.Provider>
  );
}
