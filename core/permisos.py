from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

from .auditoria import registrar


def rol_requerido(*roles, api=False):
    """Restringe una vista a los roles indicados (RF-COM-02 CA2, RNF-03).

    El Administrador hereda los permisos del Operador.
    """

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                if api:
                    return JsonResponse({"error": "Sesión requerida."}, status=401)
                return redirect_to_login(request.get_full_path())
            if not user.tiene_rol(*roles):
                registrar(user, "acceso_denegado", request.path, resultado="DENEGADO")
                if api:
                    return JsonResponse({"error": "No tiene permisos para esta operación."}, status=403)
                messages.error(request, "No tiene permisos para acceder a esa sección.")
                raise PermissionDenied("Rol no autorizado")
            return vista(request, *args, **kwargs)

        envoltura.roles_permitidos = roles
        return envoltura

    return decorador
