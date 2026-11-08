from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("terminos/", views.terminos, name="terminos"),
    path("politica-datos/", views.politica_datos, name="politica_datos"),
    path("politica-cancelacion/", views.politica_cancelacion, name="politica_cancelacion"),
    path("sin-conexion/", views.offline, name="offline"),
]
