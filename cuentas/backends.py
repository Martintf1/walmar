from django.contrib.auth.backends import ModelBackend

from .models import Usuario


class EmailBackend(ModelBackend):
    """Autenticación por correo (sin distinguir mayúsculas)."""

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        email = (email or username or "").strip().lower()
        if not email or password is None:
            return None
        try:
            user = Usuario.objects.get(email__iexact=email)
        except Usuario.DoesNotExist:
            Usuario().set_password(password)  # mitiga ataques de tiempo
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
