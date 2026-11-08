from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache

from operacion.models import PuntoEmbarque


def inicio(request):
    puntos = PuntoEmbarque.objects.filter(activo=True).select_related("ruta")
    return render(request, "core/inicio.html", {"puntos": puntos})


def terminos(request):
    return render(request, "core/terminos.html")


def politica_datos(request):
    return render(request, "core/politica_datos.html")


def politica_cancelacion(request):
    return render(request, "core/politica_cancelacion.html")


def offline(request):
    return render(request, "core/offline.html")


def manifest(request):
    return HttpResponse(render_to_string("pwa/manifest.json", request=request), content_type="application/manifest+json")


@never_cache
def service_worker(request):
    contenido = render_to_string("pwa/sw.js", {"version": settings.WALMAR.get("VERSION_SW", "v1")})
    resp = HttpResponse(contenido, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    return resp


def error_403(request, exception=None):
    return render(request, "core/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "core/404.html", status=404)
