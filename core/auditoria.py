from .models import RegistroAuditoria


def _serializable(valor):
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    return str(valor)


def registrar(usuario, accion, objeto="", resultado="OK", **detalle):
    if usuario is not None and not getattr(usuario, "is_authenticated", False):
        usuario = None
    return RegistroAuditoria.objects.create(
        usuario=usuario,
        accion=accion,
        objeto=str(objeto)[:120],
        resultado=resultado,
        detalle=_serializable(detalle),
    )
