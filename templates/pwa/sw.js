/* Service worker de WALMAR ({{ version }}).
 * - Recursos estáticos: cache-first.
 * - Páginas y consultas GET: red primero, copia local como respaldo.
 * - POST (compras, pagos, abordajes) nunca se cachean: requieren al servidor.
 */
const ESTATICOS = "walmar-estaticos-{{ version }}";
const PAGINAS = "walmar-paginas-{{ version }}";
const PRECACHE = ["/", "/sin-conexion/", "/static/css/app.css", "/static/js/app.js", "/manifest.webmanifest", "/static/img/icono.svg"];
const NO_CACHEAR = ["/pagos/", "/cuentas/", "/django-admin/", "/sw.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(ESTATICOS).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => ![ESTATICOS, PAGINAS].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) {
    // Librería de lectura QR (CDN): cache-first.
    if (url.hostname === "cdn.jsdelivr.net") {
      e.respondWith(caches.match(req).then((r) => r || fetch(req).then((resp) => {
        const copia = resp.clone(); caches.open(ESTATICOS).then((c) => c.put(req, copia)); return resp;
      })));
    }
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(req).then((r) => r || fetch(req).then((resp) => {
      const copia = resp.clone(); caches.open(ESTATICOS).then((c) => c.put(req, copia)); return resp;
    })));
    return;
  }
  if (NO_CACHEAR.some((p) => url.pathname.startsWith(p)) || url.pathname.endsWith(".pdf") || url.pathname.endsWith("/pdf/")) return;

  e.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok && resp.type === "basic") {
          const copia = resp.clone();
          caches.open(PAGINAS).then((c) => c.put(req, copia));
        }
        return resp;
      })
      .catch(() =>
        caches.match(req).then((r) => {
          if (r) return r;
          if (req.mode === "navigate") return caches.match("/sin-conexion/");
          return new Response(JSON.stringify({ error: "Sin conexión" }), { status: 503, headers: { "Content-Type": "application/json" } });
        })
      )
  );
});
