const CACHE_NAME = 'noc-center-v14';
const OFFLINE_URL = '/offline.html';

// Assets statici da precachare per funzionamento offline
const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/offline.html',
];

// ==================== INSTALL ====================
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_ASSETS))
  );
  self.skipWaiting();
});

// ==================== MESSAGE (SKIP_WAITING per update immediato) ====================
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// ==================== ACTIVATE ====================
self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Elimina TUTTE le cache diverse da quella corrente (anche quelle di versioni precedenti SW)
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

// ==================== FETCH (Stale-While-Revalidate per assets, Network-First per API) ====================
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // CRITICO: bypass assoluto per API del Web Console proxy.
  // L'iframe deve ricevere l'HTML dei device REMOTI, non l'app shell di ARGUS.
  // Questi path NON devono MAI essere intercettati dal service worker.
  if (
    url.pathname.startsWith('/api/web-proxy/live/') ||
    url.pathname.startsWith('/api/web-console/') ||
    url.pathname.startsWith('/api/connector/web-proxy/')
  ) {
    // Lascia che il network handler del browser gestisca la richiesta
    return;
  }

  // Non intercettare richieste non-GET, API generiche o WebSocket
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/ws')) return;
  if (url.protocol === 'chrome-extension:') return;

  // Navigazione HTML: Network-first con fallback offline
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request).then((r) => r || caches.match(OFFLINE_URL)))
    );
    return;
  }

  // Assets statici: Stale-While-Revalidate
  if (url.pathname.match(/\.(js|css|png|jpg|jpeg|svg|woff2?|ttf|ico)$/)) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Tutto il resto: Network-first
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && url.origin === self.location.origin) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// ==================== PUSH NOTIFICATIONS ====================
self.addEventListener('push', (event) => {
  let data = { title: 'NOC Alert', body: 'Nuovo alert dal NOC', icon: '/icon-192.png' };

  try {
    if (event.data) {
      const payload = event.data.json();
      data = {
        title: payload.title || data.title,
        body: payload.body || data.body,
        icon: payload.icon || data.icon,
        badge: '/icon-192.png',
        tag: payload.tag || 'noc-alert',
        data: payload.data || {},
        vibrate: [200, 100, 200],
        actions: payload.actions || [
          { action: 'view', title: 'Visualizza' },
          { action: 'dismiss', title: 'Ignora' },
        ],
        requireInteraction: payload.severity === 'critical',
      };
    }
  } catch {
    if (event.data) {
      data.body = event.data.text();
    }
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      badge: data.badge,
      tag: data.tag,
      data: data.data,
      vibrate: data.vibrate,
      actions: data.actions,
      requireInteraction: data.requireInteraction || false,
    })
  );
});

// ==================== NOTIFICATION CLICK ====================
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const alertData = event.notification.data || {};
  let targetUrl = '/';

  if (event.action === 'view' && alertData.alert_id) {
    targetUrl = `/alerts/${alertData.alert_id}`;
  } else if (alertData.url) {
    targetUrl = alertData.url;
  }

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Cerca una finestra gia' aperta
      for (const client of clientList) {
        if (client.url.includes(self.registration.scope) && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      // Apri nuova finestra
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});

// ==================== BACKGROUND SYNC (per invio dati offline) ====================
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-alerts') {
    event.waitUntil(syncPendingAlerts());
  }
});

async function syncPendingAlerts() {
  try {
    const cache = await caches.open('noc-pending-actions');
    const keys = await cache.keys();
    for (const request of keys) {
      try {
        const response = await fetch(request.clone());
        if (response.ok) {
          await cache.delete(request);
        }
      } catch {
        // Riprova al prossimo sync
      }
    }
  } catch {
    // Cache non disponibile
  }
}

// ==================== PERIODIC BACKGROUND SYNC (check alert periodico) ====================
self.addEventListener('periodicsync', (event) => {
  if (event.tag === 'check-alerts') {
    event.waitUntil(checkNewAlerts());
  }
});

async function checkNewAlerts() {
  try {
    const response = await fetch('/api/stats/summary');
    if (response.ok) {
      const data = await response.json();
      if (data.total_active > 0) {
        await self.registration.showNotification('NOC Alert Check', {
          body: `${data.total_active} alert attivi`,
          icon: '/icon-192.png',
          badge: '/icon-192.png',
          tag: 'periodic-check',
        });
      }
    }
  } catch {
    // Offline o errore - ignora
  }
}
