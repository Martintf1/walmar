from django.urls import path

from . import views

app_name = "reembolsos"

urlpatterns = [
    path("", views.mis_solicitudes, name="mis_solicitudes"),
    path("reserva/<str:codigo>/", views.solicitar, name="solicitar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/soporte/", views.soporte, name="soporte"),
    path("gestion/", views.bandeja, name="bandeja"),
]
