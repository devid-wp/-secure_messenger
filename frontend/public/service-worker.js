const CACHE_NAME = 'secure-messenger-shell-v3'
const APP_SHELL = ['/', '/manifest.webmanifest', '/icon.png']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  )
})

// The Service Worker MUST NOT persist encrypted attachment bodies. The
// transport guarantees are:
//   * only `application/octet-stream` ciphertext ever leaves the server,
//   * the file key, nonce, original name and MIME live only inside the
//     MLS application payload, which is fetched and decoded by the MLS
//     worker directly (it never goes through this fetch handler).
// We still defend in depth: any request whose path matches the media
// router is excluded from the cache so a misconfigured route or future
// route never lands plaintext on disk.
function isMediaApiPath(pathname) {
  return pathname.startsWith('/api/v1/media/')
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return
  const url = new URL(event.request.url)
  if (url.origin !== self.location.origin) return
  // Block all `/api/` traffic — encrypted media, decrypted media (there
  // is none) and any future API routes — from being intercepted by the
  // cache. The MLS worker fetches ciphertext directly via `fetch()` and
  // never asks the Service Worker to manage it; this guard is purely
  // defence-in-depth in case a future code path calls `fetch()` with the
  // default cache mode from the page context.
  if (url.pathname.startsWith('/api/')) return
  if (isMediaApiPath(url.pathname)) return
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match('/')))
    return
  }
  event.respondWith(caches.open(CACHE_NAME).then(async (cache) => {
    const cached = await cache.match(event.request)
    const network = fetch(event.request).then((response) => {
      if (response.ok) cache.put(event.request, response.clone())
      return response
    })
    return cached || network
  }))
})
