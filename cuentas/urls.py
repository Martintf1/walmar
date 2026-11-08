from django.urls import path

from . import views

app_name = "cuentas"

urlpatterns = [
    path("registro/", views.registro, name="registro"),
    path("ingresar/", views.iniciar_sesion, name="login"),
    path("salir/", views.cerrar_sesion, name="logout"),
    path("recuperar/", views.recuperar, name="recuperar"),
    path("recuperar/codigo/", views.recuperar_confirmar, name="recuperar_confirmar"),
    path("perfil/", views.perfil, name="perfil"),
    path("personal/", views.personal_lista, name="personal_lista"),
    path("personal/nuevo/", views.personal_crear, name="personal_crear"),
    path("personal/<int:pk>/activar/", views.personal_activar, name="personal_activar"),
]
