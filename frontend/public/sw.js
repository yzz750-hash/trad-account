// Self-unregistering service worker.
// Purpose: clear out stale service-worker registrations left over from
// earlier PWA experiments. When the browser fetches /sw.js it gets this
// file, installs it, and the new SW immediately unregisters itself and
// claims control so the next navigation has no SW intercepting fetches.
// Without this, stale SWs return the offline page ("Offline / Please
// check your connection") when the dev server is briefly unavailable.

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const registrations = await self.clients.matchAll({ includeUncontrolled: true });
      for (const client of registrations) {
        client.postMessage({ type: 'SW_UNREGISTERED' });
      }
      await self.registration.unregister();
      console.log('[sw.js] Service worker unregistered successfully.');
    })()
  );
});

// Pass-through fetch handler: never intercept network requests.
self.addEventListener('fetch', () => {});
