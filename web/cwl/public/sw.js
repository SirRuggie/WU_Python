/* Push only: deliberately no fetch handler or offline/private-data cache. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

function todoUrl(value) {
  try {
    const url = new URL(value || '/?view=todo', self.location.origin);
    if (url.origin === self.location.origin && url.pathname === '/' && url.searchParams.get('view') === 'todo') {
      return self.location.origin + '/?view=todo';
    }
  } catch (_) { /* Use the fixed safe destination. */ }
  return self.location.origin + '/?view=todo';
}

self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) { /* Empty/malformed push still gets a visible fallback. */ }
  if (!payload || typeof payload !== 'object') payload = {};
  const title = typeof payload.title === 'string' ? payload.title.slice(0, 120) : 'Warriors United reminder';
  const body = typeof payload.body === 'string' ? payload.body.slice(0, 1500) : 'Open Todo to check your remaining attacks.';
  const tag = typeof payload.tag === 'string' ? payload.tag.slice(0, 180) : 'wu-todo-reminder';
  event.waitUntil(self.registration.showNotification(title, {
    body, tag, icon: '/icons/wu-logo.png',
    data: { url: todoUrl(payload.url) },
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = todoUrl(event.notification.data && event.notification.data.url);
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
        // Navigate an existing dashboard tab to Todo, rather than leaving it on another page.
        try { await client.navigate(url); await client.focus(); return; } catch (_) { /* Try another window. */ }
      }
    }
    await self.clients.openWindow(url);
  })());
});
