import { useState, useEffect, useCallback, useRef, createContext, useContext } from "react";
import { API } from "@/App";
import axios from "axios";
import { ArrowClockwise } from "@phosphor-icons/react";

const LS_HASH_KEY = "argus_app_hash";
const LS_VERSION_KEY = "argus_app_version";
const POLL_INTERVAL = 60000;

const VersionContext = createContext(null);

export function VersionProvider({ children }) {
  const [version, setVersion] = useState(() => localStorage.getItem(LS_VERSION_KEY) || null);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const hashRef = useRef(localStorage.getItem(LS_HASH_KEY) || null);
  const initialLoadDone = useRef(false);

  const checkVersion = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/app-version`);
      const serverVersion = res.data.version;
      const serverHash = res.data.hash;

      if (!initialLoadDone.current) {
        const storedHash = localStorage.getItem(LS_HASH_KEY);
        if (storedHash && storedHash !== serverHash) {
          const alreadyReloaded = sessionStorage.getItem("argus_auto_reloaded");
          if (!alreadyReloaded) {
            sessionStorage.setItem("argus_auto_reloaded", "1");
            localStorage.setItem(LS_HASH_KEY, serverHash);
            localStorage.setItem(LS_VERSION_KEY, serverVersion);
            window.location.reload();
            return;
          }
        }
        localStorage.setItem(LS_HASH_KEY, serverHash);
        localStorage.setItem(LS_VERSION_KEY, serverVersion);
        hashRef.current = serverHash;
        setVersion(serverVersion);
        initialLoadDone.current = true;
        sessionStorage.removeItem("argus_auto_reloaded");
        return;
      }

      if (serverHash !== hashRef.current) {
        setUpdateAvailable(true);
      }
      setVersion(serverVersion);
    } catch {
      // Silent fail
    }
  }, []);

  useEffect(() => {
    checkVersion();
    const interval = setInterval(checkVersion, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [checkVersion]);

  const applyUpdate = useCallback(async () => {
    if ("caches" in window) {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    }
    localStorage.removeItem(LS_HASH_KEY);
    localStorage.removeItem(LS_VERSION_KEY);
    window.location.href = window.location.pathname + "?_upd=" + Date.now();
  }, []);

  return (
    <VersionContext.Provider value={{ version, updateAvailable, applyUpdate }}>
      {children}
    </VersionContext.Provider>
  );
}

export function useAppVersion() {
  return useContext(VersionContext) || { version: null, updateAvailable: false, applyUpdate: () => {} };
}

export function VersionBadge() {
  const { version } = useAppVersion();
  if (!version) return null;
  return (
    <span
      className="text-[10px] font-mono text-[var(--text-muted)] opacity-60 select-none"
      data-testid="app-version-badge"
      title={`ARGUS Center v${version}`}
    >
      V.{version}
    </span>
  );
}

export function UpdateBanner() {
  const { updateAvailable, applyUpdate, version } = useAppVersion();
  if (!updateAvailable) return null;

  return (
    <div
      className="fixed top-0 left-0 right-0 z-[100] flex items-center justify-center gap-3 py-2 px-4 bg-indigo-600/95 backdrop-blur-sm text-white text-xs font-medium shadow-lg"
      data-testid="update-banner"
    >
      <ArrowClockwise size={14} className="animate-spin" />
      <span>Nuova versione disponibile (v{version})</span>
      <button
        onClick={applyUpdate}
        className="ml-2 px-3 py-1 rounded-md bg-white/20 hover:bg-white/30 text-white text-[11px] font-semibold transition-colors"
        data-testid="update-now-btn"
      >
        Aggiorna ora
      </button>
    </div>
  );
}
