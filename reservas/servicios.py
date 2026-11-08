"""Lógica de negocio de reservas, cupos y tiquetes.

El servidor es la autoridad sobre los cupos (RNF-07): la ocupación se modifica
con actualizaciones condicionales atómicas (`UPDATE ... WHERE cupos_ocupados + n
<= cupos`), de modo que dos solicitudes simultáneas sobre el último cupo nunca
se aprueban ambas, en cualquier motor de base de datos.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from core import notificaciones
from core.auditoria import registrar
from operacion.models import Viaje

from .models import Pasajero, Reserva, Tiquete


class ErrorReserva(Exception):
    """Error de negocio con un mensaje apto para mostrar al usuario."""


# ---------------------------------------------------------------- cupos
def ocupar_cupos(viaje_id, cantidad):
    filas = Viaje.objects.filter(pk=viaje_id, cupos_ocupados__lte=F("cupos") - cantidad).update(
        cupos_ocupados=F("cupos_ocupados") + cantidad
    )
    return filas == 1


def liberar_cupos(viaje_id, cantidad):
    Viaje.objects.filter(pk=viaje_id, cupos_ocupados__gte=cantidad).update(cupos_ocupados=F("cupos_ocupados") - cantidad)


# ---------------------------------------------------------------- vencimientos
def expirar_reservas(viaje=None):
    """Cancela las reservas sin pago en el plazo y libera sus cupos."""
    qs = Reserva.objects.filter(estado=Reserva.Estado.PENDIENTE, expira_en__lt=timezone.now())
    if viaje is not None:
        qs = qs.filter(viaje=viaje)
    total = 0
    for reserva in qs.only("pk", "viaje_id", "cantidad", "codigo"):
        with transaction.atomic():
            cambiadas = Reserva.objects.filter(pk=reserva.pk, estado=Reserva.Estado.PENDIENTE).update(
                estado=Reserva.Estado.VENCIDA,
                cancelada_en=timezone.now(),
                motivo_cancelacion="Venció el plazo de pago.",
            )
            if cambiadas:
                liberar_cupos(reserva.viaje_id, reserva.cantidad)
                registrar(None, "reserva_vencida", reserva.codigo)
                total += 1
    return total


# ---------------------------------------------------------------- creación
def crear_reserva(usuario, viaje_id, pasajeros, acepta_politica, canal=Reserva.Canal.EN_LINEA, clave_idempotencia=None):
    """Crea una reserva con bloqueo temporal de cupos (CU-04, RF-PAS-02).

    `pasajeros` es una lista de dicts con nombre, tipo_documento, documento y telefono.
    Si llega una `clave_idempotencia` ya usada se devuelve la reserva existente
    (reintentos y sincronización sin duplicados, RNF-08 / CU-19).
    """
    if clave_idempotencia:
        existente = Reserva.objects.filter(clave_idempotencia=clave_idempotencia).first()
        if existente:
            if existente.usuario_id != usuario.pk:
                raise ErrorReserva("La operación no es válida.")
            return existente

    if not acepta_politica:
        raise ErrorReserva("Debe aceptar la política de cancelación, reprogramación y devolución.")
    cantidad = len(pasajeros)
    maximo = settings.WALMAR["MAX_PASAJES_POR_RESERVA"]
    if cantidad < 1:
        raise ErrorReserva("Debe registrar al menos un pasajero.")
    if cantidad > maximo:
        raise ErrorReserva(f"Puede reservar máximo {maximo} pasajes por operación.")
    documentos = [(p["tipo_documento"], p["documento"].strip()) for p in pasajeros]
    if len(set(documentos)) != len(documentos):
        raise ErrorReserva("Hay pasajeros repetidos con el mismo documento.")

    expirar_reservas()
    try:
        viaje = Viaje.objects.select_related("ruta", "lancha").get(pk=viaje_id)
    except Viaje.DoesNotExist:
        raise ErrorReserva("El viaje no existe.")
    problemas = viaje.problemas_para_venta()
    if problemas:
        raise ErrorReserva(problemas[0])

    ahora = timezone.now()
    plazo = ahora + timedelta(minutes=settings.WALMAR["RESERVA_PLAZO_MINUTOS"])
    # Nunca más allá del zarpe.
    plazo = min(plazo, viaje.zarpe)
    try:
        with transaction.atomic():
            # Verificación de disponibilidad en el servidor y bloqueo atómico (CA2/CA3).
            if not ocupar_cupos(viaje.pk, cantidad):
                viaje.refresh_from_db(fields=["cupos_ocupados", "cupos"])
                raise ErrorReserva(
                    f"Cupos insuficientes: quedan {viaje.cupos_disponibles} disponibles para este viaje."
                )
            reserva = Reserva.objects.create(
                usuario=usuario,
                viaje=viaje,
                cantidad=cantidad,
                tarifa_unitaria=viaje.tarifa,
                total=viaje.tarifa * cantidad,
                canal=canal,
                expira_en=plazo,
                acepto_politica_en=ahora,
                clave_idempotencia=clave_idempotencia or None,
            )
            Pasajero.objects.bulk_create(
                [
                    Pasajero(
                        reserva=reserva,
                        nombre=p["nombre"].strip(),
                        tipo_documento=p["tipo_documento"],
                        documento=p["documento"].strip(),
                        telefono=(p.get("telefono") or "").strip(),
                    )
                    for p in pasajeros
                ]
            )
            registrar(usuario, "reserva_creada", reserva.codigo, viaje=viaje.pk, cantidad=cantidad, canal=canal)
    except IntegrityError:
        if clave_idempotencia:
            existente = Reserva.objects.filter(clave_idempotencia=clave_idempotencia).first()
            if existente:
                return existente
        raise

    notificaciones.enviar(usuario.email, f"Reserva {reserva.codigo} creada", "reserva_creada", {"reserva": reserva})
    return reserva


# ---------------------------------------------------------------- confirmación
def confirmar_reserva(reserva_id, usuario=None):
    """Confirma la reserva tras un pago aprobado y emite los tiquetes (RF-TIQ-01).

    Devuelve la reserva confirmada. Si la reserva había vencido, intenta volver
    a ocupar los cupos; si ya no hay, lanza ErrorReserva (el pago debe
    devolverse).
    """
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().select_related("viaje").get(pk=reserva_id)
        if reserva.estado == Reserva.Estado.CONFIRMADA:
            return reserva
        if reserva.estado in (Reserva.Estado.VENCIDA, Reserva.Estado.CANCELADA):
            if reserva.viaje.cancelado or not ocupar_cupos(reserva.viaje_id, reserva.cantidad):
                raise ErrorReserva("La reserva ya no está vigente y no hay cupos para recuperarla.")
        reserva.estado = Reserva.Estado.CONFIRMADA
        reserva.confirmada_en = timezone.now()
        reserva.cancelada_en = None
        reserva.motivo_cancelacion = ""
        reserva.save(update_fields=["estado", "confirmada_en", "cancelada_en", "motivo_cancelacion"])
        emitir_tiquetes(reserva)
        registrar(usuario, "reserva_confirmada", reserva.codigo)
    notificaciones.enviar(
        reserva.usuario.email, f"Compra confirmada – reserva {reserva.codigo}", "reserva_confirmada", {"reserva": reserva}
    )
    return reserva


def emitir_tiquetes(reserva):
    """Un tiquete con código único por pasajero; solo si la reserva está confirmada (CA3)."""
    if reserva.estado != Reserva.Estado.CONFIRMADA:
        raise ErrorReserva("No se puede emitir el tiquete: el pago no está confirmado.")
    emitidos = []
    for pasajero in reserva.pasajeros.all():
        if not pasajero.tiquetes.exclude(estado=Tiquete.Estado.ANULADO).exists():
            emitidos.append(Tiquete.objects.create(pasajero=pasajero))
    return emitidos


def anular_tiquetes(reserva, motivo):
    return Tiquete.objects.filter(pasajero__reserva=reserva, estado=Tiquete.Estado.VALIDO).update(
        estado=Tiquete.Estado.ANULADO, anulado_en=timezone.now(), motivo_anulacion=motivo[:250]
    )


def reemplazar_tiquetes(reserva, motivo):
    """Anula los tiquetes válidos y emite unos nuevos que los reemplazan (reprogramación)."""
    nuevos = []
    for tiquete in Tiquete.objects.filter(pasajero__reserva=reserva, estado=Tiquete.Estado.VALIDO).select_related("pasajero"):
        tiquete.estado = Tiquete.Estado.ANULADO
        tiquete.anulado_en = timezone.now()
        tiquete.motivo_anulacion = motivo[:250]
        tiquete.save(update_fields=["estado", "anulado_en", "motivo_anulacion"])
        nuevos.append(Tiquete.objects.create(pasajero=tiquete.pasajero, reemplaza=tiquete))
    return nuevos


# ---------------------------------------------------------------- cancelación
def cancelar_reserva(reserva_id, motivo, usuario=None):
    """Cancela una reserva activa, anula sus tiquetes y libera cupos."""
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
        if not reserva.activa:
            return reserva
        reserva.estado = Reserva.Estado.CANCELADA
        reserva.cancelada_en = timezone.now()
        reserva.motivo_cancelacion = motivo[:250]
        reserva.save(update_fields=["estado", "cancelada_en", "motivo_cancelacion"])
        anular_tiquetes(reserva, motivo)
        liberar_cupos(reserva.viaje_id, reserva.cantidad)
        registrar(usuario, "reserva_cancelada", reserva.codigo, motivo=motivo)
    return reserva


def trasladar_reserva(reserva_id, nuevo_viaje_id, usuario):
    """Pasa una reserva confirmada a otra salida (decisión del pasajero ante un cambio)."""
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().select_related("viaje").get(pk=reserva_id)
        if not reserva.confirmada:
            raise ErrorReserva("Solo se pueden trasladar reservas confirmadas.")
        if reserva.respuesta_cambio != Reserva.RespuestaCambio.PENDIENTE:
            raise ErrorReserva("Esta reserva no tiene un cambio de salida pendiente de respuesta.")
        nuevo = Viaje.objects.select_related("ruta", "lancha").get(pk=nuevo_viaje_id)
        if nuevo.pk == reserva.viaje_id or nuevo.sentido != reserva.viaje.sentido or nuevo.ruta_id != reserva.viaje.ruta_id:
            raise ErrorReserva("Seleccione otra salida de la misma ruta y sentido.")
        problemas = nuevo.problemas_para_venta()
        if problemas:
            raise ErrorReserva(problemas[0])
        if not ocupar_cupos(nuevo.pk, reserva.cantidad):
            raise ErrorReserva("La salida seleccionada no tiene cupos suficientes.")
        anterior = reserva.viaje
        liberar_cupos(anterior.pk, reserva.cantidad)
        reserva.viaje = nuevo
        reserva.respuesta_cambio = Reserva.RespuestaCambio.OTRA_SALIDA
        reserva.save(update_fields=["viaje", "respuesta_cambio"])
        reemplazar_tiquetes(reserva, f"Traslado a la salida {nuevo}")
        emitir_tiquetes(reserva)  # pasajeros cuyos tiquetes se anularon por cancelación
        registrar(usuario, "reserva_trasladada", reserva.codigo, desde=anterior.pk, hacia=nuevo.pk)
    return reserva
