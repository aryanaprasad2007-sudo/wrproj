/* Daily Docket service worker.
   Bump CACHE_VERSION whenever you change files in PRECACHE — that's what makes
   an installed copy pick up your edits. */

const CACHE_VERSION = 'v2';
const CACHE = `docket-${CACHE_VERSION}`;

const PRECACHE = [
  './',
  './index.html',
  './manifest.webmanifest',
  './css/styles.css',
  './fonts/fonts.css',
  './fonts/Quicksand-latin.woff2',
  './fonts/Quicksand-latin-ext.woff2',
  './fonts/Nunito-latin.woff2',
  './fonts/Nunito-latin-ext.woff2',
  './vendor/ical.js',
  './config.js',
  './js/app.js',
  './js/settings.js',
  './js/areas.js',
  './js/calendar.js',
  './js/filters.js',
  './js/importance.js',
  './js/countdown.js',
  './js/render.js',
  './js/store.js',
  './js/util.js',
  './icons/favicon.svg',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/apple-touch-icon-180.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      // addAll is all-or-nothing; add individually so one 404 can't brick install.
      await Promise.all(
        PRECACHE.map((url) =>
          cache.add(new Request(url, { cache: 'reload' })).catch((err) => {
            console.warn('[sw] skipped precache:', url, err);
          }),
        ),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

const isCalendarRequest = (url) =>
  url.pathname.endsWith('/ics') ||
  url.pathname.endsWith('.ics') ||
  url.searchParams.has('ics');

/* On localhost the cache would hand you yesterday's JavaScript every time you
   edit a file, so dev flips to network-first. Offline still works — it just
   falls back to the cache instead of preferring it. */
const DEV = ['localhost', '127.0.0.1', '[::1]', ''].includes(self.location.hostname);

async function networkFirst(request, cache) {
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok && fresh.type === 'basic') cache.put(request, fresh.clone());
    return fresh;
  } catch {
    return (
      (await cache.match(request, { ignoreSearch: true })) ||
      new Response('', { status: 504, statusText: 'Offline' })
    );
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Calendar data is never served from the SW cache — the app keeps its own
  // last-good copy in localStorage and knows how to say "this is stale".
  if (isCalendarRequest(url) || url.origin !== self.location.origin) return;

  if (DEV && request.mode !== 'navigate') {
    event.respondWith(caches.open(CACHE).then((cache) => networkFirst(request, cache)));
    return;
  }

  // Navigations: try the network so a redeploy is picked up, fall back to shell.
  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(request);
          const cache = await caches.open(CACHE);
          cache.put('./index.html', fresh.clone());
          return fresh;
        } catch {
          return (await caches.match('./index.html')) || (await caches.match('./')) ||
            new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
        }
      })(),
    );
    return;
  }

  // Everything else: serve from cache instantly, refresh it in the background.
  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(request, { ignoreSearch: true });
      const network = fetch(request)
        .then((res) => {
          if (res && res.ok && res.type === 'basic') cache.put(request, res.clone());
          return res;
        })
        .catch(() => null);
      return hit || (await network) ||
        new Response('', { status: 504, statusText: 'Offline' });
    })(),
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});
