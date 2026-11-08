from django.conf import settings
from django.db import models

from reservas.models import Reserva


class SolicitudReembolso(models.Model):
    """Solicitud de desistimiento, cancelación o devolución (RF-DEV-01, CU-14, Apéndice D.2)."""

    class Tipo(models.TextChoices):
        DESISTIMIENTO = "DESISTIMIENTO", "Desistimiento del pasajero con aviso previo (C. Co. art. 1002)"
        FUERZA_MAYOR = "FUERZA_MAYOR", "Impedimento del pasajero por fuerza mayor (art. 1588)"
        CANCELACION_TRANSPORTADOR = "CANCELACION", "Cancelación del zarpe por el transportador (art. 1590)"
        CAMBIO_HORARIO = "CAMBIO_HORARIO", "No acepto la reprogramación del viaje"
        CAMBIO_NAVE = "CAMBIO_NAVE", "Sustitución de la lancha (art. 1591)"
        RETRASO = "RETRASO", "Retraso en el zarpe (art. 1593)"
        INTERRUPCION = "INTERRUPCION", "Interrupción del viaje (art. 1594)"
        OTRO = "OTRO", "Otro motivo"

    class Estado(models.TextChoices):
        RECIBIDA = "RECIBIDA", "Recibida"
        EN_REVISION = "EN_REVISION", "En revisión"
        APROBADA = "APROBADA", "Aprobada"
        EN_PROCESO = "EN_PROCESO", "En proceso de devolución"
        REEMBOLSADA = "REEMBOLSADA", "Reembolsada"
        NO_APROBADA = "NO_APROBADA", "No aprobada"

    ESTADOS_ABIERTOS = [Estado.RECIBIDA, Estado.EN_REVISION, Estado.APROBADA, Estado.EN_PROCESO]

    reserva = models.ForeignKey(Reserva, on_delete=models.PROTECT, related_name="solicitudes")
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="solicitudes")
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    motivo = models.TextField()
    soporte = models.FileField("soporte (opcional)", upload_to="soportes/%Y/%m/", blank=True)
    fecha_solicitud = models.DateTimeField("fecha y hora del aviso", auto_now_add=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.RECIBIDA, db_index=True)
    justificacion = models.TextField("justificación de la decisión", blank=True)
    valor_pagado = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    valor_autorizado = models.DecimalField("valor autorizado a devolver", max_digits=12, decimal_places=0, null=True, blank=True)
    medio_devolucion = models.CharField("medio de devolución", max_length=120, blank=True)
    referencia_devolucion = models.CharField("referencia de la devolución", max_length=120, blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="solicitudes_revisadas"
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha_solicitud"]
        verbose_name = "solicitud de reembolso"
        verbose_name_plural = "solicitudes de reembolso"

    def __str__(self):
        return f"Solicitud #{self.pk} – {self.reserva.codigo} ({self.get_estado_display()})"

    @property
    def abierta(self):
        return self.estado in self.ESTADOS_ABIERTOS


class HistorialSolicitud(models.Model):
    solicitud = models.ForeignKey(SolicitudReembolso, on_delete=models.CASCADE, related_name="historial")
    estado = models.CharField(max_length=12, choices=SolicitudReembolso.Estado.choices)
    nota = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha"]
