from django.contrib import admin

from .models import Pasajero, Reserva, Tiquete


class PasajeroInline(admin.TabularInline):
    model = Pasajero
    extra = 0


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "usuario", "viaje", "cantidad", "total", "estado", "canal", "creada_en")
    list_filter = ("estado", "canal")
    search_fields = ("codigo", "usuario__email")
    inlines = [PasajeroInline]


@admin.register(Tiquete)
class TiqueteAdmin(admin.ModelAdmin):
    list_display = ("codigo", "pasajero", "estado", "emitido_en", "utilizado_en")
    list_filter = ("estado",)
    search_fields = ("codigo", "pasajero__nombre")
