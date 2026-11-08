from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "nombre", "rol", "is_active", "date_joined")
    list_filter = ("rol", "is_active")
    search_fields = ("email", "nombre", "identificacion")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Datos personales", {"fields": ("nombre", "tipo_documento", "identificacion", "telefono", "acepto_terminos_en")}),
        ("Rol y permisos", {"fields": ("rol", "is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "nombre", "rol", "password1", "password2")}),)
