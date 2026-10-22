// Service worker: keeps the site and both models on the phone so it opens and runs with no network, and adds
// the cross-origin-isolation headers GitHub Pages cannot set (needed for multi-threaded WebAssembly).
const CACHE = 'hemlockid-v1';
const SHELL = ['./', 'index.html', 'speedtest/', 'speedtest/index.html', 'speedtest/app.js', 'lib/engine.js', 'lib/base.css',
  'speedtest/sample.jpg', 'speedtest/reference.json', 'vendor/ort/ort.all.min.mjs', 'apple-touch-icon.png', 'icon-512.png', 'manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const isolate = (res) => {
  if (!res || res.status === 0 || res.type === 'opaque') return res;
  const h = new Headers(res.headers);
  h.set('Cross-Origin-Embedder-Policy', 'require-corp');
  h.set('Cross-Origin-Opener-Policy', 'same-origin');
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
};

// Big files (models, runtime) never change at the same URL: cache first. Pages and code: network first, so an
// update shows up when online, with the cached copy when offline.
const big = (url) => /\/(models|vendor)\//.test(url.pathname) || url.pathname.endsWith('.wasm');

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    if (big(url)) {
      const hit = await cache.match(e.request, { ignoreSearch: true });
      if (hit) return isolate(hit);
      const res = await fetch(e.request);
      if (res.ok) cache.put(e.request, res.clone());
      return isolate(res);
    }
    try {
      const res = await fetch(e.request);
      if (res.ok) cache.put(e.request, res.clone());
      return isolate(res);
    } catch {
      const hit = await cache.match(e.request, { ignoreSearch: true });
      if (hit) return isolate(hit);
      throw new Error('offline and not cached');
    }
  })());
});
