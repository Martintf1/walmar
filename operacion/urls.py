from django.urls import path

from . import views

app_name = "operacion"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("viajes/", views.viajes_lista, name="viajes"),
    path("viajes/nuevo/", views.viaje_form, name="viaje_nuevo"),
    path("viajes/<int:pk>/", views.viaje_detalle, name="viaje_detalle"),
    path("viajes/<int:pk>/editar/", views.viaje_form, name="viaje_editar"),
    path("viajes/<int:pk>/habilitar/", views.viaje_habilitar, name="viaje_habilitar"),
    path("viajes/<int:pk>/hora-efectiva/", views.viaje_hora_efectiva, name="viaje_hora_efectiva"),
    path("viajes/<int:pk>/reprogramar/", views.viaje_reprogramar, name="viaje_reprogramar"),
    path("viajes/<int:pk>/cancelar/", views.viaje_cancelar, name="viaje_cancelar"),
    path("programacion/", views.programacion, name="programacion"),
    path("programacion/asignar/", views.asignar_grupo, name="asignar_grupo"),
    path("programacion/generar/", views.generar, name="generar"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("configuracion/<str:tipo>/", views.config_lista, name="config_lista"),
    path("configuracion/<str:tipo>/nuevo/", views.config_form, name="config_nuevo"),
    path("configuracion/<str:tipo>/<int:pk>/", views.config_form, name="config_editar"),
]
