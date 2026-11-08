"""Integración con la pasarela de pagos.

El proveedor real está pendiente de definir (Apéndice C). Este módulo expone
una interfaz mínima (`iniciar_pago` y `verificar_firma`) y una implementación
"simulada" que reproduce el flujo real: redirección del pasajero a la
pasarela y notificación firmada (HMAC-SHA256) del resultado al servidor.
Para integrar un proveedor (Wompi, PayU, ePayco...) se implementa una clase
con la misma interfaz y se selecciona con WALMAR_PASARELA.
"""
import hashlib
import hmac
import json

from django.conf import settings
from django.urls import reverse


def _secreto():
    return settings.WALMAR["PASARELA_SECRETO"].encode()


def firmar(payload: dict) -> str:
    cuerpo = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_secreto(), cuerpo, hashlib.sha256).hexdigest()


def verificar_firma(payload: dict, firma: str) -> bool:
    return bool(firma) and hmac.compare_digest(firmar(payload), firma)


class PasarelaSimulada:
    nombre = "Pasarela simulada (pruebas)"

    def iniciar_pago(self, pago, request):
        """Devuelve la URL a la que se redirige al pasajero."""
        return reverse("pagos:pasarela_simulada", args=[pago.referencia])


PASARELAS = {"simulada": PasarelaSimulada}


def obtener():
    return PASARELAS[settings.WALMAR["PASARELA"]]()
