from django.core.management.base import BaseCommand

from operacion.servicios import finalizar_viajes_pasados
from reservas.servicios import expirar_reservas


class Command(BaseCommand):
    help = "Cancela reservas sin pago en el plazo (libera cupos) y finaliza viajes pasados. Programar cada minuto (cron)."

    def handle(self, *args, **opts):
        n = expirar_reservas()
        f = finalizar_viajes_pasados()
        self.stdout.write(f"Reservas vencidas: {n}. Viajes finalizados: {f}.")
