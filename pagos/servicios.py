from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core import notificaciones
from core.auditoria import registrar
from reservas.models import Reserva
from reservas.servicios import ErrorReserva, cancelar_reserva, confirmar_reserva, expirar_reservas

from .models import Pago


class ErrorPago(Exception):
    pass


def _validar_reserva_pagable(reserva):
    expirar_reservas(reserva.viaje)
    reserva.refresh_from_db()
    if reserva.estado == Reserva.Estado.VENCIDA:
        raise ErrorPago("El plazo para pagar esta reserva venció y los cupos fueron liberados.")
    if reserva.estado != Reserva.Estado.PENDIENTE:
        raise ErrorPago(f"La reserva no está pendiente de pago (estado: {reserva.get_estado_display()}).")


def iniciar_pago_en_linea(reserva, usuario):
    """Crea el pago en estado pendiente para enviarlo a la pasarela (CU-06)."""
    _validar_reserva_pagable(reserva)
    with transaction.atomic():
        # Reutiliza un intento pendiente para evitar pagos duplicados.
        pago = Pago.objects.filter(reserva=reserva, medio=Pago.Medio.EN_LINEA, estado=Pago.Estado.PENDIENTE).first()
        if pago is None:
            pago = Pago.objects.create(reserva=reserva, medio=Pago.Medio.EN_LINEA, valor=reserva.total)
            registrar(usuario, "pago_en_linea_iniciado", pago.referencia, reserva=reserva.codigo)
    return pago


def procesar_notificacion(datos):
    """Aplica el resultado notificado por la pasarela. Idempotente.

    `datos`: {"referencia", "estado" (APROBADO|RECHAZADO|PENDIENTE), "transaccion", "valor"}.
    """
    with transaction.atomic():
        try:
            pago = Pago.objects.select_for_update().select_related("reserva").get(referencia=datos["referencia"])
        except Pago.DoesNotExist:
            raise ErrorPago("Pago no encontrado.")
        estado = datos.get("estado")
        if estado not in (Pago.Estado.APROBADO, Pago.Estado.RECHAZADO, Pago.Estado.PENDIENTE):
            raise ErrorPago("Estado de pago no válido.")
        if pago.estado in (Pago.Estado.APROBADO, Pago.Estado.REEMBOLSADO):
            return pago  # notificación repetida
        if str(datos.get("valor")) != str(int(pago.valor)):
            registrar(None, "pago_valor_inconsistente", pago.referencia, resultado="ERROR", datos=datos)
            raise ErrorPago("El valor notificado no coincide con el pago.")
        pago.estado = estado
        pago.referencia_externa = datos.get("transaccion", "")[:80]
        pago.detalle_pasarela = datos
        if estado == Pago.Estado.APROBADO:
            pago.confirmado_en = timezone.now()
        pago.save()
        registrar(None, "pago_en_linea_notificado", pago.referencia, resultado=estado, transaccion=pago.referencia_externa)

    reserva = pago.reserva
    if estado == Pago.Estado.APROBADO:
        try:
            confirmar_reserva(reserva.pk)
        except ErrorReserva as exc:
            pago.observacion = f"Pago aprobado sobre reserva no vigente: requiere devolución. {exc}"
            pago.save(update_fields=["observacion"])
            registrar(None, "pago_sin_cupo", pago.referencia, resultado="ERROR")
        notificaciones.enviar(reserva.usuario.email, f"Pago aprobado {pago.referencia}", "pago", {"pago": pago})
    elif estado == Pago.Estado.RECHAZADO:
        if settings.WALMAR["PAGO_RECHAZADO_ACCION"] == "liberar":
            cancelar_reserva(reserva.pk, "Pago en línea rechazado.")
        notificaciones.enviar(reserva.usuario.email, f"Pago rechazado {pago.referencia}", "pago", {"pago": pago})
    return pago


def registrar_pago_efectivo(reserva, valor_recibido, usuario):
    """Registro del pago en efectivo en el punto de atención (CU-07, RF-PAG-01)."""
    if not usuario.tiene_rol("VENTAS"):
        raise ErrorPago("Solo el personal de atención y venta puede registrar pagos en efectivo.")
    _validar_reserva_pagable(reserva)
    if valor_recibido < reserva.total:
        raise ErrorPago(f"El valor recibido es menor que el total a pagar (${reserva.total:,.0f}).".replace(",", "."))
    with transaction.atomic():
        pago = Pago.objects.create(
            reserva=reserva,
            medio=Pago.Medio.EFECTIVO,
            valor=reserva.total,
            valor_recibido=valor_recibido,
            estado=Pago.Estado.APROBADO,
            registrado_por=usuario,
            confirmado_en=timezone.now(),
        )
        # Cancela intentos en línea pendientes de la misma reserva.
        Pago.objects.filter(reserva=reserva, medio=Pago.Medio.EN_LINEA, estado=Pago.Estado.PENDIENTE).update(
            estado=Pago.Estado.RECHAZADO, observacion="Reemplazado por pago en efectivo."
        )
        confirmar_reserva(reserva.pk, usuario)
        registrar(usuario, "pago_efectivo", pago.referencia, reserva=reserva.codigo, valor=pago.valor, recibido=valor_recibido)
    notificaciones.enviar(reserva.usuario.email, f"Pago registrado {pago.referencia}", "pago", {"pago": pago})
    return pago
