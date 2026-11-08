from django.contrib import admin

from .models import HistorialSolicitud, SolicitudReembolso


class HistorialInline(admin.TabularInline):
    model = HistorialSolicitud
    extra = 0


@admin.register(SolicitudReembolso)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ("pk", "reserva", "tipo", "estado", "fecha_solicitud")
    list_filter = ("estado", "tipo")
    inlines = [HistorialInline]
