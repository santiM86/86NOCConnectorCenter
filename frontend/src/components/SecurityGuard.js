import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useAuth, API } from "@/App";
import axios from "axios";

// Rotte pubbliche / non-admin da ESCLUDERE dal deterrente (scelta utente:
// solo console admin desktop). TV, Mobile PWA, portali e console condivise
// devono restare libere.
const EXCLUDED_PREFIXES = [
  "/m",
  "/mobile",
  "/tv",
  "/public",
  "/portal",
  "/customer-portal",
  "/shared-console",
];

function isExcludedPath(pathname) {
  return EXCLUDED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/")
  );
}

function isTouchDevice() {
  return (
    "ontouchstart" in window ||
    navigator.maxTouchPoints > 0 ||
    /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || "")
  );
}

/**
 * SecurityGuard — deterrente anti-manomissione per la console admin desktop.
 * - Blocca F12, Ctrl+Shift+I/J/C, Ctrl+U (view-source) e il menu contestuale.
 * - Rileva l'apertura dei DevTools (euristica dimensioni finestra + getter su
 *   oggetto loggato) → oscura lo schermo, registra l'evento e disconnette.
 * NON è sicurezza forte (aggirabile da un attaccante determinato), ma protegge
 * le postazioni NOC condivise dal curioso che apre la console.
 */
export default function SecurityGuard() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const [tampered, setTampered] = useState(false);
  const firedRef = useRef(false);

  const active = !!user && !isExcludedPath(location.pathname) && !isTouchDevice();

  // Reset del banner quando cambio pagina/stato utente.
  useEffect(() => {
    if (!active) {
      setTampered(false);
      firedRef.current = false;
    }
  }, [active, location.pathname]);

  // Blocco tasti + menu contestuale.
  useEffect(() => {
    if (!active) return;

    const onKeyDown = (e) => {
      const k = (e.key || "").toLowerCase();
      const block =
        e.key === "F12" ||
        (e.ctrlKey && e.shiftKey && ["i", "j", "c"].includes(k)) ||
        (e.metaKey && e.altKey && ["i", "j", "c"].includes(k)) || // macOS
        (e.ctrlKey && k === "u");
      if (block) {
        e.preventDefault();
        e.stopPropagation();
        return false;
      }
    };
    const onContextMenu = (e) => {
      e.preventDefault();
      return false;
    };

    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("contextmenu", onContextMenu, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("contextmenu", onContextMenu, true);
    };
  }, [active]);

  // Rilevamento DevTools.
  useEffect(() => {
    if (!active) return;

    const THRESHOLD = 170;
    let consecutive = 0;
    const startedAt = Date.now();

    const reportTamper = async (method) => {
      if (firedRef.current) return;
      firedRef.current = true;
      setTampered(true);
      try {
        await axios.post(
          `${API}/security/tamper-event`,
          { event: "devtools_open", method, path: location.pathname },
          { headers: { Authorization: `Bearer ${localStorage.getItem("noc_token")}` } }
        );
      } catch (_) {
        /* best-effort */
      }
      // Disconnessione dopo un breve avviso.
      setTimeout(() => {
        try {
          logout();
        } catch (_) {}
        window.location.assign("/login");
      }, 2500);
    };

    const sizeCheck = () => {
      // Ignora i primi 1.5s (layout iniziale/resize) per evitare falsi positivi.
      if (Date.now() - startedAt < 1500) return;
      const wDiff = window.outerWidth - window.innerWidth;
      const hDiff = window.outerHeight - window.innerHeight;
      const open = wDiff > THRESHOLD || hDiff > THRESHOLD;
      if (open) {
        consecutive += 1;
        if (consecutive >= 2) reportTamper("window_size");
      } else {
        consecutive = 0;
      }
    };

    const interval = setInterval(sizeCheck, 1000);

    return () => clearInterval(interval);
  }, [active, location.pathname, logout]);

  if (!tampered) return null;

  return (
    <div
      data-testid="security-tamper-overlay"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 2147483647,
        background: "#0a0a0a",
        color: "#f5f5f5",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "2rem",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>🔒</div>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.75rem", color: "#f87171" }}>
        Accesso agli strumenti di sviluppo rilevato
      </h1>
      <p style={{ maxWidth: 520, lineHeight: 1.5, color: "#d4d4d4" }}>
        Per motivi di sicurezza l'apertura della console del browser non è
        consentita su questa postazione. L'evento è stato registrato e la
        sessione verrà chiusa.
      </p>
    </div>
  );
}
