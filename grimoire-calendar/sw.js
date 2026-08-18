/* Service worker — offline shell.

   Two different strategies on purpose:

   * The app shell (HTML/CSS/JS/fonts) is cache-first. It changes only when I
     change it, and you want the window to paint instantly.

   * /ics is network-only, never cached here. calendar.js already keeps its own
     copy of the last good feed in localStorage and knows how old it is; a
     second, dumber cache in front of it would serve stale events with no way
     for the UI to tell you they were stale.

   Bump CACHE when shell files change — the old cache is dropped on activate. */

const CACHE = 'grimoire-v2';

const SHELL = [
  './',
  './index.html',
  './css/grimoire.css',
  './config.js',
  './js/app.js',
  './js/calendar.js',
  './js/render.js',
  './js/local.js',
  './js/moon.js',
  './js/store.js',
  './js/util.js',
  './js/areas.js',
  './vendor/ical.js',
  './fonts/fonts.css',
  './manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    // addAll is all-or-nothing; one 404 (a font you removed, say) would leave
    // the worker uninstalled forever. Fetch individually and keep what works.
    caches.open(CACHE).then(async (cache) => {
      await Promise.all(SHELL.map((url) => cache.add(url).catch(() => {})));
      self.skipWaiting();
    }),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.replace(/\/$/, '').endsWith('/ics')) return;   // always live

  event.respondWith(
    caches.match(event.request).then((hit) => {
      if (hit) {
        // Refresh in the background so the next launch is current. This must
        // always resolve to a promise — waitUntil() throws on a bare `false`.
        event.waitUntil(
          fetch(event.request)
            .then((res) => (res.ok ? caches.open(CACHE).then((c) => c.put(event.request, res)) : null))
            .catch(() => {}),
        );
        return hit;
      }
      // Only a NAVIGATION may fall back to the shell. Handing index.html back
      // for a failed .js request makes the browser reject it as "MIME type
      // text/html" — a confusing error that hides the real cause (the fetch
      // failed), and one that persists until the cache is cleared.
      return fetch(event.request).catch(() => (
        event.request.mode === 'navigate' ? caches.match('./index.html') : Response.error()
      ));
    }),
  );
});
