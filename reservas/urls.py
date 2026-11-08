from django.urls import path

from . import views

app_name = "reservas"

urlpatterns = [
    path("viajes/", views.buscar, name="buscar"),
    path("viajes/<int:viaje_id>/reservar/", views.reservar, name="reservar"),
    path("mis-reservas/", views.mis_reservas, name="mis_reservas"),
    path("reservas/<str:codigo>/", views.detalle, name="detalle"),
    path("reservas/<str:codigo>/cancelar/", views.cancelar, name="cancelar"),
    path("reservas/<str:codigo>/cambio/", views.responder_cambio, name="responder_cambio"),
    path("reservas/<str:codigo>/tiquetes.pdf", views.tiquetes_reserva_pdf, name="tiquetes_pdf"),
    path("tiquetes/<str:codigo>/", views.tiquete, name="tiquete"),
    path("tiquetes/<str:codigo>/pdf/", views.tiquete_pdf, name="tiquete_pdf"),
    path("api/viajes/", views.api_viajes, name="api_viajes"),
    path("api/mis-tiquetes/", views.api_mis_tiquetes, name="api_mis_tiquetes"),
    path("api/reservas/sincronizar/", views.api_sincronizar_reserva, name="api_sincronizar_reserva"),
]
