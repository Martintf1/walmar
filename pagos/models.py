from django.conf import settings
from django.db import models

from core import codigos
from reservas.models import Reserva


def _referencia():
    return codigos.generar("P", 12)


class Pago(models.Model):
    class Medio(models.TextChoices):
        EN_LINEA = "EN_LINEA", "En línea (pasarela)"
        EFECTIVO = "EFECTIVO", "Efectivo (punto de atención)"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        REEMBOLSADO = "REEMBOLSADO", "Reembolsado"

    reserva = models.ForeignKey(Reserva, on_delete=models.PROTECT, related_name="pagos")
    referencia = models.CharField(max_length=20, unique=True, default=_referencia, editable=False)
    medio = models.CharField(max_length=8, choices=Medio.choices)
    valor = models.DecimalField(max_digits=12, decimal_places=0)
    valor_recibido = models.DecimalField("valor recibido", max_digits=12, decimal_places=0, null=True, blank=True)
    estado = models.CharField(max_length=11, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    referencia_externa = models.CharField("referencia de la pasarela", max_length=80, blank=True, db_index=True)
    detalle_pasarela = models.JSONField(default=dict, blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="pagos_registrados"
    )
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    confirmado_en = models.DateTimeField(null=True, blank=True)
    observacion = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-creado_en"]
        verbose_name = "pago"

    def __str__(self):
        return f"{self.referencia} {self.get_medio_display()} {self.get_estado_display()}"

    @property
    def cambio(self):
        if self.valor_recibido is None:
            return None
        return self.valor_recibido - self.valor
