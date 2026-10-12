// Web push (R8d), loaded into the generated service worker: show an alert,
// and open its page when it's tapped.
self.addEventListener("push", event => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch { d = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(d.title || "Cinema Club DC", {
    body: d.body || "", tag: d.tag, icon: "/pwa-192.png", badge: "/pwa-192.png", data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(windows => {
    const open = windows.find(w => w.url.startsWith(self.location.origin));
    if (open) return open.navigate(url).then(w => (w || open).focus()).catch(() => self.clients.openWindow(url));
    return self.clients.openWindow(url);
  }));
});
