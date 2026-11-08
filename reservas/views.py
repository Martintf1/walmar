import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from cuentas.models import Rol
from operacion.models import Ruta, Viaje
from reembolsos.models import SolicitudReembolso

from . import pdf, servicios
from .forms import BuscarViajesForm, ConfirmarReservaForm, pasajeros_formset
from .models import Reserva, Tiquete

ROLES_VEN_TIQUETES = (Rol.VENTAS, Rol.ABORDAJE, Rol.OPERADOR)


def _ciudades():
    ciudades = []
    for ruta in Ruta.objects.filter(activa=True):
        for c in (ruta.ciudad_a, ruta.ciudad_b):
            if c not in ciudades:
                ciudades.append(c)
    return ciudades


def viajes_vendibles():
    ahora = timezone.localtime()
    return (
        Viaje.objects.filter(
            habilitado=True,
            estado__in=[Viaje.Estado.PROGRAMADO, Viaje.Estado.REPROGRAMADO],
            ruta__activa=True,
            lancha__estado="ACTIVA",
            fecha__gte=ahora.date(),
        )
        .select_related("ruta", "lancha", "punto_embarque", "punto_desembarque")
        .order_by("fecha", "hora_programada")
    )


def buscar_viajes(origen, destino, fecha):
    resultados = []
    for v in viajes_vendibles().filter(fecha=fecha):
        if v.origen == origen and v.destino == destino and v.vendible:
            resultados.append(v)
    resultados.sort(key=lambda v: v.hora_vigente)
    return resultados


def buscar(request):
    """CU-03 / RF-PAS-01: consulta por origen, destino y fecha."""
    servicios.expirar_reservas()
    ciudades = _ciudades()
    datos = request.GET if "fecha" in request.GET else None
    inicial = {"fecha": timezone.localdate()}
    if len(ciudades) >= 2:
        inicial.update(origen=ciudades[0], destino=ciudades[1])
    form = BuscarViajesForm(datos, ciudades=ciudades, initial=inicial)
    resultados = None
    if datos is not None and form.is_valid():
        d = form.cleaned_data
        resultados = buscar_viajes(d["origen"], d["destino"], d["fecha"])
    return render(request, "reservas/buscar.html", {"form": form, "resultados": resultados})


def api_viajes(request):
    """Consulta JSON (usada por la PWA para guardar las últimas consultas sin conexión)."""
    ciudades = _ciudades()
    form = BuscarViajesForm(request.GET, ciudades=ciudades)
    if not form.is_valid():
        return JsonResponse({"error": "Indique origen, destino y fecha válidos.", "detalle": form.errors}, status=400)
    d = form.cleaned_data
    viajes = buscar_viajes(d["origen"], d["destino"], d["fecha"])
    return JsonResponse(
        {
            "consultado_en": timezone.now().isoformat(),
            "viajes": [
                {
                    "id": v.pk,
                    "origen": v.origen,
                    "destino": v.destino,
                    "fecha": v.fecha.isoformat(),
                    "hora": v.hora_vigente.strftime("%H:%M"),
                    "hora_programada": v.hora_programada.strftime("%H:%M"),
                    "tarifa": int(v.tarifa),
                    "duracion": v.ruta.duracion_texto,
                    "cupos_disponibles": v.cupos_disponibles,
                    "lancha": v.lancha.nombre,
                    "embarque": str(v.punto_embarque),
                }
                for v in viajes
            ],
        }
    )


def _pasajeros_desde_formset(formset):
    return [f.cleaned_data for f in formset.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]


@login_required
def reservar(request, viaje_id):
    """CU-04 / RF-PAS-02: registro de pasajeros y bloqueo temporal de cupos."""
    viaje = get_object_or_404(Viaje.objects.select_related("ruta", "lancha", "punto_embarque"), pk=viaje_id)
    es_taquilla = request.user.tiene_rol(Rol.VENTAS)
    Formset = pasajeros_formset()
    if request.method == "POST":
        formset = Formset(request.POST, prefix="p")
        confirmar = ConfirmarReservaForm(request.POST)
        if formset.is_valid() and confirmar.is_valid():
            try:
                reserva = servicios.crear_reserva(
                    request.user,
                    viaje.pk,
                    _pasajeros_desde_formset(formset),
                    confirmar.cleaned_data["acepta_politica"],
                    canal=Reserva.Canal.TAQUILLA if es_taquilla else Reserva.Canal.EN_LINEA,
                    clave_idempotencia=confirmar.cleaned_data.get("clave_idempotencia") or None,
                )
            except servicios.ErrorReserva as e:
                messages.error(request, str(e))
            else:
                messages.success(request, f"Reserva {reserva.codigo} creada. Complete el pago antes del plazo indicado.")
                if es_taquilla:
                    return redirect("pagos:efectivo", codigo=reserva.codigo)
                return redirect("reservas:detalle", codigo=reserva.codigo)
    else:
        inicial = []
        if not es_taquilla:
            u = request.user
            inicial = [{"nombre": u.nombre, "tipo_documento": u.tipo_documento, "documento": u.identificacion, "telefono": u.telefono}]
        formset = Formset(prefix="p", initial=inicial)
        confirmar = ConfirmarReservaForm(initial={"clave_idempotencia": uuid.uuid4().hex})
    return render(
        request,
        "reservas/reservar.html",
        {"viaje": viaje, "formset": formset, "confirmar": confirmar, "problemas": viaje.problemas_para_venta()},
    )


@login_required
def mis_reservas(request):
    servicios.expirar_reservas()
    reservas = request.user.reservas.select_related("viaje__ruta").prefetch_related("pasajeros")
    return render(request, "reservas/mis_reservas.html", {"reservas": reservas})


def _reserva_visible(request, codigo):
    reserva = get_object_or_404(Reserva.objects.select_related("viaje__ruta", "viaje__lancha", "usuario"), codigo=codigo)
    if reserva.usuario_id != request.user.pk and not request.user.tiene_rol(*ROLES_VEN_TIQUETES):
        raise Http404
    return reserva


@login_required
def detalle(request, codigo):
    servicios.expirar_reservas()
    reserva = _reserva_visible(request, codigo)
    alternativas = []
    if reserva.respuesta_cambio == Reserva.RespuestaCambio.PENDIENTE:
        alternativas = [
            v
            for v in viajes_vendibles().filter(ruta=reserva.viaje.ruta, sentido=reserva.viaje.sentido).exclude(pk=reserva.viaje_id)[:20]
            if v.vendible and v.cupos_disponibles >= reserva.cantidad
        ]
    return render(
        request,
        "reservas/detalle.html",
        {
            "reserva": reserva,
            "pasajeros": reserva.pasajeros.prefetch_related("tiquetes"),
            "pagos": reserva.pagos.all(),
            "solicitudes": reserva.solicitudes.all(),
            "puede_solicitar": reserva.confirmada
            and not reserva.solicitudes.filter(estado__in=SolicitudReembolso.ESTADOS_ABIERTOS).exists(),
            "alternativas": alternativas,
        },
    )


@login_required
@require_POST
def cancelar(request, codigo):
    reserva = get_object_or_404(Reserva, codigo=codigo, usuario=request.user)
    if not reserva.pendiente:
        messages.error(request, "Solo puede cancelar directamente reservas pendientes de pago. Para compras pagadas radique una solicitud.")
    else:
        servicios.cancelar_reserva(reserva.pk, "Cancelada por el pasajero antes de pagar.", request.user)
        messages.success(request, "Reserva cancelada y cupos liberados.")
    return redirect("reservas:detalle", codigo=codigo)


@login_required
@require_POST
def responder_cambio(request, codigo):
    reserva = get_object_or_404(Reserva, codigo=codigo, usuario=request.user)
    accion = request.POST.get("accion")
    if reserva.respuesta_cambio != Reserva.RespuestaCambio.PENDIENTE:
        messages.error(request, "No hay un cambio pendiente de respuesta.")
    elif accion == "aceptar":
        if reserva.viaje.cancelado:
            messages.error(request, "El viaje fue cancelado: elija otra salida o solicite la devolución.")
        else:
            reserva.respuesta_cambio = Reserva.RespuestaCambio.ACEPTA
            reserva.save(update_fields=["respuesta_cambio"])
            registrar(request.user, "cambio_aceptado", reserva.codigo)
            messages.success(request, "Registramos que acepta el nuevo horario.")
    elif accion == "trasladar":
        try:
            servicios.trasladar_reserva(reserva.pk, int(request.POST.get("viaje", 0)), request.user)
        except (servicios.ErrorReserva, Viaje.DoesNotExist, ValueError) as e:
            messages.error(request, str(e) or "Salida no válida.")
        else:
            messages.success(request, "Su reserva fue trasladada a la nueva salida y se emitieron nuevos tiquetes.")
    return redirect("reservas:detalle", codigo=codigo)


def _tiquete_visible(request, codigo):
    tiquete = get_object_or_404(
        Tiquete.objects.select_related("pasajero__reserva__viaje__ruta", "pasajero__reserva__viaje__lancha"), codigo=codigo
    )
    if tiquete.reserva.usuario_id != request.user.pk and not request.user.tiene_rol(*ROLES_VEN_TIQUETES):
        raise Http404
    return tiquete


@login_required
def tiquete(request, codigo):
    """CU-08 / IU_tiquete."""
    t = _tiquete_visible(request, codigo)
    return render(request, "reservas/tiquete.html", {"t": t, "qr": pdf.qr_svg(t.codigo)})


@login_required
def tiquete_pdf(request, codigo):
    t = _tiquete_visible(request, codigo)
    if t.estado == Tiquete.Estado.ANULADO or not t.reserva.confirmada:
        messages.error(request, "El tiquete no está vigente.")
        return redirect("reservas:detalle", codigo=t.reserva.codigo)
    registrar(request.user, "tiquete_descargado", t.codigo)
    resp = HttpResponse(pdf.tiquetes_pdf([t]), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="tiquete-{t.codigo}.pdf"'
    return resp


@login_required
def tiquetes_reserva_pdf(request, codigo):
    reserva = _reserva_visible(request, codigo)
    if not reserva.confirmada:
        messages.error(request, "Los tiquetes se emiten cuando el pago está confirmado.")
        return redirect("reservas:detalle", codigo=codigo)
    tiquetes = Tiquete.objects.filter(pasajero__reserva=reserva).exclude(estado=Tiquete.Estado.ANULADO).select_related(
        "pasajero__reserva__viaje__ruta", "pasajero__reserva__viaje__lancha"
    )
    resp = HttpResponse(pdf.tiquetes_pdf(tiquetes), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="tiquetes-{reserva.codigo}.pdf"'
    return resp


@login_required
def api_mis_tiquetes(request):
    """Tiquetes vigentes del pasajero para consulta sin conexión (RF-PWA-01)."""
    tiquetes = Tiquete.objects.filter(
        pasajero__reserva__usuario=request.user, estado__in=[Tiquete.Estado.VALIDO, Tiquete.Estado.UTILIZADO]
    ).select_related("pasajero__reserva__viaje__ruta")
    return JsonResponse(
        {
            "consultado_en": timezone.now().isoformat(),
            "tiquetes": [
                {
                    "codigo": t.codigo,
                    "pasajero": t.pasajero.nombre,
                    "reserva": t.reserva.codigo,
                    "viaje": str(t.viaje),
                    "estado": t.get_estado_display(),
                }
                for t in tiquetes
            ],
        }
    )


@login_required
@require_POST
def api_sincronizar_reserva(request):
    """Envío diferido de una reserva iniciada sin conexión (CU-19).

    La reserva solo existe cuando el servidor la acepta: se validan cupos y se
    usa la clave de idempotencia para no duplicar.
    """
    try:
        datos = json.loads(request.body)
        Formset = pasajeros_formset()
        post = {"p-TOTAL_FORMS": len(datos["pasajeros"]), "p-INITIAL_FORMS": 0}
        for i, p in enumerate(datos["pasajeros"]):
            for k in ("nombre", "tipo_documento", "documento", "telefono"):
                post[f"p-{i}-{k}"] = p.get(k, "")
        formset = Formset(post, prefix="p")
        if not formset.is_valid():
            return JsonResponse({"ok": False, "error": "Datos de pasajeros incompletos."}, status=400)
        reserva = servicios.crear_reserva(
            request.user,
            int(datos["viaje"]),
            _pasajeros_desde_formset(formset),
            bool(datos.get("acepta_politica")),
            clave_idempotencia=str(datos["clave"])[:64],
        )
    except (KeyError, ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "Solicitud no válida."}, status=400)
    except servicios.ErrorReserva as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=409)
    return JsonResponse({"ok": True, "reserva": reserva.codigo, "estado": reserva.get_estado_display()})
