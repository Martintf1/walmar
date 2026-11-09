"""Configuración de WALMAR.

Los valores sensibles y dependientes del despliegue se leen de variables de
entorno (ver README.md). Los parámetros operativos marcados como
"pendiente de validación" provienen del Apéndice C de la ERS.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def cargar_env(ruta):
    """Carga variables desde un archivo .env (CLAVE=valor) sin pisar las ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        os.environ.setdefault(clave.strip(), valor)


cargar_env(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "si", "sí")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-inseguro-cambiar-en-produccion")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "cuentas",
    "operacion",
    "reservas",
    "pagos",
    "abordaje",
    "reembolsos",
    "reportes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.walmar",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Base de datos: SQLite por defecto; PostgreSQL si se definen las variables.
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }

AUTH_USER_MODEL = "cuentas.Usuario"
AUTHENTICATION_BACKENDS = ["cuentas.backends.EmailBackend"]
LOGIN_URL = "cuentas:login"
LOGIN_REDIRECT_URL = "core:inicio"
LOGOUT_REDIRECT_URL = "core:inicio"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Correo (SMTP). Si se define EMAIL_HOST_USER se envía por SMTP real
# (ver .env.example); si no, los correos se imprimen en la consola.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "").replace(" ", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", EMAIL_PORT != 465)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "15"))
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST_USER else "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    f"WALMAR <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "WALMAR <no-responder@walmar.local>",
)

# Los errores de envío de correo se registran en la consola del servidor.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"consola": {"class": "logging.StreamHandler"}},
    "loggers": {"core.notificaciones": {"handlers": ["consola"], "level": "INFO"}},
}

# Seguridad (RNF-03): HTTPS forzado fuera de desarrollo.
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

# --- Parámetros operativos de WALMAR (pendientes de validación, Apéndice C) ---
WALMAR = {
    # Tiempo de bloqueo temporal de cupos de una reserva sin pagar.
    "RESERVA_PLAZO_MINUTOS": int(os.environ.get("WALMAR_RESERVA_PLAZO_MINUTOS", "30")),
    # Máximo de pasajes por reserva.
    "MAX_PASAJES_POR_RESERVA": int(os.environ.get("WALMAR_MAX_PASAJES", "10")),
    # Código de recuperación de contraseña.
    "CODIGO_RECUPERACION_MINUTOS": 15,
    "CODIGO_RECUPERACION_INTENTOS": 5,
    # Pasarela de pagos: "simulada" mientras se define el proveedor real.
    "PASARELA": os.environ.get("WALMAR_PASARELA", "simulada"),
    "PASARELA_SECRETO": os.environ.get("WALMAR_PASARELA_SECRETO", SECRET_KEY),
    # Si un pago en línea es rechazado: "retener" (la reserva sigue pendiente
    # hasta su plazo) o "liberar" (se cancela y se liberan los cupos).
    "PAGO_RECHAZADO_ACCION": os.environ.get("WALMAR_PAGO_RECHAZADO_ACCION", "retener"),
}
