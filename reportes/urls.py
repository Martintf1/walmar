from django.urls import path

from . import views

app_name = "reportes"

urlpatterns = [
    path("", views.reportes, name="reportes"),
    path("auditoria/", views.auditoria, name="auditoria"),
]
