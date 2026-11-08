from django.contrib import admin

from .models import AsignacionGrupo, CambioViaje, GrupoPropietarios, HorarioBase, Lancha, PuntoEmbarque, Ruta, Viaje

admin.site.register([Ruta, PuntoEmbarque, GrupoPropietarios, Lancha, AsignacionGrupo, HorarioBase])


class CambioInline(admin.TabularInline):
    model = CambioViaje
    extra = 0
    readonly_fields = ("tipo", "motivo", "datos_anteriores", "datos_nuevos", "usuario", "fecha")


@admin.register(Viaje)
class ViajeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "lancha", "cupos", "cupos_ocupados", "habilitado", "estado")
    list_filter = ("estado", "habilitado", "sentido", "fecha")
    inlines = [CambioInline]
