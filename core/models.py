from django.conf import settings
from django.db import models


class RegistroAuditoria(models.Model):
    """Trazabilidad de operaciones importantes (RNF-09)."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    accion = models.CharField(max_length=60, db_index=True)
    objeto = models.CharField(max_length=120, blank=True)
    resultado = models.CharField(max_length=20, default="OK")
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} {self.accion} {self.objeto} [{self.resultado}]"
