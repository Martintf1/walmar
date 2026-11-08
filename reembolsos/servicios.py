"""Solicitudes de desistimiento, cancelación y reembolso (CU-14, RF-DEV-01).

El sistema no aplica descuentos ni porcentajes por defecto (sección 2.4): el
valor autorizado lo registra el personal autorizado del transportador según
la política aprobada y el caso.
"""
from django.db import transaction

from core import notificaciones
from core.auditoria import registrar
from pagos.models import Pago
from reservas.models import Reserva
from reservas.servicios import cancelar_reserva

from .models import HistorialSolicitud, SolicitudReembolso

Estado = SolicitudReembolso.Estado

TRANSICIONES = {
    Estado.RECIBIDA: [Estado.EN_REVISION, Estado.APROBADA, Estado.NO_APROBADA],
    Estado.EN_REVISION: [Estado.APROBADA, Estado.NO_APROBADA],
    Estado.APROBADA: [Estado.EN_PROCESO, Estado.REEMBOLSADA],
    Estado.EN_PROCESO: [Estado.REEMBOLSADA],
    Estado.REEMBOLSADA: [],
    Estado.NO_APROBADA: [],
}


class ErrorSolicitud(Exception):
    pass


def crear_solicitud(reserva, usuario, tipo, motivo, soporte=None):
    if reserva.usuario_id != usuario.pk:
        raise ErrorSolicitud("La reserva no le pertenece.")
    if reserva.estado != Reserva.Estado.CONFIRMADA:
        raise ErrorSolicitud("Solo puede solicitar devolución de reservas pagadas. Las reservas pendientes pueden cancelarse directamente.")
    if reserva.solicitudes.filter(estado__in=SolicitudReembolso.ESTADOS_ABIERTOS).exists():
        raise ErrorSolicitud("Ya existe una solicitud abierta para esta reserva.")
    pago = reserva.pago_aprobado
    with transaction.atomic():
        solicitud = SolicitudReembolso.objects.create(
            reserva=reserva,
            solicitante=usuario,
            tipo=tipo,
            motivo=motivo,
            soporte=soporte or "",
            valor_pagado=pago.valor if pago else reserva.total,
            medio_devolucion=pago.get_medio_display() if pago else "",
        )
        HistorialSolicitud.objects.create(solicitud=solicitud, estado=solicitud.estado, nota="Solicitud radicada.", usuario=usuario)
        if reserva.respuesta_cambio == Reserva.RespuestaCambio.PENDIENTE:
            reserva.respuesta_cambio = Reserva.RespuestaCambio.DESISTE
            reserva.save(update_fields=["respuesta_cambio"])
        registrar(usuario, "solicitud_reembolso", solicitud.pk, reserva=reserva.codigo, tipo=tipo)
    _notificar(solicitud)
    return solicitud


def cambiar_estado(solicitud, nuevo_estado, usuario, justificacion="", valor_autorizado=None, referencia=""):
    if nuevo_estado not in TRANSICIONES[solicitud.estado]:
        raise ErrorSolicitud(
            f"No se puede pasar de '{solicitud.get_estado_display()}' a '{Estado(nuevo_estado).label}'."
        )
    if nuevo_estado in (Estado.APROBADA, Estado.NO_APROBADA) and not justificacion.strip():
        raise ErrorSolicitud("Debe ingresar la justificación de la decisión.")
    if nuevo_estado == Estado.APROBADA:
        if valor_autorizado is None or valor_autorizado < 0 or valor_autorizado > solicitud.valor_pagado:
            raise ErrorSolicitud("Ingrese un valor autorizado entre 0 y el valor pagado.")
    if nuevo_estado == Estado.REEMBOLSADA and not referencia.strip():
        raise ErrorSolicitud("Registre la referencia de la devolución.")

    with transaction.atomic():
        solicitud.estado = nuevo_estado
        solicitud.revisado_por = usuario
        if justificacion:
            solicitud.justificacion = justificacion
        if valor_autorizado is not None:
            solicitud.valor_autorizado = valor_autorizado
        if referencia:
            solicitud.referencia_devolucion = referencia
        solicitud.save()
        if nuevo_estado == Estado.APROBADA:
            cancelar_reserva(solicitud.reserva_id, f"Solicitud de reembolso #{solicitud.pk} aprobada.", usuario)
        if nuevo_estado == Estado.REEMBOLSADA:
            Pago.objects.filter(reserva=solicitud.reserva, estado=Pago.Estado.APROBADO).update(
                estado=Pago.Estado.REEMBOLSADO, observacion=f"Devolución {referencia[:100]}"
            )
        HistorialSolicitud.objects.create(
            solicitud=solicitud, estado=nuevo_estado, nota=justificacion or referencia, usuario=usuario
        )
        registrar(usuario, "solicitud_estado", solicitud.pk, resultado=nuevo_estado, valor=valor_autorizado)
    _notificar(solicitud)
    return solicitud


def _notificar(solicitud):
    notificaciones.enviar(
        solicitud.solicitante.email,
        f"Solicitud #{solicitud.pk}: {solicitud.get_estado_display()}",
        "solicitud",
        {"solicitud": solicitud},
    )
