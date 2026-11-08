from django import template

register = template.Library()


@register.filter
def cop(valor):
    """Formato de pesos colombianos: $160.000"""
    if valor in (None, ""):
        return "—"
    try:
        return "$" + f"{int(valor):,}".replace(",", ".")
    except (TypeError, ValueError):
        return valor
