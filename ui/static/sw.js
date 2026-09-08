// SPIDY CRYPTO 2.0 - Progressive Web App Service Worker
const CACHE_NAME = 'spidy-crypto-v4.1';
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js?v=4.1.0',
  '/static/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Let API and WebSocket calls pass through directly to live server
  if (event.request.url.includes('/api/') || event.request.url.includes('/ws')) {
    return;
  }

  // Network-first for page navigation so updates reflect immediately
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      return cachedResponse || fetch(event.request);
    })
  );
});
