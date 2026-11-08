from django.conf import settings
from django.db import models

from core import codigos
from cuentas.models import TipoDocumento
from operacion.models import Viaje


def _codigo_reserva():
    return codigos.generar("R", 8)


def _codigo_tiquete():
    return codigos.generar("WM", 8)


class Reserva(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente de pago"
        CONFIRMADA = "CONFIRMADA", "Confirmada (pagada)"
        CANCELADA = "CANCELADA", "Cancelada"
        VENCIDA = "VENCIDA", "Vencida (sin pago en el plazo)"

    class Canal(models.TextChoices):
        EN_LINEA = "EN_LINEA", "En línea"
        TAQUILLA = "TAQUILLA", "Punto de atención"

    class RespuestaCambio(models.TextChoices):
        SIN_CAMBIO = "", "—"
        PENDIENTE = "PENDIENTE", "Pendiente de respuesta del pasajero"
        ACEPTA = "ACEPTA", "Acepta el nuevo horario"
        OTRA_SALIDA = "OTRA_SALIDA", "Trasladado a otra salida"
        DESISTE = "DESISTE", "Desiste (solicita reembolso)"

    codigo = models.CharField(max_length=12, unique=True, default=_codigo_reserva, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservas")
    viaje = models.ForeignKey(Viaje, on_delete=models.PROTECT, related_name="reservas")
    cantidad = models.PositiveSmallIntegerField()
    tarifa_unitaria = models.DecimalField(max_digits=10, decimal_places=0)
    total = models.DecimalField(max_digits=12, decimal_places=0)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    canal = models.CharField(max_length=8, choices=Canal.choices, default=Canal.EN_LINEA)
    creada_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField("plazo para pagar")
    confirmada_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)
    motivo_cancelacion = models.CharField(max_length=250, blank=True)
    acepto_politica_en = models.DateTimeField("aceptó la política de cancelación")
    respuesta_cambio = models.CharField(max_length=12, choices=RespuestaCambio.choices, default="", blank=True)
    clave_idempotencia = models.CharField(max_length=64, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["-creada_en"]
        verbose_name = "reserva"

    def __str__(self):
        return f"{self.codigo} ({self.get_estado_display()})"

    @property
    def pendiente(self):
        return self.estado == self.Estado.PENDIENTE

    @property
    def confirmada(self):
        return self.estado == self.Estado.CONFIRMADA

    @property
    def activa(self):
        return self.estado in (self.Estado.PENDIENTE, self.Estado.CONFIRMADA)

    @property
    def pago_aprobado(self):
        return self.pagos.filter(estado="APROBADO").order_by("-actualizado_en").first()

    def tiquetes_vigentes(self):
        return Tiquete.objects.filter(pasajero__reserva=self, estado__in=[Tiquete.Estado.VALIDO, Tiquete.Estado.UTILIZADO])


class Pasajero(models.Model):
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name="pasajeros")
    nombre = models.CharField("nombre completo", max_length=150)
    tipo_documento = models.CharField(max_length=2, choices=TipoDocumento.choices, default=TipoDocumento.CC)
    documento = models.CharField("número de documento", max_length=30)
    telefono = models.CharField(max_length=30, blank=True)

    class Meta:
        verbose_name = "pasajero"
        constraints = [
            models.UniqueConstraint(fields=["reserva", "tipo_documento", "documento"], name="pasajero_unico_por_reserva"),
        ]

    def __str__(self):
        return self.nombre

    @property
    def documento_enmascarado(self):
        """Visibilidad restringida del documento (RNF-04)."""
        doc = self.documento or ""
        return ("•" * max(len(doc) - 4, 0)) + doc[-4:]

    @property
    def tiquete_vigente(self):
        return self.tiquetes.exclude(estado=Tiquete.Estado.ANULADO).order_by("-emitido_en").first()


class Tiquete(models.Model):
    class Estado(models.TextChoices):
        VALIDO = "VALIDO", "Válido"
        UTILIZADO = "UTILIZADO", "Utilizado (abordó)"
        ANULADO = "ANULADO", "Anulado"

    pasajero = models.ForeignKey(Pasajero, on_delete=models.CASCADE, related_name="tiquetes")
    codigo = models.CharField(max_length=16, unique=True, default=_codigo_tiquete, editable=False)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.VALIDO, db_index=True)
    emitido_en = models.DateTimeField(auto_now_add=True)
    utilizado_en = models.DateTimeField(null=True, blank=True)
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)
    reemplaza = models.OneToOneField("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reemplazado_por")

    class Meta:
        ordering = ["-emitido_en"]
        verbose_name = "tiquete"

    def __str__(self):
        return self.codigo

    @property
    def reserva(self):
        return self.pasajero.reserva

    @property
    def viaje(self):
        return self.pasajero.reserva.viaje
