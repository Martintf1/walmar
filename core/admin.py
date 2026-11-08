from django.contrib import admin

from .models import RegistroAuditoria


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "usuario", "accion", "objeto", "resultado")
    list_filter = ("accion", "resultado")
    search_fields = ("objeto", "usuario__email")
    readonly_fields = [f.name for f in RegistroAuditoria._meta.fields]
