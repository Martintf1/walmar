from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from core import notificaciones
from core.auditoria import registrar
from core.permisos import rol_requerido

from .forms import CrearPersonalForm, LoginForm, NuevaContrasenaForm, PerfilForm, RegistroForm, SolicitarCodigoForm
from .models import CodigoRecuperacion, Rol, Usuario

MENSAJE_LOGIN_FALLIDO = "Correo o contraseña incorrectos."


def _destino_por_rol(usuario):
    if usuario.tiene_rol(Rol.OPERADOR):
        return reverse("operacion:panel")
    if usuario.tiene_rol(Rol.VENTAS):
        return reverse("pagos:taquilla")
    if usuario.tiene_rol(Rol.ABORDAJE):
        return reverse("abordaje:inicio")
    return reverse("reservas:buscar")


def registro(request):
    """CU-01 / RF-COM-01: registro con acceso inmediato y correo informativo."""
    if request.user.is_authenticated:
        return redirect("core:inicio")
    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save(commit=False)
        usuario.email = form.cleaned_data["email"]
        usuario.rol = Rol.PASAJERO
        usuario.acepto_terminos_en = timezone.now()
        usuario.set_password(form.cleaned_data["password1"])
        usuario.save()
        registrar(usuario, "cuenta_creada", usuario.email)
        notificaciones.enviar(usuario.email, "Su cuenta fue creada", "cuenta_creada", {"usuario": usuario})
        login(request, usuario, backend="cuentas.backends.EmailBackend")
        messages.success(request, f"¡Bienvenido(a), {usuario.get_short_name()}! Su cuenta fue creada.")
        return redirect("reservas:buscar")
    return render(request, "cuentas/registro.html", {"form": form})


def iniciar_sesion(request):
    """CU-02 / RF-COM-02: mensaje genérico ante credenciales incorrectas."""
    form = LoginForm(request.POST or None)
    siguiente = request.POST.get("next") or request.GET.get("next") or ""
    if request.method == "POST" and form.is_valid():
        usuario = authenticate(request, email=form.cleaned_data["email"], password=form.cleaned_data["password"])
        if usuario is None:
            registrar(None, "login_fallido", form.cleaned_data["email"], resultado="ERROR")
            messages.error(request, MENSAJE_LOGIN_FALLIDO)
        else:
            login(request, usuario)
            registrar(usuario, "login", usuario.email)
            if siguiente and url_has_allowed_host_and_scheme(siguiente, {request.get_host()}, request.is_secure()):
                return redirect(siguiente)
            return redirect(_destino_por_rol(usuario))
    return render(request, "cuentas/login.html", {"form": form, "next": siguiente})


@require_POST
def cerrar_sesion(request):
    if request.user.is_authenticated:
        registrar(request.user, "logout", request.user.email)
    logout(request)
    messages.info(request, "Sesión cerrada.")
    return redirect("core:inicio")


def recuperar(request):
    """Solicitud del código de recuperación. No revela si el correo existe."""
    form = SolicitarCodigoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        usuario = Usuario.objects.filter(email__iexact=email, is_active=True).first()
        if usuario:
            codigo = CodigoRecuperacion.generar(usuario)
            notificaciones.enviar(
                usuario.email,
                "Código para recuperar su contraseña",
                "codigo_recuperacion",
                {"usuario": usuario, "codigo": codigo, "minutos": settings.WALMAR["CODIGO_RECUPERACION_MINUTOS"]},
            )
            registrar(usuario, "codigo_recuperacion", usuario.email)
        messages.info(request, "Si el correo está registrado, recibirá un código de 6 dígitos para definir una nueva contraseña.")
        return redirect(f"{reverse('cuentas:recuperar_confirmar')}?{urlencode({'email': email})}")
    return render(request, "cuentas/recuperar.html", {"form": form})


def recuperar_confirmar(request):
    form = NuevaContrasenaForm(request.POST or None, initial={"email": request.GET.get("email", "")})
    if request.method == "POST" and form.is_valid():
        usuario = Usuario.objects.filter(email__iexact=form.cleaned_data["email"], is_active=True).first()
        codigo = usuario and usuario.codigos.filter(usado=False).order_by("-creado_en").first()
        if codigo and codigo.verificar(form.cleaned_data["codigo"]):
            codigo.usado = True
            codigo.save(update_fields=["usado"])
            usuario.set_password(form.cleaned_data["password1"])
            usuario.save(update_fields=["password"])
            registrar(usuario, "contrasena_restablecida", usuario.email)
            messages.success(request, "Su contraseña fue actualizada. Ya puede iniciar sesión.")
            return redirect("cuentas:login")
        registrar(usuario, "codigo_invalido", form.cleaned_data["email"], resultado="ERROR")
        messages.error(request, "El código no es válido o ya venció. Solicite uno nuevo si es necesario.")
    return render(request, "cuentas/recuperar_confirmar.html", {"form": form})


@login_required
def perfil(request):
    form = PerfilForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        registrar(request.user, "perfil_actualizado", request.user.email)
        messages.success(request, "Datos actualizados.")
        return redirect("cuentas:perfil")
    return render(request, "cuentas/perfil.html", {"form": form})


# ------------------------------------------------------------ personal (CU-17, RF-IN-03)
@rol_requerido(Rol.ADMIN)
def personal_lista(request):
    usuarios = Usuario.objects.exclude(rol=Rol.PASAJERO).order_by("rol", "nombre")
    return render(request, "cuentas/personal_lista.html", {"usuarios": usuarios})


@rol_requerido(Rol.ADMIN)
def personal_crear(request):
    form = CrearPersonalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save(commit=False)
        usuario.set_unusable_password()
        usuario.creado_por = request.user
        usuario.save()
        codigo = CodigoRecuperacion.generar(usuario, minutos=48 * 60)
        notificaciones.enviar(
            usuario.email,
            "Se creó su cuenta de personal autorizado",
            "cuenta_personal",
            {
                "usuario": usuario,
                "codigo": codigo,
                "url": request.build_absolute_uri(reverse("cuentas:recuperar_confirmar") + "?" + urlencode({"email": usuario.email})),
            },
        )
        registrar(request.user, "personal_creado", usuario.email, rol=usuario.rol)
        messages.success(request, f"Cuenta creada para {usuario.nombre}. Se envió un código al correo para definir la contraseña.")
        return redirect("cuentas:personal_lista")
    return render(request, "cuentas/personal_form.html", {"form": form})


@rol_requerido(Rol.ADMIN)
@require_POST
def personal_activar(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    if usuario == request.user:
        messages.error(request, "No puede desactivar su propia cuenta.")
    else:
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=["is_active"])
        registrar(request.user, "personal_activo", usuario.email, activo=usuario.is_active)
        messages.success(request, f"Cuenta {'activada' if usuario.is_active else 'desactivada'}: {usuario.email}")
    return redirect("cuentas:personal_lista")
