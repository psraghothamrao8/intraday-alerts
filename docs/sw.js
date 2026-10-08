self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let p;
  try {
    p = event.data.json();
  } catch {
    p = { title: 'Alert', body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(self.registration.showNotification(p.title, {
    body: p.body,
    tag: p.tag,
    renotify: true,
    requireInteraction: !!p.sticky,
    icon: 'icons/icon-192.png',
    badge: 'icons/badge-72.png',
    vibrate: [200, 100, 200, 100, 400],
    data: { url: p.url || './' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.registration.scope).href;
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    for (const c of list) {
      if (c.url.startsWith(self.registration.scope)) {
        c.navigate(url);
        return c.focus();
      }
    }
    return clients.openWindow(url);
  }));
});
