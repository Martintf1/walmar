/* WALMAR – PWA: estado de conexión, almacenamiento local y sincronización.
 *
 * Solo se guarda en el dispositivo información no sensible (sección 3.5):
 * manifiestos reducidos (código, nombre y documento enmascarado), últimas
 * consultas de viajes, tiquetes del pasajero y operaciones pendientes.
 * Nunca contraseñas ni datos de tarjetas.
 */
(function () {
  "use strict";

  var CLAVES = {
    manifiestos: "walmar.manifiestos",
    cola: "walmar.cola",
    consultas: "walmar.consultas",
    tiquetes: "walmar.tiquetes",
    resultados: "walmar.resultadosSync",
  };

  // ---------------------------------------------------------- almacenamiento
  function leer(clave, defecto) {
    try {
      var v = localStorage.getItem(clave);
      return v ? JSON.parse(v) : defecto;
    } catch (e) {
      return defecto;
    }
  }
  function guardar(clave, valor) {
    try {
      localStorage.setItem(clave, JSON.stringify(valor));
      return true;
    } catch (e) {
      return false;
    }
  }
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "");
    return Date.now().toString(16) + Math.random().toString(16).slice(2);
  }
  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function postJSON(url, datos) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(datos),
    }).then(function (r) {
      return r.json().then(function (j) {
        return { status: r.status, json: j };
      });
    });
  }

  // ---------------------------------------------------------- cola de operaciones pendientes
  var Cola = {
    todas: function () { return leer(CLAVES.cola, []); },
    agregar: function (op) {
      var cola = this.todas();
      op.clave = op.clave || uuid();
      op.creada = op.creada || new Date().toISOString();
      cola.push(op);
      guardar(CLAVES.cola, cola);
      actualizarIndicador();
      return op;
    },
    quitar: function (claves) {
      guardar(CLAVES.cola, this.todas().filter(function (o) { return claves.indexOf(o.clave) === -1; }));
      actualizarIndicador();
    },
  };

  function actualizarIndicador() {
    var el = document.getElementById("pendientes-sync");
    if (!el) return;
    var n = Cola.todas().length;
    el.classList.toggle("visible", n > 0);
    el.textContent = n === 1
      ? "1 operación pendiente de sincronizar (no confirmada por el servidor)."
      : n + " operaciones pendientes de sincronizar (no confirmadas por el servidor).";
  }

  var sincronizando = false;
  function sincronizar() {
    if (sincronizando || !navigator.onLine) return Promise.resolve();
    var cola = Cola.todas();
    if (!cola.length) return Promise.resolve();
    sincronizando = true;
    var abordajes = cola.filter(function (o) { return o.tipo === "abordaje"; });
    var reservas = cola.filter(function (o) { return o.tipo === "reserva"; });
    var tareas = [];
    var resultados = leer(CLAVES.resultados, []);

    if (abordajes.length) {
      tareas.push(
        postJSON("/abordaje/api/sincronizar/", { operaciones: abordajes }).then(function (r) {
          if (r.status !== 200) return;
          var hechas = [];
          r.json.resultados.forEach(function (res) {
            if (res.resultado !== "ERROR") hechas.push(res.clave);
            resultados.unshift({ tipo: "abordaje", codigo: res.codigo, resultado: res.resultado, motivo: res.motivo, fecha: new Date().toISOString() });
          });
          Cola.quitar(hechas);
        })
      );
    }
    reservas.forEach(function (op) {
      tareas.push(
        postJSON("/api/reservas/sincronizar/", op).then(function (r) {
          if (r.status === 200 || r.status === 409 || r.status === 400) {
            Cola.quitar([op.clave]);
            resultados.unshift({
              tipo: "reserva",
              codigo: r.json.reserva || "",
              resultado: r.json.ok ? "ACEPTADO" : "RECHAZADO",
              motivo: r.json.ok ? "Reserva creada: " + r.json.reserva + " (pendiente de pago)" : r.json.error,
              fecha: new Date().toISOString(),
            });
          }
        })
      );
    });
    return Promise.all(tareas)
      .catch(function () {})
      .then(function () {
        guardar(CLAVES.resultados, resultados.slice(0, 50));
        sincronizando = false;
        document.dispatchEvent(new CustomEvent("walmar:sincronizado"));
      });
  }

  // ---------------------------------------------------------- conexión
  function estadoRed() {
    document.body.classList.toggle("offline", !navigator.onLine);
    if (navigator.onLine) sincronizar();
  }
  window.addEventListener("online", estadoRed);
  window.addEventListener("offline", estadoRed);

  // ---------------------------------------------------------- validación local (CU-10)
  function manifiestos() { return leer(CLAVES.manifiestos, {}); }

  function descargarManifiesto(viajeId) {
    return fetch("/abordaje/api/viajes/" + viajeId + "/manifiesto-reducido/", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("No autorizado"); return r.json(); })
      .then(function (m) {
        var todos = manifiestos();
        todos[viajeId] = m;
        guardar(CLAVES.manifiestos, todos);
        return m;
      });
  }

  function validarLocal(viajeId, codigo) {
    codigo = (codigo || "").trim().toUpperCase().replace(/\s+/g, "");
    var todos = manifiestos();
    var m = todos[viajeId];
    if (!m) return { resultado: "RECHAZADO", motivo: "No hay manifiesto guardado en este dispositivo para el viaje." };
    var t = null;
    for (var i = 0; i < m.tiquetes.length; i++) if (m.tiquetes[i].codigo === codigo) t = m.tiquetes[i];
    var op = { tipo: "abordaje", viaje: Number(viajeId), codigo: codigo, fecha: new Date().toISOString() };
    if (!t) {
      Cola.agregar(op); // se registra el intento rechazado
      return { resultado: "RECHAZADO", motivo: "El código no está en el manifiesto local." };
    }
    if (t.estado !== "VALIDO") {
      Cola.agregar(op);
      return { resultado: "RECHAZADO", motivo: "Tiquete ya utilizado (registro local).", pasajero: t.nombre };
    }
    t.estado = "UTILIZADO";
    guardar(CLAVES.manifiestos, todos);
    Cola.agregar(op);
    return { resultado: "PENDIENTE", motivo: "Abordaje registrado sin conexión. Pendiente de sincronización.", pasajero: t.nombre, documento: t.documento };
  }

  // ---------------------------------------------------------- lector QR
  function iniciarLector(contenedor, alLeer) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert("Este dispositivo no permite usar la cámara. Ingrese el código manualmente.");
      return null;
    }
    var detector = "BarcodeDetector" in window ? new window.BarcodeDetector({ formats: ["qr_code"] }) : null;
    var video = document.createElement("video");
    video.setAttribute("playsinline", "");
    video.muted = true;
    contenedor.innerHTML = "";
    contenedor.appendChild(video);
    contenedor.style.display = "block";
    var canvas = document.createElement("canvas");
    var ctx = canvas.getContext("2d", { willReadFrequently: true });
    var activo = true;
    var stream = null;

    function detener() {
      activo = false;
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      contenedor.style.display = "none";
    }
    function ciclo() {
      if (!activo) return;
      if (video.readyState >= 2) {
        if (detector) {
          detector.detect(video).then(function (cods) {
            if (cods.length && activo) { detener(); alLeer(cods[0].rawValue); }
          }).catch(function () {});
        } else if (window.jsQR) {
          canvas.width = video.videoWidth; canvas.height = video.videoHeight;
          ctx.drawImage(video, 0, 0);
          var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
          var r = window.jsQR(img.data, img.width, img.height);
          if (r && r.data) { detener(); alLeer(r.data); return; }
        }
      }
      setTimeout(ciclo, 250);
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function (s) {
      stream = s;
      video.srcObject = s;
      video.play();
      if (!detector && !window.jsQR) {
        var sc = document.createElement("script");
        sc.src = "https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js";
        document.head.appendChild(sc);
      }
      ciclo();
    }).catch(function () {
      detener();
      alert("No se pudo acceder a la cámara. Ingrese el código manualmente.");
    });
    return { detener: detener };
  }

  // ---------------------------------------------------------- consultas y tiquetes guardados
  function guardarConsulta(params, datos) {
    var c = leer(CLAVES.consultas, []);
    c = c.filter(function (x) { return x.params !== params; });
    c.unshift({ params: params, datos: datos });
    guardar(CLAVES.consultas, c.slice(0, 5));
  }

  function refrescarTiquetes() {
    if (!navigator.onLine || !document.body.dataset.autenticado) return;
    fetch("/api/mis-tiquetes/", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) guardar(CLAVES.tiquetes, j); })
      .catch(function () {});
  }

  function limpiarDatosLocales() {
    [CLAVES.manifiestos, CLAVES.consultas, CLAVES.tiquetes, CLAVES.resultados].forEach(function (k) {
      try { localStorage.removeItem(k); } catch (e) {}
    });
    if (window.caches) caches.keys().then(function (ks) { ks.forEach(function (k) { if (k.indexOf("walmar-paginas") === 0) caches.delete(k); }); });
  }

  // ---------------------------------------------------------- inicio
  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("menu-btn");
    var nav = document.getElementById("nav");
    if (btn && nav) btn.addEventListener("click", function () {
      var abierto = nav.classList.toggle("abierto");
      btn.setAttribute("aria-expanded", abierto ? "true" : "false");
    });

    document.querySelectorAll("form[data-salir]").forEach(function (f) {
      f.addEventListener("submit", function (e) {
        if (Cola.todas().length && !confirm("Hay operaciones sin sincronizar en este dispositivo. ¿Cerrar sesión de todos modos? Se conservarán para sincronizarlas luego.")) {
          e.preventDefault();
          return;
        }
        limpiarDatosLocales();
      });
    });

    // Confirmaciones genéricas
    document.querySelectorAll("[data-confirmar]").forEach(function (el) {
      el.addEventListener("submit", function (e) { if (!confirm(el.dataset.confirmar)) e.preventDefault(); });
    });

    estadoRed();
    actualizarIndicador();
    refrescarTiquetes();
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }

  window.WALMAR = {
    leer: leer,
    guardar: guardar,
    uuid: uuid,
    claves: CLAVES,
    cola: Cola,
    sincronizar: sincronizar,
    descargarManifiesto: descargarManifiesto,
    manifiestos: manifiestos,
    validarLocal: validarLocal,
    iniciarLector: iniciarLector,
    guardarConsulta: guardarConsulta,
    postJSON: postJSON,
  };
})();
