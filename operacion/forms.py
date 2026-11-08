from django import forms

from .models import AsignacionGrupo, GrupoPropietarios, HorarioBase, Lancha, PuntoEmbarque, Ruta, Viaje

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
HORA = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class RutaForm(forms.ModelForm):
    class Meta:
        model = Ruta
        fields = ["nombre", "ciudad_a", "ciudad_b", "duracion_estimada_min", "tarifa_base", "activa"]


class PuntoEmbarqueForm(forms.ModelForm):
    class Meta:
        model = PuntoEmbarque
        fields = ["ruta", "nombre", "ciudad", "direccion", "tipo", "activo"]


class GrupoForm(forms.ModelForm):
    class Meta:
        model = GrupoPropietarios
        fields = ["nombre", "orden", "responsable", "telefono", "activo"]


class LanchaForm(forms.ModelForm):
    class Meta:
        model = Lancha
        fields = ["nombre", "matricula", "capacidad_autorizada", "motores", "grupo", "estado"]


class HorarioBaseForm(forms.ModelForm):
    class Meta:
        model = HorarioBase
        fields = ["ruta", "sentido", "hora", "punto_embarque", "punto_desembarque", "activo"]
        widgets = {"hora": HORA}


class ViajeForm(forms.ModelForm):
    motivo = forms.CharField(label="Motivo del cambio (opcional)", required=False, max_length=250)

    class Meta:
        model = Viaje
        fields = [
            "ruta",
            "sentido",
            "punto_embarque",
            "punto_desembarque",
            "fecha",
            "hora_programada",
            "tarifa",
            "lancha",
            "grupo",
            "cupos",
            "habilitado",
        ]
        widgets = {"fecha": FECHA, "hora_programada": HORA}
        help_texts = {"cupos": "Máximo: capacidad autorizada de la lancha. Si lo deja vacío se usa la capacidad."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cupos"].required = False
        self.fields["lancha"].queryset = Lancha.objects.filter(estado=Lancha.Estado.ACTIVA)
        self.fields["punto_embarque"].queryset = PuntoEmbarque.objects.filter(activo=True)
        self.fields["punto_desembarque"].queryset = PuntoEmbarque.objects.filter(activo=True)
        if self.instance.pk:
            # Las fechas/horas de un viaje existente se cambian con "Reprogramar".
            self.fields["fecha"].disabled = True
            self.fields["hora_programada"].disabled = True

    def clean(self):
        datos = super().clean()
        lancha = datos.get("lancha")
        if lancha and not datos.get("cupos"):
            datos["cupos"] = lancha.capacidad_autorizada
            self.instance.cupos = lancha.capacidad_autorizada
        return datos


class HoraEfectivaForm(forms.Form):
    hora_efectiva = forms.TimeField(label="Nueva hora efectiva de zarpe", widget=HORA)
    motivo = forms.CharField(label="Motivo (marea, condiciones del mar...)", max_length=250)


class ReprogramarForm(forms.Form):
    fecha = forms.DateField(label="Nueva fecha", widget=FECHA)
    hora = forms.TimeField(label="Nueva hora programada", widget=HORA)
    motivo = forms.CharField(label="Motivo del cambio", widget=forms.Textarea(attrs={"rows": 3}))


class CancelarViajeForm(forms.Form):
    motivo = forms.CharField(label="Motivo de la cancelación", widget=forms.Textarea(attrs={"rows": 3}))
    confirmar = forms.BooleanField(label="Confirmo que deseo cancelar esta salida y notificar a los pasajeros")


class AsignacionGrupoForm(forms.ModelForm):
    class Meta:
        model = AsignacionGrupo
        fields = ["fecha", "grupo", "nota"]
        widgets = {"fecha": FECHA}


class GenerarSalidasForm(forms.Form):
    desde = forms.DateField(widget=FECHA)
    hasta = forms.DateField(widget=FECHA)
    habilitar = forms.BooleanField(label="Habilitar para la venta de inmediato", required=False)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta"):
            if datos["hasta"] < datos["desde"]:
                raise forms.ValidationError("La fecha final debe ser posterior a la inicial.")
            if (datos["hasta"] - datos["desde"]).days > 62:
                raise forms.ValidationError("Programe como máximo dos meses a la vez.")
        return datos
