from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Ruta(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    ciudad_a = models.CharField("ciudad A", max_length=80, default="Buenaventura")
    ciudad_b = models.CharField("ciudad B", max_length=80, default="Timbiquí")
    duracion_estimada_min = models.PositiveIntegerField("duración estimada (minutos)", default=240)
    tarifa_base = models.DecimalField("tarifa base (COP)", max_digits=10, decimal_places=0, default=160000)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ruta"

    def __str__(self):
        return self.nombre

    @property
    def duracion_texto(self):
        h, m = divmod(self.duracion_estimada_min, 60)
        return f"{h} h {m:02d} min" if m else f"{h} h"


class PuntoEmbarque(models.Model):
    class Tipo(models.TextChoices):
        EMBARQUE = "EMBARQUE", "Embarque"
        DESEMBARQUE = "DESEMBARQUE", "Desembarque"
        AMBOS = "AMBOS", "Embarque y desembarque"

    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE, related_name="puntos")
    nombre = models.CharField(max_length=120)
    ciudad = models.CharField(max_length=80)
    direccion = models.CharField("dirección / referencia", max_length=200, blank=True)
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.AMBOS)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "punto de embarque"
        verbose_name_plural = "puntos de embarque"
        ordering = ["ciudad", "nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.ciudad})"


class GrupoPropietarios(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    orden = models.PositiveSmallIntegerField("orden en la rotación", default=1)
    responsable = models.CharField(max_length=120, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "grupo de propietarios"
        verbose_name_plural = "grupos de propietarios"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Lancha(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        MANTENIMIENTO = "MANTENIMIENTO", "En mantenimiento"
        INACTIVA = "INACTIVA", "Inactiva"

    nombre = models.CharField("nombre / identificación", max_length=80)
    matricula = models.CharField("matrícula", max_length=40, unique=True)
    capacidad_autorizada = models.PositiveIntegerField("capacidad autorizada de pasajeros")
    motores = models.CharField("datos operativos (motores, etc.)", max_length=200, blank=True)
    grupo = models.ForeignKey(GrupoPropietarios, null=True, blank=True, on_delete=models.SET_NULL, related_name="lanchas")
    estado = models.CharField(max_length=14, choices=Estado.choices, default=Estado.ACTIVA)

    class Meta:
        verbose_name = "lancha"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.matricula}) – {self.capacidad_autorizada} pax"

    def clean(self):
        if self.capacidad_autorizada is not None and self.capacidad_autorizada < 1:
            raise ValidationError({"capacidad_autorizada": "La capacidad debe ser mayor que cero."})


class AsignacionGrupo(models.Model):
    """Grupo de propietarios responsable de la operación en una fecha (calendario de turnos)."""

    fecha = models.DateField(unique=True)
    grupo = models.ForeignKey(GrupoPropietarios, on_delete=models.CASCADE, related_name="asignaciones")
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "asignación de grupo"
        verbose_name_plural = "calendario de grupos"
        ordering = ["fecha"]

    def __str__(self):
        return f"{self.fecha}: {self.grupo}"


FECHA_REFERENCIA_ROTACION = date(2026, 1, 1)


def grupo_para(fecha):
    """Grupo asignado a la fecha: asignación explícita o rotación diaria por orden."""
    asignacion = AsignacionGrupo.objects.filter(fecha=fecha).select_related("grupo").first()
    if asignacion:
        return asignacion.grupo
    grupos = list(GrupoPropietarios.objects.filter(activo=True))
    if not grupos:
        return None
    return grupos[(fecha - FECHA_REFERENCIA_ROTACION).days % len(grupos)]


class Viaje(models.Model):
    """Salida programada de una lancha en un sentido, fecha y hora."""

    class Sentido(models.TextChoices):
        IDA = "IDA", "Ida (ciudad A → ciudad B)"
        REGRESO = "REGRESO", "Regreso (ciudad B → ciudad A)"

    class Estado(models.TextChoices):
        PROGRAMADO = "PROGRAMADO", "Programado"
        REPROGRAMADO = "REPROGRAMADO", "Reprogramado"
        CANCELADO = "CANCELADO", "Cancelado"
        FINALIZADO = "FINALIZADO", "Finalizado"

    ruta = models.ForeignKey(Ruta, on_delete=models.PROTECT, related_name="viajes")
    sentido = models.CharField(max_length=8, choices=Sentido.choices, default=Sentido.IDA)
    punto_embarque = models.ForeignKey(PuntoEmbarque, on_delete=models.PROTECT, related_name="+")
    punto_desembarque = models.ForeignKey(PuntoEmbarque, on_delete=models.PROTECT, related_name="+")
    fecha = models.DateField(db_index=True)
    hora_programada = models.TimeField()
    hora_efectiva = models.TimeField("hora efectiva (ajuste por marea)", null=True, blank=True)
    tarifa = models.DecimalField("tarifa unitaria (COP)", max_digits=10, decimal_places=0)
    lancha = models.ForeignKey(Lancha, on_delete=models.PROTECT, related_name="viajes")
    grupo = models.ForeignKey(GrupoPropietarios, null=True, blank=True, on_delete=models.SET_NULL, related_name="viajes")
    cupos = models.PositiveIntegerField("cupos a la venta")
    cupos_ocupados = models.PositiveIntegerField(default=0, editable=False)
    habilitado = models.BooleanField("habilitado para la venta", default=False)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PROGRAMADO)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "viaje (salida)"
        verbose_name_plural = "viajes (salidas)"
        ordering = ["fecha", "hora_programada"]
        constraints = [
            models.CheckConstraint(condition=models.Q(cupos_ocupados__lte=models.F("cupos")), name="viaje_sin_sobreventa"),
        ]

    def __str__(self):
        return f"{self.origen} → {self.destino} {self.fecha:%d/%m/%Y} {self.hora_vigente:%H:%M}"

    @property
    def origen(self):
        return self.ruta.ciudad_a if self.sentido == self.Sentido.IDA else self.ruta.ciudad_b

    @property
    def destino(self):
        return self.ruta.ciudad_b if self.sentido == self.Sentido.IDA else self.ruta.ciudad_a

    @property
    def hora_vigente(self):
        return self.hora_efectiva or self.hora_programada

    @property
    def hora_cambiada(self):
        return bool(self.hora_efectiva and self.hora_efectiva != self.hora_programada)

    @property
    def zarpe(self):
        return timezone.make_aware(datetime.combine(self.fecha, self.hora_vigente))

    @property
    def llegada_estimada(self):
        return self.zarpe + timedelta(minutes=self.ruta.duracion_estimada_min)

    @property
    def cupos_disponibles(self):
        return max(self.cupos - self.cupos_ocupados, 0)

    @property
    def cancelado(self):
        return self.estado == self.Estado.CANCELADO

    def problemas_para_venta(self):
        """Lista de motivos por los que el viaje no puede venderse (CU-16 excepción)."""
        problemas = []
        if not self.habilitado:
            problemas.append("El viaje no está habilitado para la venta.")
        if self.estado not in (self.Estado.PROGRAMADO, self.Estado.REPROGRAMADO):
            problemas.append("El viaje no está programado.")
        if not self.ruta.activa:
            problemas.append("La ruta no está activa.")
        if self.lancha.estado != Lancha.Estado.ACTIVA:
            problemas.append("La lancha asignada no está disponible.")
        if not self.tarifa or self.tarifa <= 0:
            problemas.append("El viaje no tiene tarifa.")
        if self.zarpe <= timezone.now():
            problemas.append("La hora de zarpe ya pasó.")
        return problemas

    @property
    def vendible(self):
        return not self.problemas_para_venta()

    def clean(self):
        errores = {}
        if self.lancha_id and self.cupos is not None and self.cupos > self.lancha.capacidad_autorizada:
            errores["cupos"] = (
                f"Los cupos ({self.cupos}) superan la capacidad autorizada de la lancha "
                f"({self.lancha.capacidad_autorizada})."
            )
        if self.cupos is not None and self.cupos < self.cupos_ocupados:
            errores["cupos"] = f"Ya hay {self.cupos_ocupados} cupos vendidos o reservados; no puede reducirse por debajo."
        if self.lancha_id and self.lancha.estado != Lancha.Estado.ACTIVA:
            errores["lancha"] = "La lancha seleccionada no está disponible."
        if self.lancha_id and self.fecha:
            choque = Viaje.objects.filter(lancha_id=self.lancha_id, fecha=self.fecha, sentido=self.sentido).exclude(
                estado=self.Estado.CANCELADO
            )
            if self.pk:
                choque = choque.exclude(pk=self.pk)
            if choque.exists():
                errores["lancha"] = "La lancha ya tiene una salida asignada en esa fecha y sentido."
        if self.punto_embarque_id and self.punto_desembarque_id and self.punto_embarque_id == self.punto_desembarque_id:
            errores["punto_desembarque"] = "El punto de desembarque debe ser distinto al de embarque."
        if errores:
            raise ValidationError(errores)


class CambioViaje(models.Model):
    """Historial de cambios, reprogramaciones y cancelaciones (RF-ADM-03, CU-13)."""

    class Tipo(models.TextChoices):
        CREACION = "CREACION", "Creación"
        EDICION = "EDICION", "Edición"
        HORA_EFECTIVA = "HORA_EFECTIVA", "Ajuste de hora por marea"
        REPROGRAMACION = "REPROGRAMACION", "Reprogramación"
        CAMBIO_LANCHA = "CAMBIO_LANCHA", "Cambio de lancha"
        CANCELACION = "CANCELACION", "Cancelación"

    viaje = models.ForeignKey(Viaje, on_delete=models.CASCADE, related_name="cambios")
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    motivo = models.TextField(blank=True)
    datos_anteriores = models.JSONField(default=dict, blank=True)
    datos_nuevos = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "cambio de viaje"
        verbose_name_plural = "cambios de viajes"


CAMPOS_HISTORIAL = ["fecha", "hora_programada", "hora_efectiva", "tarifa", "lancha_id", "cupos", "habilitado", "estado"]


def instantanea(viaje):
    datos = {}
    for campo in CAMPOS_HISTORIAL:
        valor = getattr(viaje, campo)
        datos[campo] = str(valor) if valor is not None and not isinstance(valor, (bool, int)) else valor
    return datos


class HorarioBase(models.Model):
    """Horario tipo de salida usado para programar los viajes de cada día."""

    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE, related_name="horarios")
    sentido = models.CharField(max_length=8, choices=Viaje.Sentido.choices)
    hora = models.TimeField("hora programada")
    punto_embarque = models.ForeignKey(PuntoEmbarque, on_delete=models.PROTECT, related_name="+")
    punto_desembarque = models.ForeignKey(PuntoEmbarque, on_delete=models.PROTECT, related_name="+")
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "horario base"
        verbose_name_plural = "horarios base"
        ordering = ["sentido", "hora"]

    def __str__(self):
        return f"{self.get_sentido_display()} {self.hora:%H:%M}"
