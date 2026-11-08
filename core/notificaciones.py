"""Envío de correos (servicio de correo vía SMTP)."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def enviar(destinatario, asunto, plantilla, contexto=None):
    contexto = dict(contexto or {})
    contexto.setdefault("sitio", "WALMAR")
    cuerpo = render_to_string(f"correos/{plantilla}.txt", contexto)
    try:
        send_mail(f"WALMAR - {asunto}", cuerpo, settings.DEFAULT_FROM_EMAIL, [destinatario])
        return True
    except Exception:  # el fallo del correo no debe romper la operación
        logger.exception("No se pudo enviar el correo '%s' a %s", asunto, destinatario)
        return False
