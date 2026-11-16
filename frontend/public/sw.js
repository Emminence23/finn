// FINN app shell: pages and static files, so the app opens without a network. Data comes from
// the app's own saved copies (lib/api.ts); this worker never touches API requests.
const VERSION = "finn-shell-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(["/", "/icon.svg", "/manifest.webmanifest"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return; // API and others: untouched

  if (url.pathname.startsWith("/_next/static/")) {
    // content-hashed: cache first, forever
    e.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            const copy = res.clone();
            caches.open(VERSION).then((c) => c.put(req, copy));
            return res;
          }),
      ),
    );
    return;
  }

  // pages and RSC payloads: network first, saved copy when offline, Today as the last resort
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(req).then((hit) => hit || (req.mode === "navigate" ? caches.match("/") : Response.error())),
      ),
  );
});
