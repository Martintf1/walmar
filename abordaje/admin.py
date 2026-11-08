from django.contrib import admin

from .models import RegistroAbordaje


@admin.register(RegistroAbordaje)
class RegistroAbordajeAdmin(admin.ModelAdmin):
    list_display = ("fecha", "codigo_leido", "viaje", "usuario", "resultado", "sin_conexion")
    list_filter = ("resultado", "sin_conexion")
    search_fields = ("codigo_leido",)
