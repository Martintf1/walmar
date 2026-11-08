from django.conf import settings
from django.db import models

from operacion.models import Viaje
from reservas.models import Tiquete


class RegistroAbordaje(models.Model):
    """Intento de validación de un tiquete en el muelle (aceptado o rechazado)."""

    class Resultado(models.TextChoices):
        ACEPTADO = "ACEPTADO", "Aceptado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    viaje = models.ForeignKey(Viaje, on_delete=models.PROTECT, related_name="abordajes")
    tiquete = models.ForeignKey(Tiquete, null=True, blank=True, on_delete=models.PROTECT, related_name="abordajes")
    codigo_leido = models.CharField(max_length=40)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="abordajes")
    resultado = models.CharField(max_length=9, choices=Resultado.choices)
    motivo = models.CharField(max_length=200, blank=True)
    fecha = models.DateTimeField("fecha y hora de la validación", db_index=True)
    recibido_en = models.DateTimeField("recibido por el servidor", auto_now_add=True)
    sin_conexion = models.BooleanField(default=False)
    clave_idempotencia = models.CharField(max_length=64, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "registro de abordaje"
        verbose_name_plural = "registros de abordaje"

    def __str__(self):
        return f"{self.codigo_leido} {self.resultado} {self.fecha:%Y-%m-%d %H:%M}"
