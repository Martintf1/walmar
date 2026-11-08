"""Validación de tiquetes y registro de abordaje (CU-09, CU-10, CU-19)."""
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import codigos
from core.auditoria import registrar
from operacion.models import Viaje
from reservas.models import Reserva, Tiquete

from .models import RegistroAbordaje


def _motivo_rechazo(tiquete, viaje):
    if tiquete is None:
        return "Tiquete inválido: el código no existe."
    if tiquete.pasajero.reserva.viaje_id != viaje.pk:
        return "El tiquete no corresponde a este viaje."
    if viaje.estado == Viaje.Estado.CANCELADO:
        return "El viaje está cancelado."
    if tiquete.estado == Tiquete.Estado.UTILIZADO:
        hora = timezone.localtime(tiquete.utilizado_en).strftime("%H:%M") if tiquete.utilizado_en else ""
        return f"Tiquete ya utilizado {('a las ' + hora) if hora else ''}".strip() + "."
    if tiquete.estado == Tiquete.Estado.ANULADO:
        return "Tiquete anulado o cancelado."
    if tiquete.pasajero.reserva.estado != Reserva.Estado.CONFIRMADA:
        return "La compra no está confirmada."
    return ""


def validar_tiquete(codigo, viaje, usuario, sin_conexion=False, clave_idempotencia=None, fecha=None):
    """Valida un tiquete y registra el intento. Devuelve el RegistroAbordaje.

    Idempotente por `clave_idempotencia`: un reintento o una sincronización
    repetida devuelve el registro original sin duplicarlo.
    """
    if clave_idempotencia:
        previo = RegistroAbordaje.objects.filter(clave_idempotencia=clave_idempotencia).first()
        if previo:
            return previo
    codigo = codigos.normalizar(codigo)
    fecha = fecha or timezone.now()
    try:
        with transaction.atomic():
            tiquete = (
                Tiquete.objects.select_for_update()
                .select_related("pasajero__reserva")
                .filter(codigo=codigo)
                .first()
            )
            motivo = _motivo_rechazo(tiquete, viaje)
            if not motivo:
                # Bloqueo de reutilización con actualización condicional.
                marcado = Tiquete.objects.filter(pk=tiquete.pk, estado=Tiquete.Estado.VALIDO).update(
                    estado=Tiquete.Estado.UTILIZADO, utilizado_en=fecha
                )
                if not marcado:
                    motivo = "Tiquete ya utilizado."
            registro = RegistroAbordaje.objects.create(
                viaje=viaje,
                tiquete=tiquete,
                codigo_leido=codigo[:40],
                usuario=usuario,
                resultado=RegistroAbordaje.Resultado.RECHAZADO if motivo else RegistroAbordaje.Resultado.ACEPTADO,
                motivo=motivo,
                fecha=fecha,
                sin_conexion=sin_conexion,
                clave_idempotencia=clave_idempotencia or None,
            )
            registrar(
                usuario,
                "abordaje",
                codigo,
                resultado=registro.resultado,
                viaje=viaje.pk,
                motivo=motivo,
                sin_conexion=sin_conexion,
            )
    except IntegrityError:
        previo = RegistroAbordaje.objects.filter(clave_idempotencia=clave_idempotencia).first()
        if previo:
            return previo
        raise
    return registro


def manifiesto(viaje):
    """Pasajeros del viaje con estado de pago y de abordaje (CU-15, RF-IN-04)."""
    filas = []
    reservas = (
        viaje.reservas.filter(estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.PENDIENTE])
        .select_related("usuario")
        .prefetch_related("pasajeros__tiquetes", "pagos")
        .order_by("creada_en")
    )
    for reserva in reservas:
        pago = reserva.pago_aprobado
        for pasajero in reserva.pasajeros.all():
            tiquete = pasajero.tiquete_vigente
            filas.append(
                {
                    "reserva": reserva,
                    "pasajero": pasajero,
                    "tiquete": tiquete,
                    "estado_pago": "Pagado" if reserva.confirmada else "Pendiente de pago",
                    "medio_pago": pago.get_medio_display() if pago else "",
                    "abordo": bool(tiquete and tiquete.estado == Tiquete.Estado.UTILIZADO),
                }
            )
    return filas


def manifiesto_reducido(viaje):
    """Datos mínimos para validar sin conexión (sin documentos completos, RNF-04 / 3.5)."""
    tiquetes = Tiquete.objects.filter(
        pasajero__reserva__viaje=viaje,
        pasajero__reserva__estado=Reserva.Estado.CONFIRMADA,
        estado__in=[Tiquete.Estado.VALIDO, Tiquete.Estado.UTILIZADO],
    ).select_related("pasajero")
    return {
        "viaje": {
            "id": viaje.pk,
            "descripcion": str(viaje),
            "lancha": viaje.lancha.nombre,
            "zarpe": viaje.zarpe.isoformat(),
            "estado": viaje.estado,
        },
        "generado_en": timezone.now().isoformat(),
        "tiquetes": [
            {
                "codigo": t.codigo,
                "nombre": t.pasajero.nombre,
                "documento": t.pasajero.documento_enmascarado,
                "estado": t.estado,
            }
            for t in tiquetes
        ],
    }
