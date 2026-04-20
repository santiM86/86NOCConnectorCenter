import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .then((reg) => {
        // Forza update check immediato - se c'e' una versione nuova, la installa e la attiva.
        // Senza questo, il browser aspetta fino a 24h prima di controllare nuovi SW.
        reg.update().catch(() => {});
        // Quando un nuovo SW entra in stato 'waiting', forza skipWaiting via postMessage
        if (reg.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        reg.addEventListener('updatefound', () => {
          const nw = reg.installing;
          if (!nw) return;
          nw.addEventListener('statechange', () => {
            if (nw.state === 'installed' && navigator.serviceWorker.controller) {
              // Nuova versione pronta: refresha la pagina per evitare conflitti Web Console iframe
              nw.postMessage({ type: 'SKIP_WAITING' });
            }
          });
        });
      })
      .catch(() => {});
  });
  // Reload pagina quando nuovo SW prende controllo (una volta per sessione)
  let _swReloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (_swReloaded) return;
    _swReloaded = true;
    // Soft reload
    window.location.reload();
  });
}
