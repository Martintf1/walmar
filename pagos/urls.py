from django.urls import path

from . import views

app_name = "pagos"

urlpatterns = [
    path("reservas/<str:codigo>/pagar-en-linea/", views.pagar_en_linea, name="pagar_en_linea"),
    path("pasarela-simulada/<str:referencia>/", views.pasarela_simulada, name="pasarela_simulada"),
    path("notificacion/", views.notificacion, name="notificacion"),
    path("estado/<str:referencia>/", views.estado, name="estado"),
    path("comprobantes/<str:referencia>/", views.comprobante, name="comprobante"),
    path("comprobantes/<str:referencia>/pdf/", views.comprobante_pdf, name="comprobante_pdf"),
    path("taquilla/", views.taquilla, name="taquilla"),
    path("taquilla/<str:codigo>/", views.efectivo, name="efectivo"),
]
