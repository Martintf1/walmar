from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envía un correo de prueba para verificar la configuración SMTP (.env)."

    def add_arguments(self, parser):
        parser.add_argument("destinatario", help="Correo que recibirá la prueba")

    def handle(self, destinatario, **opciones):
        self.stdout.write(f"Backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"Servidor: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}  Usuario: {settings.EMAIL_HOST_USER or '(ninguno)'}")
        try:
            send_mail(
                "WALMAR - Correo de prueba",
                "Si recibe este mensaje, el envío de correos de WALMAR está configurado correctamente.",
                settings.DEFAULT_FROM_EMAIL,
                [destinatario],
            )
        except Exception as e:
            raise CommandError(f"No se pudo enviar el correo: {e}") from e
        self.stdout.write(self.style.SUCCESS(f"Correo enviado a {destinatario}."))
