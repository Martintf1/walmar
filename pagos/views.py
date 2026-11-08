import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.permisos import rol_requerido
from cuentas.models import Rol
from reservas import pdf
from reservas.models import Reserva
from reservas.views import viajes_vendibles

from . import pasarela, servicios
from .models import Pago


@login_required
@require_POST
def pagar_en_linea(request, codigo):
    """CU-06: crea el pago pendiente y redirige a la pasarela."""
    reserva = get_object_or_404(Reserva, codigo=codigo, usuario=request.user)
    try:
        pago = servicios.iniciar_pago_en_linea(reserva, request.user)
    except servicios.ErrorPago as e:
        messages.error(request, str(e))
        return redirect("reservas:detalle", codigo=codigo)
    return redirect(pasarela.obtener().iniciar_pago(pago, request))


@login_required
def pasarela_simulada(request, referencia):
    """Simula la página externa de la pasarela (solo mientras no se defina el proveedor)."""
    pago = get_object_or_404(Pago, referencia=referencia, medio=Pago.Medio.EN_LINEA, reserva__usuario=request.user)
    if request.method == "POST":
        resultado = request.POST.get("resultado")
        if resultado not in ("APROBADO", "RECHAZADO", "PENDIENTE"):
            raise Http404
        datos = {
            "referencia": pago.referencia,
            "estado": resultado,
            "transaccion": f"SIM-{timezone.now():%Y%m%d%H%M%S}-{pago.pk}",
            "valor": str(int(pago.valor)),
        }
        # Mismo camino que la notificación servidor-a-servidor de una pasarela real.
        if pasarela.verificar_firma(datos, pasarela.firmar(datos)):
            try:
                servicios.procesar_notificacion(datos)
            except servicios.ErrorPago as e:
                messages.error(request, str(e))
        return redirect("pagos:estado", referencia=pago.referencia)
    return render(request, "pagos/pasarela_simulada.html", {"pago": pago})


@csrf_exempt
@require_POST
def notificacion(request):
    """Webhook de la pasarela: notificación firmada del resultado (HMAC-SHA256)."""
    try:
        datos = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "JSON inválido"}, status=400)
    firma = request.headers.get("X-Walmar-Firma", "")
    if not pasarela.verificar_firma(datos, firma):
        registrar(None, "notificacion_pasarela", datos.get("referencia", "?"), resultado="FIRMA_INVALIDA")
        return JsonResponse({"error": "Firma inválida"}, status=403)
    try:
        pago = servicios.procesar_notificacion(datos)
    except servicios.ErrorPago as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"ok": True, "estado": pago.estado})


@login_required
def estado(request, referencia):
    """IU_estado_pago: aprobado, rechazado o pendiente."""
    pago = get_object_or_404(Pago.objects.select_related("reserva"), referencia=referencia)
    if pago.reserva.usuario_id != request.user.pk and not request.user.tiene_rol(Rol.VENTAS, Rol.OPERADOR):
        raise Http404
    return render(request, "pagos/estado.html", {"pago": pago, "reserva": pago.reserva})


def _comprobante_visible(request, referencia):
    pago = get_object_or_404(Pago.objects.select_related("reserva__viaje__ruta", "registrado_por"), referencia=referencia)
    if pago.reserva.usuario_id != request.user.pk and not request.user.tiene_rol(Rol.VENTAS, Rol.OPERADOR):
        raise Http404
    if pago.estado not in (Pago.Estado.APROBADO, Pago.Estado.REEMBOLSADO):
        raise Http404
    return pago


@login_required
def comprobante(request, referencia):
    """IU_comprobante: comprobante imprimible."""
    return render(request, "pagos/comprobante.html", {"pago": _comprobante_visible(request, referencia)})


@login_required
def comprobante_pdf(request, referencia):
    pago = _comprobante_visible(request, referencia)
    resp = HttpResponse(pdf.comprobante_pdf(pago), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="comprobante-{pago.referencia}.pdf"'
    return resp


# ------------------------------------------------------------ taquilla (personal de atención y venta)
@rol_requerido(Rol.VENTAS)
def taquilla(request):
    codigo = (request.GET.get("codigo") or "").strip().upper()
    if codigo:
        if Reserva.objects.filter(codigo=codigo).exists():
            return redirect("pagos:efectivo", codigo=codigo)
        messages.error(request, f"No se encontró la reserva {codigo}.")
    hoy = timezone.localdate()
    return render(
        request,
        "pagos/taquilla.html",
        {
            "viajes": [v for v in viajes_vendibles().filter(fecha__lte=hoy + timedelta(days=3)) if v.vendible][:30],
            "pagos_hoy": Pago.objects.filter(registrado_por=request.user, confirmado_en__date=hoy).select_related("reserva"),
            "codigo": codigo,
        },
    )


@rol_requerido(Rol.VENTAS)
def efectivo(request, codigo):
    """CU-07 / RF-PAG-01: registro del pago en efectivo."""
    reserva = get_object_or_404(Reserva.objects.select_related("viaje__ruta", "usuario"), codigo=codigo.upper())
    if request.method == "POST":
        try:
            valor = Decimal(request.POST.get("valor_recibido", "").replace(".", "").replace(",", "").replace("$", "").strip())
        except InvalidOperation:
            messages.error(request, "Ingrese un valor numérico.")
        else:
            try:
                pago = servicios.registrar_pago_efectivo(reserva, valor, request.user)
            except servicios.ErrorPago as e:
                messages.error(request, str(e))
            else:
                messages.success(request, "Pago registrado. Reserva confirmada y tiquetes emitidos.")
                return redirect("pagos:comprobante", referencia=pago.referencia)
        reserva.refresh_from_db()
    return render(request, "pagos/efectivo.html", {"reserva": reserva, "pasajeros": reserva.pasajeros.all()})
