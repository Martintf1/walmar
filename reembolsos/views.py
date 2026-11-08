from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from core.permisos import rol_requerido
from cuentas.models import Rol
from reservas.models import Reserva

from . import servicios
from .forms import ResolverForm, SolicitudForm
from .models import SolicitudReembolso


@login_required
def solicitar(request, codigo):
    """IU_solicitud_reembolso."""
    reserva = get_object_or_404(Reserva, codigo=codigo, usuario=request.user)
    inicial = {}
    if reserva.viaje.cancelado:
        inicial["tipo"] = SolicitudReembolso.Tipo.CANCELACION_TRANSPORTADOR
    elif reserva.respuesta_cambio == Reserva.RespuestaCambio.PENDIENTE:
        inicial["tipo"] = SolicitudReembolso.Tipo.CAMBIO_HORARIO
    form = SolicitudForm(request.POST or None, request.FILES or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        try:
            solicitud = servicios.crear_solicitud(
                reserva, request.user, form.cleaned_data["tipo"], form.cleaned_data["motivo"], form.cleaned_data.get("soporte")
            )
        except servicios.ErrorSolicitud as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Solicitud #{solicitud.pk} radicada. Le notificaremos cada cambio de estado.")
            return redirect("reembolsos:detalle", pk=solicitud.pk)
    return render(request, "reembolsos/solicitar.html", {"form": form, "reserva": reserva})


@login_required
def mis_solicitudes(request):
    return render(
        request,
        "reembolsos/mis_solicitudes.html",
        {"solicitudes": SolicitudReembolso.objects.filter(solicitante=request.user).select_related("reserva")},
    )


def _visible(request, pk):
    solicitud = get_object_or_404(SolicitudReembolso.objects.select_related("reserva__viaje", "solicitante"), pk=pk)
    if solicitud.solicitante_id != request.user.pk and not request.user.tiene_rol(Rol.OPERADOR):
        raise Http404
    return solicitud


@login_required
def detalle(request, pk):
    solicitud = _visible(request, pk)
    form = None
    if request.user.tiene_rol(Rol.OPERADOR) and servicios.TRANSICIONES[solicitud.estado]:
        form = ResolverForm(
            request.POST or None,
            initial={"valor_autorizado": solicitud.valor_autorizado},
        )
        form.fields["estado"].choices = [
            (e.value, e.label) for e in servicios.TRANSICIONES[SolicitudReembolso.Estado(solicitud.estado)]
        ]
        if request.method == "POST" and form.is_valid():
            d = form.cleaned_data
            try:
                servicios.cambiar_estado(solicitud, d["estado"], request.user, d["justificacion"], d["valor_autorizado"], d["referencia"])
            except servicios.ErrorSolicitud as e:
                messages.error(request, str(e))
            else:
                messages.success(request, "Estado actualizado y pasajero notificado.")
                return redirect("reembolsos:detalle", pk=pk)
    return render(
        request,
        "reembolsos/detalle.html",
        {"s": solicitud, "form": form, "historial": solicitud.historial.select_related("usuario")},
    )


@login_required
def soporte(request, pk):
    solicitud = _visible(request, pk)
    if not solicitud.soporte:
        raise Http404
    return FileResponse(solicitud.soporte.open("rb"), as_attachment=True)


@rol_requerido(Rol.OPERADOR)
def bandeja(request):
    estado = request.GET.get("estado", "abiertas")
    qs = SolicitudReembolso.objects.select_related("reserva__viaje", "solicitante")
    if estado == "abiertas":
        qs = qs.filter(estado__in=SolicitudReembolso.ESTADOS_ABIERTOS)
    elif estado:
        qs = qs.filter(estado=estado)
    return render(
        request,
        "reembolsos/bandeja.html",
        {"solicitudes": qs, "estado": estado, "estados": SolicitudReembolso.Estado.choices},
    )
