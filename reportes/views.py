import csv
from datetime import date, timedelta

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from abordaje.models import RegistroAbordaje
from core.models import RegistroAuditoria
from core.permisos import rol_requerido
from cuentas.models import Rol
from pagos.models import Pago
from reembolsos.models import SolicitudReembolso
from reservas.models import Reserva


def _rango(request):
    hoy = timezone.localdate()
    try:
        desde = date.fromisoformat(request.GET.get("desde", ""))
    except ValueError:
        desde = hoy.replace(day=1)
    try:
        hasta = date.fromisoformat(request.GET.get("hasta", ""))
    except ValueError:
        hasta = hoy
    if hasta < desde:
        desde, hasta = hasta, desde
    return desde, hasta


@rol_requerido(Rol.OPERADOR)
def reportes(request):
    """CU-18 / RF-REP-01: ventas, pagos y abordajes por periodo."""
    desde, hasta = _rango(request)
    pagos = Pago.objects.filter(creado_en__date__range=(desde, hasta))
    por_medio_estado = list(
        pagos.values("medio", "estado").annotate(n=Count("id"), total=Sum("valor")).order_by("medio", "estado")
    )
    etiquetas_medio = dict(Pago.Medio.choices)
    etiquetas_estado = dict(Pago.Estado.choices)
    for fila in por_medio_estado:
        fila["medio_txt"] = etiquetas_medio[fila["medio"]]
        fila["estado_txt"] = etiquetas_estado[fila["estado"]]
    aprobados = pagos.filter(estado=Pago.Estado.APROBADO)
    ventas = aprobados.aggregate(n=Count("id"), total=Sum("valor"))
    pasajes = Reserva.objects.filter(pagos__in=aprobados).distinct().aggregate(n=Sum("cantidad"))["n"] or 0
    abordajes = RegistroAbordaje.objects.filter(fecha__date__range=(desde, hasta))
    abordajes_res = {r["resultado"]: r["n"] for r in abordajes.values("resultado").annotate(n=Count("id"))}
    reembolsos = SolicitudReembolso.objects.filter(fecha_solicitud__date__range=(desde, hasta))
    reembolsos_res = list(reembolsos.values("estado").annotate(n=Count("id"), total=Sum("valor_autorizado")).order_by("estado"))
    etiquetas_sol = dict(SolicitudReembolso.Estado.choices)
    for fila in reembolsos_res:
        fila["estado_txt"] = etiquetas_sol[fila["estado"]]
    por_dia = list(
        aprobados.values("confirmado_en__date").annotate(n=Count("id"), total=Sum("valor")).order_by("confirmado_en__date")
    )

    if request.GET.get("formato") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="reporte-{desde}-{hasta}.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Periodo", str(desde), str(hasta)])
        w.writerow(["Medio", "Estado", "Cantidad", "Total COP"])
        for f in por_medio_estado:
            w.writerow([f["medio_txt"], f["estado_txt"], f["n"], f["total"] or 0])
        w.writerow([])
        w.writerow(["Abordajes aceptados", abordajes_res.get("ACEPTADO", 0)])
        w.writerow(["Intentos rechazados", abordajes_res.get("RECHAZADO", 0)])
        return resp

    sin_datos = not (por_medio_estado or abordajes_res or reembolsos_res)
    return render(
        request,
        "reportes/reportes.html",
        {
            "desde": desde,
            "hasta": hasta,
            "por_medio_estado": por_medio_estado,
            "ventas": ventas,
            "pasajes": pasajes,
            "abordajes": abordajes_res,
            "reembolsos": reembolsos_res,
            "por_dia": por_dia,
            "max_dia": max((d["total"] or 0 for d in por_dia), default=0),
            "sin_datos": sin_datos,
        },
    )


@rol_requerido(Rol.ADMIN)
def auditoria(request):
    """Consulta de la trazabilidad (RNF-09)."""
    registros = RegistroAuditoria.objects.select_related("usuario")
    accion = request.GET.get("accion")
    if accion:
        registros = registros.filter(accion=accion)
    acciones = RegistroAuditoria.objects.values_list("accion", flat=True).distinct().order_by("accion")
    return render(
        request,
        "reportes/auditoria.html",
        {"registros": registros[:300], "acciones": acciones, "accion": accion},
    )
