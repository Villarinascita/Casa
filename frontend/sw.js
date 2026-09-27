// Service worker: solo l'interfaccia va in cache (rete prima, cache se offline). Mai i dati di /api.
// Aggiornare VERSION a ogni rilascio che cambia l'elenco dei file.

const VERSION = '16';
const CACHE = `insieme-shell-v${VERSION}`;
const ASSETS = [
  './', './index.html', './styles.css', './layout.css', './manifest.webmanifest', './icon.svg',
  './js/main.js', './js/api.js', './js/store.js', './js/dom.js', './js/dates.js', './js/editor.js',
  './js/views/common.js', './js/views/oggi.js', './js/views/calendario.js', './js/views/attivita.js',
  './js/views/spesa.js', './js/views/famiglia.js', './js/views/archivio.js', './js/views/impostazioni.js',
  './js/views/login.js', './js/views/controllare.js', './js/views/altro.js', './js/views/nonni.js',
];

self.addEventListener('install', (event) => {
  // cache: 'reload' e 'no-cache': Cloudflare dice ai browser di tenere i file 4 ore; qui si chiede sempre
  // al server (con ETag, quindi costa poco) per non restare su una versione vecchia dopo un rilascio.
  event.waitUntil(caches.open(CACHE)
    .then((cache) => cache.addAll(ASSETS.map((path) => new Request(path, { cache: 'reload' }))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('insieme-shell-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  const shell = ASSETS.some((path) => new URL(path, self.registration.scope).href === url.href);
  if (!shell) return;
  event.respondWith(
    fetch(request, { cache: 'no-cache' })
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request)),
  );
});
