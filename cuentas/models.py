import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Rol(models.TextChoices):
    PASAJERO = "PASAJERO", "Pasajero"
    VENTAS = "VENTAS", "Personal de atención y venta"
    ABORDAJE = "ABORDAJE", "Personal de abordaje"
    OPERADOR = "OPERADOR", "Operador / empresa transportadora"
    ADMIN = "ADMIN", "Administrador"


# Roles que hereda cada rol (el Administrador hereda las funciones del Operador).
HERENCIA_ROLES = {
    Rol.ADMIN: {Rol.ADMIN, Rol.OPERADOR},
}

ROLES_PERSONAL = [Rol.VENTAS, Rol.ABORDAJE, Rol.OPERADOR, Rol.ADMIN]


class TipoDocumento(models.TextChoices):
    CC = "CC", "Cédula de ciudadanía"
    TI = "TI", "Tarjeta de identidad"
    CE = "CE", "Cédula de extranjería"
    PA = "PA", "Pasaporte"
    RC = "RC", "Registro civil"


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("El correo es obligatorio")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("rol", Rol.ADMIN)
        extra.setdefault("nombre", "Administrador")
        return self._create_user(email, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("correo electrónico", unique=True)
    nombre = models.CharField("nombre completo", max_length=150)
    tipo_documento = models.CharField(max_length=2, choices=TipoDocumento.choices, default=TipoDocumento.CC)
    identificacion = models.CharField("número de identificación", max_length=30, blank=True)
    telefono = models.CharField("teléfono", max_length=30, blank=True)
    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.PASAJERO)
    acepto_terminos_en = models.DateTimeField("aceptó términos y tratamiento de datos", null=True, blank=True)
    is_active = models.BooleanField("activo", default=True)
    is_staff = models.BooleanField("acceso al admin de Django", default=False)
    date_joined = models.DateTimeField("fecha de registro", default=timezone.now)
    creado_por = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["nombre"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self):
        return f"{self.nombre} <{self.email}>"

    @property
    def roles_efectivos(self):
        return HERENCIA_ROLES.get(self.rol, {self.rol})

    def tiene_rol(self, *roles):
        return bool(self.roles_efectivos & set(roles))

    @property
    def es_personal(self):
        return self.rol in ROLES_PERSONAL

    def get_full_name(self):
        return self.nombre

    def get_short_name(self):
        return self.nombre.split(" ")[0] if self.nombre else self.email


class CodigoRecuperacion(models.Model):
    """Código temporal de un solo uso enviado al correo (RF-COM-02 CA3/CA4)."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="codigos")
    codigo_hash = models.CharField(max_length=64)
    creado_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField()
    intentos = models.PositiveSmallIntegerField(default=0)
    usado = models.BooleanField(default=False)

    @staticmethod
    def _hash(codigo):
        return hashlib.sha256(codigo.encode()).hexdigest()

    @classmethod
    def generar(cls, usuario, minutos=None):
        cls.objects.filter(usuario=usuario, usado=False).update(usado=True)
        codigo = f"{secrets.randbelow(10**6):06d}"
        minutos = minutos or settings.WALMAR["CODIGO_RECUPERACION_MINUTOS"]
        cls.objects.create(
            usuario=usuario,
            codigo_hash=cls._hash(codigo),
            expira_en=timezone.now() + timedelta(minutes=minutos),
        )
        return codigo

    @property
    def vigente(self):
        return (
            not self.usado
            and self.expira_en > timezone.now()
            and self.intentos < settings.WALMAR["CODIGO_RECUPERACION_INTENTOS"]
        )

    def verificar(self, codigo):
        if not self.vigente:
            return False
        self.intentos += 1
        ok = secrets.compare_digest(self._hash(codigo.strip()), self.codigo_hash)
        self.save(update_fields=["intentos"])
        return ok
