from django import forms
from django.conf import settings
from django.forms import formset_factory

from cuentas.models import TipoDocumento


class BuscarViajesForm(forms.Form):
    origen = forms.ChoiceField(label="Origen")
    destino = forms.ChoiceField(label="Destino")
    fecha = forms.DateField(label="Fecha", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, ciudades=(), **kwargs):
        super().__init__(*args, **kwargs)
        opciones = [("", "Seleccione...")] + [(c, c) for c in ciudades]
        self.fields["origen"].choices = opciones
        self.fields["destino"].choices = opciones

    def clean(self):
        datos = super().clean()
        if datos.get("origen") and datos.get("origen") == datos.get("destino"):
            raise forms.ValidationError("El origen y el destino deben ser diferentes.")
        return datos


class PasajeroForm(forms.Form):
    nombre = forms.CharField(label="Nombre completo", max_length=150)
    tipo_documento = forms.ChoiceField(label="Tipo de documento", choices=TipoDocumento.choices)
    documento = forms.CharField(label="Número de documento", max_length=30)
    telefono = forms.CharField(label="Teléfono (opcional)", max_length=30, required=False)

    def clean_documento(self):
        doc = self.cleaned_data["documento"].strip().replace(".", "").replace(" ", "")
        if not doc.isalnum():
            raise forms.ValidationError("Use solo letras y números.")
        return doc


def pasajeros_formset():
    return formset_factory(
        PasajeroForm, extra=0, min_num=1, max_num=settings.WALMAR["MAX_PASAJES_POR_RESERVA"], validate_min=True, validate_max=True
    )


class ConfirmarReservaForm(forms.Form):
    acepta_politica = forms.BooleanField(
        label="He leído y acepto la política de cancelación, reprogramación y devolución",
        error_messages={"required": "Debe aceptar la política antes de continuar."},
    )
    clave_idempotencia = forms.CharField(widget=forms.HiddenInput, required=False, max_length=64)
