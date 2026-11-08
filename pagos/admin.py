from django.contrib import admin

from .models import Pago


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("referencia", "reserva", "medio", "valor", "estado", "registrado_por", "creado_en")
    list_filter = ("medio", "estado")
    search_fields = ("referencia", "reserva__codigo", "referencia_externa")
