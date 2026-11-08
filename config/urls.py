from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

admin.site.site_header = "WALMAR – administración técnica"
admin.site.site_title = "WALMAR"

urlpatterns = [
    path("", include("core.urls")),
    path("cuentas/", include("cuentas.urls")),
    path("", include("reservas.urls")),
    path("pagos/", include("pagos.urls")),
    path("abordaje/", include("abordaje.urls")),
    path("operacion/", include("operacion.urls")),
    path("solicitudes/", include("reembolsos.urls")),
    path("reportes/", include("reportes.urls")),
    path("manifest.webmanifest", core_views.manifest, name="manifest"),
    path("sw.js", core_views.service_worker, name="service_worker"),
    path("django-admin/", admin.site.urls),
]

handler403 = "core.views.error_403"
handler404 = "core.views.error_404"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
