from django.urls import path

from . import views

app_name = "abordaje"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("sin-conexion/", views.sin_conexion, name="sin_conexion"),
    path("viajes/<int:viaje_id>/validar/", views.validar, name="validar"),
    path("viajes/<int:viaje_id>/manifiesto/", views.manifiesto, name="manifiesto"),
    path("api/viajes/<int:viaje_id>/validar/", views.api_validar, name="api_validar"),
    path("api/viajes/<int:viaje_id>/manifiesto-reducido/", views.manifiesto_reducido, name="manifiesto_reducido"),
    path("api/sincronizar/", views.api_sincronizar, name="api_sincronizar"),
]
