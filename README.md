# WALMAR

Sistema web (PWA) de consulta, reserva y compra de pasajes en lancha en la ruta **Buenaventura – Timbiquí**, construido según la ERS `WALMAR-IEEE830.docx` y la descripción de casos de uso `descripcion.docx`.

- **Backend:** Python 3.11+ con Django 5.2
- **Frontend:** plantillas Django, CSS y JavaScript propios (sin framework), con diseño responsive para celular y computador
- **PWA:** service worker, `manifest.webmanifest`, almacenamiento local y sincronización sin duplicados
- **Base de datos:** SQLite en desarrollo; PostgreSQL configurable por variables de entorno
- **PDF y QR:** ReportLab

## Puesta en marcha

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py cargar_datos_iniciales --demo
python manage.py runserver
```

Abra <http://127.0.0.1:8000>. Con `--demo` se crean estos usuarios (contraseña `Walmar2026*`):

| Rol | Correo |
|---|---|
| Administrador | admin@walmar.local |
| Operador / empresa transportadora | operador@walmar.local |
| Personal de atención y venta | ventas@walmar.local |
| Personal de abordaje | abordaje@walmar.local |
| Pasajero | pasajero@walmar.local |

Las cuentas, los códigos de recuperación y el resto de datos se guardan en la base de datos `db.sqlite3`, que se crea con `migrate`.

### Envío real de correos (código de recuperación)

Sin configuración, los correos (cuenta creada, código de recuperación, notificaciones) se imprimen en la consola. Para enviarlos a la bandeja de entrada:

1. Copie `.env.example` como `.env`.
2. Complete `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD`. Con Gmail, use una **contraseña de aplicación** (<https://myaccount.google.com/apppasswords>, requiere la verificación en dos pasos), no su contraseña normal.
3. Verifique la configuración con `python manage.py probar_correo destino@ejemplo.com`.

El código de recuperación tiene 6 dígitos, vence en 15 minutos, admite 5 intentos y solo se guarda su hash (SHA-256) en la base de datos.

### Abrir la app desde otros dispositivos

- **Misma red Wi-Fi:** agregue la IP del computador a `DJANGO_ALLOWED_HOSTS` en `.env` y ejecute `python manage.py runserver 0.0.0.0:8000`. Luego abra `http://<IP>:8000` desde el otro dispositivo (permita Python en el Firewall de Windows).
- **Cualquier red (enlace público temporal):** con [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) instalado y el servidor corriendo, ejecute `cloudflared tunnel --url http://127.0.0.1:8000`. Muestra un enlace `https://….trycloudflare.com` que cambia en cada ejecución.

Antes de exponer la app a internet, cambie las contraseñas de los usuarios demo: la contraseña por defecto aparece en este README.

Pruebas automáticas:

```bash
python manage.py test
```

Tarea periódica (cada minuto, con cron o el programador de tareas): libera las reservas vencidas y finaliza los viajes pasados.

```bash
python manage.py liberar_reservas_vencidas
```

## Módulos (RNF-10)

| App | Responsabilidad | Requisitos |
|---|---|---|
| `core` | Permisos por rol, auditoría, correos, PWA, páginas legales | RNF-03, RNF-09, RF-PWA-01 |
| `cuentas` | Registro, inicio de sesión, recuperación por código, usuarios del personal | RF-COM-01, RF-COM-02, RF-IN-03 |
| `operacion` | Ruta, puntos, grupos, lanchas, horarios, viajes, turnos, marea, reprogramación y cancelación | RF-IN-01, RF-IN-02, RF-ADM-01…04 |
| `reservas` | Búsqueda, reserva con bloqueo de cupos, tiquetes con QR y PDF | RF-PAS-01, RF-PAS-02, RF-TIQ-01 |
| `pagos` | Pago en línea (pasarela + webhook firmado), pago en efectivo, comprobantes | RF-PAG-01, RF-PAG-02 |
| `abordaje` | Validación de tiquetes, manifiesto, manifiesto reducido, sincronización offline | RF-ABO-01, RF-IN-04, RF-PWA-01 |
| `reembolsos` | Solicitudes de desistimiento, cancelación y devolución con seguimiento | RF-DEV-01 |
| `reportes` | Ventas, pagos y abordajes por periodo; registro de auditoría | RF-REP-01, RNF-09 |

## Decisiones de diseño

- **Sin sobreventa (RNF-07):** los cupos se ocupan con un `UPDATE` condicional atómico (`cupos_ocupados + n <= cupos`), respaldado por una restricción `CHECK` en la base de datos. Hay una prueba con solicitudes simultáneas sobre el último cupo.
- **El servidor es la autoridad:** una reserva o abordaje hecho sin conexión queda como *pendiente de sincronización* y solo se confirma cuando el servidor lo valida. Cada operación lleva una **clave de idempotencia**, así que los reintentos no duplican registros (RNF-08).
- **Datos locales mínimos:** el manifiesto reducido solo guarda código, nombre y documento enmascarado. Nunca se guardan contraseñas ni datos de tarjeta en el dispositivo.
- **Hora efectiva por marea:** se guarda aparte de la hora programada. Consultas y tiquetes muestran siempre la hora vigente.
- **Reembolsos:** no se aplican porcentajes por defecto (sección 2.4 de la ERS). El personal autorizado registra el valor según la causa, el aviso y la norma (Código de Comercio, arts. 1002 y 1588–1594).
- **Registro:** se sigue la ERS IEEE 830 (v1.0): acceso inmediato y correo informativo; el código por correo se usa solo para recuperar la contraseña. El documento `descripcion.docx` describía una activación previa por correo, que la ERS reemplazó.

## Pendientes de validación (Apéndice C de la ERS)

Estos valores están parametrizados y deben confirmarse con el operador y la autoridad marítima:

- **Datos operativos iniciales:** el comando `cargar_datos_iniciales` crea 3 grupos con 2 lanchas cada uno, con capacidad de 40, matrícula `PENDIENTE-*` y salida diaria a las 07:00 en cada sentido. La duración es de 4 h y la tarifa de $160.000. Se ajustan en *Configuración*.
- **Plazo de bloqueo de la reserva:** `WALMAR_RESERVA_PLAZO_MINUTOS`, 30 min por defecto.
- **Pasarela de pagos:** `pagos/pasarela.py` trae una pasarela **simulada** con la misma interfaz que una real (redirección y notificación firmada con HMAC). Para integrar Wompi, PayU, ePayco u otra, se implementa `iniciar_pago` y se mapea su webhook a `pagos:notificacion`.
- **Comportamiento ante un pago rechazado:** `WALMAR_PAGO_RECHAZADO_ACCION` (`retener` o `liberar`).
- **Textos legales:** términos, tratamiento de datos y política de cancelación son borradores marcados para revisión legal.
- **Información del manifiesto:** debe confirmarse con la DIMAR qué información exige.

## Variables de entorno (producción)

`DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `POSTGRES_DB/USER/PASSWORD/HOST/PORT`, `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `WALMAR_PASARELA_SECRETO`.

Con `DJANGO_DEBUG=0` se activan la redirección a HTTPS, las cookies seguras y HSTS (RNF-03). Los archivos estáticos se sirven con WhiteNoise (`python manage.py collectstatic`).

> WALMAR es un apoyo tecnológico: no reemplaza permisos, habilitaciones ni el zarpe expedidos por la DIMAR y la Capitanía de Puerto.
