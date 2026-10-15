// Service worker: makes the app work offline and receives shared files.
// Only the app's own files are cached; files to print are never stored.
// Bump VERSION whenever the files below change.
const VERSION = "v2";
const SHELL_CACHE = `catprinter-shell-${VERSION}`;
const RUNTIME_CACHE = "catprinter-runtime";
const LEGACY_CACHES = ["catprinter-shared"];

const SHELL_FILES = [
  "./",
  "./index.html",
  "./css/app.css",
  "./js/app.js",
  "./js/imaging.js",
  "./js/printer.js",
  "./js/protocol.js",
  "./manifest.webmanifest",
  "./icons/icon.svg",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-maskable-512.png",
];
const SHELL_PATHS = new Set(SHELL_FILES.map((file) => new URL(file, self.location).pathname));

// Files received from the share sheet, kept in memory until the page asks for them.
let sharedFiles = [];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      const old = key.startsWith("catprinter-shell-") && key !== SHELL_CACHE;
      if (old || LEGACY_CACHES.includes(key)) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method === "POST" && url.pathname.endsWith("/compartir")) {
    event.respondWith(receiveShare(event.request));
  } else if (event.request.method === "GET" && url.origin === location.origin
             && SHELL_PATHS.has(url.pathname)) {
    event.respondWith(staleWhileRevalidate(event.request));
  } else if (event.request.method === "GET" && url.hostname === "cdnjs.cloudflare.com") {
    // Versioned library URLs (pdf.js) never change: cache them for offline use.
    event.respondWith(cacheFirst(event.request));
  }
});

// Answers from the cache right away and refreshes it for the next visit.
async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request, { ignoreSearch: true });
  const network = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  });
  if (cached) {
    network.catch(() => {});
    return cached;
  }
  return network;
}

async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

// Share target: keeps the shared files in memory and opens the page, which
// asks for them with a "shared-files" message.
async function receiveShare(request) {
  const form = await request.formData();
  sharedFiles = form.getAll("archivos").filter((f) => f instanceof File);
  return Response.redirect("./?compartido", 303);
}

self.addEventListener("message", (event) => {
  if (event.data !== "shared-files") return;
  event.source.postMessage({ type: "shared-files", files: sharedFiles });
  sharedFiles = [];
});
