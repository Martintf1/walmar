import calendar
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.permisos import rol_requerido
from cuentas.models import Rol
from pagos.models import Pago
from reembolsos.models import SolicitudReembolso
from reservas.models import Reserva

from . import servicios
from .forms import (
    AsignacionGrupoForm,
    CancelarViajeForm,
    GenerarSalidasForm,
    GrupoForm,
    HoraEfectivaForm,
    HorarioBaseForm,
    LanchaForm,
    PuntoEmbarqueForm,
    ReprogramarForm,
    RutaForm,
    ViajeForm,
)
from .models import AsignacionGrupo, GrupoPropietarios, HorarioBase, Lancha, PuntoEmbarque, Ruta, Viaje, grupo_para

operador = rol_requerido(Rol.OPERADOR)
administrador = rol_requerido(Rol.ADMIN)


def _fecha(valor, defecto):
    try:
        return date.fromisoformat(valor) if valor else defecto
    except ValueError:
        return defecto


@operador
def panel(request):
    hoy = timezone.localdate()
    viajes_hoy = Viaje.objects.filter(fecha=hoy).select_related("ruta", "lancha", "grupo")
    ventas_hoy = Pago.objects.filter(estado=Pago.Estado.APROBADO, confirmado_en__date=hoy).aggregate(
        total=Sum("valor"), n=Count("id")
    )
    contexto = {
        "hoy": hoy,
        "grupo_hoy": grupo_para(hoy),
        "viajes_hoy": viajes_hoy,
        "ventas_hoy": ventas_hoy,
        "reservas_pendientes": Reserva.objects.filter(estado=Reserva.Estado.PENDIENTE).count(),
        "solicitudes_abiertas": SolicitudReembolso.objects.filter(estado__in=SolicitudReembolso.ESTADOS_ABIERTOS).count(),
        "proximos": Viaje.objects.filter(fecha__gt=hoy, fecha__lte=hoy + timedelta(days=7))
        .exclude(estado=Viaje.Estado.CANCELADO)
        .select_related("ruta", "lancha")[:20],
        "config_incompleta": not (
            Ruta.objects.filter(activa=True).exists()
            and PuntoEmbarque.objects.exists()
            and Lancha.objects.filter(estado=Lancha.Estado.ACTIVA).exists()
        ),
    }
    return render(request, "operacion/panel.html", contexto)


# ------------------------------------------------------------------ viajes
@operador
def viajes_lista(request):
    hoy = timezone.localdate()
    desde = _fecha(request.GET.get("desde"), hoy)
    hasta = _fecha(request.GET.get("hasta"), desde + timedelta(days=14))
    viajes = (
        Viaje.objects.filter(fecha__range=(desde, hasta))
        .select_related("ruta", "lancha", "grupo")
        .order_by("fecha", "hora_programada")
    )
    estado = request.GET.get("estado")
    if estado:
        viajes = viajes.filter(estado=estado)
    return render(
        request,
        "operacion/viajes_lista.html",
        {"viajes": viajes, "desde": desde, "hasta": hasta, "estado": estado, "estados": Viaje.Estado.choices},
    )


@operador
def viaje_form(request, pk=None):
    viaje = get_object_or_404(Viaje, pk=pk) if pk else None
    inicial = {}
    if viaje is None:
        ruta = Ruta.objects.filter(activa=True).first()
        inicial = {"ruta": ruta, "tarifa": ruta.tarifa_base if ruta else None, "fecha": request.GET.get("fecha")}
    form = ViajeForm(request.POST or None, instance=viaje, initial=inicial)
    if request.method == "POST" and form.is_valid():
        try:
            nuevo = form.save(commit=False)
            nuevo.full_clean()
            servicios.guardar_viaje(nuevo, request.user, form.cleaned_data.get("motivo", ""))
        except ValidationError as e:
            for campo, errores in e.message_dict.items():
                form.add_error(campo if campo in form.fields else None, errores)
        else:
            messages.success(request, "Viaje guardado.")
            return redirect("operacion:viaje_detalle", pk=nuevo.pk)
    return render(request, "operacion/viaje_form.html", {"form": form, "viaje": viaje})


@operador
def viaje_detalle(request, pk):
    viaje = get_object_or_404(Viaje.objects.select_related("ruta", "lancha", "grupo"), pk=pk)
    reservas = viaje.reservas.select_related("usuario").order_by("-creada_en")
    return render(
        request,
        "operacion/viaje_detalle.html",
        {
            "viaje": viaje,
            "reservas": reservas,
            "cambios": viaje.cambios.select_related("usuario"),
            "form_hora": HoraEfectivaForm(initial={"hora_efectiva": viaje.hora_vigente}),
            "form_reprogramar": ReprogramarForm(initial={"fecha": viaje.fecha, "hora": viaje.hora_programada}),
            "form_cancelar": CancelarViajeForm(),
        },
    )


@operador
@require_POST
def viaje_habilitar(request, pk):
    viaje = get_object_or_404(Viaje, pk=pk)
    if viaje.cancelado:
        messages.error(request, "Un viaje cancelado no puede habilitarse.")
        return redirect("operacion:viaje_detalle", pk=pk)
    viaje.habilitado = not viaje.habilitado
    if viaje.habilitado:
        problemas = [p for p in viaje.problemas_para_venta() if "habilitado" not in p]
        if problemas:
            messages.error(request, "No se puede habilitar la venta: " + " ".join(problemas))
            return redirect("operacion:viaje_detalle", pk=pk)
    servicios.guardar_viaje(viaje, request.user, "Habilitado para la venta" if viaje.habilitado else "Venta suspendida")
    messages.success(request, "Venta habilitada." if viaje.habilitado else "Venta suspendida.")
    return redirect("operacion:viaje_detalle", pk=pk)


@operador
@require_POST
def viaje_hora_efectiva(request, pk):
    viaje = get_object_or_404(Viaje, pk=pk)
    form = HoraEfectivaForm(request.POST)
    if form.is_valid() and not viaje.cancelado:
        servicios.ajustar_hora_efectiva(viaje, form.cleaned_data["hora_efectiva"], form.cleaned_data["motivo"], request.user)
        messages.success(request, "Hora efectiva actualizada y pasajeros notificados.")
    else:
        messages.error(request, "Revise la hora y el motivo.")
    return redirect("operacion:viaje_detalle", pk=pk)


@operador
@require_POST
def viaje_reprogramar(request, pk):
    viaje = get_object_or_404(Viaje, pk=pk)
    form = ReprogramarForm(request.POST)
    if form.is_valid() and not viaje.cancelado:
        try:
            servicios.reprogramar_viaje(viaje, form.cleaned_data["fecha"], form.cleaned_data["hora"], form.cleaned_data["motivo"], request.user)
        except (ValidationError, ValueError) as e:
            messages.error(request, " ".join(getattr(e, "messages", [str(e)])))
        else:
            messages.success(request, "Viaje reprogramado. Se reemplazaron los tiquetes y se notificó a los pasajeros.")
    else:
        messages.error(request, "Indique la nueva fecha, hora y el motivo.")
    return redirect("operacion:viaje_detalle", pk=pk)


@operador
@require_POST
def viaje_cancelar(request, pk):
    viaje = get_object_or_404(Viaje, pk=pk)
    form = CancelarViajeForm(request.POST)
    if form.is_valid() and not viaje.cancelado:
        servicios.cancelar_viaje(viaje, form.cleaned_data["motivo"], request.user)
        messages.success(request, "Viaje cancelado. Se anularon los tiquetes y se notificó a los pasajeros.")
    else:
        messages.error(request, "Indique el motivo y confirme la cancelación.")
    return redirect("operacion:viaje_detalle", pk=pk)


# ------------------------------------------------------------------ programación
@operador
def programacion(request):
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get("anio", hoy.year))
        mes = int(request.GET.get("mes", hoy.month))
        primero = date(anio, mes, 1)
    except ValueError:
        primero = hoy.replace(day=1)
    ultimo = primero.replace(day=calendar.monthrange(primero.year, primero.month)[1])
    viajes = Viaje.objects.filter(fecha__range=(primero, ultimo)).select_related("lancha").order_by("hora_programada")
    por_dia = {}
    for v in viajes:
        por_dia.setdefault(v.fecha, []).append(v)
    semanas = []
    for semana in calendar.Calendar(firstweekday=0).monthdatescalendar(primero.year, primero.month):
        semanas.append(
            [
                {
                    "fecha": d,
                    "del_mes": d.month == primero.month,
                    "grupo": grupo_para(d),
                    "explicito": AsignacionGrupo.objects.filter(fecha=d).exists(),
                    "viajes": por_dia.get(d, []),
                }
                for d in semana
            ]
        )
    anterior = (primero - timedelta(days=1)).replace(day=1)
    siguiente = ultimo + timedelta(days=1)
    form_generar = GenerarSalidasForm(initial={"desde": max(primero, hoy), "hasta": ultimo})
    return render(
        request,
        "operacion/programacion.html",
        {
            "primero": primero,
            "semanas": semanas,
            "anterior": anterior,
            "siguiente": siguiente,
            "form_asignar": AsignacionGrupoForm(),
            "form_generar": form_generar,
            "grupos": GrupoPropietarios.objects.prefetch_related("lanchas"),
            "dias": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"],
        },
    )


@operador
@require_POST
def asignar_grupo(request):
    form = AsignacionGrupoForm(request.POST)
    fecha = request.POST.get("fecha")
    existente = AsignacionGrupo.objects.filter(fecha=fecha).first() if fecha else None
    if existente:
        form = AsignacionGrupoForm(request.POST, instance=existente)
    if form.is_valid():
        asignacion = form.save()
        registrar(request.user, "grupo_asignado", asignacion.fecha, grupo=asignacion.grupo.nombre)
        messages.success(request, f"Grupo {asignacion.grupo} asignado al {asignacion.fecha:%d/%m/%Y}.")
        f = asignacion.fecha
        return redirect(f"{reverse('operacion:programacion')}?anio={f.year}&mes={f.month}")
    messages.error(request, "Revise la fecha y el grupo.")
    return redirect("operacion:programacion")


@operador
@require_POST
def generar(request):
    form = GenerarSalidasForm(request.POST)
    if form.is_valid():
        try:
            creados, avisos = servicios.generar_salidas(
                form.cleaned_data["desde"], form.cleaned_data["hasta"], request.user, form.cleaned_data["habilitar"]
            )
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            messages.success(request, f"Se programaron {len(creados)} salidas.")
            for aviso in avisos[:10]:
                messages.warning(request, aviso)
    else:
        for err in form.errors.values():
            messages.error(request, " ".join(err))
    return redirect("operacion:programacion")


# ------------------------------------------------------------------ configuración (CU-16)
CONFIG = {
    "rutas": {"modelo": Ruta, "form": RutaForm, "titulo": "Rutas", "singular": "ruta",
              "columnas": [("nombre", "Nombre"), ("ciudad_a", "Ciudad A"), ("ciudad_b", "Ciudad B"), ("duracion_texto", "Duración"), ("tarifa_base", "Tarifa base"), ("activa", "Activa")]},
    "puntos": {"modelo": PuntoEmbarque, "form": PuntoEmbarqueForm, "titulo": "Puntos de embarque y desembarque", "singular": "punto",
               "columnas": [("nombre", "Nombre"), ("ciudad", "Ciudad"), ("direccion", "Dirección"), ("get_tipo_display", "Tipo"), ("activo", "Activo")]},
    "grupos": {"modelo": GrupoPropietarios, "form": GrupoForm, "titulo": "Grupos de propietarios", "singular": "grupo",
               "columnas": [("orden", "Orden"), ("nombre", "Nombre"), ("responsable", "Responsable"), ("telefono", "Teléfono"), ("activo", "Activo")]},
    "lanchas": {"modelo": Lancha, "form": LanchaForm, "titulo": "Lanchas", "singular": "lancha",
                "columnas": [("nombre", "Nombre"), ("matricula", "Matrícula"), ("capacidad_autorizada", "Capacidad"), ("grupo", "Grupo"), ("get_estado_display", "Estado")]},
    "horarios": {"modelo": HorarioBase, "form": HorarioBaseForm, "titulo": "Horarios base", "singular": "horario",
                 "columnas": [("get_sentido_display", "Sentido"), ("hora", "Hora"), ("punto_embarque", "Embarque"), ("punto_desembarque", "Desembarque"), ("activo", "Activo")]},
}


def _config(tipo):
    if tipo not in CONFIG:
        raise Http404
    return CONFIG[tipo]


@administrador
def configuracion(request):
    resumen = [(clave, c["titulo"], c["modelo"].objects.count()) for clave, c in CONFIG.items()]
    return render(request, "operacion/configuracion.html", {"resumen": resumen})


@administrador
def config_lista(request, tipo):
    c = _config(tipo)
    objetos = c["modelo"].objects.all()
    filas = []
    for obj in objetos:
        valores = []
        for attr, _ in c["columnas"]:
            valor = getattr(obj, attr)
            valores.append(valor() if callable(valor) else valor)
        filas.append((obj, valores))
    return render(request, "operacion/config_lista.html", {"c": c, "tipo": tipo, "filas": filas})


@administrador
def config_form(request, tipo, pk=None):
    c = _config(tipo)
    obj = get_object_or_404(c["modelo"], pk=pk) if pk else None
    form = c["form"](request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        guardado = form.save()
        registrar(request.user, f"config_{tipo}", guardado, nuevo=obj is None)
        messages.success(request, f"{c['singular'].capitalize()} guardado(a).")
        return redirect("operacion:config_lista", tipo=tipo)
    return render(request, "operacion/config_form.html", {"c": c, "tipo": tipo, "form": form, "obj": obj})
