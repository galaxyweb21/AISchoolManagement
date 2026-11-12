'use strict';
const CACHE_NAME = 'eduai-static-v2';
self.addEventListener('install', function () {
  // Keep a waiting worker available so the user can choose when to refresh.
});
self.addEventListener('message', function (event) {
  if (event.data && event.data.type === 'EDUAI_SKIP_WAITING') self.skipWaiting();
});
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) {
        return key.startsWith('eduai-static-') && key !== CACHE_NAME;
      }).map(function (key) { return caches.delete(key); }));
    }).then(function () { return self.clients.claim(); })
  );
});
// Cache only same-origin static assets. Never cache HTML, API responses, or school records.
self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/static/')) return;
  event.respondWith(
    caches.match(request).then(function (cached) {
      if (cached) return cached;
      return fetch(request).then(function (response) {
        if (response && response.ok && response.type === 'basic') {
          var copy = response.clone();
          caches.open(CACHE_NAME).then(function (cache) { cache.put(request, copy); });
        }
        return response;
      });
    })
  );
});
