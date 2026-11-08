"""Carga la configuración inicial del servicio (RF-IN-01/02).

Los valores son parámetros iniciales PENDIENTES DE VALIDACIÓN con el operador
y la autoridad marítima (Apéndice C de la ERS): ajuste capacidades, horarios
y puntos de embarque desde el módulo de Configuración.
"""
from datetime import time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from cuentas.models import Rol, Usuario
from operacion.models import GrupoPropietarios, HorarioBase, Lancha, PuntoEmbarque, Ruta, Viaje
from operacion.servicios import generar_salidas

USUARIOS_DEMO = [
    ("admin@walmar.local", "Administrador WALMAR", Rol.ADMIN),
    ("operador@walmar.local", "Operador Transportadora", Rol.OPERADOR),
    ("ventas@walmar.local", "Taquilla Buenaventura", Rol.VENTAS),
    ("abordaje@walmar.local", "Control de Abordaje", Rol.ABORDAJE),
    ("pasajero@walmar.local", "Pasajero de Prueba", Rol.PASAJERO),
]


class Command(BaseCommand):
    help = "Crea la ruta Buenaventura–Timbiquí, puntos, 3 grupos con 2 lanchas, horarios y (opcional) datos demo."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Crea usuarios de prueba por rol y salidas para 14 días.")
        parser.add_argument("--password", default="Walmar2026*", help="Contraseña de los usuarios demo.")

    @transaction.atomic
    def handle(self, *args, **opts):
        ruta, _ = Ruta.objects.get_or_create(
            nombre="Buenaventura – Timbiquí",
            defaults={"ciudad_a": "Buenaventura", "ciudad_b": "Timbiquí", "duracion_estimada_min": 240, "tarifa_base": 160000},
        )
        bun, _ = PuntoEmbarque.objects.get_or_create(
            ruta=ruta, nombre="Muelle de Buenaventura", defaults={"ciudad": "Buenaventura", "direccion": "Por confirmar con el operador"}
        )
        tim, _ = PuntoEmbarque.objects.get_or_create(
            ruta=ruta, nombre="Muelle de Timbiquí", defaults={"ciudad": "Timbiquí", "direccion": "Por confirmar con el operador"}
        )
        for i in range(1, 4):
            grupo, _ = GrupoPropietarios.objects.get_or_create(nombre=f"Grupo {i}", defaults={"orden": i})
            for j in range(1, 3):
                Lancha.objects.get_or_create(
                    matricula=f"PENDIENTE-G{i}-L{j}",
                    defaults={
                        "nombre": f"Lancha {i}{'AB'[j - 1]}",
                        "capacidad_autorizada": 40,
                        "grupo": grupo,
                        "motores": "Datos operativos por validar",
                    },
                )
        HorarioBase.objects.get_or_create(
            ruta=ruta, sentido=Viaje.Sentido.IDA, hora=time(7, 0), defaults={"punto_embarque": bun, "punto_desembarque": tim}
        )
        HorarioBase.objects.get_or_create(
            ruta=ruta, sentido=Viaje.Sentido.REGRESO, hora=time(7, 0), defaults={"punto_embarque": tim, "punto_desembarque": bun}
        )
        self.stdout.write(self.style.SUCCESS("Configuración inicial cargada (valores pendientes de validación)."))

        if opts["demo"]:
            for email, nombre, rol in USUARIOS_DEMO:
                u, creado = Usuario.objects.get_or_create(
                    email=email,
                    defaults={"nombre": nombre, "rol": rol, "identificacion": "1000000000", "telefono": "3000000000",
                              "acepto_terminos_en": timezone.now(), "is_staff": rol == Rol.ADMIN, "is_superuser": rol == Rol.ADMIN},
                )
                if creado:
                    u.set_password(opts["password"])
                    u.save()
                self.stdout.write(f"  {rol.label:35} {email}")
            hoy = timezone.localdate()
            admin = Usuario.objects.get(email="admin@walmar.local")
            creados, avisos = generar_salidas(hoy, hoy + timedelta(days=14), admin, habilitar=True)
            self.stdout.write(self.style.SUCCESS(f"Usuarios demo (contraseña: {opts['password']}) y {len(creados)} salidas creadas."))
            for a in avisos:
                self.stdout.write(self.style.WARNING(a))
