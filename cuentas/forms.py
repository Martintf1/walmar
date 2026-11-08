from django import forms
from django.contrib.auth import password_validation

from .models import ROLES_PERSONAL, Rol, Usuario


class RegistroForm(forms.ModelForm):
    acepta_terminos = forms.BooleanField(
        label="He leído y acepto los términos y condiciones y la política de tratamiento de datos personales",
        required=True,
        error_messages={"required": "Debe aceptar los términos y la política de tratamiento de datos para continuar."},
    )
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = Usuario
        fields = ["nombre", "tipo_documento", "identificacion", "telefono", "email"]
        widgets = {"email": forms.EmailInput(attrs={"autocomplete": "email"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("identificacion", "telefono"):
            self.fields[campo].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Usuario.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta registrada con este correo.")
        return email

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        if p1:
            usuario = Usuario(email=datos.get("email") or "", nombre=datos.get("nombre") or "")
            try:
                password_validation.validate_password(p1, usuario)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return datos


class LoginForm(forms.Form):
    email = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class SolicitarCodigoForm(forms.Form):
    email = forms.EmailField(label="Correo electrónico registrado")


class NuevaContrasenaForm(forms.Form):
    email = forms.EmailField(label="Correo electrónico")
    codigo = forms.CharField(label="Código recibido", max_length=6, min_length=6, widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}))
    password1 = forms.CharField(label="Nueva contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        datos = super().clean()
        if datos.get("password1") and datos.get("password1") != datos.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        if datos.get("password1"):
            try:
                password_validation.validate_password(datos["password1"])
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return datos


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["nombre", "tipo_documento", "identificacion", "telefono"]


class CrearPersonalForm(forms.ModelForm):
    rol = forms.ChoiceField(choices=[(r.value, r.label) for r in ROLES_PERSONAL] + [(Rol.PASAJERO.value, Rol.PASAJERO.label)])

    class Meta:
        model = Usuario
        fields = ["nombre", "email", "tipo_documento", "identificacion", "telefono", "rol"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Usuario.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Correo ya registrado: no se puede crear la cuenta.")
        return email
