import csv
import json
from datetime import timedelta

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from core.permisos import rol_requerido
from cuentas.models import Rol
from operacion.models import Viaje

from . import servicios
from .models import RegistroAbordaje

abordaje = rol_requerido(Rol.ABORDAJE)
manifiesto_roles = rol_requerido(Rol.ABORDAJE, Rol.OPERADOR)


def _viajes_cercanos():
    hoy = timezone.localdate()
    return (
        Viaje.objects.filter(fecha__range=(hoy - timedelta(days=1), hoy + timedelta(days=2)))
        .exclude(estado=Viaje.Estado.FINALIZADO)
        .select_related("ruta", "lancha")
        .order_by("fecha", "hora_programada")
    )


@abordaje
def inicio(request):
    return render(request, "abordaje/inicio.html", {"viajes": _viajes_cercanos()})


@abordaje
def validar(request, viaje_id):
    """CU-09 / IU_validar_tiquete (y CU-10 sin conexión desde la misma pantalla)."""
    viaje = get_object_or_404(Viaje.objects.select_related("ruta", "lancha"), pk=viaje_id)
    registro = None
    if request.method == "POST":
        codigo = request.POST.get("codigo", "")
        if codigo.strip():
            registro = servicios.validar_tiquete(codigo, viaje, request.user, clave_idempotencia=request.POST.get("clave") or None)
        else:
            messages.error(request, "Ingrese o escanee el código del tiquete.")
    recientes = viaje.abordajes.select_related("tiquete__pasajero", "usuario")[:15]
    abordados = viaje.abordajes.filter(resultado=RegistroAbordaje.Resultado.ACEPTADO).count()
    return render(
        request,
        "abordaje/validar.html",
        {"viaje": viaje, "registro": registro, "recientes": recientes, "abordados": abordados},
    )


@abordaje
@require_POST
def api_validar(request, viaje_id):
    viaje = get_object_or_404(Viaje, pk=viaje_id)
    try:
        datos = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "JSON inválido"}, status=400)
    registro = servicios.validar_tiquete(datos.get("codigo", ""), viaje, request.user, clave_idempotencia=datos.get("clave"))
    return JsonResponse(_registro_json(registro))


def _registro_json(registro, clave=None):
    pasajero = registro.tiquete.pasajero if registro.tiquete else None
    return {
        "clave": clave or registro.clave_idempotencia,
        "codigo": registro.codigo_leido,
        "resultado": registro.resultado,
        "motivo": registro.motivo,
        "pasajero": pasajero.nombre if pasajero else "",
        "fecha": registro.fecha.isoformat(),
    }


@abordaje
@require_POST
def api_sincronizar(request):
    """CU-19: recibe los abordajes registrados sin conexión. Idempotente por clave."""
    try:
        operaciones = json.loads(request.body).get("operaciones", [])
    except (ValueError, AttributeError):
        return JsonResponse({"error": "JSON inválido"}, status=400)
    resultados = []
    for op in operaciones[:500]:
        clave = str(op.get("clave", ""))[:64]
        try:
            viaje = Viaje.objects.get(pk=int(op.get("viaje")))
        except (Viaje.DoesNotExist, TypeError, ValueError):
            resultados.append({"clave": clave, "resultado": "ERROR", "motivo": "Viaje no encontrado."})
            continue
        if not clave:
            resultados.append({"clave": clave, "resultado": "ERROR", "motivo": "Falta la clave de idempotencia."})
            continue
        fecha = parse_datetime(op.get("fecha") or "") or timezone.now()
        if timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha)
        fecha = min(fecha, timezone.now())
        registro = servicios.validar_tiquete(
            op.get("codigo", ""), viaje, request.user, sin_conexion=True, clave_idempotencia=clave, fecha=fecha
        )
        resultados.append(_registro_json(registro, clave))
    return JsonResponse({"resultados": resultados, "sincronizado_en": timezone.now().isoformat()})


@manifiesto_roles
def manifiesto(request, viaje_id):
    """CU-15 / RF-IN-04: manifiesto con estado de pago y abordaje."""
    viaje = get_object_or_404(Viaje.objects.select_related("ruta", "lancha", "grupo", "punto_embarque"), pk=viaje_id)
    filas = servicios.manifiesto(viaje)
    if request.GET.get("formato") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="manifiesto-{viaje.pk}-{viaje.fecha}.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Viaje", str(viaje)])
        w.writerow(["Lancha", f"{viaje.lancha.nombre} {viaje.lancha.matricula}", "Capacidad", viaje.lancha.capacidad_autorizada])
        w.writerow([])
        w.writerow(["#", "Nombre", "Tipo doc.", "Documento", "Teléfono", "Reserva", "Tiquete", "Estado pago", "Abordó"])
        for i, f in enumerate(filas, 1):
            p = f["pasajero"]
            w.writerow(
                [i, p.nombre, p.tipo_documento, p.documento, p.telefono, f["reserva"].codigo,
                 f["tiquete"].codigo if f["tiquete"] else "", f["estado_pago"], "Sí" if f["abordo"] else "No"]
            )
        return resp
    return render(
        request,
        "abordaje/manifiesto.html",
        {
            "viaje": viaje,
            "filas": filas,
            "total_pagados": sum(1 for f in filas if f["reserva"].confirmada),
            "total_abordo": sum(1 for f in filas if f["abordo"]),
        },
    )


@abordaje
def manifiesto_reducido(request, viaje_id):
    """Manifiesto reducido descargable al dispositivo para validar sin conexión."""
    viaje = get_object_or_404(Viaje.objects.select_related("ruta", "lancha"), pk=viaje_id)
    return JsonResponse(servicios.manifiesto_reducido(viaje))


@abordaje
def sin_conexion(request):
    """IU_validar_sin_conexion: funciona con el manifiesto guardado en el dispositivo."""
    return render(request, "abordaje/sin_conexion.html")
