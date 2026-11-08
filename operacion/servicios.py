"""Gestión de salidas: creación, ajustes por marea, reprogramación y cancelación."""
from django.db import transaction
from django.utils import timezone

from core import notificaciones
from core.auditoria import registrar
from reservas.models import Reserva
from reservas.servicios import anular_tiquetes, cancelar_reserva, reemplazar_tiquetes

from .models import CambioViaje, Viaje, grupo_para, instantanea


def guardar_viaje(viaje, usuario, motivo=""):
    """Crea o actualiza un viaje registrando el historial (RF-ADM-01 CA2)."""
    nuevo = viaje.pk is None
    anterior = {} if nuevo else instantanea(Viaje.objects.get(pk=viaje.pk))
    if viaje.grupo_id is None and viaje.lancha_id and viaje.lancha.grupo_id:
        viaje.grupo_id = viaje.lancha.grupo_id
    if viaje.grupo_id is None and viaje.fecha:
        grupo = grupo_para(viaje.fecha)
        viaje.grupo = grupo
    if nuevo:
        viaje.creado_por = usuario
    viaje.actualizado_por = usuario
    with transaction.atomic():
        viaje.save()
        datos = instantanea(viaje)
        CambioViaje.objects.create(
            viaje=viaje,
            tipo=CambioViaje.Tipo.CREACION if nuevo else CambioViaje.Tipo.EDICION,
            motivo=motivo,
            datos_anteriores=anterior,
            datos_nuevos=datos,
            usuario=usuario,
        )
        registrar(usuario, "viaje_creado" if nuevo else "viaje_editado", viaje.pk, antes=anterior, despues=datos)
    if not nuevo and anterior.get("lancha_id") != datos.get("lancha_id"):
        _notificar_pasajeros(viaje, "Cambio de lancha", "Se asignó una nueva embarcación a su viaje.", motivo)
    return viaje


def _reservas_afectadas(viaje):
    return Reserva.objects.filter(viaje=viaje, estado__in=[Reserva.Estado.PENDIENTE, Reserva.Estado.CONFIRMADA]).select_related(
        "usuario"
    )


def _notificar_pasajeros(viaje, asunto, mensaje, motivo):
    enviados = 0
    for reserva in _reservas_afectadas(viaje):
        enviados += notificaciones.enviar(
            reserva.usuario.email,
            f"{asunto} – {viaje}",
            "cambio_viaje",
            {"reserva": reserva, "viaje": viaje, "mensaje": mensaje, "motivo": motivo},
        )
    return enviados


def ajustar_hora_efectiva(viaje, hora, motivo, usuario):
    """Ajuste de la hora de zarpe por marea o condiciones del mar (RF-ADM-02 CA2/CA3)."""
    anterior = instantanea(viaje)
    viaje.hora_efectiva = hora
    viaje.actualizado_por = usuario
    with transaction.atomic():
        viaje.save(update_fields=["hora_efectiva", "actualizado_por", "actualizado_en"])
        CambioViaje.objects.create(
            viaje=viaje,
            tipo=CambioViaje.Tipo.HORA_EFECTIVA,
            motivo=motivo,
            datos_anteriores=anterior,
            datos_nuevos=instantanea(viaje),
            usuario=usuario,
        )
        registrar(usuario, "hora_efectiva", viaje.pk, hora=hora, motivo=motivo)
    _notificar_pasajeros(
        viaje,
        "Nueva hora de zarpe",
        f"La hora de salida de su viaje se ajustó a las {viaje.hora_vigente:%H:%M} "
        f"(hora programada: {viaje.hora_programada:%H:%M}).",
        motivo,
    )
    return viaje


def reprogramar_viaje(viaje, fecha, hora, motivo, usuario):
    """Cambio de fecha/hora: conserva datos anteriores, reemplaza tiquetes y notifica (CU-13)."""
    if not motivo.strip():
        raise ValueError("El motivo es obligatorio.")
    anterior = instantanea(viaje)
    with transaction.atomic():
        viaje.fecha = fecha
        viaje.hora_programada = hora
        viaje.hora_efectiva = None
        viaje.estado = Viaje.Estado.REPROGRAMADO
        viaje.actualizado_por = usuario
        viaje.full_clean()
        viaje.save()
        CambioViaje.objects.create(
            viaje=viaje,
            tipo=CambioViaje.Tipo.REPROGRAMACION,
            motivo=motivo,
            datos_anteriores=anterior,
            datos_nuevos=instantanea(viaje),
            usuario=usuario,
        )
        for reserva in _reservas_afectadas(viaje):
            if reserva.confirmada:
                reemplazar_tiquetes(reserva, f"Reprogramación del viaje: {motivo}")
                reserva.respuesta_cambio = Reserva.RespuestaCambio.PENDIENTE
                reserva.save(update_fields=["respuesta_cambio"])
        registrar(usuario, "viaje_reprogramado", viaje.pk, antes=anterior, motivo=motivo)
    _notificar_pasajeros(
        viaje,
        "Viaje reprogramado",
        f"Su viaje fue reprogramado para el {viaje.fecha:%d/%m/%Y} a las {viaje.hora_vigente:%H:%M}. "
        "Puede aceptar el nuevo horario, elegir otra salida o solicitar el reembolso desde 'Mis reservas'.",
        motivo,
    )
    return viaje


def cancelar_viaje(viaje, motivo, usuario):
    """Cancelación del zarpe por el transportador (CU-13, C. Co. art. 1590)."""
    if not motivo.strip():
        raise ValueError("El motivo es obligatorio.")
    anterior = instantanea(viaje)
    afectadas = list(_reservas_afectadas(viaje))
    with transaction.atomic():
        viaje.estado = Viaje.Estado.CANCELADO
        viaje.habilitado = False
        viaje.actualizado_por = usuario
        viaje.save(update_fields=["estado", "habilitado", "actualizado_por", "actualizado_en"])
        CambioViaje.objects.create(
            viaje=viaje,
            tipo=CambioViaje.Tipo.CANCELACION,
            motivo=motivo,
            datos_anteriores=anterior,
            datos_nuevos=instantanea(viaje),
            usuario=usuario,
        )
        for reserva in afectadas:
            if reserva.pendiente:
                cancelar_reserva(reserva.pk, f"Viaje cancelado por el transportador: {motivo}", usuario)
            else:
                anular_tiquetes(reserva, f"Viaje cancelado: {motivo}")
                reserva.respuesta_cambio = Reserva.RespuestaCambio.PENDIENTE
                reserva.save(update_fields=["respuesta_cambio"])
        registrar(usuario, "viaje_cancelado", viaje.pk, motivo=motivo, reservas=len(afectadas))
    for reserva in afectadas:
        notificaciones.enviar(
            reserva.usuario.email,
            f"Viaje cancelado – {viaje}",
            "cambio_viaje",
            {
                "reserva": reserva,
                "viaje": viaje,
                "motivo": motivo,
                "mensaje": "Su viaje fue cancelado por el transportador. "
                + (
                    "Puede elegir otra salida o solicitar la devolución desde 'Mis reservas'."
                    if reserva.confirmada
                    else "Su reserva pendiente de pago fue cancelada."
                ),
            },
        )
    return viaje


def finalizar_viajes_pasados():
    """Marca como finalizados los viajes cuya llegada estimada ya pasó."""
    total = 0
    for viaje in Viaje.objects.filter(
        estado__in=[Viaje.Estado.PROGRAMADO, Viaje.Estado.REPROGRAMADO], fecha__lt=timezone.localdate()
    ):
        viaje.estado = Viaje.Estado.FINALIZADO
        viaje.save(update_fields=["estado"])
        total += 1
    return total


def generar_salidas(desde, hasta, usuario, habilitar=False):
    """Programa las salidas de un rango de fechas a partir de los horarios base.

    Para cada fecha toma el grupo de propietarios asignado (calendario o
    rotación) y reparte sus lanchas activas: en ida en orden y en regreso en
    orden inverso. Devuelve (creados, avisos).
    """
    from datetime import timedelta

    from .models import HorarioBase, Lancha

    creados, avisos = [], []
    horarios = list(HorarioBase.objects.filter(activo=True, ruta__activa=True).select_related("ruta"))
    if not horarios:
        return creados, ["No hay horarios base activos configurados."]
    dia = desde
    while dia <= hasta:
        grupo = grupo_para(dia)
        lanchas = list(Lancha.objects.filter(grupo=grupo, estado=Lancha.Estado.ACTIVA).order_by("nombre")) if grupo else []
        if not lanchas:
            avisos.append(f"{dia:%d/%m/%Y}: el grupo {grupo or '(sin grupo)'} no tiene lanchas activas.")
            dia += timedelta(days=1)
            continue
        for sentido in (Viaje.Sentido.IDA, Viaje.Sentido.REGRESO):
            disponibles = lanchas if sentido == Viaje.Sentido.IDA else list(reversed(lanchas))
            for i, horario in enumerate(sorted((h for h in horarios if h.sentido == sentido), key=lambda h: h.hora)):
                if Viaje.objects.filter(
                    ruta=horario.ruta, fecha=dia, sentido=sentido, hora_programada=horario.hora
                ).exclude(estado=Viaje.Estado.CANCELADO).exists():
                    continue
                libres = [
                    l for l in disponibles
                    if not Viaje.objects.filter(lancha=l, fecha=dia, sentido=sentido).exclude(estado=Viaje.Estado.CANCELADO).exists()
                ]
                if not libres:
                    avisos.append(f"{dia:%d/%m/%Y} {horario}: no hay lancha disponible del grupo {grupo}.")
                    continue
                lancha = libres[0]
                viaje = Viaje(
                    ruta=horario.ruta,
                    sentido=sentido,
                    punto_embarque=horario.punto_embarque,
                    punto_desembarque=horario.punto_desembarque,
                    fecha=dia,
                    hora_programada=horario.hora,
                    tarifa=horario.ruta.tarifa_base,
                    lancha=lancha,
                    grupo=grupo,
                    cupos=lancha.capacidad_autorizada,
                    habilitado=habilitar,
                )
                viaje.full_clean()
                guardar_viaje(viaje, usuario, motivo="Programación automática desde horarios base")
                creados.append(viaje)
        dia += timedelta(days=1)
    return creados, avisos
