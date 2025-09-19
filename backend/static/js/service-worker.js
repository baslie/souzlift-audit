const CACHE_PREFIX = "souzlift-audit";
const CACHE_VERSION = "v20240922";
const CACHE_NAME = `${CACHE_PREFIX}-${CACHE_VERSION}`;

const PRECACHE_URLS = [
  "/static/css/tailwind.min.css",
  "/static/js/offline-storage.js",
  "/static/js/auditor-portal.js",
  "/static/js/object-info-form.js",
  "/static/js/checklist-form.js",
  "/static/js/offline-checklist.js",
  "/static/js/alpine.min.js",
  "/static/js/htmx.min.js",
  "/audits/offline/object-info/",
  "/audits/offline/checklist/",
  "/audits/",
  "/accounts/dashboard/",
];

const PRECACHE_SET = new Set(PRECACHE_URLS);
const OFFLINE_FALLBACK = "/audits/offline/object-info/";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS.map((url) => new Request(url, { credentials: "same-origin" }))))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(handleNavigationRequest(request));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(request));
    return;
  }

  if (PRECACHE_SET.has(url.pathname)) {
    event.respondWith(cacheFirst(request, { ignoreSearch: true }));
    return;
  }

  event.respondWith(
    fetch(request).catch(() => caches.match(request, { ignoreSearch: true }))
  );
});

async function handleNavigationRequest(request) {
  try {
    const networkResponse = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, networkResponse.clone());
    return networkResponse;
  } catch (error) {
    const cached = await caches.match(request, { ignoreSearch: true });
    if (cached) {
      return cached;
    }
    const fallback = await caches.match(OFFLINE_FALLBACK, { ignoreSearch: true });
    if (fallback) {
      return fallback;
    }
    return new Response("", { status: 504, statusText: "Offline" });
  }
}

async function cacheFirst(request, options = {}) {
  const cached = await caches.match(request, options);
  if (cached) {
    return cached;
  }
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    if (cached) {
      return cached;
    }
    throw error;
  }
}
