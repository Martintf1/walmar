from django import forms

from .models import SolicitudReembolso

Estado = SolicitudReembolso.Estado


class SolicitudForm(forms.ModelForm):
    class Meta:
        model = SolicitudReembolso
        fields = ["tipo", "motivo", "soporte"]
        widgets = {"motivo": forms.Textarea(attrs={"rows": 4})}

    def clean_soporte(self):
        archivo = self.cleaned_data.get("soporte")
        if archivo and hasattr(archivo, "size"):
            if archivo.size > 5 * 1024 * 1024:
                raise forms.ValidationError("El soporte no puede superar 5 MB.")
            nombre = archivo.name.lower()
            if not nombre.endswith((".pdf", ".jpg", ".jpeg", ".png")):
                raise forms.ValidationError("Adjunte un PDF o una imagen (JPG/PNG).")
        return archivo


class ResolverForm(forms.Form):
    estado = forms.ChoiceField(
        label="Nuevo estado",
        choices=[(e.value, e.label) for e in (Estado.EN_REVISION, Estado.APROBADA, Estado.NO_APROBADA, Estado.EN_PROCESO, Estado.REEMBOLSADA)],
    )
    justificacion = forms.CharField(label="Justificación / nota", widget=forms.Textarea(attrs={"rows": 3}), required=False)
    valor_autorizado = forms.DecimalField(label="Valor autorizado a devolver (COP)", required=False, min_value=0, decimal_places=0)
    referencia = forms.CharField(label="Referencia de la devolución", required=False, max_length=120)
